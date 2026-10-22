import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

BOX = Path(__file__).resolve().parents[1] / "bin/box"


@unittest.skipUnless(shutil.which("zsh"), "box requires zsh")
class ThreadSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        db = self.home / ".t3/userdata/statev2.sqlite"
        db.parent.mkdir(parents=True)
        self.db = db
        with sqlite3.connect(db) as conn:
            conn.executescript("""
                CREATE TABLE projection_threads(thread_id,title,deleted_at);
                CREATE TABLE orchestration_v2_projection_threads(thread_id,title,deleted_at);
                CREATE TABLE projection_thread_messages(thread_id,text,created_at);
                CREATE TABLE orchestration_v2_projection_messages(thread_id,payload_json,created_at);
                CREATE TABLE projection_thread_sessions(thread_id,provider_session_id,provider_thread_id);
                CREATE TABLE orchestration_v2_projection_provider_threads(thread_id,payload_json);
            """)
            conn.executemany("INSERT INTO projection_threads VALUES (?,?,?)", [
                ("legacy", "A legacy title", None), ("deleted", "Boat.dev old title", None),
                ("current", "Outdated title", None)])
            conn.executemany("INSERT INTO orchestration_v2_projection_threads VALUES (?,?,?)", [
                ("current", "Boat.dev title", None), ("deleted", "Boat.dev deleted", "today"),
                ("transcript", "Claude tooling", None), ("literal", "Literal search", None)])
            conn.execute("INSERT INTO projection_thread_messages VALUES (?,?,?)",
                         ("legacy", "We talked about BOAT.DEV here", "2026-01-01"))
            conn.execute("INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?)",
                         ("current", json.dumps({"text": "another boat.dev mention"}), "2026-01-02"))
            conn.execute("INSERT INTO orchestration_v2_projection_provider_threads VALUES (?,?)",
                         ("transcript", json.dumps({"nativeThreadRef": {"nativeId": "session"}})))
        transcript = self.home / ".claude/projects/project/session.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('malformed\n' + json.dumps({"message": {"content": [
            {"type": "tool_result", "content": "boat.dev in tool output"}]}}) + '\n')
        self.machines = self.home / "machines"
        self.machines.write_text("remote fixture.local - default\n")
        # Simulate SSH's command-string parsing, not argv-preserving local execution.
        mockbin = self.home / "bin"
        mockbin.mkdir()
        for name, script in {
            "nc": "#!/bin/sh\nexit 0\n",
            "ssh": '#!/bin/sh\nshift 4\nexec bash -c "$*"\n',
        }.items():
            p = mockbin / name
            p.write_text(script)
            p.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), BOX_MACHINES=str(self.machines),
                        BOX_NO_TS_START="1", PATH=str(mockbin) + os.pathsep + os.environ["PATH"])
        self.env.pop("T3CODE_HOME", None)

    def search(self, query):
        return subprocess.run([str(BOX), "threads", "search", query], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def test_current_legacy_and_linked_transcript(self):
        before = self.db.read_bytes(), self.db.stat().st_mtime_ns
        result = self.search("boat.dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [line.split("\t") for line in result.stdout.splitlines()[1:]]
        self.assertEqual({r[1] for r in rows}, {"current", "legacy", "transcript"})
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r[0] == "remote" and "boat.dev" in json.loads(r[3]).lower() for r in rows))
        self.assertEqual(before, (self.db.read_bytes(), self.db.stat().st_mtime_ns))

    def test_query_survives_remote_shell_and_sql_literally(self):
        marker = self.home / "injected"
        query = "'%;_ $(touch " + str(marker) + "); `touch " + str(marker) + "`\nUnicode Straße"
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO orchestration_v2_projection_messages VALUES (?,?,?)",
                         ("literal", json.dumps({"text": "prefix " + query + " suffix"}), "today"))
        result = self.search(query.upper())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\tliteral\t", result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        self.assertFalse(marker.exists())

    def test_unreachable_is_reported(self):
        (self.home / "bin/nc").write_text("#!/bin/sh\nexit 1\n")
        result = self.search("anything")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreachable, skipped", result.stderr)

    def test_empty_query_rejected(self):
        result = self.search("  ")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("usage: box threads search", result.stderr)


if __name__ == "__main__":
    unittest.main()
