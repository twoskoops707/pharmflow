# Cloud phones + agent — one-login free path

PharmFlow wires **Oracle Cloud Always Free + Redroid** (phones) and **FreeLLMAPI** (agent) through one Control Panel login. There is no separate CloudPhones.exe and no second farm Python stack.

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
