# VCS-42: A Git-compatible version control system

Implement a version control tool, executable as `./ugit` from the workspace root (any language; do not
shell out to, link, or embed git/libgit2/dulwich/go-git/gitoxide/JGit). It must be **interoperable with
Git**: it reads and writes the standard `.git` layout so that real `git` can work on repositories it
creates and vice versa, and its command-line behaviour and output match `git` 2.4x for the commands
below. The Git documentation (man pages) is the normative reference.

* Object store: loose zlib-compressed `blob`, `tree`, `commit`, `tag` objects with SHA-1 ids identical to
  git's for identical content; reading packed objects and packed refs written by git (`objects/pack/*.idx`
  v2 + `.pack` incl. OFS/REF deltas, `packed-refs`) is required; writing packs is not.
* Index: the binary `.git/index` (version 2) compatible with git in both directions (stat data, mode,
  sha, flags, sorted entries); `.gitignore` handling.
* Environment: honour `GIT_AUTHOR_NAME/EMAIL/DATE`, `GIT_COMMITTER_NAME/EMAIL/DATE`, `GIT_DIR`,
  `GIT_WORK_TREE`, and `user.name/user.email` from `.git/config`; dates like `@1700000000 +0000` or
  `1700000000 +0000`.
* Commands & options (output identical to git, including headers, spacing and colour-less formatting):
  `init [-b <branch>] [dir]` (default branch `master`), `add <paths>|-A|.`, `rm [--cached] [-r]`, `mv`,
  `commit -m <msg> [-a] [--allow-empty] [--amend]`, `status` (long format and `--porcelain`/`-s`),
  `diff` (worktree vs index), `diff --cached|--staged`, `diff <commit> <commit>`, unified format with
  correct hunks (Myers algorithm, 3 lines of context, `\ No newline at end of file`), `log` (default
  format, `--oneline`, `-n`, `--format=%H %h %s %an %ae %ad`, `--graph` not required), `show <rev>`,
  `cat-file -p|-t|-s`, `hash-object [-w]`, `ls-files [-s]`, `ls-tree [-r] <tree-ish>`, `rev-parse
  <rev>` (incl. `HEAD~2`, `HEAD^`, `<branch>`, abbreviated ids), `branch [-d] [name]` and listing,
  `checkout <branch>|-b <new>|<commit> -- <paths>`, `switch [-c]`, `merge <branch>` (fast-forward,
  three-way merge with the default `Merge branch '<name>'` message, conflicts written with standard
  markers and exit status 1), `tag [-a -m <msg>] <name>` and listing, `reset [--soft|--mixed|--hard]
  <rev>`, `restore [--staged]`, `config [--get] <key> [value]`.
* Errors and exit codes like git (e.g. `fatal: not a git repository (or any of the parent directories):
  .git` with status 128, `nothing to commit, working tree clean` with status 1).

Deliverables: the tool, an integration test-suite (ideally validating against real git where available),
and a README describing the object/index formats and the diff and merge algorithms.
