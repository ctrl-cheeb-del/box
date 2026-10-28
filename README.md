# box

Art's always-on agent machines: the `box` CLI that drives them from the Mac, the list of machines, the
setup guide, and the scripts that keep them healthy.

```
box list                      machines and whether they're reachable now
box [machine]                 shell (tmux "main"); default machine: skynet
box desktop [machine]         Ubuntu desktop over FreeRDP (Screen Sharing on a macOS box)
box status [machine|all]      services, Claude, browser sandbox, battery, disk
box run [machine] <cmd>       one command
box logs [machine] [unit]     follow a user unit's journal (default t3code; T3's log file on macOS)
box update [machine|all]      apt (Ubuntu) + t3/claude/codex/bun updates
box reboot [machine]          reboot, wait, show status
box threads search <query>    search T3 threads on every reachable machine
box sync-memory               two-way sync of revnu2 Claude memories with every machine
box sync-skills               install bot-loop from revnu2 main on every machine (also hourly)
box usage                     5-hour and weekly use per Claude account, and when each resets
box proxy | claude-login      CLIProxyAPI dashboard / add a Claude account (on the proxy machine)
```

## Layout

| Path | What |
|---|---|
| `bin/box` | the CLI. `~/.local/bin/box` is a symlink to it |
| `machines` | the registered machines (name, `.local` host, Tailscale IP, roles; `macbox` = an agent box on macOS). Add a line to add one |
| `docs/setup.md` | building a box from scratch, every trap included, plus a prompt to hand the job to an agent |
| `docs/add-a-device.md` | adding a laptop, phone or another box to this setup (copy-paste prompt inside) |
| `docs/machines.md` | the running record: what's on each machine, where credentials live, past incidents |
| `reapers/` | forgotten dev stacks, orphaned executors and stale /tmp trees: systemd user timers on Linux, launchd on a macOS box |
| `bin/heavy-check`, `bin/install-heavy-checks` | `heavy-check run/submit/status/logs`; `cancel [JOB_ID / --id JOB_ID / --pid PID]` targets this cwd; [Linux/macOS install and usage](docs/heavy-checks.md) |
| `heartbeat/` | every 30 min each box posts "alive" to ntfy and alerts if a peer goes quiet or it's unhealthy |
| `watch/` | babysits a few revnu creators every 3 hours and opens a T3 thread per problem (skynet) |
| `skills/` | `sync-skills`: the global `bot-loop` skill on every machine, copied from revnu2 main hourly |
| `mac/` | launchd jobs: `box sync-memory` every 6 hours (never starts Tailscale), `sync-skills` hourly; `install-macbox` sets up a macOS agent box's heartbeat, reapers and `box-launch` (see docs/machines.md, "macOS box: air") |

Paths only, never secret values. Machine-local state (FreeRDP logs, `.rdp` files) stays in
`~/.config/agentbox/`.

## Install on a new Mac

```bash
gh repo clone ctrl-cheeb-del/box ~/Documents/projects/box
ln -sf ~/Documents/projects/box/bin/box ~/.local/bin/box
brew install freerdp
```
Then the SSH, Keychain and Tailscale steps in `docs/add-a-device.md`.

## Heartbeat and alerts

Each box runs `box-heartbeat` every 30 minutes (`heartbeat/`). It posts an "alive" message (uptime,
memory, disk, load, Claude/T3 status) to `<topic>-hb`, which only the boxes read, so the phone stays
quiet. The phone subscribes to `<topic>` and gets an urgent push when a peer box has sent nothing for 75
minutes, memory or disk passes 90%, Claude can't reach the proxy, or T3 is down, and another when it
clears. Messages go to an ntfy.sh topic; the topic name is the only secret, so it lives in
`~/.config/box/ntfy-topic` on each box (and `~/.config/agentbox/ntfy-topic` on the Mac), never here.
Subscribe to it in the ntfy phone app. A power cut takes both boxes down at once, so nobody is left to
alert: silence in the ntfy app is the signal then.

Install on a box: copy `heartbeat/box-heartbeat` to `~/.local/bin/`, the unit and timer to
`~/.config/systemd/user/`, write the topic and a `~/.config/box/peers` file (the other boxes'
hostnames, one per line), then `systemctl --user enable --now box-heartbeat.timer`. On a macOS box,
`mac/install-macbox` installs it (and the reapers) as launchd agents; the topic and peers files are the same.

## Memory sync

`mac/com.box.sync-memory.plist` runs `box sync-memory` every 6 hours. Copy it to
`~/Library/LaunchAgents/` and `launchctl bootstrap gui/$(id -u) <that file>`. Background jobs can't read
`~/Documents`, so `box` keeps a copy of itself and `machines` in `~/.local/share/box`, refreshed each
time you run it; the job runs that copy. Log: `/tmp/box-sync-memory.log`.

## Skills

revnu2's `.agents/skills/bot-loop` is the only copy of the bot-loop skill anyone edits. `skills/sync-skills`
downloads it from revnu2 `main` with `gh api` into `~/.claude/skills/bot-loop` and links
`~/.codex/skills/bot-loop` to it, so agents in any repo, Claude Code or Codex, on any machine, run the same
version. It runs hourly: a systemd user timer on the boxes, `mac/com.box.sync-skills.plist` on the Mac.
`box sync-skills` installs the script and its timer everywhere and runs it now. Local edits to the global
copy are overwritten; change it in revnu2 and merge. Log on the Mac: `/tmp/box-sync-skills.log`.

## Watch

`watch` (skynet) babysits a short list of revnu creators. Each one is checked every 3 hours,
counted from when it was added; a 15-minute timer runs whoever is due. A check reads everything
since the last one (with the day before as context) through `bun investigate` and `bun ops`, and
Opus judges it against the creator's Memory (`watch/judge.md`). A quiet window is skipped unless
the quiet is the problem: a customer message with no reply, or nothing shipped in 24 hours. Each
problem opens a T3 thread in the revnu2 project on the box; the same problem at the next check
becomes a follow-up turn in that thread, and a problem that stops showing up is closed.

```
watch add <creator>            resolve by name like `bun ops` (substring of the business name)
watch rm <creator>
watch ls                       last and next check, open problems and their threads
watch ok <creator> <key> [why] "that's fine": closes it and the judge stops flagging it
watch check <creator> [--since 6h] [--dry-run]   check now; --dry-run judges but opens nothing
```

It is read-only. Prod is read with the `revnu2-readonly/prd` Doppler token in a clone with no
`.env.local`, so nothing it runs can write or message a customer; the clone is reset to
`origin/main` before each run. The threads it opens get the same read-only instruction.

Install on skynet: copy `watch/watch` and `watch/judge.md` to `~/.local/share/watch/bin/`, symlink
`~/.local/bin/watch` to the script, clone revnu2 to `~/.local/share/watch/revnu2` and `bun install`
there, copy the unit and timer to `~/.config/systemd/user/`, then
`systemctl --user enable --now watch.timer`. Needs `doppler login`, `claude` and `t3` on the box.
