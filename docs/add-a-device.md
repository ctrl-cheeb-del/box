# Adding a device to Art's setup

Two cases: a new **client** (laptop, phone) that drives the existing box, or a **second box**.
The general recipe for building a box is in the revnu2 repo: `docs/setup.md`.
This file is the Art-specific part. Paths only, no secret values.

## A new laptop (drives the box)

1. **T3 Code**: install, sign in to T3 Connect as **art@revnu.com**, then Settings → Connections →
   Add environment → T3 Connect → skynet. Projects are per environment: add the box's repos
   (`/home/art/Documents/projects/revnu2`, `/home/art/projects/pokeheartgold`, ...) as projects on skynet.
   That's enough for agent work; the rest is for SSH and remote desktop.
2. **SSH key**: on the new laptop `ssh-keygen -t ed25519`, then from a machine that already has access:
   `cat new_laptop_key.pub | ssh agentbox 'cat >> ~/.ssh/authorized_keys'`.
   Password SSH is not the way in; only keys work.
3. **The `box` CLI and SSH alias**: install this repo (README, "Install on a new Mac"), copy
   nothing else. Append the `agentbox` blocks from the old Mac's
   `~/.ssh/config` (the `Match ... exec nc` block plus `Host agentbox` / `agentbox-remote`).
   Aliases (`bx`, `bxd`, `bxs`, `bxp`) are four lines at the end of `~/.zshrc`.
4. **Remote desktop**: `brew install freerdp`, then store the RDP password in the new Keychain:
   `security add-generic-password -a art -s agentbox-rdp -w` (prompts for it). `box desktop` reads it.
5. **Tailscale**: install, sign in as theredxer@ (same tailnet). Only needed away from home.
6. **Claude memories**: `box sync-memory` pulls the box's revnu2 memories onto the new Mac.
7. If it's a Ghostty user: push its terminfo (README troubleshooting has the one-liner).

## A phone

T3 app signed in as art@revnu.com, then add skynet as an environment (T3 account → T3 Connect →
tap it). Optional: Tailscale app (same tailnet) plus an RDP client for the desktop.

## Another box (the third, fourth...)

Install Ubuntu and do section 3 of `docs/setup.md` at the machine (SSH server, passwordless
sudo, this Mac's key, `hostname`). Then paste this into a T3 thread on the Mac:

> New agent box `<name>`: `ssh art@<name>.local` works. Set it up exactly like jarvis, following
> `docs/setup.md` from section 4 and `docs/machines.md` ("Second box: jarvis").
> Specifically: no Claude logins on it; point Claude at skynet's proxy by Tailscale IP
> (`http://100.85.99.101:24873`, key from skynet's `~/.cli-proxy-api/api-key-helper.sh` into
> `~/.cli-proxy-api/proxy-key`). Copy skills, plugins, settings, MCP config, the GSC client secrets and
> the revnu memory folder from skynet. revnu2 at `~/Documents/projects/revnu2` (full clone), Doppler
> `revnu2/dev`, `t3 project add` it. Reapers + zram + /tmp age-out. Tailscale with key expiry off.
> Remote desktop with the `agentbox-rdp` Keychain password. Add it to `machines`.
> Give me every approval link (T3 Connect, gh, Doppler, Convex, Vercel, Codex, Tailscale) as you go.
> Verify with a throwaway worktree: `bun e2e` PASS and `bun screenshot /dashboard/leads`, then
> `bun errors --prod`, `box status <name>` and `box sync-memory`.

Accounts on every box: GitHub ctrl-cheeb-del, Doppler (Revnu workplace), Convex (`--device-name <name>`),
Vercel ctrl-cheeb-del, Codex (ChatGPT), T3 Connect art@revnu.com, Tailscale theredxer@.

Things that will need you:
- **T3 Connect free tier = 3 tunnels.** skynet + jarvis + one more. A fourth box needs a machine removed
  from Settings → Connections first (or a paid tier).
- After approving T3 Connect, click **Add** on the box in Settings → Connections.
- The OAuth MCPs (revnu, Linear, Slack, Vercel, Cloudflare, Replicate): `box desktop <name>`, run
  `claude` in `~/Documents/projects/revnu2`, `/mcp`, sign in to each.

## Handing a box to a coworker

Point them at `docs/setup.md`. They use their own accounts for everything except the
Doppler `revnu2` project and the `revnu-app` GitHub org, which an admin grants. Don't give them this
folder: it describes Art's credential locations.
