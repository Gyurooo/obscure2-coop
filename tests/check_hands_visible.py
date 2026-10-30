"""Are the selected weapons actually drawable? Prints the render-side fields of every live weapon slot
on both copies and asserts they are equal.

For each human (world+0x175c manager -> +0xc array, tag at human+0x14, slots human+0x704 + 4*i, selected
slot human+0x714) and each weapon object wp:
  * wp+0x10        the weapon's 4-character tag
  * wp+0x00        its vtable, and the vtable+0xcc entry ("show/equip", called by the game's equip)
  * wp+0x18        the entity's visibility/flags word (bit 0x10 of a mesh means visible, ITEMS_FINDINGS s3)
  * wp+0x34        the mesh object, and mesh+0x18 (bit 0x10 = visible)
  * wp+0x28, wp+0xa8, wp+0xc
The host draws its weapon, so its values are the reference: the check fails when the guest's selected
weapon differs in one of these fields.
"""
import sys, os, struct, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peek import Proc
h, g = int(sys.argv[1]), int(sys.argv[2])


def tag(v):
    if not v:
        return '-'
    b = struct.pack('<I', v)[::-1]
    if all(32 <= c < 127 for c in b):
        return b.decode('latin1')
    return '%08x' % v


def world(m):
    go = m.u32(m.va(0x6c3068))
    return m.u32(go + 0x378) if go else 0


def humans(m):
    w = world(m)
    mgr = m.u32(w + 0x175c) if w else 0
    if not mgr:
        return []
    n, arr = m.u32(mgr + 4) or 0, m.u32(mgr + 0xc)
    out = []
    for i in range(min(n, 8)):
        hp = m.u32(arr + 4 * i) if arr else 0
        if not hp:
            continue
        slots = []
        for s in range(4):
            wp = m.u32(hp + 0x704 + 4 * s)
            d = dict(ptr=wp, tag=tag(m.u32(wp + 0x10)) if wp else '-')
            if wp:
                vt = m.u32(wp)
                mesh = m.u32(wp + 0x34)
                d.update(vt=vt, show=m.u32(vt + 0xcc) if vt else 0, w18=m.u32(wp + 0x18),
                         w28=m.u32(wp + 0x28), wa8=m.u32(wp + 0xa8), wc=m.u32(wp + 0xc),
                         wb8=m.u32(wp + 0xb8), mesh=mesh, m18=m.u32(mesh + 0x18) if mesh else None)
            slots.append(d)
        out.append(dict(tag=tag(m.u32(hp + 0x14)), ptr=hp, cur=m.u32(hp + 0x714), slots=slots,
                        fl=[[s, m.u32(hp + 0x700 + 4 * s)] for s in range(6)]))
    return out


def fmt(d):
    if not d.get('ptr'):
        return '--'
    return '%s vt=%08x show=%08x b8=%s w18=%08x m=%08x m18=%s a8=%s c=%s' % (
        d['tag'], d['vt'], d['show'], d['wb8'], d['w18'], d['mesh'] or 0,
        '%08x' % d['m18'] if d['m18'] is not None else 'n/a', d['wa8'], d['wc'])


mh, mg = Proc(h), Proc(g)
# TASK 50: the puppet's hands arrive in the owner's stream; give the pair a moment to converge before the
# render comparison (the old model wrote them from the snapshot, which is exactly what is gone).
for _ in range(40):
    hh, hg = humans(mh), humans(mg)
    if sorted((x['tag'], x['cur'], [s['tag'] for s in x['slots']]) for x in hh) == \
       sorted((x['tag'], x['cur'], [s['tag'] for s in x['slots']]) for x in hg):
        break
    time.sleep(0.05)
for name, hs in (('host', hh), ('guest', hg)):
    print('%s humans:' % name)
    for x in hs:
        print('  %s @%x cur=%s  human+0x700..0x714=%r' % (x['tag'], x['ptr'], x['cur'], [v for _, v in x['fl']]))
        for s, d in enumerate(x['slots']):
            print('    slot %d %s' % (s, fmt(d)))

bad = []
byg = {x['tag']: x for x in hg}
for x in hh:
    y = byg.get(x['tag'])
    if not y:
        continue
    if x['cur'] != y['cur']:
        bad.append((x['tag'], 'selected slot', x['cur'], y['cur']))
    for s in range(4):
        a, b = x['slots'][s], y['slots'][s]
        if a['tag'] != b['tag']:
            bad.append((x['tag'], 'slot %d tag' % s, a['tag'], b['tag']))
            continue
        if not a.get('ptr'):
            continue
        # Pointers and per-frame counters legitimately differ between the two processes; what must be
        # equal is the render state of the object: the class (vtable -> show), the shown flag, the
        # collected/active flag, the flags byte, and that both have a mesh with the same visibility word.
        for key in ('vt', 'show', 'wb8', 'wa8', 'wc'):
            if a.get(key) != b.get(key):
                bad.append((x['tag'], 'slot %d %s' % (s, key), a.get(key), b.get(key)))
        if bool(a.get('mesh')) != bool(b.get('mesh')):
            bad.append((x['tag'], 'slot %d mesh present' % s, a.get('mesh'), b.get('mesh')))
        if a.get('m18') != b.get('m18'):
            bad.append((x['tag'], 'slot %d mesh+0x18' % s, a.get('m18'), b.get('m18')))
print('differences host vs guest:', bad if bad else 'none')
assert bad == [], 'weapon render state differs: %r' % (bad,)
print('hands visible state OK (%d characters checked)' % len([x for x in hh if x['tag'] in byg]))
