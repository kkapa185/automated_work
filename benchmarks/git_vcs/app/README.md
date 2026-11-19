# ugit — a Git-compatible version control system

`ugit` is a from-scratch implementation of a large part of Git in pure Python 3.10+ (standard library
only). It reads and writes the standard `.git` layout, so real `git` and `ugit` can work on the same
repository, and its command-line output and exit codes follow `git` 2.4x. It never runs, links or embeds
git; real git is used **only by the test-suite** to check interoperability (tests that need it are skipped
when `git` is not installed).

```
./ugit init -b main demo && cd demo
../ugit add . && ../ugit commit -m "first"
../ugit log --oneline
```

## Install, run, test
* Nothing to install (`requirements.txt` documents that there are no dependencies). `./ugit` is a
  Python launcher; run it from any directory (or put it on `PATH`).
* Tests: `make test` (= `python3 -m unittest discover -s tests`). Useful extras:
  `python3 tests/smoke.py` (end-to-end smoke run), `FUZZ_SEEDS=10:60 python3 -m unittest
  test_fuzz_workflow` from `tests/` (more random differential sequences).
* `UGIT_DEBUG=1` re-raises internal errors with a traceback (normally they print `fatal: internal error`).

## Commands
`init [-b branch] [--bare] [dir]`, `add [-A|-u|-f|-n|-v] <paths>`, `rm [--cached] [-r] [-f] [-n]`, `mv`,
`commit [-m]… [-a] [-F] [--allow-empty] [--amend] [--author] [--date]`, `status` (long, `-s`,
`--porcelain`, `-b`, `-z`, `-u<mode>`, `--ignored`), `diff` (worktree/index/commits, `--cached`, `a..b`,
`a...b`, `--stat/--numstat/--shortstat/--name-only/--name-status/--summary`, `-U<n>`),
`log` (ranges, `--oneline`, `-n`, `--format/--pretty`, `--date`, `--all`, `-p`, `--stat`, paths),
`show`, `cat-file`, `hash-object`, `ls-files`, `ls-tree`, `rev-parse`, `branch`, `tag`, `checkout`,
`switch`, `restore`, `reset`, `merge`, `config`. Honoured environment: `GIT_AUTHOR_*`,
`GIT_COMMITTER_*` (names, emails, dates such as `@1700000000 +0000`), `GIT_DIR`, `GIT_WORK_TREE`,
`GIT_INDEX_FILE`, `HOME`/`XDG_CONFIG_HOME` (global config), `user.name`/`user.email`.

Exit codes follow git: `128` for `fatal:` errors (e.g. `fatal: not a git repository (or any of the parent
directories): .git`), `129` for usage errors, `1` for "nothing to commit", merge conflicts, `diff --exit-code`
and unknown commands.

## Repository formats

**Loose objects** – `objects/ab/cdef…` is `zlib(<type> <size>\0<body>)`; the object id is the SHA-1 of the
*uncompressed* bytes `<type> <size>\0<body>`. Tree bodies are `<octal mode> <name>\0<20-byte id>` entries
sorted bytewise with directories compared as if their name ended in `/`; commits are header lines
(`tree`, `parent`*, `author`, `committer`) + blank line + message; tags carry `object/type/tag/tagger`.
(`ugitlib/objects.py`)

**Packs (read-only)** – `.idx` v2: magic `\377tOc`, version 2, 256-entry fan-out table, sorted 20-byte ids,
CRC-32s, 32-bit offsets (MSB set ⇒ index into a 64-bit table). `.pack`: per object a varint type/size header;
types 1–4 are whole objects, 6 is `OFS_DELTA` (negative offset, git's offset varint) and 7 is `REF_DELTA`
(base id). Deltas are applied iteratively (copy/insert opcodes). Alternates are honoured.

**Refs** – loose files under `refs/`, `packed-refs` (with `^` peel lines ignored), symbolic `HEAD`.
Writes go to a `.lock` file and are renamed into place; ugit always writes loose refs, which shadow packed
ones. Reflogs (`logs/HEAD`, `logs/refs/heads/*`) are written in git's format so `git reflog`, `checkout -`
and git's "HEAD detached at …" work on ugit-made repositories.

**Index (`.git/index`)** – `DIRC`, version (2 written; 3 with extended flags and 4 with prefix-compressed
paths are read), entry count; each entry is ten big-endian 32-bit words (ctime s/ns, mtime s/ns, dev, ino,
mode, uid, gid, size), the 20-byte id, 16 flag bits (assume-valid, extended, 2 stage bits, 12 name-length
bits) and the path, NUL-padded so that every entry is a multiple of 8 bytes; entries sorted bytewise by
path then stage; a SHA-1 checksum of everything before it closes the file. Extensions are skipped on read
and not written (git rebuilds them). Stat data is stored exactly as git expects so `git status` reports a
clean tree after `ugit add`; entries whose mtime is not older than the index file ("racy") are re-hashed
instead of trusted. (`ugitlib/index.py`)

**Config** – INI-like files with quoted subsections, escapes, comments and continuation lines; lookups are
layered system → global → local → `-c`. `config` edits files in place, preserving unrelated lines.

## Algorithms

**Diff (`ugitlib/diff.py`)** – lines are interned to integers; the common prefix/suffix is trimmed and
lines occurring on one side only are marked changed up front (so heavy edits stay cheap). The rest runs
Myers' O(ND) algorithm in its linear-space bidirectional "middle snake" form with the same tie-breaking and
cost cut-off as xdiff (beyond a cost of max(256, √n) the search splits at the most advanced path). The
resulting change groups are *compacted*: a group is slid up/down across identical lines, merged with
neighbours, aligned with the other file's groups, and — when several positions are equivalent — placed by
git's indent heuristic (blank-line/indentation scoring). Hunks carry 3 lines of context, adjacent hunks
merge when the gap is ≤ 6 lines, headers are `@@ -a,b +c,d @@ <function line>` (the nearest earlier line that
starts with a letter, `_` or `$`), and a missing final newline prints `\ No newline at end of file`. Renames:
identical blobs pair first (preferring equal basenames); remaining deleted/added files are compared by
64-byte/line span hashing and paired greedily when ≥ 50% similar. `--stat` scales to 80 columns like git.

**Merge (`ugitlib/merge3.py`, `commands/merge.py`)** – merge bases come from the commit graph (common
ancestors that are not ancestors of another); several bases are folded into a virtual base recursively.
Per path (no rename detection): equal results or one-sided changes resolve trivially; otherwise a three-way
line merge diffs base→ours and base→theirs with the engine above, groups hunks that overlap **or touch**
into clusters, applies single-sided clusters, accepts identical ones and turns the rest into conflicts. A
conflict is refined ("zealous"): ours/theirs are diffed against each other and lines they agree on move out
of the markers, leaving `<<<<<<< HEAD` / `=======` / `>>>>>>> <name>` blocks only around the differing
parts. Modify/delete, add/add, binary and mode conflicts keep index stages 1–3, write `MERGE_HEAD`,
`MERGE_MSG` (`# Conflicts:` list) and `ORIG_HEAD`, print git's `CONFLICT (...)` lines and exit 1. Fast
forwards print `Updating a..b` / `Fast-forward` with a diffstat; real merges create a two-parent commit
(`Merge branch 'x'`, plus ` into <branch>` off the default branch).

**Switching (`ugitlib/checkout.py`)** – branch switches use git's two-way-merge rules: a path moves to the
target unless local work would be lost (modified worktree file, staged change differing from both trees,
untracked file in the way); everything else is carried over, and nothing is touched unless the whole plan
is acceptable. `checkout <tree> -- paths` overlays, `restore --source` mirrors.

## Tests (what covers what)
* `test_objects`, `test_dates_config`, `test_repo_cli` – object model, packs (OFS/REF deltas written by
  git), refs, config, dates, discovery (R1–R9).
* `test_index`, `test_ignore`, `test_staging` – index bytes, ignore rules, add/rm/mv/ls-files/ls-tree (R10–R16).
* `test_commit_status`, `test_diff`, `test_history` – commit/status/diff/log/show/branch/tag, algorithm
  known-answer tests and fuzz against `git diff` (R17–R23).
* `test_switching`, `test_merge` – checkout/switch/restore/reset/merge incl. conflicts (R24–R28).
* `test_errors`, `test_interop`, `test_fuzz_workflow`, `test_perf` – exit codes/messages, both tools on one
  repository, randomised command sequences compared with git, scalability (R29–R32).
Differential tests run the same commands with `git` and `ugit` on twin repositories and compare stdout,
stderr, exit status, object ids, index contents and worktree state.

## Limitations / assumptions
No rename detection during merge (a rename plus an edit on the other side shows as delete/modify);
file/directory merge conflicts are refused; no combined (`--cc`) diff for unmerged paths; no octopus merges,
`--squash`, interactive modes, submodules (nested repositories are skipped), pack writing or `gc`.
`show` of a merge prints no patch (only stat-like formats use the first parent). Commit messages come from
`-m/-F`/merge state only (no editor). Authors without configured identity get git's "Author identity
unknown" message (no hostname auto-detection). Never uses a pager or colour. Global/system git config files
are read like git does. Usage text printed with exit 129 is shortened to the first line.
