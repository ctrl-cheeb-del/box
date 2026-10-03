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

Paths only, never secret values. Machine-local state (FreeRDP logs, `.rdp` files) stays in
`~/.config/agentbox/`.

## Install on a new Mac

```bash
gh repo clone ctrl-cheeb-del/box ~/Documents/projects/box
ln -sf ~/Documents/projects/box/bin/box ~/.local/bin/box
brew install freerdp
```
Then the SSH, Keychain and Tailscale steps in `docs/add-a-device.md`.
