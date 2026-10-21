# Heavy check queue

`heavy-check` limits expensive local verification across all worktrees on one Linux or macOS
machine and Unix user. Agents can continue editing and running lightweight commands
while a background check waits. It uses Python 3's standard library; no daemon,
package installation, or network service is involved.

## Install

```sh
python3 bin/install-heavy-checks
```

This installs the runner to `~/.local/bin/heavy-check` and atomically wraps the
existing `~/.bun/bin/bun`. The native binary is preserved beside it as
`bun.heavy-check-original`. Re-running the installer is safe. `bunx` continues
working through its existing symlink. Use `--bun /actual/path/to/bun` for a native
binary installed elsewhere; the installer refuses to overwrite an unknown script.

The launcher automatically queues `bun run check`, `bun run typecheck` (including
`typecheck:*`), `bun run build`, `bun run test`, matching shorthand scripts,
native `bun build`, full `bun test`, and `bunx tsc` / `bun x tsc`.
This works for **existing and future worktrees, and other projects**, without
editing their package files or committing a wrapper to each repository.

`bun install`, dev servers, lint, ordinary scripts, version/help queries, and
**targeted** native tests (`bun test path.test.ts` or `bun test -t pattern`) bypass
the queue. Direct Node/tsc invocations or the preserved native Bun binary also
bypass it; this is a launcher guard, not an OS-wide memory limit.

The original `wire-heavy-checks PROJECT --apply` is still available as an optional
project-level integration for machines using a different Bun launcher. It keeps
original commands under `heavy:raw:*` and creates `scripts/heavy-check.sh`; it is
not needed when the machine launcher is installed. Nested wrappers reuse a slot.

`box update` reapplies the installer after upgrading Bun when
`~/.local/bin/install-heavy-checks` exists. To undo the machine launcher:

```sh
python3 bin/install-heavy-checks --uninstall
```

## Use

```sh
bun run check                         # existing command, now queued
heavy-check run -- bun run check      # foreground; preserves output and exit status
heavy-check submit -- bun run check   # returns a job ID immediately
heavy-check status                    # latest 50 jobs, command, directory, exit code
heavy-check status --json
heavy-check logs JOB_ID               # background job's accumulated output
heavy-check cancel JOB_ID             # queued or running job
```

For agents: use `submit` for long checks, do independent work, then read status and
logs before reporting verification. A queued job is **not** a successful check.
Cancel an obsolete check before submitting its replacement. Keep the checkout
unchanged during its final verification; submitted commands read the working tree
when they run, not a snapshot from submission time. Use targeted tests and lint
freely. Route full checks, builds, and typechecks through the queue.

## Scheduling and memory

Defaults: two slots, one running job per working directory, FIFO among
eligible jobs. A checkout waiting on its own running check does not block other
checkouts. Nested foreground commands in an existing queued process group reuse
its slot, so a full check can call queued typechecks without deadlocking.

A job starts only when available memory is at least 10 GiB: 6 GiB estimated
working memory plus 4 GiB headroom. Jobs started in the previous 10 seconds each
reserve an additional 6 GiB while their memory use ramps up. This is an admission
check, **not a hard memory limit**; a command can still exceed the estimate and
unrelated processes can consume memory after admission. Linux uses `MemAvailable`;
macOS estimates reclaimable memory from free, inactive, and speculative VM pages,
and pauses admission while the OS reports elevated memory pressure. The queue does not stop
already-running, unwrapped processes.

Configure `~/.config/box/heavy-check.json` (changes affect the next admission):

```json
{"slots": 2, "reserve_gib": 6, "headroom_gib": 4}
```

Queue metadata, slot locks, and background logs live in
`~/.local/state/box/heavy-check`, on disk rather than `/tmp`. `HEAVY_CHECK_STATE`
and `HEAVY_CHECK_CONFIG` override those paths for isolated tests. Use the same
configuration and state paths for every worktree to share capacity. Historical
records/logs are retained in this basic version; no automatic log retention,
per-agent round-robin scheduling, or automatic replacement of queued jobs yet.

SIGINT/SIGTERM cancels a foreground job. Cancellation sends TERM, then KILL after
two seconds, to the entire command process group. Background children remaining
after a command exits are also stopped: this queue is for finite checks, not dev
servers. Stale supervisors are detected using boot ID plus process start time
(Linux clock ticks; macOS `ps` timestamps), not PID alone; still-identifiable command groups are killed. The command inherits
the slot's kernel lock, preventing over-admission if its supervisor dies. Children
that deliberately create a new session escape process-group cancellation; use
systemd/cgroup isolation if that needs enforcing.

## Test

```sh
python3 -m unittest discover -s tests -v
python3 tests/probe_default_queue.py
```

Run on Linux or macOS for the process/memory integration tests. Tests use isolated queue state and tiny dummy commands; they
do not take production slots or change the production memory thresholds.

The separate probe deliberately uses the real default queue and an unmodified
temporary package. If it waits for memory or a slot, the probe cancels its own job;
otherwise it runs only `echo`. It never starts a project build.
