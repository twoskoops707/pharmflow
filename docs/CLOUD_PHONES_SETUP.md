# Cloud phones + agent — one-login free path

PharmFlow wires **Oracle Cloud Always Free + Redroid** (phones) and **FreeLLMAPI** (agent) through one Control Panel login. There is no separate CloudPhones.exe and no second farm Python stack.

## Audit A6 / other checkouts (skoops)

`tools/cloud_connect.py` ships on branch `cursor/cloud-connect-widget-1a5f` (and on `main` only **after** that PR merges). A checkout still on older `main` correctly reports the file **absent** — that is not a live-EXE bug.

**Do not stomp farm/Builder work.** Prefer waiting for the PR merge, then `git pull origin main`. If you must preview before merge:

```bat
git fetch origin cursor/cloud-connect-widget-1a5f
git checkout origin/cursor/cloud-connect-widget-1a5f -- tools/cloud_connect.py tools/cloud_agent.py tests/test_cloud_connect.py docs/CLOUD_PHONES_SETUP.md docs/EXE_QUICK_START.md cloud_phones/README.md wizard/assets/pharmflow_app/index.html wizard/assets/pharmflow_app/app.js wizard/assets/pharmflow_app/app.css
```

Shared bridge/webview/desktop files also contain cloud hunks — take those only if you can merge by hand (`cloud_connect_login` / `cloud_session_status`). Never `git checkout … -- .` from this branch onto a dirty farm/Builder tree. This work does **not** swap `C:\PharmFlow\PharmFlow.exe`.

## One login (Control Panel)

1. Open **PharmFlow.exe** → **Run** → **Cloud connect**.
2. Enter the Oracle/Redroid **host IP** (Tailscale / private), the instance **count**, and leave **Agent key** blank if FreeLLMAPI is already running on this PC.
3. Click **Connect cloud phones + agent**.

That single action:

- Saves `cloud_session.json` (host + count)
- Wires `cloud_agent.json` to FreeLLMAPI (`http://127.0.0.1:31415/v1`) when possible
- Starts `PharmFlow.exe --cloud-phones-cli setup` (connect + stealth + Tor)

CLI equivalent (same code path):

```batch
PharmFlow.exe --cloud-phones-cli setup --host 100.x.x.x --count N
```

Agent-only (FreeLLMAPI already up): leave host blank and paste a key only if `freellmapi.env` is missing.

## Free-tier limits (clear)

| Piece | Free path | Limits |
|-------|-----------|--------|
| Cloud phones host | Oracle Cloud **Always Free** Ampere `VM.Standard.A1.Flex` | Up to **4 OCPU** and **24 GB RAM** total in the home region (shared across Always Free A1 VMs) |
| Block storage | Oracle Always Free | Up to **200 GB** home-region block volume (shared with other Always Free volumes) |
| Network | Tailscale or VCN private IP | **Do not** publish ADB ports (`5555+`) on the public Internet |
| Agent | **FreeLLMAPI** on `127.0.0.1:31415` | Local gateway is free; upstream model quotas depend on providers FreeLLMAPI routes to on this PC |
| Phone count | Operator `--count` | **No product phone ceiling.** On 24 GB, leave RAM for the host OS + Docker — hardware headroom, not a hard cap |

PharmFlow does **not** invent a paid device-farm vendor for this path.

## First-time Oracle host (once)

1. Create an Always Free A1.Flex VM (Ubuntu 24.04 ARM) at https://cloud.oracle.com
2. SSH in and run:

```bash
bash cloud_phones/setup-oracle-cloud.sh
```

Or create phones with a count you choose:

```bash
py -3 cloud_phones/redroid_local.py up --count N
```

Then use **Cloud connect** on Windows.

## Advanced tools

Under **Advanced cloud tools** on the Run page (or `Tools → Cloud Phones` in the Tk menu):

- Cloud phone setup / status
- Agent status / Run cloud agent / Agent settings

These call the same `cloud_phones_cli` and `cloud_agent` modules — not a parallel stack.

## Verify

```batch
PharmFlow.exe --cloud-phones-cli status
PharmFlow.exe --cloud-agent "Summarize farm health"
```

Cloud devices appear as normal ADB serials next to local MuMu phones.
