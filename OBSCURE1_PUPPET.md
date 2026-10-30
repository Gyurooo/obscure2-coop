# How the Obscure 1 co-op mod (owner's own, smooth in real Steam play) drives the remote character - port this to Obscure II

Source: `<local>\coopdll\src\sync.c` (Obscure 1, build 215286). Read it; addresses differ.

1. **The game's own update runs on the puppet with the owner's MOVE INTENT** (CPlayerHuman::Update hook, sync.c ~1663): the
   receiver writes the owner's intent (direction vectors, magnitude, moving flag, requested state) into the puppet's intent
   fields before its Update, so the game's own state machine picks the state AND the animation (walk/run blends, turns,
   transitions look natural). It does NOT set animation ids directly. A whitelist (`puppet_state_ok`) limits which requested
   states a puppet may run; interaction states get their local context (door: character+0x224 = the local copy of the door).
2. **Then the position is put back with the game's own setters** (`put_char`, sync.c ~1587): character vtable slot 2
   SetPosition(pos), the PHYSICS BODY (+0x68) slot 2 SetPosition(pos) unless the body is disabled (+0x6c), then the body's sub-object
   (+0x94) slot 2 update; and slot 3 SetDirection(dir). So the collision body is never left behind (the Obscure II stale-body bug).
3. **One-frame requests are replayed as events** (`host_record_wanted` / replay, sync.c ~90): an attack swing is a one-frame
   requested state; the owner records every change with a sequence number, the receiver replays missed ones in order, one per Update.
4. **Smoothing** (sync.c ~1341): 32 snapshots with the sender's time; show "sender time - delay", blend position and facing
   between the two snapshots around it; the delay = 90th percentile of packet lateness over ~2 s + one send interval, 20..200 ms.
   Performance-counter clock (GetTickCount is too coarse).

TASK 42's Obscure II puppet skips the movement state machine, sets the state id with the game's setter and raw-writes +0x23c
(no body). Points 1 and 2 are the difference. Obscure II equivalents found so far: SetPosition = CCharacterHuman vtable slot 4
(FUN_004c6880, updates the impact/collision manager at human+0x30c and the kinematic object human+0x124 - FINDINGS_45 §2).
