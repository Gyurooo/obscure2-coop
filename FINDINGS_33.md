# FINDINGS 33 — Inno Setup installer (TASK 33)

Base: `6d1f94d` (tag `v1.7`, protocol 17). No game source (`src/`, `relay/`) is changed by this task.
Labels: **OBSERVED** = printed by a run in this task or read in a file with a line reference;
**DERIVED** = follows from the code but was not exercised; **GUESS**; **UNKNOWN**.

## 0. What was added

| item | state |
|---|---|
| `package/obscoop2.iss` | new: the Inno Setup wizard (welcome -> licence -> game folder -> ready -> install -> finish) |
| `package/LICENSE.txt` | new: the MIT text, shown as the licence page (not installed into the game folder) |
| `tools/build_release.sh` | now also runs ISCC when `OBSCOOP_ISCC` is set and prints the setup's SHA-256 and size |
| `package/INSTALL.txt`, `package/README.txt` | the setup exe is the normal way in, SmartScreen note; version lines taken from `VERSION.txt` |

(work in progress - this file is filled in as the run goes; see the bottom for the results)
