import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "reapers/reap-stale-tmp"
loader = importlib.machinery.SourceFileLoader("reap_stale_tmp", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
reaper = importlib.util.module_from_spec(spec)
loader.exec_module(reaper)


@unittest.skipUnless(sys.platform.startswith("linux") and os.getuid() != 0, "Linux user reaper")
class ReaperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="box-reaper-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "tmp"
        self.root.mkdir()
        self.cutoff = time.time() - 2 * 86400
        self.old = self.cutoff - 3600
        self.uid, self.dev = os.getuid(), self.root.stat().st_dev
        self.runtime = patch.dict(os.environ, XDG_RUNTIME_DIR=self.tmp.name)
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def age(self, path):
        for directory, dirs, files in os.walk(path, topdown=False):
            for name in dirs + files:
                os.utime(Path(directory) / name, (self.old, self.old), follow_symlinks=False)
            os.utime(directory, (self.old, self.old))

    def tree(self, name="stale"):
        path = self.root / name
        (path / "nested").mkdir(parents=True)
        (path / "nested/file").write_bytes(b"x" * 8192)
        self.age(path)
        return path

    def scan(self, path, uid=None, dev=None):
        return reaper.old_tree(path, self.uid if uid is None else uid,
                               self.dev if dev is None else dev, self.cutoff)

    def run_reaper(self, dry=False, refs=None, extra=()):
        output = io.StringIO()
        with patch.object(reaper, "open_refs", return_value=refs or set()), contextlib.redirect_stdout(output):
            code = reaper.main((["--dry-run"] if dry else []) + list(extra), root=self.root)
        self.assertEqual(code, 0)
        return output.getvalue()

    def test_large_runs_print_only_the_largest_entries_and_summary(self):
        # regression: jarvis's first run printed ~63k lines; journald dropped the summary and errors
        for i in range(reaper.SHOWN + 5):
            self.tree(f"stale-{i}")
        big = self.tree("big")
        (big / "nested/more").write_bytes(b"x" * 65536)
        self.age(big)
        output = self.run_reaper(dry=True)
        listed = [line for line in output.splitlines() if line.startswith("would remove ")]
        self.assertEqual(len(listed), reaper.SHOWN)
        self.assertIn("'" + str(big) + "'", listed[0])
        self.assertIn("... and 6 smaller entries", output)
        self.assertIn(f"{reaper.SHOWN + 6} entries", output)
        everything = self.run_reaper(dry=True, extra=["--list"])
        self.assertEqual(len([l for l in everything.splitlines() if l.startswith("would remove ")]), reaper.SHOWN + 6)

    def test_nested_mtime_and_atime_keep_whole_tree(self):
        for clock in ("mtime", "atime"):
            with self.subTest(clock=clock):
                path = self.tree(clock)
                leaf = path / "nested/file"
                now = time.time()
                os.utime(leaf, (now, self.old) if clock == "atime" else (self.old, now))
                self.assertIsNone(self.scan(path))
                self.run_reaper()
                self.assertTrue(path.exists())

    def test_dry_run_preserves_atime_and_real_removal_logs_size(self):
        path = self.tree()
        before = (path.stat().st_atime_ns, (path / "nested").stat().st_atime_ns)
        output = self.run_reaper(dry=True)
        self.assertIn("would remove", output)
        self.assertTrue(path.exists())
        self.assertEqual(before, (path.stat().st_atime_ns, (path / "nested").stat().st_atime_ns))
        self.assertIsNotNone(self.scan(path))
        output = self.run_reaper()
        self.assertFalse(path.exists())
        self.assertIn("removed", output)
        self.assertRegex(output, r"freed ~[1-9][0-9]* bytes")

    def test_socket_symlink_and_protected_names_are_kept(self):
        path = self.tree()
        sock = socket.socket(socket.AF_UNIX)
        self.addCleanup(sock.close)
        sock.bind(str(path / "sock"))
        self.age(path)
        self.assertIsNone(self.scan(path))
        link = self.root / "link"
        link.symlink_to(path, target_is_directory=True)
        self.assertIsNone(self.scan(link))
        for name in ("tmux-1000", "ssh-xyz", "systemd-private-xyz", ".X11-unix", ".ICE-unix"):
            self.tree(name)
        output = self.run_reaper()
        self.assertIn("0 entries", output)
        self.assertTrue(all((self.root / name).exists() for name in ("stale", "link", "tmux-1000")))

    def test_foreign_descendant_and_device_are_kept(self):
        path = self.tree()
        self.assertIsNone(self.scan(path, uid=self.uid + 1))
        self.assertIsNone(self.scan(path, dev=self.dev + 1))
        original = os.stat

        def foreign(name, **kwargs):
            result = original(name, **kwargs)
            if str(name) == "file":
                values = list(result)
                values[4] = self.uid + 1
                return os.stat_result(values)
            return result

        with patch.object(reaper.os, "stat", side_effect=foreign):
            self.assertIsNone(self.scan(path))

    def test_nested_bind_mount_is_kept_even_on_same_device(self):
        path = self.tree()
        with patch.object(reaper, "mounted_paths", return_value={path / "nested"}):
            self.assertIn("0 entries", self.run_reaper())
        self.assertTrue(path.exists())

    def test_live_cwd_and_open_file_are_protected_by_inode(self):
        path = self.tree()
        process = subprocess.Popen([sys.executable, "-c",
                                    "import os,sys,time; f=open(sys.argv[1]); os.chdir(sys.argv[2]); "
                                    "print('ready',flush=True); time.sleep(60)",
                                    str(path / "nested/file"), str(path / "nested")], stdout=subprocess.PIPE, text=True)
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.wait)
        self.addCleanup(process.terminate)
        self.assertEqual(process.stdout.readline().strip(), "ready")
        # Keep timestamps old even though a live process just opened the tree.
        self.age(path)
        refs = reaper.open_refs()
        for entry in (path / "nested", path / "nested/file"):
            s = entry.stat()
            self.assertIn((s.st_dev, s.st_ino), refs)
        self.assertIn("kept 1 busy", self.run_reaper(refs=refs))
        self.assertTrue(path.exists())

    def test_incomplete_process_scan_aborts_without_deletion(self):
        path = self.tree()
        with patch.object(reaper, "open_refs", side_effect=RuntimeError("hidden process")), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(reaper.main([], root=self.root), 1)
        self.assertTrue(path.exists())
        self.assertIn("removed nothing", err.getvalue())

    def test_changed_tree_is_kept(self):
        path = self.tree()

        def touch():
            (path / "new").write_text("new activity")
            return set()

        with patch.object(reaper, "open_refs", side_effect=touch), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(reaper.main([], root=self.root), 0)
        self.assertTrue(path.exists())
        self.assertIn("1 changed during scan", out.getvalue())


if __name__ == "__main__":
    unittest.main()
