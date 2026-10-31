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

`box update` pulls this repo and reruns its installer (after upgrading Bun) when
`~/.local/share/box/heavy-check-install.json` exists, so the pulled `heavy-check` is
what gets installed. Swapping it is safe with jobs queued or running: both files are
replaced atomically, running processes keep the code they started with, and old and
new workers share the queue database and slot locks. To undo the machine launcher:

```sh
python3 bin/install-heavy-checks --uninstall
```

## Use

```sh
bun run check                         # existing command, now queued
heavy-check run -- bun run check      # foreground; preserves output and exit status
heavy-check submit -- bun run check   # returns a job ID immediately
heavy-check status                    # latest 50 jobs, PIDs, command, directory, exit code/reason
heavy-check status --json
heavy-check logs JOB_ID               # accumulated stdout, then stderr/queue diagnostics
heavy-check cancel                    # cancel active jobs in this cwd only
heavy-check cancel JOB_ID             # precise queued/running job in this cwd
heavy-check cancel --id JOB_ID        # same explicit ID form
heavy-check cancel --pid PID          # current worker or command PID, in this cwd
```

`run` and `submit` print the job ID and detached worker PID to stderr when queued;
`submit` continues to print only the ID to stdout for scripts. `status` shows worker
and command PIDs. `cancel` is scoped to the current Unix user and exact working
directory, including explicit ID/PID targets; run it from the job's recorded cwd.
On a shared Unix account, the cwd is the ownership boundary: agents sharing the
same cwd also share its jobs. Target an ID to cancel only one of them. This replaces
`pkill -f`, which can match other agents across the box. Finished jobs are unchanged.

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

While waiting, the job prints one line as soon as it queues, again every 30 seconds
and whenever its place or what blocks it changes:

```
[heavy-check 56fb8ea5fe1d] waiting 1m30s; place 2 of 3 queued; ahead: 8b74a766171e running 4m10s in t3-29aff96e (bun scripts/check.ts); 91c41329bfa1 queued 2m00s in t3-1a2111a6 (bun run typecheck); memory 5.3 GiB free, 10.0 GiB needed; blocked by: eligible jobs ahead, memory; gives up in 13m30s (HEAVY_CHECK_MAX_WAIT=900s)
```

**No job waits forever.** After `HEAVY_CHECK_MAX_WAIT` (default 15 minutes) a job
that never started fails with exit 124, its last state and the jobs that were ahead
of it, without running the command. Set it in the caller's environment: seconds, or a
number ending in `s`, `m` or `h`; `0` waits forever. `HEAVY_CHECK_MAX_WAIT=30m bun run check`.

With one of the queue's jobs already running, a job starts only when available
memory is at least 10 GiB: 6 GiB estimated working memory plus 4 GiB headroom, and
jobs started in the previous 10 seconds each reserve another 6 GiB while their memory
use ramps up. With none running, nothing of the queue's can grow into the headroom,
so the first job needs only `idle_gib` (6 GiB). That is what stops the queue starving
at 8 GiB free with nothing running. This is an admission
check, **not a hard memory limit**; a command can still exceed the estimate and
unrelated processes can consume memory after admission. Linux uses `MemAvailable`;
macOS estimates reclaimable memory from free, inactive, and speculative VM pages,
and pauses admission only at critical memory pressure (a busy Mac sits at "warn" for
hours, and the page count already shrinks then). The queue does not stop
already-running, unwrapped processes.

Configure `~/.config/box/heavy-check.json` (changes affect the next admission):

```json
{"slots": 2, "reserve_gib": 6, "headroom_gib": 4, "idle_gib": 6}
```

Queue metadata, slot locks, and background logs live in
`~/.local/state/box/heavy-check`, on disk rather than `/tmp`. `HEAVY_CHECK_STATE`
and `HEAVY_CHECK_CONFIG` override those paths for isolated tests. Use the same
configuration and state paths for every worktree to share capacity. Historical
records/logs are retained in this basic version; no automatic log retention,
per-agent round-robin scheduling, or automatic replacement of queued jobs yet.

Every job has its own worker in a detached session, including foreground `run`.
The foreground caller streams the worker's saved stdout and stderr and waits for
the recorded exit status. There is no shared daemon or global cancel flag. The old
foreground runner itself supervised the job and converted any SIGINT/SIGTERM into
an unexplained exit 130; a broad process/group signal could therefore cancel many
independent foreground runs at once.

SIGINT/SIGTERM **to the foreground caller** requests cancellation of that job only.
The `cancel` verb records the requester's PID, UID, cwd and timestamp. Signals
record their number/name, recipient and sender PID on Linux via `sigtimedwait`;
macOS's Python handler cannot identify the sender and records `unknown`. The first
cancellation reason is retained in `status` (also in `status --json`) and the waiting
caller's stderr. Cancelled jobs always return 130; failed/lost workers return 125,
never success. A successful `submit` or `cancel` means the request was accepted,
not that verification succeeded. Shell wrappers must propagate `run`'s exit code.

A SIGTERM/SIGINT **to a queued worker** is recorded as an interruption and leaves
the job queued. If a queued worker disappears (including SIGKILL), the next caller,
worker or `status` invocation restarts it with the same ID, FIFO position, cwd and
saved environment. A foreground `run` whose **caller** dies (an agent's Bash timeout
SIGKILLs it) is cancelled, queued or running: nobody is left to read it, and it would
otherwise hold its place or slot. `submit` jobs outlive their submitter by design.
If all processes are killed, invoke `status` or another queue command to recover
queued jobs. Recovery is reported in logs and `status`. This cannot identify an
unobserved SIGKILL's sender or signal number. Queued recovery uses closed stdin;
these commands should be noninteractive. Saved environments stay in the private
state directory and are omitted from `status --json`.

SIGINT/SIGTERM to a **running worker** cancels its command and records the signal.
Cancellation sends TERM, then KILL after two seconds, to the entire command process
group. Background children remaining after a command exits are also stopped: this
queue is for finite checks, not dev servers. Stale workers are detected using boot
ID plus process start time (Linux clock ticks; macOS `ps` timestamps), not PID alone.
A running job whose worker disappears is marked `lost` (125), with a reason, and
its still-identifiable command group is killed; it is never rerun automatically.
The slot limit is the count of running jobs in the queue database. Slot lock files
are still taken by the worker so workers from an older install, which count by lock,
don't over-admit during an upgrade; the command no longer inherits the lock, so a
daemon it leaves behind can't hold a slot after the job ends, and a lock held by a
stray process is logged and ignored. Children that deliberately create a new session escape process-group
cancellation; use systemd/cgroup isolation if that needs enforcing.

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
