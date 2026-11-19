# Benchmark report — git/git

**Ticket:** [`task.md`](task.md) (VCS-42). It asks for a Git-compatible VCS (`./ugit`) that is byte-compatible with
git's object store and index (v2) in both directions, reads git's packfiles, and produces git-identical output
for init/add/rm/mv/commit/status/diff/log/show/cat-file/ls-files/ls-tree/rev-parse/branch/checkout/switch/
merge/tag/reset/restore/config. Calling git, libgit2 or dulwich was not allowed.

**Reference execution:** git 2.43, the same software as the `git/git` repo. The hidden harness
[`compare.py`](compare.py) plays a 90-step scripted scenario twice, once with real git and once with
`./ugit`, using fixed author/committer identities and dates. The scenario covers:
- ignore rules, staging, commits with bodies;
- fast-forward and three-way merges, and a conflicting merge with markers;
- annotated tags, rename/remove, soft/hard/mixed resets, restore and checkout of paths.

It compares:
- **every commit id**, read by real git;
- the output and exit status of every recorded command;
- `git fsck --strict` on the generated repository;
- real git reading the generated index and log;
- `./ugit` reading a repository that real git packed with `git gc --aggressive`;
- the fatal error outside a repository.

## Result (attempt 1): **score 1.00 (85/85)**
- All commit ids are identical to git's, including merge commits and annotated tags.
- All status, diff (Myers, unified), log, show, cat-file and ls-tree outputs are identical.
- `git fsck --strict` passes, and the generated `.git` is fully interoperable.
- Packed objects with OFS/REF deltas and `packed-refs` written by git are read correctly.

**Process:** milestone mode, 7 turns on one session. $15.20, about 23.5 h wall time. That includes three
automatic 5-hour usage-limit pauses and several VM reboots; the task resumed on the same session each
time.
