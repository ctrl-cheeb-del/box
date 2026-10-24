"""Linux/macOS integration tests using real processes, isolated state and tiny jobs."""
import importlib.machinery
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import shutil
import sqlite3
from unittest import mock

QUEUE = Path(__file__).resolve().parents[1] / "bin/heavy-check"


@unittest.skipUnless(sys.platform in ("linux", "darwin"), "queue supports Linux and macOS")
class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config.json"
        self.configure()
        self.env = os.environ | {"HEAVY_CHECK_STATE": str(self.root / "state"), "HEAVY_CHECK_CONFIG": str(self.config)}
        self.ids = []

    def configure(self, slots=2, reserve=0):
        self.config.write_text(json.dumps({"slots": slots, "reserve_gib": reserve, "headroom_gib": 0}))

    def cli(self, *args, cwd=None, check=True):
        return subprocess.run([sys.executable, str(QUEUE), *args], env=self.env, cwd=cwd or self.root,
                              text=True, capture_output=True, timeout=15, check=check)

    def submit(self, code, cwd=None):
        job = self.cli("submit", "--", sys.executable, "-c", code, cwd=cwd).stdout.strip()
        self.ids.append(job)
        return job

    def jobs(self):
        return {j["id"]: j for j in json.loads(self.cli("status", "--json").stdout)}

    def wait(self, condition, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = condition()
            if result:
                return result
            time.sleep(0.05)
        self.fail("condition timed out; jobs=" + str(self.jobs()))

    def finished(self, job):
        return self.wait(lambda: (j if (j := self.jobs()[job])["finished"] else None))

    def tearDown(self):
        jobs = self.jobs() if self.ids else {}
        for job in self.ids:
            self.cli("cancel", job, cwd=jobs[job]["cwd"], check=False)
        for job in self.ids:
            self.finished(job)
        self.temp.cleanup()

    def foreground(self, code="pass", cwd=None):
        process = subprocess.Popen([sys.executable, str(QUEUE), "run", "--", sys.executable, "-c", code],
                                   cwd=cwd or self.root, env=self.env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=15)
        self.addCleanup(cleanup)
        job = self.wait(lambda: next((j for j in self.jobs().values() if j["submitter"] == process.pid), None))
        self.ids.append(job["id"])
        return process, job

    def test_queue_diagnostics_show_position_holders_memory_and_changes(self):
        self.configure(slots=1)
        holder = self.submit("import time; time.sleep(30)")
        running = self.wait(lambda: (j if (j := self.jobs()[holder])["state"] == "running" else None))
        other = self.root / "other"
        other.mkdir()
        waiting = self.submit("pass", other)
        self.wait(lambda: "queued position=1/1" in self.cli("logs", waiting).stdout)
        log = self.cli("logs", waiting).stdout
        for expected in ("slots full", "memory available=", "required=0.0 GiB", "ETA unknown",
                         f"id={holder}", f"pid={running['pgid']}", f"cwd={self.root.resolve()}", "command=", "running="):
            self.assertIn(expected, log)
        same = self.submit("pass")
        self.wait(lambda: "same cwd already running" in self.cli("logs", same).stdout)
        self.wait(lambda: "queued position=1/2" in self.cli("logs", waiting).stdout)
        self.cli("cancel", waiting, cwd=other)
        self.assertEqual(self.finished(waiting)["code"], 130)

    def test_cancel_defaults_to_cwd_and_explicit_targets_cannot_cross_it(self):
        self.configure(reserve=1000000)
        first = self.submit("pass")
        second = self.submit("pass")
        other = self.root / "other"
        other.mkdir()
        foreign = self.submit("pass", other)
        for args in ((foreign,), ("--id", foreign), ("--pid", str(self.jobs()[foreign]["owner"]))):
            result = self.cli("cancel", *args, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no matching job owned by you in this cwd", result.stderr)
        result = self.cli("cancel")
        self.assertIn(first, result.stdout)
        self.assertIn(second, result.stdout)
        for job in (first, second):
            final = self.finished(job)
            self.assertEqual(final["code"], 130)
            self.assertIn("cancel verb", final["cancel_reason"])
            self.assertIsNotNone(final["cancel_pid"])
            self.assertIsNotNone(final["cancel_at"])
        self.assertEqual(self.jobs()[foreign]["state"], "queued")
        self.cli("cancel", "--pid", str(self.jobs()[foreign]["owner"]), cwd=other)
        self.assertEqual(self.finished(foreign)["code"], 130)

    def test_explicit_cancel_reaches_foreground_caller_with_reason(self):
        self.configure(reserve=1000000)
        process, job = self.foreground("raise Exception('must not run')")
        result = self.cli("cancel", "--id", job["id"])
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 130)
        self.assertEqual(stdout, "")
        self.assertIn(f"id={job['id']} pid={job['owner']}", stderr)
        self.assertIn("cancelled (exit 130): cancel verb by pid=", stderr)
        self.assertIn(self.jobs()[job["id"]]["cancel_reason"], self.cli("status").stdout)
        self.assertIn(job["id"], result.stdout)

    def test_caller_signal_only_cancels_its_job_and_records_sender(self):
        self.configure(reserve=1000000)
        first, job = self.foreground()
        other = self.root / "other"
        other.mkdir()
        second, survivor = self.foreground(cwd=other)
        os.killpg(first.pid, signal.SIGTERM)
        _, stderr = first.communicate(timeout=15)
        self.assertEqual(first.returncode, 130)
        final = self.jobs()[job["id"]]
        self.assertEqual(final["cancel_signal"], signal.SIGTERM)
        self.assertIn("SIGTERM", final["cancel_reason"])
        if hasattr(signal, "sigtimedwait"):
            self.assertEqual(final["cancel_pid"], os.getpid())
        else:
            self.assertIn("sender pid=unknown", final["cancel_reason"])
        self.assertIn(final["cancel_reason"], stderr)
        self.assertEqual(self.jobs()[survivor["id"]]["state"], "queued")
        self.configure()
        second.communicate(timeout=15)
        self.assertEqual(second.returncode, 0)

    def test_queued_workers_survive_term_and_recover_after_kill(self):
        self.configure(reserve=1000000)
        self.env["HEAVY_CHECK_TEST_ORIGINAL"] = "original"
        process, job = self.foreground("import os; print(os.environ['HEAVY_CHECK_TEST_ORIGINAL'])")
        self.env["HEAVY_CHECK_TEST_ORIGINAL"] = "changed"
        self.wait(lambda: "queued position=" in self.cli("logs", job["id"]).stdout)
        os.kill(job["owner"], signal.SIGTERM)
        self.wait(lambda: self.jobs()[job["id"]]["recovery_reason"])
        retained = self.jobs()[job["id"]]
        self.assertEqual(retained["state"], "queued")
        self.assertIn("SIGTERM", retained["recovery_reason"])
        os.kill(job["owner"], signal.SIGKILL)
        recovered = self.wait(lambda: (j if (j := self.jobs()[job["id"]])["owner"] != job["owner"] else None))
        self.assertEqual(recovered["state"], "queued")
        self.assertIn("disappeared", recovered["recovery_reason"])
        self.configure()
        stdout, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stdout.strip(), "original")
        self.assertNotIn("environment", recovered)
        self.assertIn("restarted", stderr)

    def test_dead_caller_does_not_own_or_cancel_worker(self):
        self.configure(reserve=1000000)
        process, job = self.foreground()
        os.kill(process.pid, signal.SIGKILL)
        process.communicate(timeout=15)
        self.assertEqual(self.jobs()[job["id"]]["state"], "queued")
        self.configure()
        self.assertEqual(self.finished(job["id"])["code"], 0)

    def test_running_worker_death_is_not_success_and_other_queued_jobs_survive(self):
        self.configure(slots=1)
        process, job = self.foreground("import time; time.sleep(30)")
        running = self.wait(lambda: (j if (j := self.jobs()[job["id"]])["state"] == "running" else None))
        other = self.root / "other"
        other.mkdir()
        queued = self.submit("print('survived')", other)
        os.kill(running["owner"], signal.SIGKILL)
        _, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 125)
        self.assertIn("lost (exit 125)", stderr)
        self.assertIn("disappeared", stderr)
        self.assertEqual(self.finished(queued)["code"], 0)

    def test_running_worker_signal_cancels_with_reason_and_releases_slot(self):
        self.configure(slots=1)
        process, job = self.foreground("import time; time.sleep(30)")
        running = self.wait(lambda: (j if (j := self.jobs()[job["id"]])["state"] == "running" else None))
        os.kill(running["owner"], signal.SIGTERM)
        _, stderr = process.communicate(timeout=15)
        self.assertEqual(process.returncode, 130)
        self.assertIn("SIGTERM", stderr)
        self.assertEqual(self.finished(self.submit("pass"))["code"], 0)

    def test_two_slots_fifo_and_async_submission(self):
        events = self.root / "events"
        def command(n):
            return f"import time; f=open({str(events)!r},'a',buffering=1); f.write('{n} start\\n'); time.sleep(2); f.write('{n} end\\n')"
        directories = [self.root / str(n) for n in range(4)]
        for path in directories:
            path.mkdir()
        first = self.submit(command(0), directories[0])
        self.wait(lambda: self.jobs()[first]["state"] == "running")
        second = self.submit(command(1), directories[1])
        self.wait(lambda: self.jobs()[second]["state"] == "running")
        third = self.submit(command(2), directories[2])
        fourth = self.submit(command(3), directories[3])
        self.assertEqual(self.jobs()[third]["state"], "queued")
        for job in (first, second, third, fourth):
            self.assertEqual(self.finished(job)["code"], 0)
        active, maximum, starts = 0, 0, []
        for line in events.read_text().splitlines():
            n, event = line.split()
            active += 1 if event == "start" else -1
            maximum = max(maximum, active)
            if event == "start":
                starts.append(int(n))
        self.assertEqual(maximum, 2)
        self.assertEqual(starts, [0, 1, 2, 3])

    def test_memory_gate_and_queued_cancellation(self):
        self.configure(reserve=1000000)
        job = self.submit("raise Exception('must not start')")
        self.assertEqual(self.jobs()[job]["state"], "queued")
        self.cli("cancel", job)
        self.assertEqual(self.finished(job)["state"], "cancelled")
        next_job = self.submit("print('released')")
        self.configure()
        self.assertEqual(self.finished(next_job)["code"], 0)

    def test_nested_run_and_exit_code(self):
        self.configure(slots=1)
        nested = [sys.executable, str(QUEUE), "run", "--", sys.executable, "-c", "raise SystemExit(7)"]
        job = self.submit(f"import subprocess; raise SystemExit(subprocess.call({nested!r}))")
        self.assertEqual(self.finished(job)["code"], 7)
        self.assertIn("failed", self.cli("logs", job).stdout)

    def test_cancel_kills_child_group_and_releases_slot(self):
        self.configure(slots=1)
        marker = self.root / "should-not-exist"
        grandchild = f"import time; from pathlib import Path; time.sleep(3); Path({str(marker)!r}).touch()"
        job = self.submit(f"import subprocess,time; subprocess.Popen([{sys.executable!r},'-c',{grandchild!r}]); time.sleep(30)")
        self.wait(lambda: self.jobs()[job]["state"] == "running")
        self.cli("cancel", job)
        self.assertEqual(self.finished(job)["state"], "cancelled")
        self.assertEqual(self.finished(self.submit("pass"))["code"], 0)
        time.sleep(1)
        self.assertFalse(marker.exists())

    def test_crashed_supervisor_and_invalid_command_release_slots(self):
        self.configure(slots=1)
        job = self.submit("import time; time.sleep(30)")
        running = self.wait(lambda: (j if (j := self.jobs()[job])["state"] == "running" else None))
        os.kill(running["owner"], signal.SIGKILL)
        self.assertEqual(self.finished(job)["state"], "lost")
        bad = self.cli("run", "--", "/no/such/program", check=False)
        self.assertEqual(bad.returncode, 125)
        self.assertEqual(self.finished(self.submit("pass"))["code"], 0)

    def test_same_checkout_is_serial_and_foreground_output_preserved(self):
        first = self.submit("import time; time.sleep(1)")
        self.wait(lambda: self.jobs()[first]["state"] == "running")
        second = self.submit("print('second')")
        self.assertEqual(self.jobs()[second]["state"], "queued")
        self.assertEqual(self.finished(second)["code"], 0)
        result = self.cli("run", "--", sys.executable, "-c", "print('visible'); raise SystemExit(3)", check=False)
        self.assertEqual(result.stdout.strip(), "visible")
        self.assertEqual(result.returncode, 3)

    def test_waiting_checkout_does_not_block_other_checkouts(self):
        first = self.submit("import time; time.sleep(3)")
        self.wait(lambda: self.jobs()[first]["state"] == "running")
        second = self.submit("pass")
        other = self.root / "other"
        other.mkdir()
        third = self.submit("pass", other)
        self.assertEqual(self.finished(third)["code"], 0)
        self.assertEqual(self.jobs()[second]["state"], "queued")

    def test_real_bun_script_wiring_and_nested_slot_reuse(self):
        bun = shutil.which("bun") or str(Path.home() / ".bun/bin/bun")
        if not Path(bun).is_file():
            self.skipTest("Bun not installed")
        self.configure(slots=1)
        scripts = {"check": f"{bun} run typecheck && {bun} run test",
                   "typecheck": "python3 -c 'print(123)'", "test": "python3 -c 'print(456)'"}
        (self.root / "package.json").write_text(json.dumps({"scripts": scripts}, indent=2))
        subprocess.run([sys.executable, str(QUEUE.with_name("wire-heavy-checks")), str(self.root), "--apply"],
                       check=True, stdout=subprocess.DEVNULL)
        env = self.env | {"PATH": str(QUEUE.parent) + ":" + str(Path(bun).parent) + ":" + os.environ["PATH"]}
        result = subprocess.run([bun, "run", "check"], cwd=self.root, env=env,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("123", result.stdout)
        self.assertIn("456", result.stdout)
        self.assertEqual(len(self.jobs()), 1, "nested scripts must reuse the outer slot")

    def test_machine_launcher_queues_unmodified_projects_and_can_be_uninstalled(self):
        bun = Path(shutil.which("bun") or Path.home() / ".bun/bin/bun")
        if not bun.is_file():
            self.skipTest("Bun not installed")
        if b"box-heavy-check-launcher-v1" in bun.read_bytes()[:256]:
            bun = bun.with_name(bun.name + ".heavy-check-original")
        home = self.root / "home"
        executable = home / ".bun/bin/bun"
        executable.parent.mkdir(parents=True)
        shutil.copy2(bun, executable)
        installer = [sys.executable, str(QUEUE.with_name("install-heavy-checks")), "--home", str(home)]
        subprocess.run(installer, check=True, capture_output=True)
        subprocess.run(installer, check=True, capture_output=True)
        version = subprocess.run([str(executable), "--version"], env=self.env, text=True, capture_output=True, check=True)
        self.assertTrue(version.stdout.strip())
        self.assertEqual(len(self.jobs()), 0, "lightweight commands bypass the queue")
        (self.root / "package.json").write_text(json.dumps({"scripts": {
            "check": "bun run typecheck && bun run test", "typecheck": "echo typed", "test": "echo checked"}}))
        env = self.env | {"PATH": str(executable.parent) + ":" + os.environ["PATH"]}
        result = subprocess.run([str(executable), "run", "check"], cwd=self.root, env=env,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checked", result.stdout)
        self.assertEqual(len(self.jobs()), 1, "unmodified nested scripts share the automatically acquired slot")
        executable.with_name("bunx").symlink_to(executable)
        # Avoid network/package execution while checking bunx remains an alias for `bun x`.
        alias_help = subprocess.run([str(executable.with_name("bunx")), "--help"], env=self.env,
                                    text=True, capture_output=True, timeout=15)
        native_help = subprocess.run([str(bun), "x", "--help"], text=True, capture_output=True, timeout=15)
        self.assertEqual(alias_help.returncode, native_help.returncode)
        self.assertIn("bunx", alias_help.stderr + alias_help.stdout)
        subprocess.run(installer + ["--uninstall"], check=True, capture_output=True)
        self.assertNotIn(b"box-heavy-check-launcher-v1", executable.read_bytes()[:256])
        subprocess.run([str(executable), "--version"], check=True, capture_output=True)


class QueueMetadataTests(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader("queue_metadata", str(QUEUE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.queue = importlib.util.module_from_spec(spec)
        loader.exec_module(self.queue)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue.ROOT = Path(self.temp.name)

    def test_legacy_database_is_migrated_without_losing_jobs(self):
        with sqlite3.connect(self.queue.ROOT / "queue.sqlite") as db:
            db.execute("""CREATE TABLE jobs (
                id TEXT PRIMARY KEY, created REAL, cwd TEXT, command TEXT,
                state TEXT, owner INTEGER, identity TEXT, pgid INTEGER,
                child_identity TEXT, started REAL, finished REAL, code INTEGER,
                cancel INTEGER DEFAULT 0)""")
            db.execute("INSERT INTO jobs (id,state,code) VALUES ('old','done',0)")
        with self.queue.database() as db:
            job = db.execute("SELECT * FROM jobs WHERE id='old'").fetchone()
            self.assertEqual(job["code"], 0)
            self.assertIsNone(job["cancel_reason"])
            self.assertIsNone(job["uid"])
        with self.queue.database() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_reaping_worker_preserves_original_cancel_request(self):
        with self.queue.database() as db:
            db.execute("""INSERT INTO jobs (id,state,owner,identity,cancel,cancel_reason,cancel_pid)
                VALUES ('dying','running',424242,'old',1,'cancel verb by pid=123',123)""")
            with mock.patch.object(self.queue, "identity", return_value=None):
                self.queue.reap(db)
            job = db.execute("SELECT * FROM jobs WHERE id='dying'").fetchone()
            self.assertEqual(job["state"], "lost")
            self.assertEqual(job["code"], 125)
            self.assertEqual(job["cancel_reason"], "cancel verb by pid=123")
            self.assertEqual(job["cancel_pid"], 123)
            self.assertIn("disappeared", job["recovery_reason"])

    def test_notices_only_change_or_heartbeat_and_first_cancel_reason_wins(self):
        queue = self.queue
        with queue.database() as db:
            db.execute("""INSERT INTO jobs (id,created,cwd,command,state,owner,identity)
                VALUES ('waiting',0,?,'["unused"]','queued',?,?)""",
                       (str(queue.ROOT), os.getpid(), queue.identity(os.getpid())))
        ticks = iter((0.25, 30.5, 31))
        clock = [0]
        def advance(_):
            clock[0] = next(ticks)
            if clock[0] == 31:
                with queue.database() as db:
                    queue.request_cancel(db, "waiting", "first cancel", 123)
                    queue.request_cancel(db, "waiting", "second cancel", 456)
        stderr = io.StringIO()
        config = {"slots": 1, "reserve_gib": 6, "headroom_gib": 4}
        with mock.patch.object(queue, "settings", return_value=config), \
             mock.patch.object(queue, "available_gib", return_value=2.25), \
             mock.patch.object(queue, "watch_signals"), \
             mock.patch.object(queue, "pending_signal", return_value=None), \
             mock.patch.object(queue.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(queue.time, "sleep", side_effect=advance), \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(queue.work("waiting"), 130)
        output = stderr.getvalue()
        self.assertEqual(output.count("queued position=1/1"), 2)
        self.assertIn("waiting for memory", output)
        self.assertIn("available=2.2 GiB required=10.0 GiB", output)
        self.assertIn("cancelled (exit 130): first cancel", output)
        with queue.database() as db:
            job = db.execute("SELECT * FROM jobs WHERE id='waiting'").fetchone()
            self.assertEqual(job["cancel_pid"], 123)
            self.assertEqual(job["code"], 130)


class WiringTests(unittest.TestCase):
    def test_bun_dispatch_classification(self):
        loader = importlib.machinery.SourceFileLoader("queue_classifier", str(QUEUE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        for args in (["run", "check"], ["run", "--silent", "typecheck:scripts"],
                     ["--cwd", "/project", "run", "build"], ["run", "--filter", "*", "test"],
                     ["test"], ["test", "--timeout", "5000"], ["x", "tsc", "-b"], ["check"], ["build"]):
            with self.subTest(args=args):
                self.assertTrue(module.heavy_bun(args))
        for args in (["--version"], ["install"], ["run", "dev"], ["run", "lint"],
                     ["scripts/small.ts"], ["test", "unit.test.ts"],
                     ["test", "-t", "one test"], ["run", "check", "--help"]):
            with self.subTest(args=args):
                self.assertFalse(module.heavy_bun(args))

    def test_self_queued_scripts_bypass_the_launcher(self):
        loader = importlib.machinery.SourceFileLoader("queue_self", str(QUEUE))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sub").mkdir()
            (root / "package.json").write_text(json.dumps({"heavyCheck": {"selfQueued": ["check"]}}))
            with contextlib.chdir(root / "sub"):
                self.assertFalse(module.heavy_bun(["run", "check", "--only", "nosuch"]))
                self.assertFalse(module.heavy_bun(["run", "check", "--bogus"]))
                self.assertTrue(module.heavy_bun(["run", "typecheck"]))
            other = root / "other"
            other.mkdir()
            (other / "package.json").write_text("{}")
            with contextlib.chdir(other):
                self.assertTrue(module.heavy_bun(["run", "check"]))
                self.assertFalse(module.heavy_bun(["--cwd", str(root), "run", "check"]))
            (other / "package.json").write_text("not json")
            with contextlib.chdir(other):
                self.assertTrue(module.heavy_bun(["run", "check"]))

    def test_wiring_preserves_commands_and_is_idempotent(self):
        loader = importlib.machinery.SourceFileLoader("wire", str(QUEUE.with_name("wire-heavy-checks")))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        wire = importlib.util.module_from_spec(spec)
        loader.exec_module(wire)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = {"check": "echo first && echo second", "typecheck": "echo typed", "lint": "echo lint"}
            original = json.dumps({"scripts": scripts}, indent=2) + "\n"
            (root / "package.json").write_text(original)
            with contextlib.redirect_stdout(io.StringIO()):
                wire.wire(root)
            self.assertEqual((root / "package.json").read_text(), original)
            with contextlib.redirect_stdout(io.StringIO()):
                wire.wire(root, True)
            first = (root / "package.json").read_text()
            with contextlib.redirect_stdout(io.StringIO()):
                wire.wire(root, True)
            self.assertEqual((root / "package.json").read_text(), first)
            wired = json.loads(first)["scripts"]
            self.assertEqual(wired["heavy:raw:check"], scripts["check"])
            self.assertEqual(wired["lint"], scripts["lint"])


if __name__ == "__main__":
    unittest.main()
