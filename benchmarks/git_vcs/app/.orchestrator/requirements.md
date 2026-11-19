# VCS-42 requirements: `ugit`, a Git-compatible VCS

## Product
`./ugit` is a command-line version control tool written in Python 3 (stdlib only: zlib, hashlib, struct, os).
It reads/writes the standard `.git` layout (loose objects, packfiles v2 read-only, packed-refs, index v2,
config) so real git and ugit can operate on the same repository, and its output/exit codes match git 2.4x
for the supported commands. It never invokes git. The test-suite (unittest, runnable via `make test`)
validates against real git when available.

## Acceptance criteria
### Core / storage (M1)
R1. `./ugit` executable from the workspace root (python3 shebang launcher); package in `ugitlib/`.
R2. Loose objects: zlib-compressed `<type> <size>\0<content>`, SHA-1 ids identical to git; git can read them (`git fsck` clean) and vice versa.
R3. Read packed objects: `.idx` v2 + `.pack`, including OFS_DELTA and REF_DELTA; `packed-refs` (incl. peeled lines).
R4. Refs: HEAD (symbolic/detached), refs/heads, refs/tags, packed-refs; ref update writes loose ref file; reflog not required.
R5. Config: parse `.git/config` (sections, subsections, case-insensitive keys); `user.name`, `user.email`; `config [--get] <key> [value]` (get prints value exit 0; missing key exit 1; set writes file; `--list` bonus).
R6. Environment: GIT_AUTHOR_NAME/EMAIL/DATE, GIT_COMMITTER_*, GIT_DIR, GIT_WORK_TREE honoured. Dates `@1700000000 +0000`, `1700000000 +0000`, also ISO-ish `2023-11-14T22:13:20 +0000`/`YYYY-MM-DD HH:MM:SS +ZZZZ`. Default tz when no date given: local offset.
R7. Repository discovery walking up parent directories; outside a repo: `fatal: not a git repository (or any of the parent directories): .git`, exit 128.
R8. `init [-b <branch>] [dir]`: creates `.git` (HEAD, objects, refs/heads, refs/tags, config, description, hooks dir optional); default branch `master`; prints `Initialized empty Git repository in <abs>/.git/`; re-init prints `Reinitialized existing Git repository in ...`.
R9. `hash-object [-w] [-t type] [--stdin] <file>`, `cat-file -p|-t|-s|-e <obj>` (-p pretty for tree `mode type sha\tname`, commit/blob/tag raw), `rev-parse <rev>` incl. `HEAD`, `HEAD~N`, `HEAD^`, `HEAD^N`, `<branch>`, `<tag>`, `<tag>^{commit}`, `^{tree}`, abbreviated ids (>=4 hex, ambiguity error), `--git-dir`, `--show-toplevel`, `--abbrev-ref HEAD`, `--verify`.
### Index & worktree (M2)
R10. Index v2 read/write, byte-compatible with git: header, entries sorted by path (bytewise), stat data (ctime, mtime, dev, ino, mode, uid, gid, size), sha, flags (name length, stage), 1-8 NUL padding, trailing SHA-1 checksum; ignores/preserves extensions it can skip (TREE, etc.; dropped on write is OK). Git `status` clean after ugit `add` and vice versa. Reads stage 1/2/3 entries.
R11. `.gitignore` handling: patterns, negation, dir-only `/`, anchored, `**`, `*`,`?`,`[]`, nested .gitignore, `.git/info/exclude`; tracked files not ignored.
R12. `add <paths>|-A|.|-u`: files, dirs recursively, removed files with -A/-u; pathspec dir; ignored files skipped (error message `The following paths are ignored by one of your .gitignore files:` exit 1 when explicitly named); nonexistent path `fatal: pathspec 'x' did not match any files` exit 128. Symlinks (mode 120000) and executable bit (100755) supported.
R13. `rm [--cached] [-r] [-f]`: removes from index and worktree, prints `rm 'path'`; errors as git for dirs without -r (`fatal: not removing 'd' recursively without -r`), modified files (`error: the following file has local modifications:` ...).
R14. `mv <src> <dst>` (also into directory), updates index and worktree.
R15. `ls-files [-s] [-c|-o|-m|-d|--others --exclude-standard]` ; `-s` prints `mode sha stage\tpath`.
R16. `ls-tree [-r] [-t] [-d] [--name-only] <tree-ish>` format `mode type sha\tpath`.
### Commits & history (M3)
R17. `commit -m <msg> [-a] [--allow-empty] [--amend] [-F file]`: builds tree objects from index, writes commit with author/committer from env/config; prints `[branch abcdefg] subject` (`(root-commit)` for the first), then ` N file(s) changed, X insertions(+), Y deletions(-)` and ` create mode 100644 f` / ` delete mode` lines; multiple `-m` joined by blank line; message gets trailing newline; missing identity -> git's error text.  `nothing to commit, working tree clean` exit 1 (status output goes to stdout as git does); `no changes added to commit` variants as git.
R18. `status` long format exactly as git (branch line `On branch X` / `HEAD detached at <sha>`, `No commits yet`, `Changes to be committed:`, `Changes not staged for commit:`, `Untracked files:`, hints, `Unmerged paths:`, `nothing added to commit but untracked files present (use "git add" to track)`, etc.); `--porcelain`/`-s`/`--short`/`-b`/`--branch` short formats (`XY path`, `?? path`, renames not detected in worktree unless staged: staged renames detected as `R  old -> new`).
R19. `log` default format (`commit <sha>`, `Author:`, `Date:   Tue Nov 14 22:13:20 2023 +0000`, indented message), `--oneline`, `-n N`/`-N`/`--max-count=N`, `--format=`/`--pretty=format:` with %H %h %T %t %P %p %s %b %an %ae %ad %cn %ce %cd %at %ct %n %% %an %d(optional) ; `tformat` semantics; history ordering by commit date with parents (git's default order); `log <rev>`; `log -- path` optional; `--graph` not required.
R20. `show <rev>`: commit header + message + diff (`diff --git` patch against first parent, root commit vs empty; merges show combined header `Merge: a b` and no diff), `show <tag>` for annotated tags (tag header), `show <blob>`, `show <tree>` (`tree <rev>\n\nentries`), `rev:path`.
R21. `diff` (worktree vs index), `diff --cached|--staged [<commit>]`, `diff <commit> [<commit>]`, `diff <a>..<b>`, `-- <paths>`, `--stat`, `--name-only`, `--name-status`, `--no-index` optional. Headers: `diff --git a/x b/x`, `new file mode`, `deleted file mode`, `old mode/new mode`, `index abc1234..def5678 100644`, `--- a/x`/`+++ b/x` (`/dev/null` for add/delete), `@@ -l,s +l,s @@ funcname-free` (git's default hunk header with no funcname config prints text of previous line matching git's default funcname rule: a line beginning with alpha, `_` or `$`), binary files `Binary files a/x and b/x differ`, `\ No newline at end of file`. Diff uses Myers with git-compatible hunk merging (3 lines context; hunks within 2*ctx merged); also exact rename detection (identical blobs) in `diff --cached`/commit-diff (`rename from/to`, `similarity index 100%`) and fuzzy rename detection >=50% similarity as git does for `status`/`diff -M` default (git 2.4x diff.renames=true default for diff porcelain).
R22. Branches: `branch` list (`* cur`, sorted, two-space indent), `branch <name> [start]`, `branch -d|-D <name>` (`Deleted branch x (was abc1234).`; not-fully-merged error), `branch -m`, `branch --show-current`, `branch -v`; errors `fatal: a branch named 'x' already exists`, `fatal: not a valid object name: 'master'` on an unborn branch.
R23. `tag` listing (sorted), `tag <name> [<rev>]` lightweight, `tag -a -m <msg> <name>` annotated tag object (tagger from env/config), `tag -d`, `tag -l <pattern>`; `fatal: tag 'x' already exists`.
### Branch switching, merge, reset (M4)
R24. `checkout <branch>` (prints `Switched to branch 'x'`, or `Already on 'x'`), `checkout -b <new> [start]` (`Switched to a new branch 'x'`), `checkout <commit>` (detached HEAD, advice text on stderr `Note: switching to ...` + `HEAD is now at abc1234 subject`), `checkout [<commit>] -- <paths>`, refusing when local changes would be overwritten (`error: Your local changes to the following files would be overwritten by checkout:` ... `Aborting`, exit 1); correctly adds/removes files and empty directories; carries over non-conflicting local changes.
R25. `switch <branch>`, `switch -c <new> [start]`, `switch --detach`, `switch -` optional.
R26. `restore [--staged] [--worktree] [-s <src>] <paths>` ; `restore .`.
R27. `reset [--soft|--mixed|--hard] [<rev>] [-- paths]`: moves branch, resets index/worktree appropriately; `--hard` prints `HEAD is now at abc1234 subject`; mixed prints `Unstaged changes after reset:` listing `M\tfile`; `reset <paths>` unstages.
R28. `merge <branch>`: already up to date (`Already up to date.`), fast-forward (`Updating a..b` / `Fast-forward` + diffstat), true three-way merge (merge-base by commit graph, ort-like recursive on tree level, line-level diff3 merge of files; default message `Merge branch 'x'` and for a non-default current... always `Merge branch 'x'`; prints `Merge made by the 'ort' strategy.` + diffstat), conflicts: markers `<<<<<<< HEAD` / `=======` / `>>>>>>> x`, `CONFLICT (content): Merge conflict in f` + `Automatic merge failed; fix conflicts and then commit the result.`, exit 1, index stages 1/2/3, `.git/MERGE_HEAD`, `MERGE_MSG`; `commit` after resolve creates 2-parent commit; `merge --abort`; `--no-ff`, `--ff-only`, `-m`; add/delete & modify/delete conflicts, rename-free handling; refuses with uncommitted conflicting changes; `status` shows `You have unmerged paths.` / `All conflicts fixed but you are still merging.`
### Quality (M5)
R29. Errors & exit codes like git: 128 for fatal, 1 for nothing-to-commit/diff conflicts, 129 for usage errors; unknown command `ugit: 'x' is not a git command`-style (`git: 'x' is not a git command. See 'git --help'.`, 1 ... 1 exit status as git: 1). Messages on stderr as git does.
R30. Interop tests: for every command a test builds repos with real git and ugit and compares stdout, exit status, index bytes ls-files, object ids; `git fsck` passes on ugit-created repos; ugit reads git-created packs (`git gc`, `git repack -ad`, deltas) and packed-refs.
R31. README describing object formats, index format, pack reading, diff algorithm (Myers + hunk assembly), merge algorithm (merge-base, three-way diff3), how to test; Makefile with `make test`.
R32. Performance: handle repos with thousands of files / MB-size files in reasonable time (index stat-cache used to skip rehash).

## Assumptions
A1. Python 3.10+, stdlib only; target output of git 2.4x with default config (no colour, `diff.renames` default true, `init.defaultBranch` ignored: `init` default `master` per ticket).
A2. Merge strategy name printed as `ort`. Rename detection in merge is not required (modify/delete conflicts etc. handled by path).
A3. `core.filemode` honoured from config (default true); symlinks supported on Linux.
A4. Where the ticket is silent on pager/colour: never use a pager and never colour.
A5. Hint/advice text printed like git 2.4x (advice enabled by default), on stderr where git uses stderr.
A6. Tests that need real git skip when git is missing; known-answer vectors (SHA-1 of `blob 0\0` = e69de29..., `hello\n` blob = ce013625030ba8dba906f756967f9e9ca394464a, empty tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904) are asserted directly.

## Test strategy
- unit tests (R2,R3,R5,R6,R10,R11, diff/merge algos): `tests/test_*.py` unittest.
- integration/differential tests (R8-R28): run `./ugit` and `git` in parallel temp repos with fixed env dates, compare outputs/exit codes/objects/index.
- error-path tests (R7,R12,R13,R17,R29).
- Run with `make test` (`python3 -m unittest discover -s tests`).
