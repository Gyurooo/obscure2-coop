# Owner report while TASK 43 ran (2026-10-30)

The owner watched the test windows: **both characters do not show up on screen** in the tests. The puppet stats only compare
memory values (position, state id), so they can say "anim 100%" while the remote character is not drawn (or drawn elsewhere).

Reviewer snapshot of the live test logs at that moment (steam-link soak, TASK 43 build):
* host copy: `peer GIR1 ... drift mean 49-92 max 89-1054, 32 underruns, 548-566 extrapolated`
* guest copy: `peer BOY1 ... drift mean 450-552 max 844, anim 98%`

Next task must: take a screenshot of both windows (the mod's `request_shot` / pipe shot) while both characters should be in view,
and assert the remote character is visible (rendered, in the right place, not hidden / culled / at the origin / under the floor);
find why it is not drawn and fix it; add the visual check to check_movement so this can never pass silently again.
