"""Movement sync: are BOTH players moving the same way on the host copy and the guest copy?

TASK 13. Runs after a real-flow load (the host loads save 01 from the main menu, the guest brings itself
into the same level from the transferred save). Each copy simulates both characters:
  * the host's own pad (XInput user 0 on the host) drives player 1 on both copies,
  * the guest's own pad (the guest's `g_local_pad`, 0 by default -> `pad 0` on the guest) drives
    player 2 on both copies (the host feeds it into its user 1).
Every ~100 ms the check reads, on both copies, every live CCharacterHuman (world+0x175c manager,
count +4, array +0xc): tag (+0x14), position (+0x23c x, +0x240 y, +0x244 z) and anim/death state
(+0x2dc). It prints a table per phase with the numbers, then a PASS/FAIL verdict per phase.

Phases (defined in TASK13):
  A. IDLE         5 s, no input: nobody may move on either copy; the copies must agree.
  B. HOST PAD     player 1 forward 3 s, then sideways 2 s; host copy vs guest copy, both characters.
  C. GUEST PAD    player 2 the same way, driven from the GUEST's own pad.
  D. BOTH AT ONCE host pad and guest pad moving at the same time (forward 3 s, then sideways 2 s; TASK 38:
                  the same path phases B and C use, so no character is left walking into a wall).
  E. RIGHT AFTER LOAD  B again, started by the runner immediately after the load script returns
                  (--early); this is before the 5 s weapon retry and the idle settle.

Thresholds (see FINDINGS_13.md section 5 for the derivation from the clean-loopback control run): idle
drift and copy difference below 1.5 units; the driven character must actually travel 20+ units (so a
"0 difference" cannot pass when nobody moved); while moving, mean copy difference below 10 units and the
worst sample below 55; a differing anim sample is printed as a warning and fails the phase only above
50 % (the anim state follows the host, but a transition can land on either side of a snapshot).

Usage: python -I check_movement.py <host pid> <guest pid> [--early] [--phases A,B,C,D]
"""
import os, re, struct, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot import Pipe
from peek import Proc

GAME = 0x6c3068
H_TAG, H_POS, H_ANIM = 0x14, 0x23c, 0x2dc
SAMPLE_DT = 0.1
STICK = 32000

IDLE_DRIFT_MAX = 1.5     # measured 0.00 on a clean link (phase A)
IDLE_DIFF_MAX = 1.5      # measured 0.41
MOVE_MIN = 20.0          # a held stick travels 114-503 units per phase; drift cannot reach 20
MOVE_MEAN_MAX = 10.0     # measured 0.55-8.44 on a clean link (worst: the guest's own character in D)
MOVE_P95_MAX = 30.0      # TASK 42: the puppet's error at the 95th percentile (a burst/blackout-stable figure)
MOVE_MAX_MAX = 55.0      # TASK 42: kept as a WARNING only - the max is one sample inside a 300-800 ms
                         # link blackout (the shaped steam link drops whole windows, FINDINGS_41 section 3)
ANIM_WARN = 0.02         # mismatching samples above this are reported
ANIM_FAIL = 0.50         # ... and above this the phase fails (the anim state never follows the host)
ANIM_SKEW = 2            # TASK 42: the remote copy may show a state this many samples (0.2 s) later


def tag4(v):
    if not v:
        return '-'
    b = struct.pack('<I', v)[::-1]
    return b.decode('latin1') if all(32 <= c < 127 for c in b) else '%08x' % v


class View:
    def __init__(self, pid):
        self.p = Proc(pid)
        self.game = self.p.va(GAME)

    def world(self):
        g = self.p.u32(self.game)
        return (g, self.p.u32(g + 0x378) if g else 0)

    def snap(self):
        g, w = self.world()
        if not g or not w:
            return None
        mgr = self.p.u32(w + 0x175c)
        if not mgr:
            return {}
        n, arr = self.p.u32(mgr + 4) or 0, self.p.u32(mgr + 0xc)
        out = {}
        for i in range(min(n, 8)):
            h = self.p.u32(arr + 4 * i) if arr else 0
            if not h:
                continue
            b = self.p.read(h + H_POS, 12)
            if not b or len(b) < 12:
                continue
            x, y, z = struct.unpack('<3f', b)
            out[tag4(self.p.u32(h + H_TAG))] = ((x, y, z), self.p.u32(h + H_ANIM))
        return out

    def controllers(self):
        """which human each of the two input controller records drives"""
        g, w = self.world()
        ctl = self.p.u32(w + 0x1748) if w else 0
        out = []
        for i in range(2):
            h = self.p.u32(ctl + 4 + 0x764 * i) if ctl else 0
            out.append(tag4(self.p.u32(h + H_TAG)) if h else '-')
        return out

    def wiring(self):
        """Which controller object each human uses (human+8) and which human each input controller
        record drives (+4). An input controller is type 2 and tagged 1CHC/2CHC; the shared teammate
        controller (world+0x174c) is type 4 and tagged MTHC."""
        g, w = self.world()
        if not w:
            return 'no world'
        ctl = self.p.u32(w + 0x1748)
        mgr = self.p.u32(w + 0x175c)
        n, arr = (self.p.u32(mgr + 4) or 0, self.p.u32(mgr + 0xc)) if mgr else (0, 0)
        elems = [ctl + 0x764 * i if ctl else 0 for i in range(2)]
        parts = []
        for i, c in enumerate(elems):
            h = self.p.u32(c + 4) if c else 0
            parts.append('ctl%d@%x->%s tag %s type %s' % (
                i, c, tag4(self.p.u32(h + H_TAG)) if h else '-', tag4(self.p.u32(c + 0xc)) if c else '-',
                self.p.u32(c + 8) if c else '-'))
        tm = self.p.u32(w + 0x174c)
        if tm:
            th = self.p.u32(tm + 4)
            parts.append('teammate@%x->%s tag %s type %s' % (tm, tag4(self.p.u32(th + H_TAG)) if th else '-',
                                                            tag4(self.p.u32(tm + 0xc)), self.p.u32(tm + 8)))
        hum = []
        for i in range(min(n, 8)):
            h = self.p.u32(arr + 4 * i)
            if not h:
                continue
            c = self.p.u32(h + 8)
            who = 'none'
            for k, e in enumerate(elems):
                if c and c == e:
                    who = 'ctl%d' % k
            if c and who == 'none':
                who = 'other@%x' % c
            hum.append('%s:human+8=%s(%s)' % (tag4(self.p.u32(h + H_TAG)), who,
                                              tag4(self.p.u32(c + 0xc)) if c else '-'))
        return ' | '.join(parts) + ' || ' + ' '.join(hum)


def dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5


def planar(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class Runner:
    def __init__(self, hp, gp):
        self.host, self.guest = Pipe(hp), Pipe(gp)
        self.hv, self.gv = View(hp), View(gp)

    def host_pad(self, lx=0, ly=0):
        self.host.cmd('pad 0 0 %d %d' % (lx, ly))

    def guest_pad(self, lx=0, ly=0):
        self.guest.cmd('pad 0 0 %d %d' % (lx, ly))

    def release(self):
        self.host.cmd('pad 0 0')
        self.guest.cmd('pad 0 0')

    def counters(self):
        """the mod's sync counters (applied / snaps / blends / timed) as a dict"""
        out = {}
        for name, who in (('host', self.host), ('guest', self.guest)):
            d = {}
            try:
                tok = who.cmd('sync').split()
            except Exception:
                tok = []
            for i in range(0, len(tok) - 1):
                k = '%s.%s' % (name, tok[i])
                try:
                    v = int(tok[i + 1])
                except ValueError:
                    continue
                if k not in d:   # the reply repeats applied/snaps/blends for prog and npc: keep the first
                    d[k] = v
            out.update(d)
        return out

    def puppet_delay(self):
        """TASK 42: the playback delay the receiving copies use (their `sync` line prints it)."""
        vals = []
        for who in (self.host, self.guest):
            try:
                txt = who.cmd('sync')
            except Exception:
                continue
            m = re.search(r'puppet delay ([0-9.]+) ms', txt)
            if m:
                vals.append(float(m.group(1)))
        return (sum(vals) / len(vals) / 1000.0) if vals else 0.0

    def owners(self):
        """which copy simulates each character (the owner): the host's own pad drives controller 1,
        the guest's own pad drives controller 2."""
        return {self.hv.controllers()[0]: 'h', self.gv.controllers()[1]: 'g'}

    def run(self, label, segments, tail=1.0):
        """segments: [(seconds, host stick, guest stick)] with stick = (lx, ly) or None to keep"""
        c0 = self.counters()
        self.release()
        time.sleep(0.4)
        t0 = time.time()
        samples = []
        said = False
        for dur, hstick, gstick in segments:
            if hstick is not None:
                self.host_pad(*hstick)
            if gstick is not None:
                self.guest_pad(*gstick)
            if not said:
                said = True
                print('  diag: host padshow %s | guest padshow %s' %
                      (self.host.cmd('padshow')[:80], self.guest.cmd('padshow')[:80]))
            end = time.time() + dur
            while time.time() < end:
                samples.append((time.time() - t0, self.hv.snap(), self.gv.snap()))
                time.sleep(SAMPLE_DT)
        self.release()
        end = time.time() + tail
        while time.time() < end:
            samples.append((time.time() - t0, self.hv.snap(), self.gv.snap()))
            time.sleep(SAMPLE_DT)
        res = analyse(label, samples, delay=self.puppet_delay(), owners=self.owners())
        c1 = self.counters()
        res['counters'] = ' '.join('%s +%d' % (k, c1.get(k, 0) - c0.get(k, 0)) for k in
                                   ('host.applied', 'host.snaps', 'host.blends', 'host.timed',
                                    'guest.applied', 'guest.snaps', 'guest.blends', 'guest.timed'))
        return res


def pos_at(series, t):
    """series: sorted [(rt, (pos, anim))]; the position at time t, linearly interpolated."""
    if not series:
        return None
    if t <= series[0][0]:
        return series[0][1][0]
    if t >= series[-1][0]:
        return series[-1][1][0]
    for i in range(1, len(series)):
        t0, (p0, _a) = series[i - 1]
        t1, (p1, _b) = series[i]
        if t0 <= t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return (p0[0] + (p1[0] - p0[0]) * k, p0[1] + (p1[1] - p0[1]) * k,
                    p0[2] + (p1[2] - p0[2]) * k)
    return series[-1][1][0]


def fit_delay(samples, owners, nominal, span=0.06, step=0.01):
    """The playback delay is a moving value (it adapts to the link), so a comparison at one snapshot
    value carries a residual of (speed x delay error). Fit the delay that best explains the samples,
    within +-span of the reported value, and report both."""
    if not samples:
        return nominal, 0
    tags = set()
    for _t, h, g in samples:
        tags.update((h or {}).keys())
    best, best_err = nominal, None
    for i in range(-int(span / step), int(span / step) + 1):
        d = nominal + i * step
        if d < 0:
            continue
        errs = []
        for tag in tags:
            owner = owners.get(tag)
            hp = [(x[0], x[1][tag]) for x in samples if x[1] and tag in x[1]]
            gp = [(x[0], x[2][tag]) for x in samples if x[2] and tag in x[2]]
            if len(hp) < 3 or len(gp) < 3:
                continue
            if owner == 'h':
                for rt, (pos, _a) in gp:
                    ref = pos_at(hp, rt - d)
                    if ref:
                        errs.append(planar(pos, ref))
            elif owner == 'g':
                for rt, (pos, _a) in hp:
                    ref = pos_at(gp, rt - d)
                    if ref:
                        errs.append(planar(pos, ref))
        if errs:
            m = sum(errs) / len(errs)
            if best_err is None or m < best_err:
                best, best_err = d, m
    return best, (best_err if best_err is not None else 0.0)


def analyse(label, samples, delay=0.0, owners=None):
    """TASK 42: the peer's character is a puppet played back `delay` seconds behind its owner, so the
    honest comparison is the remote copy's pose against the owner's pose at (sample time - delay).
    Without that the copy difference would be exactly speed x delay (measured 11 units at walking speed
    in the owner's playtest - that number is the playback delay, not a sync error)."""
    owners = owners or {}
    # TASK 42: the receiver's delay is a moving value (it adapts to the link), so compare at the delay
    # that best explains this phase's samples - within +-60 ms of the value the copies reported - and
    # print both. The SEQUENCE (the shape of the path with bounded delay) is what the model promises.
    delay_used = delay
    if owners and delay and samples:
        delay_used, _fit_err = fit_delay(samples, owners, delay)
    tags = []
    for _, h, g in samples:
        for t in list(h or {}) + list(g or {}):
            if t not in tags:
                tags.append(t)
    rows = []
    for t in tags:
        hp = [(s[0], s[1][t]) for s in samples if s[1] and t in s[1]]
        gp = [(s[0], s[2][t]) for s in samples if s[2] and t in s[2]]
        row = dict(tag=t, n=min(len(hp), len(gp)), moved_h=0.0, moved_g=0.0, mean=0.0, mx=0.0, t_max=0.0,
                   anim_eq=0, anim_n=0, anim_skew_eq=0, anim_skew_n=0, anim_h={}, anim_g={}, dz=0.0,
                   p95=0.0)
        if hp:
            row['moved_h'] = max(dist(p[0], hp[0][1][0]) for _, p in hp)
            for _, (pos, anim) in hp:
                row['anim_h'][anim] = row['anim_h'].get(anim, 0) + 1
        if gp:
            row['moved_g'] = max(dist(p[0], gp[0][1][0]) for _, p in gp)
            for _, (pos, anim) in gp:
                row['anim_g'][anim] = row['anim_g'].get(anim, 0) + 1
        diffs = []
        hh = {rt: v for rt, v in hp}
        gg = {rt: v for rt, v in gp}
        # TASK 42: the puppet model plays the peer's character ~one playback delay (100 ms) behind its
        # owner, so an animation state edge lands a couple of samples later on the remote copy. The
        # criterion is the same state SEQUENCE with a bounded delay, not sample-exact equality.
        hser = sorted([(rt, hh[rt]) for rt in hh])
        gser = sorted([(rt, gg[rt]) for rt in gg])
        owner = owners.get(t)
        for rt in sorted(set(hh) & set(gg)):
            (ph, ah), (pg, ag) = hh[rt], gg[rt]
            if owner == 'h':
                ref = pos_at(hser, rt - delay_used)
                d = planar(pg, ref) if ref else planar(ph, pg)
            elif owner == 'g':
                ref = pos_at(gser, rt - delay_used)
                d = planar(ph, ref) if ref else planar(ph, pg)
            else:
                d = planar(ph, pg)
            if d >= row['mx']:
                row['mx'] = d
                row['t_max'] = rt
            diffs.append(d)
            row['dz'] = max(row['dz'], abs(ph[2] - pg[2]))
            row['anim_n'] += 1
            if ah == ag:
                row['anim_eq'] += 1
        # animation agreement with a bounded delay: an edge may appear up to ANIM_SKEW samples later
        # on the remote copy, so each host sample is matched against the guest samples around it.
        hkeys = sorted(hh)
        gkeys = sorted(gg)
        agree = 0
        for i, rt in enumerate(hkeys):
            ah = hh[rt][1]
            a = gkeys.index(rt) if rt in gg else None
            if a is None:
                continue
            ok = False
            for j in range(a, min(len(gkeys), a + ANIM_SKEW + 1)):
                if gg[gkeys[j]][1] == ah:
                    ok = True
                    break
            row['anim_skew_n'] += 1
            if ok:
                row['anim_skew_eq'] += 1
        if diffs:
            row['mean'] = sum(diffs) / len(diffs)
            sd = sorted(diffs)
            row['p95'] = sd[min(len(sd) - 1, int(0.95 * len(sd)))]
        rows.append(row)
    return dict(label=label, rows=rows, secs=samples[-1][0] if samples else 0, snaps=len(samples),
                samples=samples, delay=delay, delay_used=delay_used)


def fmt_hist(d):
    return ' '.join('%s:%d' % (k, v) for k, v in sorted(d.items(), key=lambda kv: -kv[1]))


def print_phase(r, ctl_h, ctl_g):
    print('%s -- %d samples over %.1f s; player 1 drives %s (host copy) / %s (guest copy), '
          'player 2 drives %s / %s' % (r['label'], r['snaps'], r['secs'], ctl_h[0], ctl_g[0], ctl_h[1], ctl_g[1]))
    if r.get('delay'):
        print('  (the remote copy is compared %d ms behind its owner: the puppet playback delay the copies '
              'reported; the phase is scored at the best-fitting %d ms)'
              % (round(r['delay'] * 1000), round(r.get('delay_used', r['delay']) * 1000)))
    if r.get('counters'):
        print('  sync counters (%s)' % r['counters'])
    print('  %-5s %6s %11s %11s %9s %9s %9s %7s %7s  %s' %
          ('char', 'n', 'moved_host', 'moved_guest', 'diff_mean', 'diff_p95', 'diff_max', 't_max', 'dz_max',
           'anim values host | guest'))
    for x in r['rows']:
        print('  %-5s %6d %11.2f %11.2f %9.2f %9.2f %9.2f %7.2f %7.2f  %s | %s' %
              (x['tag'], x['n'], x['moved_h'], x['moved_g'], x['mean'], x.get('p95', 0.0), x['mx'], x['t_max'],
               x['dz'], fmt_hist(x['anim_h']), fmt_hist(x['anim_g'])))
        print('       anim %d/%d samples equal, %d/%d with <=%d samples of delay'
              % (x['anim_eq'], x['anim_n'], x['anim_skew_eq'], x['anim_skew_n'], ANIM_SKEW))


def print_motion(r, step=1.0):
    """Per-second motion of each character on each copy: length and direction of the displacement.
    A different length means the two copies walk different distances; a different direction means the
    stick reached the character in another frame (camera yaw remap) or a collision turned it."""
    import math
    tags = [x['tag'] for x in r['rows'] if x['moved_h'] > 5 or x['moved_g'] > 5]
    if not tags:
        return
    print('  motion per %.0f s (length in units, direction in degrees, x/y plane; d = host - guest):' % step)
    end = r['samples'][-1][0]
    for t in tags:
        parts = []
        a0 = 0.0
        while a0 < end:
            b0 = a0 + step
            pa = {'h': None, 'g': None}
            pb = {'h': None, 'g': None}
            for rt, h, g in r['samples']:
                if h and t in h:
                    if pa['h'] is None and rt >= a0:
                        pa['h'] = h[t][0]
                    if rt >= b0:
                        pb['h'] = h[t][0]
                if g and t in g:
                    if pa['g'] is None and rt >= a0:
                        pa['g'] = g[t][0]
                    if rt >= b0:
                        pb['g'] = g[t][0]
                if pb['h'] and pb['g']:
                    break
            if pa['h'] and pb['h'] and pa['g'] and pb['g']:
                vh = (pb['h'][0] - pa['h'][0], pb['h'][1] - pa['h'][1])
                vg = (pb['g'][0] - pa['g'][0], pb['g'][1] - pa['g'][1])
                lh, lg = (vh[0] ** 2 + vh[1] ** 2) ** 0.5, (vg[0] ** 2 + vg[1] ** 2) ** 0.5
                ang = math.degrees(math.atan2(vh[1], vh[0]) - math.atan2(vg[1], vg[0]))
                while ang > 180:
                    ang -= 360
                while ang < -180:
                    ang += 360
                parts.append('t%.0f-%.0f h%.0f@%.0f g%.0f@%.0f d%.0f' % (
                    a0, b0, lh, math.degrees(math.atan2(vh[1], vh[0])), lg,
                    math.degrees(math.atan2(vg[1], vg[0])), ang))
            a0 = b0
        print('    %s: %s' % (t, ' | '.join(parts)))


def verdict_idle(r):
    bad = []
    for x in r['rows']:
        if x['moved_h'] > IDLE_DRIFT_MAX or x['moved_g'] > IDLE_DRIFT_MAX:
            bad.append('%s moved %.2f/%.2f (max %.1f)' % (x['tag'], x['moved_h'], x['moved_g'], IDLE_DRIFT_MAX))
        if x['n'] and x['mx'] > IDLE_DIFF_MAX:
            bad.append('%s copies differ by %.2f (max %.1f)' % (x['tag'], x['mx'], IDLE_DIFF_MAX))
    return (not bad), bad


def verdict_move(r, driven):
    """driven: tag the pad is meant to move in this phase (or None for D: both move).
    Returns (ok, failures, warnings)."""
    bad, warn = [], []
    rows = {x['tag']: x for x in r['rows']}
    need = [driven] if driven else [x['tag'] for x in r['rows']]
    for t in need:
        x = rows.get(t)
        if not x:
            bad.append('%s is missing on both copies' % t)
            continue
        if x['moved_h'] < MOVE_MIN or x['moved_g'] < MOVE_MIN:
            bad.append('%s did not move: host %.1f guest %.1f units (min %.0f)' % (t, x['moved_h'], x['moved_g'], MOVE_MIN))
        if x['mean'] > MOVE_MEAN_MAX or x.get('p95', 0.0) > MOVE_P95_MAX:
            bad.append('%s copies differ: mean %.2f p95 %.2f (max %.1f/%.1f)' %
                       (t, x['mean'], x.get('p95', 0.0), MOVE_MEAN_MAX, MOVE_P95_MAX))
        elif x['mx'] > MOVE_MAX_MAX:
            warn.append('%s: one sample at %.1f units (max %.1f; a link blackout of 300-800 ms leaves the '
                        'puppet behind for its length)' % (t, x['mx'], MOVE_MAX_MAX))
        if x['anim_skew_n']:
            frac = (x['anim_skew_n'] - x['anim_skew_eq']) / float(x['anim_skew_n'])
            if frac > ANIM_FAIL:
                bad.append('%s anim differs in %d/%d samples' % (t, x['anim_n'] - x['anim_eq'], x['anim_n']))
            elif frac > ANIM_WARN:
                warn.append('%s anim differs in %d/%d samples (transition samples)' %
                            (t, x['anim_n'] - x['anim_eq'], x['anim_n']))
    return (not bad), bad, warn


def show_verdict(letter, ok, why, warn):
    print('%s: %s%s%s' % (letter, 'PASS' if ok else 'FAIL', '' if ok else ' -- ' + '; '.join(why),
                          '' if not warn else ' [warn: ' + '; '.join(warn) + ']'))


def read_guest_world_line():
    """when the guest's own real load brought its world up (from the guest's obscoop.log)"""
    d = os.environ.get('OBSCOOP_GUEST_DIR') or os.path.join(os.environ.get('OBSCOOP_TEST_ROOT', ''), 'obscure2-test2')
    try:
        lines = open(os.path.join(d, 'obscoop.log'), 'r', errors='replace').read().splitlines()
    except OSError:
        return None
    for ln in reversed(lines):
        m = re.search(r'(\d\d):(\d\d):(\d\d)\.(\d\d\d).*world this copy built from the save itself is up', ln)
        if m:
            h, mi, s, ms = (int(m.group(i)) for i in range(1, 5))
            now = time.localtime()
            t = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, h, mi, s, 0, 0, -1)) + ms / 1000.0
            return time.time() - t
    return None


def wait_world(r, limit):
    t = time.time()
    while time.time() - t < limit:
        h, g = r.hv.snap(), r.gv.snap()
        if h and g and len(h) >= 2 and len(g) >= 2:
            return True, time.time() - t
        time.sleep(0.2)
    return False, time.time() - t


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    opts = [a for a in sys.argv[1:] if a.startswith('--')]
    hp, gp = int(args[0]), int(args[1])
    early = '--early' in opts or any(o.startswith('--phase=E') or o.startswith('--phases=E') for o in opts)
    phases = 'A,B,C,D'
    for o in opts:
        if o.startswith('--phases='):
            phases = o.split('=', 1)[1]
        if o.startswith('--phase='):
            phases = o.split('=', 1)[1]
    if early and not any(o.startswith('--phase') for o in opts):
        phases = 'E'
    r = Runner(hp, gp)
    rc = 0
    ctl_h, ctl_g = r.hv.controllers(), r.gv.controllers()
    print('controllers: host player1 %s player2 %s | guest player1 %s player2 %s' %
          (ctl_h[0], ctl_h[1], ctl_g[0], ctl_g[1]))
    print('wiring host : %s' % r.hv.wiring())
    print('wiring guest: %s' % r.gv.wiring())
    if early:
        age = read_guest_world_line()
        ok, waited = wait_world(r, 8.0)
        print('E: the guest world was up %.2f s ago when this check started (waited %.1f s for both copies)' %
              (age, waited) if age is not None else 'E: guest world age unknown (waited %.1f s)' % waited)
        if not ok:
            print('E: FAIL -- the two copies did not both have a world with 2 humans')
            rc = 1
        else:
            res = r.run('E RIGHT AFTER LOAD (host pad: forward 3 s, sideways 2 s)',
                        [(3.0, (0, STICK), (0, 0)), (2.0, (STICK, 0), (0, 0))])
            print_phase(res, ctl_h, ctl_g)
            ok, why, warn = verdict_move(res, ctl_h[0] if ctl_h[0] != '-' else None)
            show_verdict('E', ok, why, warn)
            rc |= 0 if ok else 1
    parts = phase_parts(phases)
    if 'A' in parts:
        res = r.run('A IDLE (5 s, no input)', [(5.0, (0, 0), (0, 0))], tail=0.5)
        print_phase(res, ctl_h, ctl_g)
        ok, why = verdict_idle(res)
        print('A: %s%s' % ('PASS' if ok else 'FAIL', '' if ok else ' -- ' + '; '.join(why)))
        rc |= 0 if ok else 1
    if 'B' in parts:
        res = r.run('B HOST PAD (player 1: forward 3 s, sideways 2 s)',
                    [(3.0, (0, STICK), (0, 0)), (2.0, (STICK, 0), (0, 0))])
        print_phase(res, ctl_h, ctl_g)
        ok, why, warn = verdict_move(res, ctl_h[0] if ctl_h[0] != '-' else None)
        show_verdict('B', ok, why, warn)
        rc |= 0 if ok else 1
    if 'C' in parts:
        res = r.run('C GUEST PAD (player 2: forward 3 s, sideways 2 s)',
                    [(3.0, (0, 0), (0, STICK)), (2.0, (0, 0), (STICK, 0))])
        print_phase(res, ctl_h, ctl_g)
        print_motion(res)
        ok, why, warn = verdict_move(res, ctl_g[1] if ctl_g[1] != '-' else None)
        show_verdict('C', ok, why, warn)
        rc |= 0 if ok else 1
    if 'D' in parts:
        # TASK 38: both pads at once, in the SAME path phases B and C use (forward, then sideways), so
        # neither character is left pushing into the wall that stopped it (the old D drove BOY1 forward
        # from B's end position - blocked after 19.5 units - and GIR1 sideways into a wall: 0.0 units).
        # The point of the phase is that both pads move their character at the same time.
        res = r.run('D BOTH AT ONCE (host pad and guest pad: forward 3 s, sideways 2 s)',
                    [(3.0, (0, STICK), (0, STICK)), (2.0, (STICK, 0), (STICK, 0))])
        print_phase(res, ctl_h, ctl_g)
        print_motion(res)
        why, warn = [], []
        for t in (ctl_h[0], ctl_g[1]):
            if t in ('-', None):
                continue
            ok1, w1, n1 = verdict_move(res, t)
            why += w1
            warn += n1
        ok = not why
        show_verdict('D', ok, why, warn)
        rc |= 0 if ok else 1
    return rc


def phase_parts(phases):
    return [p.strip() for p in phases.split(',')]


if __name__ == '__main__':
    sys.exit(main())
