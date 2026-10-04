# Agent box (skynet)

Renamed from art-M6-Ultra on 2026-10-02 (hostname, mDNS, Tailscale). Same machine, same T3 environment ID.

Art's always-on Linux box for running coding agents. Set up 2026-09-25.
Everything here is reachable from the Mac with the `box` script (`~/.local/bin/box`).

## The machine

- GMKtec M6 Ultra: Ryzen, 12 cores, 39 GB RAM, 937 GB NVMe
- Ubuntu 26.04.1 LTS Desktop, user `art`, hostname `skynet`
- Lives headless (no keyboard or monitor). **Wired** to the Hyperoptic router (enp3s0, 1 Gbps) since
  2026-09-25; Wi-Fi "MineShock Labs" stays connected as a fallback route.
- avahi only advertises the wired interface (`allow-interfaces=enp3s0,eno1`), so `skynet.local`
  never resolves to the Wi-Fi address. Wi-Fi jitter was what kept dropping RDP (0x200d).

## Reaching it

| From | How |
|---|---|
| Home network | `skynet.local` (mDNS; the IP changes, the name doesn't) |
| Anywhere | Tailscale, box IP `100.85.99.101`. Tailscale runs 24/7 on the box; on the Mac turn it on only when away |
| T3 Code (any network) | T3 Connect, account art@revnu.com, environment "skynet" |

`ssh agentbox` picks the right one automatically (see `~/.ssh/config`: a `Match exec` tries the
LAN name, otherwise Tailscale). SSH is key-only from this Mac (`~/.ssh/id_ed25519`).
`art` has passwordless sudo (`/etc/sudoers.d/art-nopasswd`) so agents can administer it.

## The `box` script (on the Mac)

Since 2026-10-02 one CLI drives every machine listed in `machines` (skynet is the
default). Name a machine anywhere: `box desktop jarvis`, `box jarvis status`, `box status all`, `box list`.
Register a new machine by adding a line to that file. `box help` prints the current command list.

```
box                 shell on the box (tmux session "main")
box desktop         Ubuntu desktop via FreeRDP, auto-reconnects (--windows-app for the old client)
box proxy           CLIProxyAPI dashboard, management key copied to clipboard
box status          health check of every service
box run <cmd>       one command on the box, e.g. box run 'df -h'
box logs [unit]     follow t3code / cliproxyapi / gnome-remote-desktop logs
box claude-login    add or re-auth a Claude account in the proxy
box update          apt upgrade + t3/claude/codex/bun updates
box sync-memory     two-way sync of revnu2 Claude memories (newer file wins)
box reboot          reboot, wait, show status
box hermes          Hermes Agent dashboard, tunnelled to http://localhost:9119
```

Each tries the home network first and starts Tailscale on the Mac if that fails.
Aliases in `~/.zshrc`: `bx`, `bxd` (desktop), `bxs` (status), `bxp` (proxy).

## What runs on it

All are systemd **user** services with linger on, so they start at boot with nobody logged in.

| Service | Unit | Notes |
|---|---|---|
| T3 Code server | `t3code.service` | `t3 service status`, logs `~/.t3/userdata/logs/boot-service.log`. If T3 Connect ever shows "pending server startup", `systemctl --user restart t3code` |
| CLIProxyAPI | `cliproxyapi.service` | `0.0.0.0:24873` (LAN, for jarvis; API key required), fill-first across 3 Claude accounts (since 2026-10-02; backup config `*.bak-2026-10-02`). Dashboard on the box: http://localhost:24873/management.html |
| Remote desktop | `gnome-remote-desktop.service` | RDP on 3389, user `art`. `screen-share-mode=extend`: each session gets its own virtual monitor, since no physical display is attached |
| Tailscale | `tailscaled` (system) | Advertised as an **exit node** since 2026-09-27 (forwarding in `/etc/sysctl.d/99-tailscale.conf`); approve it in the admin console |

Claude Code on the box talks to the proxy via `~/.claude/settings.json`
(`ANTHROPIC_BASE_URL=http://127.0.0.1:24873` + `apiKeyHelper`). Same config as the Mac's.

## Staying on

- sleep/suspend/hibernate targets are masked; GNOME idle and screen lock off
- GDM auto-login as `art` (`/etc/gdm3/custom.conf`)
- Wi-Fi power saving off (`/etc/NetworkManager/conf.d/wifi-powersave-off.conf`)
- BIOS "Restore on AC Power Loss" should be **Power On** (only settable at the box: Esc/Del at boot)
- The login keyring has a blank password so auto-login unlocks it; otherwise RDP can't read
  its credentials after a reboot and Chrome prompts for the keyring

## Where credentials live (paths only, never values)

| What | Where |
|---|---|
| Claude accounts (revnu.com, vinta.app, freebrey.com) | box: `~/.cli-proxy-api/claude-*.json`. Do not copy these between machines: the proxy refreshes tokens and two machines refreshing one token log each other out. Re-auth with `box claude-login` |
| Proxy management key | box and Mac: `~/.cli-proxy-api/management-key` (same key on both) |
| Proxy config | box: `~/.config/cliproxyapi/config.yaml`; Mac: `/opt/homebrew/etc/cliproxyapi.conf` |
| GitHub | box: `gh auth` (ctrl-cheeb-del) |
| Doppler | box: `doppler login` (Art) |
| Codex | box: `~/.codex/auth.json` |
| T3 Connect | box: `~/.t3/userdata` (art@revnu.com) |
| Convex CLI | box: `~/.convex/config.json` (device login, `npx convex login --no-open`) |
| Vercel CLI | box: `vercel login` device flow; user ctrl-cheeb-del, teams Revnu + Mineshock Labs |
| RDP login | box: GNOME keyring (`grdctl status --show-credentials`); Mac: Keychain item `agentbox-rdp` |
| Tailscale | account theredxer@; disable key expiry for skynet in the admin console |

## Claude memories

revnu2's auto-memories live on the Mac at `~/.claude/projects/-Users-art-Documents-projects-revnu2/memory/`
and on the box at `~/.claude/projects/-home-art-Documents-projects-revnu2/memory/` (the slot is named after the main
checkout path; T3 worktrees map back to it). `box sync-memory` rsyncs both ways, newest file wins, so
if both sides edited `MEMORY.md` since the last sync, one side's new index line can be lost.

## Projects

- `~/Documents/projects/revnu2` — cloned, `bun setup` done, Doppler `revnu2/dev` env pulled.
  In T3 Code, add it as a project on the **skynet** environment (projects belong to one environment).

## Toolchain on the box

bun, node 22, npm globals in `~/.local` (codex), bun globals (convex, vercel, wrangler, pnpm, tsx,
typescript), claude (native installer, `~/.local/bin`), gh, doppler, uv, ripgrep, just, cloudflared,
tmux, Chrome. PATH for login shells is set in `~/.profile` (T3 Code needs `sh -lc` to find CLIs).

## Troubleshooting

- **Can't reach it**: `box status`. If LAN and Tailscale both fail it's off or offline; someone
  has to press the power button (and check the BIOS power-loss setting).
- **Claude errors on the box**: `box status` shows each account's state; re-auth with `box claude-login`.
  `/api/hello` 404s in the proxy logs are harmless.
- **RDP rejects the login, or gh/doppler lose auth, after a reboot**: the login keyring must have a
  blank password (set 2026-09-25; `~/.local/share/keyrings/login.keyring` starts with `[keyring]`
  in plain text when it does). It reports `Locked b true` right after boot and unlocks on first access,
  which is normal. Check creds with `grdctl status --show-credentials` (flag goes after `status`).
- **CLI logins over SSH** (convex, vercel, codex, doppler, gh): all support a device-code flow. Run with
  `--no-open`/device mode and open the printed URL in any browser, including the Mac's.
- **Balena Etcher fails on macOS** ("requestMetadata is not a function"): flash with
  `sudo dd if=<full path to iso> of=/dev/rdiskN bs=4m` instead (zsh won't expand `~` after `if=`).
- **`missing or unsuitable terminal: xterm-ghostty`**: the box lacks Ghostty's terminfo. Fix from the Mac:
  `TERMINFO=/Applications/Ghostty.app/Contents/Resources/terminfo infocmp -x xterm-ghostty | ssh agentbox 'tic -x -'`
- **RDP connects then drops with "Failed to record monitor: Unknown monitor"**: no physical display, and
  RDP was mirroring it. Fixed 2026-09-25 with a virtual monitor:
  `gsettings set org.gnome.desktop.remote-desktop.rdp screen-share-mode extend` (needs the DBUS env).
- **RDP drops with 0x200d / `TRANSPORT_FAILED`**: Microsoft's Windows App (Mac) drops GNOME RDP
  sessions after ~1 min, even on the wired link. FreeRDP (`brew install freerdp`) held the same session,
  so `box desktop` uses `sdl-freerdp` with `+auto-reconnect`. Its password is the Mac Keychain item
  `agentbox-rdp` (`security find-generic-password -a art -s agentbox-rdp -w`). If FreeRDP ever drops too,
  the untried fallback is NoMachine (Homebrew cask failed its checksum on 2026-09-25; use nomachine.com).
- **Cloudflare MCP returns HTTP 405**: it must be registered as `--transport http` (its `/mcp` endpoint
  is streamable HTTP, not SSE).

## revnu workflow on the box (verified 2026-09-25)

Proven end to end from a fresh worktree: `bun setup`, `bun dev --worktree` (local Convex, tunnel,
seeded creator, Slack #test-blank, spawns ready), `bun e2e` PASS, `bun screenshot /dashboard/leads`
(real page), and prod reads: `bun ops ... --prod`, `bun investigate --prod`, `bun errors --prod`.
Playwright Chromium is installed for screenshots. Worker logs: `bun logs` on a dev stack; prod worker
failures land in Convex errorLogs, so `bun investigate --prod` / `bun errors --prod --source worker`.

MCP servers on the box (Claude, user scope): vercel plugin + gscServer work; slack plugin, linear-server,
cloudflare-api, replicate need a one-time OAuth: in a box terminal (remote desktop) run `claude`, then
`/mcp`, and authenticate each; the browser opens on the box. Not available on the box: claude.ai
connectors (Gmail etc., need claude.ai login, the box uses the proxy), Coast (Mac screen history),
Codex computer-use.

## Linux-specific fixes (2026-09-25)

- **inotify limits** raised in `/etc/sysctl.d/60-agentbox-inotify.conf` (524288 watches, 1024 instances):
  several `bun dev --worktree` stacks at once exhaust the default 128 instances (ENOSPC).
- **gstack** (`~/.claude/skills/gstack`) was copied from the Mac with a Mac `browse` binary. Rebuilt on
  the box: `rm -rf browse/dist && PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 ./setup` then
  `bun run build` (its Playwright predates Ubuntu 26.04; the override is needed for any gstack upgrade).
  gstack's setup garbage-collects "unused" Playwright browsers, which deletes revnu's; afterwards run
  `bunx playwright install chromium` in `~/Documents/projects/revnu2`.
- **Chrome sandbox**: Ubuntu 23.10+ blocks unprivileged user namespaces, so sandboxed Playwright Chrome
  dies with "No usable sandbox!". `/etc/apparmor.d/playwright-chrome` grants `userns` to
  `~/.cache/ms-playwright/**/chrom*` only (targeted, instead of disabling the restriction globally).

## Other repos on the box (~/projects)

Cloned from GitHub 2026-09-25: `pokeheartgold`, `resoled-app`, `personal` (personal-site), `blog`.

**pokeheartgold** builds a matching HeartGold ROM on the box (sha1 4fcded0e..., `make -j12`, verified
2026-09-25). A clone alone is NOT enough; these git-ignored pieces were copied from the Mac's active
checkout (`~/.t3/worktrees/pokeheartgold/t3code-32aa0f3c`):
- `AGENTS.md`, `PROJECT-MEMORY.md` (agent rules and project memory)
- `tools/mwccarm/` (Metrowerks compilers, proprietary), `tools/bin/` (NitroSDK Windows tools)
- `ARM9-TS.lcf.template`, `sub/ARM7-TS.lcf.template`, `mwldarm.response.template`
- `.local-tools/` (7.2 GB: reference objects, scratch, helper scripts), minus the Mac Wine app and prefixes
- the 8 unpushed local agent branches, via `git bundle` (nothing pushed to GitHub)
Linux-specific: apt deps from INSTALL.md (wine + wine32:i386, binutils-arm-none-eabi, libpng-dev,
libpugixml-dev); `tools/gen_fx_consts` must be built first with
`make -C tools/gen_fx_consts LDFLAGS=-Wl,--no-as-needed` (its Makefile puts `-lm` before the objects);
`.local-tools/Wine Devel.app/Contents/Resources/wine/bin/wine` is a symlink to `/usr/bin/wine` so the
helper scripts' hard-coded Mac path works unchanged. Mac and box `.local-tools` are not synced.

## T3 browser previews of the box's dev servers (2026-09-26)

T3's built-in browser only maps `localhost:<port>` to the box when the environment's server address is
a private-network host (`.local`, 192.168.x, Tailscale 100.64/10). Through T3 Connect (a public relay)
it can't yet ("needs the planned authenticated preview gateway"), so `localhost:3000` in that browser
is the MAC's localhost. Fix: the box's T3 server listens on all interfaces
(`~/.config/systemd/user/t3code.service.d/network.conf`: `T3CODE_HOST=0.0.0.0`), and the Mac adds a
pairing link to `http://skynet.local:3773` (`t3 pair --ttl 30m`; the 30 min is only the window to
use it, the pairing is permanent). T3 MERGED it with the T3 Connect entry (same environment id): the Mac
now reaches the box directly, and `localhost:3000` in the preview became `skynet.local:3000`
(verified 2026-09-26). Untested: away from home the `.local` address won't resolve; if the box shows
disconnected, pair `http://100.85.99.101:3773` with Tailscale on. The phone still uses T3 Connect.
OAuth sign-in on a box stack redirects to the Mac's `localhost:3000`; use `bun dev-login` instead.

## Slow/laggy box: leaked Convex executors (2026-09-29)

Symptom: `box`/`box proxy` crawl and ping to the box jitters to 100+ ms while the network is fine.
Cause: `convex-local-backend` does not stop its node executor (`node /tmp/.tmpX/local.cjs`) when it shuts
down, even on a clean SIGTERM (reproduced 2026-09-29). Every local backend that stops, from `bun dev --worktree`
boot (`convex dev --once`) or teardown, leaks one executor plus its temp dir in RAM-backed `/tmp`. 128 had piled
up: ~8 GB RAM, 13 GB `/tmp`, swap full, load 38. The Mac leaks the same way.
Prevention: user timer `reap-convex-executors.timer` (every 10 min) runs `~/.local/bin/reap-convex-executors`,
which kills executors whose parent is no longer a `convex-local-backend` and deletes their temp dir.
Check: `systemctl --user list-timers reap-convex-executors.timer`; `journalctl --user -u reap-convex-executors`.

## /tmp age-out (2026-09-29)

`/tmp` is RAM-backed, and agents fill it with Chrome automation profiles, video renders and scratch dirs.
`/etc/tmpfiles.d/tmp.conf` overrides Ubuntu's 10-day default: anything in `/tmp` untouched for 3 days is removed
by the daily `systemd-tmpfiles-clean.timer`. Excluded because they live as long as a dev stack or session:
`/tmp/.tmp*` (Convex executors), `/tmp/revnu-wt-tar-*`, `/tmp/tmux-*`, `/tmp/codex-*`. Run by hand with
`sudo systemd-tmpfiles --clean`. Repo-side leaks fixed in #1914 (Convex executors) and #1915 (worktree tarballs).

## T3 service won't start after `t3 update` (2026-09-29)

Updating 0.0.42 -> 0.0.44 left the service crash-looping with `[service-launcher] Service state is invalid or
unsupported`, and `t3 service install` failed the same way. Cause: the update left a stale
`~/.t3/runtime/.service-stopping` marker. Fix: move that file aside, then
`systemctl --user reset-failed t3code && systemctl --user start t3code`. Codex is the standalone install
(`~/.codex/packages/standalone`), so update it with `codex update`, not npm.

## Out of memory from forgotten dev stacks (2026-10-02)

Symptom: T3 Code can't connect, `box status` shows memory ~full, load 30+. Not the executor leak: the box had 7
`bun dev --worktree` stacks (3-5 GB each: next-server + convex-local-backend + workerd), 4 of them days old, plus
one thread's 3 subagents each booting its own stack. Swap filled and T3 stopped answering. The Mac rarely hits this
because stacks die when it sleeps/reboots, and macOS compresses memory before swapping.
- **zram**: `/etc/systemd/zram-generator.conf` (zstd, ram/2 = 20 GB, priority 100, used before `/swap.img`) and
  `/etc/sysctl.d/99-zram.conf` (swappiness 180, page-cluster 0). Check with `zramctl`. Note: installing the package
  starts zram with defaults before the config exists; `systemctl restart systemd-zram-setup@zram0` after editing.
- **Idle stack reaper**: user timer `reap-idle-dev-stacks.timer` (every 30 min) runs `~/.local/bin/reap-idle-dev-stacks`.
  It SIGTERMs a stack's `scripts/dev.ts` (clean teardown) when the worktree shows no activity for 8h (edited files
  outside build dirs, git index/HEAD, or a Claude transcript for that path), and appends a `[reaper]` line to that
  stack's `dev.log` so the agent sees why. It also kills next/convex/workerd processes with no live `scripts/dev.ts`
  ancestor, only in directories that have a `.dev/*/dev.pid`. Try `reap-idle-dev-stacks --dry-run`; tune with
  `IDLE_HOURS=`. Logs: `journalctl --user -u reap-idle-dev-stacks`.

## Second box: jarvis (2026-10-02)

Dell Precision 5550 laptop (12 threads, 30 GB, 937 GB), Ubuntu 26.04, user `art`, `ssh jarvis` (home network,
`jarvis.local`, Wi-Fi only so far). T3 Connect environment "jarvis".
- Always-on: sleep masked, `HandleLidSwitch*=ignore` in `/etc/systemd/logind.conf.d/lid.conf`, GNOME idle off,
  auto-login, linger, inotify raised, Wi-Fi power save off.
- Battery capped 75-80% by `battery-limit.service` (it is always plugged in).
- **No Claude logins on jarvis.** `~/.claude/settings.json` points at skynet's proxy
  (`ANTHROPIC_BASE_URL=http://skynet.local:24873`); the proxy key is in `~/.cli-proxy-api/proxy-key`. For this,
  skynet's proxy listens on `0.0.0.0` (still API-key protected). Away from home jarvis has no Claude.
- T3 Connect free tier allows 3 tunnels per account (skynet, jarvis, +1). The MacBook Air was removed to make room.
  "pending server startup" after linking needed several `systemctl --user restart t3code`.
- Login keyring created with no password (2026-10-02).
- 2026-10-02 later: Doppler + gh logged in; `~/Documents/projects/revnu2` cloned, `bun setup` green. Verified in a throwaway
  worktree: `bun dev --worktree` up, `bun e2e` PASS, `bun screenshot /dashboard/leads` renders. Reaper timers and
  zram copied from skynet.
- **Trap:** a fresh Ubuntu with auto-login has NO login keyring at all. Chrome then blocks forever on the first
  cookie write (CDP `Network.setCookie` never answers), so `bun screenshot` "gave up after 90s". Fix: create
  `~/.local/share/keyrings/login.keyring` with no password (`[keyring]` plaintext header) + `default` = `login`.
- 2026-10-02 parity with skynet: skills/plugins/settings/MCP config/memories copied from skynet (same paths), git
  identity set, codex/convex/vercel/wrangler/pnpm/uv installed and logged in (Convex device "jarvis"). revnu2 added as
  a T3 project via `t3 project add`. Prod reads (`bun errors --prod`, `bun ops creators --prod`) verified.
  Still per-machine: OAuth MCPs (revnu, linear, slack, vercel, cloudflare, replicate) via `/mcp` at jarvis's desktop.
- 2026-10-02: Tailscale on jarvis (`100.123.203.103`, exit node advertised, forwarding in `/etc/sysctl.d/99-tailscale.conf`).
  Claude on jarvis now uses skynet's proxy by Tailscale IP (`http://100.85.99.101:24873`), so it works away from home.
  `box ... jarvis` falls back to Tailscale. Remote desktop on jarvis: same Keychain password (`agentbox-rdp`). RAM: 2x16 GB DDR4 SODIMM, max 64 GB.

## revnu2 path standardised (2026-10-02)

Every machine keeps revnu2 at `~/Documents/projects/revnu2`, like the Mac, so Claude's memory folder is
`-home-art-Documents-projects-revnu2` on both Linux boxes. skynet had a second, unused clone at `~/projects/revnu2`
(deleted; it was clean) whose memory folder `box sync-memory` was syncing while skynet's threads wrote to the
Documents one. Old folder kept in `~/old-memory-backup/` on skynet. Other repos on skynet stay in `~/projects`.
- 2026-10-03: Tailscale SSH turned off on jarvis (`tailscale set --ssh=false`); it demanded a browser check,
  so `box` couldn't reach jarvis away from home. Fixed by hopping through skynet (`ssh -J`).
- 2026-10-03: heartbeat (ntfy, 30 min) on skynet + jarvis, `box usage`, 6-hourly memory sync on the Mac.

## Hermes Agent (2026-10-04)

Nous Research's personal agent, installed to look around in. **No tasks, cron jobs or messaging set up.**

- Installed with the official script (`--non-interactive --skip-computer-use`): code in `~/.hermes/hermes-agent`,
  data and config in `~/.hermes/` (`config.yaml`, `.env`, `memories/`, `sessions/`). Backup of the stock config:
  `~/.hermes/config.yaml.bak-install`. Update with `hermes update`.
- Model: `providers.claude-proxy` in `config.yaml` points at this box's CLIProxyAPI (`http://127.0.0.1:24873`,
  `transport: anthropic_messages`), key minted by `key_cmd: ~/.cli-proxy-api/api-key-helper.sh` so no key is copied.
  Primary `claude-sonnet-5-5`, fallback `claude-haiku-4-5-20251001`. It shares the Claude accounts' limits with the
  coding agents: when they're spent it drops to Haiku.
- Dashboard: `hermes-dashboard.service` (systemd user unit) on `127.0.0.1:9119` only. A non-loopback bind needs an
  auth provider (password/OAuth), so reach it with `box hermes` (SSH tunnel), never by binding 0.0.0.0.
- Messaging isn't configured. Telegram/WhatsApp/Slack/Discord/Signal via `hermes gateway setup`; iMessage via
  BlueBubbles (needs an always-on Mac) or Photon (`hermes photon setup --phone ...`, no Mac).
