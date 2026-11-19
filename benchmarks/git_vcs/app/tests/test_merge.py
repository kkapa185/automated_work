"""merge: ugit vs real git (and known-answer text merges)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers import PairTest, needs_git  # noqa: E402
from test_switching import StateMixin  # noqa: E402
from ugitlib.merge3 import merge_text  # noqa: E402
from ugitlib.diff import split_lines  # noqa: E402


def mt(base, ours, theirs):
    lines, n = merge_text(split_lines(base.encode()), split_lines(ours.encode()), split_lines(theirs.encode()),
                          b"HEAD", b"topic")
    return b"".join(lines).decode(), n


class TextMergeKnownAnswers(unittest.TestCase):
    """Expected results follow from the diff3 definition (non-overlapping changes merge, overlapping
    or adjacent ones conflict, markers use `<<<<<<< HEAD` / `=======` / `>>>>>>> topic`)."""

    def test_disjoint_changes_merge(self):
        out, n = mt("1\n2\n3\n4\n5\n6\n7\n", "1\nA\n3\n4\n5\n6\n7\n", "1\n2\n3\n4\n5\nB\n7\n")
        self.assertEqual((out, n), ("1\nA\n3\n4\n5\nB\n7\n", 0))

    def test_identical_changes_merge(self):
        self.assertEqual(mt("a\nb\nc\n", "a\nX\nc\n", "a\nX\nc\n"), ("a\nX\nc\n", 0))

    def test_overlapping_conflict(self):
        out, n = mt("a\nb\nc\n", "a\nX\nc\n", "a\nY\nc\n")
        self.assertEqual(out, "a\n<<<<<<< HEAD\nX\n=======\nY\n>>>>>>> topic\nc\n")
        self.assertEqual(n, 1)

    def test_adjacent_changes_conflict(self):
        out, n = mt("a\nb\nc\nd\n", "a\nX\nc\nd\n", "a\nb\nY\nd\n")
        self.assertEqual(n, 1)
        self.assertEqual(out, "a\n<<<<<<< HEAD\nX\nc\n=======\nb\nY\n>>>>>>> topic\nd\n")

    def test_one_side_deletes_other_edits(self):
        out, n = mt("a\nb\nc\n", "a\nc\n", "a\nB\nc\n")
        self.assertEqual(out, "a\n<<<<<<< HEAD\n=======\nB\n>>>>>>> topic\nc\n")

    def test_zealous_refinement_moves_common_lines_out(self):
        out, n = mt("x\n", "p\nq\nr\n", "p\nZ\nr\n")
        self.assertEqual(out, "p\n<<<<<<< HEAD\nq\n=======\nZ\n>>>>>>> topic\nr\n")

    def test_add_add_with_empty_base(self):
        out, n = mt("", "one\n", "two\n")
        self.assertEqual(out, "<<<<<<< HEAD\none\n=======\ntwo\n>>>>>>> topic\n")

    def test_missing_trailing_newline_gets_one_inside_markers(self):
        out, n = mt("a\n", "b", "c")
        self.assertEqual(out, "<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> topic\n")


@needs_git
class Merge(StateMixin, PairTest):
    def base(self, files=None):
        files = files or {"f": "1\n2\n3\n4\n5\n", "g": "g\n", "keep": "k\n"}
        for n, c in files.items():
            self.put(n, c)
        self.both("add", ".")
        self.both("commit", "-m", "base")

    def branch_commit(self, branch, files, delete=(), msg=None):
        self.both("checkout", branch)
        for n, c in files.items():
            self.put(n, c)
        for n in delete:
            for d in self.dirs.values():
                os.unlink(os.path.join(d, n))
        self.both("add", "-A")
        self.both("commit", "-m", msg or "%s change" % branch)

    def setup_two(self, ours, theirs, odel=(), tdel=(), files=None):
        self.base(files)
        self.both("branch", "topic")
        self.branch_commit("master", ours, odel, "ours")
        self.branch_commit("topic", theirs, tdel, "theirs")
        self.both("checkout", "master")

    def merged(self, *args):
        self.both("merge", *args)
        self.same_state()

    def test_fast_forward_and_up_to_date(self):
        self.base()
        self.both("branch", "topic")
        self.branch_commit("topic", {"f": "1\n2\n3\n4\n5\n6\n", "new": "n\n"}, ["g"])
        self.both("checkout", "master")
        self.merged("topic")
        self.merged("topic")
        self.both("log", "--oneline")
        self.both("merge", "master")

    def test_ff_variants(self):
        self.base()
        self.both("branch", "topic")
        self.branch_commit("topic", {"f": "changed\n"})
        self.both("checkout", "master")
        self.both("merge", "--no-ff", "topic")
        self.same_state()
        self.both("reset", "--hard", "HEAD~1")
        self.both("merge", "--ff-only", "topic")
        self.same_state()

    def test_ff_only_fails(self):
        self.setup_two({"f": "1\nO\n3\n4\n5\n"}, {"g": "tg\n"})
        self.both("merge", "--ff-only", "topic")
        self.same_state()

    def test_clean_three_way(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n", "o": "ours only\n"}, {"f": "1\n2\n3\n4\nT5\n", "t": "theirs only\n"})
        self.merged("topic")
        self.both("log", "--format=%H %P %s")
        self.both("show", "--stat", "HEAD")

    def test_clean_merge_deletions(self):
        self.setup_two({"keep": "ko\n"}, {"f": "tf\n"}, [], ["g"])
        self.merged("topic")

    def test_message_variants(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.merged("topic", "-m", "custom message")
        self.both("log", "-1", "--format=%B")

    def test_merge_into_other_branch_name(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.both("checkout", "-b", "dev")
        self.merged("topic")
        self.both("log", "-1", "--format=%s")
        self.both("checkout", "master")
        self.both_git("tag", "-a", "-m", "tg", "rel", "topic")
        self.both("checkout", "-b", "dev2")
        self.merged("rel")
        self.both("log", "-1", "--format=%s")

    def test_merge_commit_by_sha(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        sha = self.git("rev-parse", "topic", cwd=self.dirs["g"]).text.strip()
        self.merged(sha)
        self.both("log", "-1", "--format=%s")

    def test_content_conflict(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n"}, {"f": "1\nT2\n3\n4\n5\n"})
        self.merged("topic")
        self.both("status")
        self.both("status", "-s")
        self.both("ls-files", "-u")

    def test_multiple_conflicts_and_clean_files(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n", "g": "go\n", "a": "a-ours\n"},
                       {"f": "1\nT2\n3\n4\nT5\n", "g": "gt\n", "b": "b-theirs\n"})
        self.merged("topic")
        self.both("status")

    def test_add_add_conflict(self):
        self.setup_two({"n": "ours new\n"}, {"n": "theirs new\n"})
        self.merged("topic")
        self.both("status")

    def test_add_add_identical_is_clean(self):
        self.setup_two({"n": "same\n"}, {"n": "same\n"})
        self.merged("topic")

    def test_modify_delete_conflicts(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n"}, {"keep": "kt\n"}, [], ["f"])
        self.merged("topic")
        self.both("status")
        self.both("ls-files", "-u")

    def test_delete_modify_conflict(self):
        self.setup_two({"g": "g-ours\n"}, {"f": "1\nT2\n3\n4\n5\n"}, ["f"], [])
        self.merged("topic")
        self.both("status")

    def test_both_delete_is_clean(self):
        self.setup_two({"keep": "o\n"}, {"f": "t\n"}, ["g"], ["g"])
        self.merged("topic")

    def test_binary_conflict(self):
        self.setup_two({"bin": b"\0ours\0"}, {"bin": b"\0theirs\0"}, files={"bin": b"\0base\0", "x": "x\n"})
        self.merged("topic")
        self.both("status")

    def test_mode_change_merge(self):
        self.setup_two({"f": "1\n2\n3\n4\nO5\n"}, {"g": "tg\n"})
        for d in self.dirs.values():
            os.chmod(os.path.join(d, "keep"), 0o755)
        self.both("commit", "-a", "-m", "chmod")
        self.merged("topic")

    def test_eof_newline_conflict(self):
        self.setup_two({"f": "1\n2\n3\n4\nO5"}, {"f": "1\n2\n3\n4\nT5\n"})
        self.merged("topic")

    def test_zealous_conflict_refinement_matches_git(self):
        base = "head\nx\ntail\n"
        self.setup_two({"f": "head\np\nq\nr\ntail\n"}, {"f": "head\np\nZ\nr\ntail\n"}, files={"f": base})
        self.merged("topic")
        self.assertIn("<<<<<<< HEAD\nq\n=======\nZ\n>>>>>>> topic",
                      open(os.path.join(self.dirs["u"], "f")).read())

    def test_adjacent_line_conflict_matches_git(self):
        self.setup_two({"f": "a\nX\nc\nd\n"}, {"f": "a\nb\nY\nd\n"}, files={"f": "a\nb\nc\nd\n"})
        self.merged("topic")

    def test_multi_hunk_mix(self):
        base = "".join("line %d\n" % i for i in range(1, 41))
        ours = base.replace("line 3\n", "ours 3\n").replace("line 20\n", "ours 20\n").replace("line 38\n", "ours 38\n")
        theirs = base.replace("line 10\n", "theirs 10\n").replace("line 20\n", "theirs 20\n").replace(
            "line 39\n", "theirs 39\nextra\n")
        self.setup_two({"f": ours}, {"f": theirs}, files={"f": base})
        self.merged("topic")

    def test_resolve_and_commit(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n"}, {"f": "1\nT2\n3\n4\n5\n"})
        self.merged("topic")
        self.put("f", "resolved\n")
        self.both("status")
        self.both("add", "f")
        self.both("status")
        self.both("commit", "--no-edit")
        self.same_state()
        self.both("log", "--format=%H %P %s")
        self.both("status")

    def test_resolve_with_message(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n"}, {"f": "1\nT2\n3\n4\n5\n"})
        self.merged("topic")
        self.put("f", "resolved\n")
        self.both("commit", "-a", "-m", "resolved merge")
        self.same_state()
        self.both("log", "-1", "--format=%P")

    def test_commit_with_unresolved_conflicts(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n"}, {"f": "1\nT2\n3\n4\n5\n"})
        self.merged("topic")
        self.both("commit", "-m", "x")
        self.both("merge", "topic")
        self.both("add", "f")
        self.both("merge", "topic")

    def test_abort(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n", "a": "a\n"}, {"f": "1\nT2\n3\n4\n5\n", "b": "b\n"})
        self.merged("topic")
        self.both("merge", "--abort")
        self.same_state()
        self.both("merge", "--abort")
        self.both("status")

    def test_abort_keeps_unrelated_local_changes(self):
        self.setup_two({"f": "1\nO2\n3\n4\n5\n"}, {"f": "1\nT2\n3\n4\n5\n"})
        self.put("keep", "local edit\n")
        self.merged("topic")
        self.both("merge", "--abort")
        self.same_state()

    def test_no_commit(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.merged("topic", "--no-commit")
        self.both("status")
        self.both("commit", "--no-edit")
        self.same_state()

    def test_dirty_worktree_refuses(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"f": "1\n2\n3\n4\nT5\n", "g": "tg\n"})
        self.put("g", "local edit\n")
        self.merged("topic")
        self.both("checkout", "--", "g")
        self.put("unrelated", "u\n")
        self.merged("topic")

    def test_dirty_unrelated_is_carried(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.put("keep", "local edit\n")
        self.merged("topic")

    def test_staged_changes_refuse(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.put("g", "staged\n")
        self.both("add", "g")
        self.merged("topic")

    def test_untracked_in_the_way(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"newfile": "tn\n"})
        self.put("newfile", "untracked\n")
        self.merged("topic")

    def test_ff_with_dirty_files(self):
        self.base()
        self.both("branch", "topic")
        self.branch_commit("topic", {"f": "ff change\n"})
        self.both("checkout", "master")
        self.put("f", "dirty\n")
        self.merged("topic")
        self.both("checkout", "--", "f")
        self.put("keep", "dirty keep\n")
        self.merged("topic")

    def test_errors(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.both("merge", "nonexistent")
        self.both("merge")
        self.both_git("checkout", "-q", "--orphan", "unrelated")
        self.both("commit", "--allow-empty", "-m", "unrelated root")
        self.both("merge", "topic")

    def test_criss_cross_multiple_bases(self):
        self.base({"f": "1\n2\n3\n4\n5\n6\n7\n8\n"})
        self.both("branch", "b")
        self.branch_commit("master", {"f": "m1\n2\n3\n4\n5\n6\n7\n8\n"}, msg="m1")
        self.branch_commit("b", {"f": "1\n2\n3\n4\n5\n6\n7\nb8\n"}, msg="b1")
        # cross merges so both tips have two merge bases
        self.both("checkout", "master")
        self.both("merge", "b", "-m", "master takes b")
        self.both("checkout", "b")
        self.both_git("merge", "-q", "--no-edit", "master~1")
        self.branch_commit("master", {"z": "z\n"}, msg="m2")
        self.branch_commit("b", {"y": "y\n"}, msg="b2")
        self.both("checkout", "master")
        self.merged("b")

    def test_merge_in_subdirectory(self):
        self.setup_two({"d/f": "1\nO2\n3\n"}, {"d/g": "tg\n", "d/f": "1\n2\n3\nT4\n"}, files={"d/f": "1\n2\n3\n"})
        self.both("merge", "topic", sub="d")
        self.same_state()

    def test_file_deleted_in_ours_untouched_in_theirs(self):
        self.setup_two({"keep": "o\n"}, {"f": "tf\n"}, ["g"], [])
        self.merged("topic")

    def test_reflog_matches_git(self):
        self.setup_two({"f": "O1\n2\n3\n4\n5\n"}, {"g": "tg\n"})
        self.merged("topic")
        self.both("checkout", "-b", "x")
        self.both("checkout", "master")
        self.both("reset", "--hard", "HEAD~1")
        self.assertEqual(self.git("reflog", cwd=self.dirs["g"]).text, self.git("reflog", cwd=self.dirs["u"]).text)
        self.assertEqual(self.git("reflog", "x", cwd=self.dirs["g"]).text,
                         self.git("reflog", "x", cwd=self.dirs["u"]).text)


if __name__ == "__main__":
    unittest.main()


@needs_git
class PreviousBranchAndPerf(StateMixin, PairTest):
    def test_switch_dash(self):
        self.put("a", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        self.both("branch", "other")
        for cmd in (["switch", "-"], ["checkout", "other"], ["checkout", "-"], ["switch", "other"],
                    ["switch", "-"], ["switch", "-"]):
            self.both(*cmd)
            self.same_state()

    def test_reflog_of_branches(self):
        self.put("a", "1\n")
        self.both("add", ".")
        self.both("commit", "-m", "x")
        self.both("branch", "b1")
        self.both("branch", "-m", "b1", "b2")
        self.both("checkout", "-b", "c1")
        self.both("branch", "-d", "b2")
        self.assertEqual(self.git("reflog", cwd=self.dirs["g"]).text, self.git("reflog", cwd=self.dirs["u"]).text)
        self.assertEqual(self.git("reflog", "c1", cwd=self.dirs["g"]).text,
                         self.git("reflog", "c1", cwd=self.dirs["u"]).text)

    def test_large_file_merge_is_fast(self):
        import time
        base = "".join("line %d\n" % i for i in range(30000))
        ours = base
        theirs = base
        for i in range(0, 30000, 500):
            ours = ours.replace("line %d\n" % i, "ours %d\n" % i)
        for i in range(250, 30000, 500):
            theirs = theirs.replace("line %d\n" % i, "theirs %d\n" % i)
        self.put("big", base)
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "topic")
        self.put("big", ours)
        self.both("commit", "-a", "-m", "ours")
        self.both("checkout", "topic")
        self.put("big", theirs)
        self.both("commit", "-a", "-m", "theirs")
        self.both("checkout", "master")
        t = time.time()
        r = self.ugit("merge", "topic", cwd=self.dirs["u"])
        self.assertEqual(r.rc, 0, r.etext)
        self.assertLess(time.time() - t, 30)
        self.git("merge", "topic", cwd=self.dirs["g"])
        self.same_state()

    def test_many_conflicts_large_file(self):
        import time
        base = "".join("line %d\n" % i for i in range(5000))
        self.put("big", base)
        self.both("add", ".")
        self.both("commit", "-m", "base")
        self.both("branch", "topic")
        self.put("big", base.replace("line 5", "ours 5"))
        self.both("commit", "-a", "-m", "ours")
        self.both("checkout", "topic")
        self.put("big", base.replace("line 5", "theirs 5"))
        self.both("commit", "-a", "-m", "theirs")
        self.both("checkout", "master")
        t = time.time()
        self.both("merge", "topic")
        self.assertLess(time.time() - t, 30)
        self.same_state()


class FileBecomesDirectory(PairTest):
    init_repos = False

    def test_file_replaced_by_directory_on_one_side_merges_cleanly(self):
        self.ugit("init", "-q", "u")
        u = self.dirs["u"]
        self.sb.write("u/x", "file\n")
        self.sb.write("u/keep", "k\n")
        self.ugit("add", ".", cwd=u)
        self.ugit("commit", "-q", "-m", "base", cwd=u)
        self.ugit("branch", "topic", cwd=u)
        self.sb.write("u/keep", "k2\n")
        self.ugit("commit", "-q", "-a", "-m", "ours", cwd=u)
        self.ugit("checkout", "-q", "topic", cwd=u)
        os.unlink(os.path.join(u, "x"))
        self.sb.write("u/x/inner", "dir\n")
        self.ugit("add", "-A", cwd=u)
        self.ugit("commit", "-q", "-m", "theirs", cwd=u)
        self.ugit("checkout", "-q", "master", cwd=u)
        before = self.ugit("status", "--porcelain", cwd=u).text
        r = self.ugit("merge", "topic", cwd=u)
        self.assertEqual(r.rc, 0)  # x was modified only by theirs (file -> dir): a clean change
