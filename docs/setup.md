# Your own agent box: an always-on Linux machine for T3 Code

An agent box is a mini PC (or an old laptop) that sits at home, never sleeps, and runs your coding
agents. You drive it from T3 Code on your laptop or phone through T3 Connect, so agents keep working
with the laptop shut. Art set up the first one on 2026-09-25 (a GMKtec M6 Ultra) and a second on
2026-10-02 (a Dell Precision laptop); this is the recipe, including every trap he hit.

Everything below is done with **your own** accounts. The only shared secrets are the revnu env files,
which come from Doppler (see "Shared vs personal" at the end).

## Hand it to an agent

Do steps 1 to 3 by hand (install Ubuntu, then SSH). After that, an agent on your laptop can do the rest.
Give it this:

> New agent box: `ssh you@<host>.local` works (key auth, passwordless sudo). Set it up by following
> `docs/setup.md` from section 4 on, and verify each section before moving on. Ask me only
> for the device-code approvals (T3 Connect, GitHub, Doppler, Codex, Convex, Vercel, Tailscale) and the
> per-machine MCP sign-ins. Finish with the health check and a passing `bun e2e` +
> `bun screenshot /dashboard/leads` in a throwaway worktree.

Expect about an hour, most of it installs, with you clicking approval links as they appear.

## 1. Hardware

- Any x86-64 machine with **16 GB+ RAM** (32 GB+ if it will run several revnu dev stacks; each takes
  3-5 GB) and an SSD. Ryzen mini PCs from GMKtec, Beelink or Minisforum are fine, and so is a spare
  laptop. The CPU sits near idle; RAM is what runs out.
- **Plug it into the router with ethernet.** Over Wi-Fi, remote desktop kept dropping (error 0x200d)
  and latency jumped from 3 to 120 ms. Wi-Fi works as a fallback, or until you get a USB adapter.
- **Not a VPS.** It costs more than a mini PC within months, and Claude subscription logins from
  datacenter IPs get flagged. A box at home also draws only a few pounds of electricity a month
  (measured: ~7 W CPU idle on the Ryzen mini PC, ~2 W on the laptop).
- For setup only: a USB stick (8 GB+), a wired keyboard, a monitor (a laptop has its own).

## 2. Install Ubuntu

1. Download **Ubuntu 26.04 LTS Desktop** (amd64) from ubuntu.com. Desktop, not Server: you get a real
   browser for OAuth logins and a desktop to remote into, for ~1 GB of RAM.
2. Flash it from your Mac. balenaEtcher currently fails on macOS ("requestMetadata is not a function"),
   so use `dd`, with the **full** path (zsh doesn't expand `~` after `if=`):
   ```bash
   diskutil list external physical          # find the stick, e.g. disk4. Check the size!
   diskutil unmountDisk /dev/diskN
   sudo dd if=/Users/you/Downloads/ubuntu-26.04.1-desktop-amd64.iso of=/dev/rdiskN bs=4m status=progress
   ```
   A 16 GB stick at 12 MB/s takes ~9 minutes.
3. Boot from USB. On GMKtec: **F7** is the boot menu, **Esc** is the BIOS (Dell: **F12**). Mac-style
   keyboards may need **Fn+F7**, and a Bluetooth keyboard won't work at this stage. If no key works,
   Windows setup's Shift+F10 → `shutdown /r /fw /t 0` reboots straight into the BIOS.
4. **In the BIOS, set "Restore on AC Power Loss" to Power On** (under Advanced/Chipset). Otherwise the
   box stays off after a power cut. You can't change this remotely later.
5. Install: erase the disk, **no disk encryption** (it would need a password at every boot), tick
   third-party software. Pick a short hostname; it becomes the T3 environment name (renaming later is
   possible but fiddly, see section 7).

A Bluetooth mouse's USB cable only charges it; pair it in Settings → Bluetooth after install.

## 3. Hand it over to SSH (at the box, once)

Open a terminal on the box (Ctrl+Alt+T). Ubuntu Desktop ships without an SSH server:
```bash
sudo apt install -y openssh-server
echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/$USER-nopasswd   # lets agents administer it
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "<contents of your laptop's ~/.ssh/id_ed25519.pub>" >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
hostname
```
(`ssh-keygen -t ed25519` on the laptop first if you have no key.) From here on everything is remote:
`ssh you@<hostname>.local` works on your home network even when the IP changes. You never need the box's
screen again.

## 4. Make it always-on

Over SSH (`B=` is needed for the GNOME settings):
```bash
B="DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus"
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
env $B gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing
env $B gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type nothing
env $B gsettings set org.gnome.desktop.session idle-delay 0
env $B gsettings set org.gnome.desktop.screensaver lock-enabled false
printf "[connection]\nwifi.powersave = 2\n" | sudo tee /etc/NetworkManager/conf.d/wifi-powersave-off.conf
sudo sed -i -E "s/^#?\s*AutomaticLoginEnable.*/AutomaticLoginEnable = true/; s/^#?\s*AutomaticLogin\s*=.*/AutomaticLogin = $USER/" /etc/gdm3/custom.conf
sudo loginctl enable-linger $USER          # user services run at boot with nobody logged in
printf "fs.inotify.max_user_watches=524288\nfs.inotify.max_user_instances=1024\n" | sudo tee /etc/sysctl.d/60-inotify.conf && sudo sysctl --system
```
The inotify limits stop parallel `bun dev --worktree` stacks failing with ENOSPC.

**The login keyring must exist and have no password.** With auto-login, a password-protected keyring
stays locked after every reboot, which silently breaks remote desktop, `gh` and Doppler. And a fresh
install that has never had a password-entry login may have **no** login keyring at all: then Chrome
blocks forever on its first cookie write, and `bun screenshot` "gives up after 90s" (2026-10-02, the
laptop box). Check `ls ~/.local/share/keyrings/`. If `login.keyring` is missing, create an unlocked one:
```bash
K=~/.local/share/keyrings; mkdir -p $K && chmod 700 $K
printf "[keyring]\ndisplay-name=Login\nctime=0\nmtime=0\nlock-on-idle=false\nlock-after=false\n" > $K/login.keyring
echo -n login > $K/default && chmod 600 $K/*
```
If it exists with a password, do it at the screen instead: **Passwords and Keys** → right-click
**Login** → Change Password, enter your password and leave the new one blank.

**Laptop as a box**, also:
```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf "[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n" | sudo tee /etc/systemd/logind.conf.d/lid.conf
sudo systemctl kill -s HUP systemd-logind
```
and cap the battery so it doesn't sit at 100% forever (it swells). If
`/sys/class/power_supply/BAT0/charge_control_end_threshold` exists, a oneshot service that writes
`Custom` to `charge_types`, 75 to `charge_control_start_threshold` and 80 to the end threshold at boot
does it. Otherwise set a charge limit in the BIOS.

Also on the box:
- Only advertise the wired address, so `<host>.local` never resolves to Wi-Fi:
  `sudo sed -i -E "s/^#?allow-interfaces=.*/allow-interfaces=enp3s0,eno1/" /etc/avahi/avahi-daemon.conf`
  (check your interface names with `ip -br a`), then `sudo systemctl restart avahi-daemon`.
- If you use Ghostty on the Mac, copy its terminfo over or tmux refuses to start:
  `TERMINFO=/Applications/Ghostty.app/Contents/Resources/terminfo infocmp -x xterm-ghostty | ssh you@box 'tic -x -'`

## 5. Toolchain

```bash
sudo apt install -y git curl tmux btop build-essential unzip jq ripgrep nodejs npm gh libfuse2t64
curl -fsSL https://bun.sh/install | bash
curl -fsSL https://claude.ai/install.sh | bash
curl -fsSL https://t3.codes/install.sh | sh
curl -LsSf https://astral.sh/uv/install.sh | sh
echo 'export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"' >> ~/.profile
export PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"
npm config set prefix ~/.local && npm i -g @openai/codex
bun add -g convex vercel wrangler pnpm tsx typescript
```
Plus, from their apt repos: **cloudflared** (install it before `t3 connect`, or T3 stops at an
interactive "download the relay client?" prompt), **Doppler**, and Google Chrome:
```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-public-v2.gpg | sudo tee /usr/share/keyrings/cloudflare-public-v2.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-public-v2.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
curl -sLf "https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key" | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" | sudo tee /etc/apt/sources.list.d/doppler-cli.list
sudo apt-get update && sudo apt-get install -y cloudflared doppler
```
**Put PATH in `~/.profile`, not `~/.bashrc`:** T3 Code finds CLIs through a non-interactive login shell,
so anything only in `.bashrc` is invisible to it.

## 6. Accounts (all yours)

Every CLI below has a device-code login: run it over SSH, open the printed link in any browser
(your Mac's is fine), approve. An agent can start several at once and hand you all the links together.

| Tool | Command | Needed for |
|---|---|---|
| GitHub | `gh auth login -h github.com -p https -w`, then `gh auth setup-git` | cloning, pushing, PRs |
| Doppler | `doppler login` (you need an invite to the `revnu2` project) | `bun setup` env files |
| Convex | `bunx convex login --no-open --device-name <host>` | `bun investigate/errors/ops --prod` |
| Vercel | `vercel login` | deploy and env tooling |
| Codex | `codex login --device-auth` | Codex threads |
| Claude | run `claude` in a terminal on the box, then `/login` (or point it at a proxy, below) | Claude threads |

Over SSH, `convex login` fails with "Cannot prompt for input" unless you pass `--device-name`. Also set
your git identity (`git config --global user.name/user.email`), or commits from the box go out unnamed.

**Never copy Claude or CLIProxyAPI token files from another machine.** Both machines refresh the same
token and log each other out. Log in fresh on the box instead.

**A second box doesn't need its own Claude login.** If your first box runs CLIProxyAPI (a proxy that
holds your Claude subscription logins), point the second box's Claude Code at it instead:
`~/.claude/settings.json` gets `env.ANTHROPIC_BASE_URL=http://<first-box Tailscale IP>:<port>` plus an
`apiKeyHelper` that prints the proxy's API key. The proxy must listen beyond `127.0.0.1` (`host: "0.0.0.0"`
in its config; the API key still guards it). One proxy means one set of logins, all traffic from your
home IP, and its `routing.strategy: fill-first` spends one account down before touching the next.
Only ever use a Claude subscription inside Claude Code.

## 7. T3 Code server and T3 Connect

```bash
t3 service install                       # systemd user service, starts at boot
t3 connect link --headless               # device code: approve with your T3 account
systemctl --user restart t3code          # repeat until `t3 connect status` says "provisioned"
```
After linking, `t3 connect status` often says "pending server startup"; restart the service again
(it took two restarts on both of Art's boxes). If it never provisions, read
`~/.t3/userdata/logs/boot-service.log`: **the free T3 Connect tier allows 3 tunnels per account**
("Relay managed tunnel limit reached"). Remove a machine you no longer use from Settings → Connections,
then restart again.

Then on your laptop, in T3 Code: **Settings → Connections**, click **Add** on the box. **Projects belong
to one environment**: add the repo as a project on the box, from the box:
`t3 project add ~/Documents/projects/revnu2`. Sign in to the T3 mobile app with the same account to see
it on your phone. T3 groups the copies of one repo across machines by its git remote, so they share
settings; see section 8 for the one way that breaks.

**To see the box's dev servers in T3's built-in browser**, T3 Connect is not enough: T3 only maps
`localhost:<port>` to a remote environment whose address is on a private network, so over T3 Connect
`localhost:3000` is your laptop. Make the box's server listen on the network and pair it directly:
```bash
mkdir -p ~/.config/systemd/user/t3code.service.d
printf "[Service]\nEnvironment=T3CODE_HOST=0.0.0.0\n" > ~/.config/systemd/user/t3code.service.d/network.conf
systemctl --user daemon-reload && systemctl --user restart t3code
t3 pair --ttl 30m        # prints a pairing URL
```
Replace the IP in the printed URL with `<host>.local` (or the box's Tailscale IP when away) and paste it
into Settings → Connections → Add environment. The pairing is permanent; the TTL is only how long the
link can be used. T3 merges it with the T3 Connect entry (same environment), after which your laptop
reaches the box directly and the preview rewrites `localhost:3000` to `<host>.local:3000`. Sign in to a
box stack with `bun dev-login`; OAuth redirects back to your laptop's `localhost:3000`.

Restarting `t3code.service` (or rebooting) kills every agent thread running on the box ("Provider session
did not survive a server restart"); the files survive, send each thread a message to continue.

**Renaming a box** keeps its threads (they live in `~/.t3/userdata/state.sqlite`, keyed by
`~/.t3/userdata/environment-id`, not the hostname), but T3 Connect caches the old name. Rename with
`sudo hostnamectl set-hostname <new>` (and the `127.0.1.1` line in `/etc/hosts`,
`sudo systemctl restart avahi-daemon`, `sudo tailscale set --hostname=<new>`), then
`t3 connect unlink && t3 connect link --headless`, restart until provisioned, and on the laptop remove the
environment and **Add** it again. Everything pointing at `<old>.local` (SSH config, pairings) needs updating.

## 8. revnu on the box

**Use the same path on every machine: `~/Documents/projects/revnu2`.** Claude keeps memories per
directory path, so two paths means two memory folders that never see each other (on 2026-10-02 one box
had a second, unused clone whose memories were being synced while its threads wrote somewhere else).
Clone it normally, **not** with `--filter=blob:none`: on a partial clone `git remote -v` appends
`[blob:none]`, T3 fails to parse the remote, and the project stops grouping across machines and hides its
linked PRs (T3 issue #12764). To fix an existing partial clone:
`git config --unset remote.origin.partialclonefilter && git fetch --refetch origin`, check
`git fsck --connectivity-only` reports nothing missing, then `git config --unset remote.origin.promisor`.

```bash
mkdir -p ~/Documents/projects && cd ~/Documents/projects && gh repo clone revnu-app/revnu2 && cd revnu2
doppler setup --project revnu2 --config dev --no-interactive
bun setup                                          # env files from Doppler + bun doctor
bunx playwright install --with-deps chromium       # for bun screenshot
```
Verify with a worktree stack, the same loop as on a laptop. `bun dev --worktree` refuses to run in the
main checkout, so make a throwaway worktree:
```bash
git worktree add --detach ../revnu2-smoketest && cd ../revnu2-smoketest && bun setup
bun dev --worktree     # wait for "sandbox spawns ready", then in another shell:
bun e2e                # expect PASS
bun screenshot /dashboard/leads
```
Then stop the stack and `git worktree remove --force ../revnu2-smoketest`. Also check prod reads:
`bun errors --prod --since 1h`.

Ubuntu 23.10+ blocks the Chrome sandbox ("No usable sandbox!"). If a Playwright tool hits it, allow
it for Playwright's browsers only:
```bash
sudo tee /etc/apparmor.d/playwright-chrome <<'EOF'
abi <abi/4.0>,
include <tunables/global>
profile playwright-chrome /home/*/.cache/ms-playwright/**/chrom* flags=(unconfined) {
  userns,
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/playwright-chrome
```

**Claude setup, the same as your laptop:** copy `~/.claude/skills/`, `~/.claude/plugins/` and
`~/.claude/settings.json` from your laptop or first box (keep the box's own `env`/`apiKeyHelper`), and
the `mcpServers` block of `~/.claude.json`. These are config, not credentials. Each OAuth MCP server
(revnu, Linear, Slack, Vercel, Cloudflare, Replicate) then needs its own sign-in on the box: run `claude`
in a terminal on the box's desktop, `/mcp`, sign in to each (the browser opens there). Don't copy
their tokens, for the same reason as Claude's. Cloudflare's MCP must be `--transport http`; as SSE it
fails with HTTP 405. The revnu memory folder (`~/.claude/projects/<path-slug>/memory`) can be copied
over too, and kept in sync with rsync.

## 9. Keep it healthy

A box never reboots, so leaks that a laptop clears by sleeping pile up. On 2026-10-02 forgotten
`bun dev` stacks (3-5 GB each) filled skynet's memory and T3 stopped answering. Three guards:

- **Reaper timers.** Copy the files in [`reapers/`](../reapers/): the two scripts to `~/.local/bin/`
  (`chmod +x`), the four units to `~/.config/systemd/user/`, then
  `systemctl --user daemon-reload && systemctl --user enable --now reap-convex-executors.timer reap-idle-dev-stacks.timer`.
  `reap-idle-dev-stacks` stops a stack with no activity for 8 hours and writes a `[reaper]` line to its
  `dev.log`; try `reap-idle-dev-stacks --dry-run`. `reap-convex-executors` kills Convex local-backend
  executors orphaned by a stopped backend.
- **zram** (compressed swap, used before the disk):
  `sudo apt install -y systemd-zram-generator`, then `/etc/systemd/zram-generator.conf` with
  `[zram0]`, `zram-size = ram / 2`, `compression-algorithm = zstd`, `swap-priority = 100`;
  `/etc/sysctl.d/99-zram.conf` with `vm.swappiness = 180` and `vm.page-cluster = 0`; then
  `sudo sysctl --system && sudo systemctl daemon-reload && sudo systemctl restart systemd-zram-setup@zram0`.
- **/tmp age-out.** `/tmp` is RAM-backed. An `/etc/tmpfiles.d/tmp.conf` with `Q /tmp 1777 root root 3d`
  plus `x` lines excluding `/tmp/.tmp*`, `/tmp/revnu-wt-tar-*`, `/tmp/tmux-*` and `/tmp/codex-*` clears
  anything untouched for 3 days.

If `t3 update` leaves the service crash-looping with "Service state is invalid or unsupported", move
`~/.t3/runtime/.service-stopping` aside, then `systemctl --user reset-failed t3code && systemctl --user start t3code`.

## 10. Remote desktop (for the occasional GUI job)

```bash
B="DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus"; export $B
D=~/.local/share/gnome-remote-desktop; mkdir -p $D
openssl req -new -newkey rsa:4096 -days 3650 -nodes -x509 -subj "/CN=$(hostname)" -keyout $D/rdp-tls.key -out $D/rdp-tls.crt
grdctl rdp set-tls-key $D/rdp-tls.key && grdctl rdp set-tls-cert $D/rdp-tls.crt
grdctl rdp set-credentials you '<pick a password>'
grdctl rdp disable-view-only && grdctl rdp enable
gsettings set org.gnome.desktop.remote-desktop.rdp screen-share-mode extend   # virtual monitor, no screen attached
systemctl --user enable --now gnome-remote-desktop
```
**Connect with FreeRDP, not Microsoft's Windows App.** Against GNOME's RDP server the Windows App
dropped every session after about a minute, even wired; FreeRDP held:
```bash
brew install freerdp
sdl-freerdp /v:<host>.local /u:you /p:'<password>' /cert:ignore /dynamic-resolution +clipboard +auto-reconnect
```

## 11. Away from home

T3 Connect already works from anywhere. For SSH, remote desktop and a second box reaching the first
box's Claude proxy, install Tailscale on each box, in **your own** tailnet:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname=<host>     # prints a login link
```
In the admin console, **disable key expiry** for the box, or it drops off after 180 days. Your laptop
only needs Tailscale switched on when you're away. Never port-forward SSH or RDP on the router. To offer
the box as an exit node, enable forwarding (`net.ipv4.ip_forward = 1` and
`net.ipv6.conf.all.forwarding = 1` in `/etc/sysctl.d/99-tailscale.conf`), add `--advertise-exit-node`,
and approve it in the admin console.

## Shared vs personal

| Shared (granted by an admin) | Personal (never copied between people) |
|---|---|
| Doppler `revnu2` project: every revnu env var, incl. dev Convex, Slack, Cloudflare | Claude subscription / Anthropic workspace key |
| Doppler `revnu2-readonly` `prd`: prod reads for `bun investigate --prod` (see revnu2 `docs/knowledge/secrets-doppler-2026-08-30.md`) | GitHub, T3, Vercel, Convex, Codex logins |
| GitHub `revnu-app` org membership | Tailscale tailnet, RDP password, SSH keys |

A box that runs `bun dev` stacks spends model money like any laptop. Keep dev stacks on your own
Anthropic workspace and don't leave them running (revnu2 `docs/knowledge/anthropic-spend-dev-stacks-2026-09-20.md`).

## Health check

```bash
systemctl --user is-active t3code gnome-remote-desktop; systemctl is-active tailscaled
t3 connect status | grep -E "link|Relay"      # "provisioned"
systemctl --user list-timers | grep reap       # both reapers scheduled
zramctl                                        # zram0 present
sudo systemctl suspend      # should fail with "Access denied": sleep is masked
```
Reboot it once (`sudo systemctl reboot`) and confirm T3 Connect, SSH and remote desktop come back with
nobody touching it before you unplug the keyboard for good.
