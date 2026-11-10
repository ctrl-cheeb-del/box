import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "reapers/reap-merged-worktrees"
loader = importlib.machinery.SourceFileLoader("reap_merged_worktrees", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
reaper = importlib.util.module_from_spec(spec)
loader.exec_module(reaper)

OLD = time.time() - 10 * 86400


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class ReapMergedWorktreesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="box-wt-reaper-test-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.runtime = patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.base), GIT_AUTHOR_NAME="t",
                                  GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        self.runtime.start()
        self.addCleanup(self.runtime.stop)
        self.remote = self.base / "remote.git"
        sh(self.base, "git", "init", "-q", "--bare", "-b", "main", str(self.remote))
        self.repo = self.base / "repo"
        sh(self.base, "git", "clone", "-q", str(self.remote), str(self.repo))
        (self.repo / ".gitignore").write_text("node_modules/\n")
        (self.repo / "a").write_text("a")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-qm", "init")
        sh(self.repo, "git", "push", "-q", "origin", "HEAD:main")
        self.root = self.base / "worktrees"
        (self.root / "proj").mkdir(parents=True)
        self.db = self.base / "state.sqlite"
        with sqlite3.connect(self.db) as conn:
            conn.execute("CREATE TABLE orchestration_v2_projection_threads "
                         "(archived_at, deleted_at, payload_json)")
        self.prs = {}
        self.cwds = set()

    def worktree(self, name, push=True, commit=True):
        path = self.root / "proj" / name
        sh(self.repo, "git", "worktree", "add", "-q", "-b", name, str(path))
        (path / "node_modules").mkdir()
        (path / "node_modules/big").write_text("x" * 4096)
        if commit:
            (path / name).write_text(name)
            sh(path, "git", "add", name)
            sh(path, "git", "commit", "-qm", name)
        if push:
            sh(path, "git", "push", "-q", "origin", name)
        return path

    def age(self, path):
        gitdir = Path(subprocess.check_output(["git", "-C", str(path), "rev-parse", "--absolute-git-dir"],
                                              text=True).strip())
        for p in (path, gitdir / "index", gitdir / "HEAD", gitdir / "logs/HEAD"):
            if p.exists():
                os.utime(p, (OLD, OLD))

    def thread(self, path, deleted=False, archived=False):
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?)",
                         ("x" if archived else None, "x" if deleted else None,
                          json.dumps({"worktreePath": str(path)})))

    def run_reaper(self, *argv):
        out = io.StringIO()
        with patch.object(reaper, "pr_states", return_value=self.prs), \
                patch.object(reaper, "process_cwds", return_value=self.cwds), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = reaper.main(list(argv), root=self.root, db=self.db)
        return code, out.getvalue()

    def test_merged_clean_idle_worktree_is_removed_with_its_node_modules(self):
        path = self.worktree("merged")
        self.thread(path)  # a live thread doesn't keep it once the PR merged
        self.prs["merged"] = {"merged"}
        self.age(path)
        code, out = self.run_reaper()
        self.assertEqual(code, 0, out)
        self.assertFalse(path.exists())
        self.assertIn("removed 1", out)
        listed = subprocess.check_output(["git", "-C", str(self.repo), "worktree", "list"], text=True)
        self.assertNotIn(str(path), listed)

    def test_dry_run_removes_nothing(self):
        path = self.worktree("merged")
        self.prs["merged"] = {"merged"}
        self.age(path)
        code, out = self.run_reaper("--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(path.exists())
        self.assertIn("would remove", out)

    def test_unsafe_worktrees_are_kept(self):
        dirty = self.worktree("dirty")
        (dirty / "a").write_text("edited")
        untracked = self.worktree("untracked")
        (untracked / "new-file").write_text("not committed")
        recent = self.worktree("recent")
        busy = self.worktree("busy")
        self.cwds.add(str(busy / "sub"))
        reopened = self.worktree("reopened")
        for name in ("dirty", "untracked", "recent", "busy"):
            self.prs[name] = {"merged"}
        self.prs["reopened"] = {"closed", "open"}
        live = self.worktree("live-no-pr")
        self.thread(live)
        for path in (dirty, untracked, busy, reopened, live):
            self.age(path)
        code, out = self.run_reaper()
        self.assertEqual(code, 0, out)
        for path in (dirty, untracked, recent, busy, reopened, live):
            self.assertTrue(path.exists(), path)
        self.assertIn("removed 0", out)

    def test_deleted_thread_goes_only_when_everything_is_pushed(self):
        pushed = self.worktree("pushed")
        unpushed = self.worktree("unpushed", push=False)
        for path in (pushed, unpushed):
            self.thread(path, deleted=True)
            self.age(path)
        code, out = self.run_reaper()
        self.assertEqual(code, 0, out)
        self.assertFalse(pushed.exists())
        self.assertTrue(unpushed.exists())

    def test_archived_thread_without_pr_is_kept(self):
        path = self.worktree("archived")
        self.thread(path, archived=True)
        self.age(path)
        self.run_reaper()
        self.assertTrue(path.exists())

    def test_unreadable_thread_db_removes_nothing(self):
        path = self.worktree("merged")
        self.prs["merged"] = {"merged"}
        self.age(path)
        self.db.write_text("not a database")
        code, out = self.run_reaper()
        self.assertEqual(code, 1)
        self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
