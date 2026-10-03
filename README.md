# box

Art's always-on agent machines: the `box` CLI that drives them from the Mac, the list of machines, the
setup guide, and the scripts that keep them healthy.

```
box list                      machines and whether they're reachable now
box [machine]                 shell (tmux "main"); default machine: skynet
box desktop [machine]         Ubuntu desktop over FreeRDP
box status [machine|all]      services, Claude, battery, T3 Connect, disk
box run [machine] <cmd>       one command
box logs [machine] [unit]     follow a user unit's journal (default t3code)
box update [machine|all]      apt + t3/claude/codex/bun updates
box reboot [machine]          reboot, wait, show status
box sync-memory               two-way sync of revnu2 Claude memories with every machine
box usage                     5-hour and weekly use per Claude account, and when each resets
box proxy | claude-login      CLIProxyAPI dashboard / add a Claude account (on the proxy machine)
```

## Layout

| Path | What |
|---|---|
| `bin/box` | the CLI. `~/.local/bin/box` is a symlink to it |
| `machines` | the registered machines (name, `.local` host, Tailscale IP, roles). Add a line to add one |
| `docs/setup.md` | building a box from scratch, every trap included, plus a prompt to hand the job to an agent |
| `docs/add-a-device.md` | adding a laptop, phone or another box to this setup (copy-paste prompt inside) |
| `docs/machines.md` | the running record: what's on each machine, where credentials live, past incidents |
| `reapers/` | systemd user timers that stop forgotten dev stacks and orphaned Convex executors |
| `heartbeat/` | every 30 min each box posts "alive" to ntfy and alerts if a peer goes quiet or it's unhealthy |
| `mac/` | launchd job: `box sync-memory` every 6 hours (never starts Tailscale) |

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
hostnames, one per line), then `systemctl --user enable --now box-heartbeat.timer`.

## Memory sync

`mac/com.box.sync-memory.plist` runs `box sync-memory` every 6 hours. Copy it to
`~/Library/LaunchAgents/` and `launchctl bootstrap gui/$(id -u) <that file>`. Background jobs can't read
`~/Documents`, so `box` keeps a copy of itself and `machines` in `~/.local/share/box`, refreshed each
time you run it; the job runs that copy. Log: `/tmp/box-sync-memory.log`.
