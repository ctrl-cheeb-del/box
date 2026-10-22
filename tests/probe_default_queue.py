#!/usr/bin/env python3
"""Verify ordinary `bun run check` is queued, without starting a real build."""
import json
from pathlib import Path
import subprocess
import tempfile
import time


with tempfile.TemporaryDirectory(prefix="heavy-check-probe-") as directory:
    root = Path(directory)
    (root / "package.json").write_text(json.dumps({"scripts": {"check": "echo automatic-queue-ok"}}))
    runner = str(Path.home() / ".local/bin/heavy-check")
    process = subprocess.Popen([str(Path.home() / ".bun/bin/bun"), "run", "check"], cwd=root,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    job = None
    try:
        for _ in range(30):
            rows = json.loads(subprocess.check_output([runner, "status", "--json"], text=True))
            job = next((row for row in rows if Path(row["cwd"]).resolve() == root.resolve()), None)
            if job:
                break
            time.sleep(0.1)
        if not job:
            raise RuntimeError("normal bun run check did not enter the queue")
        if job["state"] == "queued":
            subprocess.run([runner, "cancel", job["id"]], cwd=root, check=True, stdout=subprocess.DEVNULL)
        stdout, stderr = process.communicate(timeout=15)
        rows = json.loads(subprocess.check_output([runner, "status", "--json"], text=True))
        final = next(row for row in rows if row["id"] == job["id"])
        if final["state"] not in ("done", "cancelled"):
            raise RuntimeError(f"probe failed: {final['state']}: {stderr}")
        print(f"PASS: unmodified bun run check automatically queued; observed {job['state']}, final {final['state']}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=15)
