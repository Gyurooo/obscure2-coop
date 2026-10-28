#!/usr/bin/env python3
"""Decode an Obscure II input map (.ipt) and print it as a table.

Format (decoded in FINDINGS_24 section 1, from data/o2_input.ipt and the owner's real
Steam o2.ipt, both of which parse exactly with this layout):

  u32 version           1
  u32 action_count      200
  action_count x {
      u8  bound         0 = no binding for this action
                        1 = one binding follows
      u32 device        1 keyboard, 2 mouse, 3 gamepad 1, 4 gamepad 2
      u32 code          see CODES below
  }
  optional trailing words (the live o2.ipt has 5 extra words: the two pad devices 3, 4)

The action slots are grouped: 0x00-0x27 player 1, 0x28-0x4f player 2
(FUN_004a2b50 clears the block of `param_1` = 0 or 0x28, 0x27 entries;
FUN_004cf940 reads player actions as FUN_0059b3e0(in_ECX[5] + N) with the same 0x28 step),
0x50+ global/menu actions (0x51 INV_NEXT, 0x52 INV_PREV, 0x53/0x54, 0x59, 0x73 - the
names come from the string pool at 0x662348 in the exe, in that order).

Codes 1003-1030 are the X360 pad buttons, keyboard codes are DirectInput scancodes.
"""
import struct
import sys

# Codes 1003-1014 (0x3eb-0x3f6) are the six analog axes, +/- each: FUN_0059b4f0 switches on
# exactly these 12 codes and returns (is_axis, axis_pair). 1015-1030 (0x3f7-0x406) are buttons.
# A per-code name table exists in the exe (the string pool at 0x662348: PC_MOUSE1 ... X360_RT),
# but its order could not be tied to the code numbers here, so names stay numeric.
DEVICE_NAMES = {1: "keyboard", 2: "mouse", 3: "pad1", 4: "pad2"}


def parse(path):
    d = open(path, "rb").read()
    endian = "<" if path.lower().endswith(".t") else "<"
    ver, count = struct.unpack_from("<2I", d, 0)
    off = 8
    acts = []
    for _ in range(count):
        if off >= len(d):
            break
        n = d[off]
        off += 1
        pairs = []
        for _ in range(n):
            if off + 8 > len(d):
                break
            dev, code = struct.unpack_from("<2I", d, off)
            off += 8
            pairs.append((dev, code))
        acts.append(pairs)
    return ver, count, acts, d[off:], d


def parse_be(path):
    """The game's shipped data/o2_input.ipt is big-endian."""
    d = open(path, "rb").read()
    ver, count = struct.unpack_from(">2I", d, 0)
    off = 8
    acts = []
    for _ in range(count):
        n = d[off]
        off += 1
        pairs = []
        for _ in range(n):
            dev, code = struct.unpack_from(">2I", d, off)
            off += 8
            pairs.append((dev, code))
        acts.append(pairs)
    return ver, count, acts, d[off:], d


def name(dev, code):
    if dev in (3, 4):
        kind = "axis" if 1003 <= code <= 1014 else "btn"
        return "%s:%s%d" % (DEVICE_NAMES.get(dev, "dev%d" % dev), kind, code)
    return "%s:%d" % (DEVICE_NAMES.get(dev, "dev%d" % dev), code)


def block(i):
    if i < 0x28:
        return "P1"
    if i < 0x50:
        return "P2"
    return "global"


def main(argv):
    be = "--be" in argv
    files = [a for a in argv[1:] if not a.startswith("--")]
    for f in files:
        ver, count, acts, rest, d = (parse_be(f) if be else parse(f))
        print("== %s  %d bytes  version %d  actions %d  consumed %d  trailing %d bytes %s"
              % (f, len(d), ver, count, 8 + len(acts) + 8 * sum(map(len, acts)),
                 len(rest), rest.hex(" ") if rest else ""))
        for i, pairs in enumerate(acts):
            if not pairs:
                continue
            bs = ", ".join(name(dv, c) for dv, c in pairs)
            print("  %3d 0x%02x %-6s %s" % (i, i, block(i), bs))
        print("  bound actions: %d  of which pad1 %d  pad2 %d  keyboard %d  mouse %d"
              % (sum(1 for a in acts if a),
                 sum(1 for a in acts for dv, c in a if dv == 3),
                 sum(1 for a in acts for dv, c in a if dv == 4),
                 sum(1 for a in acts for dv, c in a if dv == 1),
                 sum(1 for a in acts for dv, c in a if dv == 2)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
