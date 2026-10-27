"""Both copies hold the same weapons in their hands.

Reads, per live CCharacterHuman (world+0x175c manager):
  human+0x14  character tag
  human+0x704 4 weapon slot pointers; each weapon object carries its tag at +0x10
  human+0x714 current weapon slot
and the saved party records (progress+0x1b0c, stride 0x28: tag, weap0..3 at +0x14, current slot at +0x24).
Prints everything, then asserts that every character that exists on both copies has the same slot tags
and the same current slot.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import struct
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
            slots.append(tag(m.u32(wp + 0x10) if wp else 0))
        out.append(dict(ptr=hp, tag=tag(m.u32(hp + 0x14)), slots=slots, cur=m.u32(hp + 0x714)))
    return out


def records(m):
    go = m.u32(m.va(0x6c3068))
    p = m.u32(go + 0x318) if go else 0
    out = []
    for i in range(8):
        base = p + 0x1b0c + i * 0x28
        t = m.u32(base)
        if not t:
            continue
        out.append((tag(t), [tag(m.u32(base + 0x14 + 4 * s)) for s in range(4)], m.u32(base + 0x24)))
    return out


def inv(m):
    w = world(m)
    i = m.u32(w + 0x1790) if w else 0
    return m.u32(i + 4) if i else None


def inv_entries(m):
    """Every inventory entry as (index, first 16 bytes hex, decoded tag). Entries are 32 bytes
    (FUN_004b04a0: entry = inv + 8 + index*0x20; tag at entry+4)."""
    w = world(m)
    i = m.u32(w + 0x1790) if w else 0
    n = m.u32(i + 4) if i else 0
    out = []
    for k in range(min(n or 0, 99)):
        e = i + 8 + k * 0x20
        b = m.read(e, 16) or b'\0' * 16
        out.append((k, b.hex(), tag(m.u32(e + 4))))
    return n, out


def dump_inv(mh, mg):
    """Dumps both inventories: index, 16-byte hex of the entry, and its decoded tag."""
    for name, m in (('host', mh), ('guest', mg)):
        n, es = inv_entries(m)
        print('%s inventory: count %s (%d entries of 16 hex bytes, stride 0x20)' % (name, n, len(es)))
        for k, hx, t in es:
            print('  %s [%2d] %s  tag=%s' % (name, k, hx, t))


def held(x):
    c = x['cur']
    return x['slots'][c] if isinstance(c, int) and 0 <= c < 4 else '?'


mh, mg = Proc(h), Proc(g)
hh, hg = humans(mh), humans(mg)
print('host humans: ', [(x['tag'], x['slots'], x['cur']) for x in hh])
print('guest humans:', [(x['tag'], x['slots'], x['cur']) for x in hg])
print('in hand: host', [(x['tag'], held(x)) for x in hh], 'guest', [(x['tag'], held(x)) for x in hg])
bh = {x['tag']: held(x) for x in hh}
assert all(bh.get(x['tag']) == held(x) for x in hg), 'the weapon in the hand differs'
print('host records: ', records(mh))
print('guest records:', records(mg))
print('inventory: host', inv(mh), 'guest', inv(mg))
byg = {x['tag']: x for x in hg}
bad, checked = [], 0
for x in hh:
    y = byg.get(x['tag'])
    if not y:
        continue
    checked += 1
    if x['slots'] != y['slots'] or x['cur'] != y['cur']:
        bad.append((x['tag'], x['slots'], x['cur'], y['slots'], y['cur']))
if checked == 0:
    print('hands: NO character exists on both copies')
if bad:
    dump_inv(mh, mg)
assert bad == [], 'held weapons differ: %r' % (bad,)
assert any(any(s != '-' for s in x['slots']) for x in hh), 'host has no weapon in any hand either'
print('hands OK (%d characters checked)' % checked)
