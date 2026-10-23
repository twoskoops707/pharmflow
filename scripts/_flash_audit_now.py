"""One-shot conhost/flash audit. Delete after use."""
from __future__ import annotations

import json
import subprocess
from collections import defaultdict

ps = subprocess.check_output(
    [
        "powershell",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-Command",
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress",
    ],
    text=True,
    errors="replace",
    creationflags=0x08000000,
)
procs = json.loads(ps)
by_pid = {p["ProcessId"]: p for p in procs}
conhosts = [p for p in procs if (p.get("Name") or "").lower() == "conhost.exe"]
non_headless = []
headless = []
for c in conhosts:
    cl = (c.get("CommandLine") or "")
    if "--headless" in cl.lower():
        headless.append(c)
    else:
        non_headless.append(c)
print("CONHOST_TOTAL", len(conhosts))
print("CONHOST_HEADLESS", len(headless))
print("CONHOST_NON_HEADLESS", len(non_headless))
print("--- NON-HEADLESS PARENTS ---")
parents: dict[str, list[int]] = defaultdict(list)
for c in non_headless:
    ppid = c.get("ParentProcessId")
    parent = by_pid.get(ppid, {})
    pname = parent.get("Name") or "?"
    pcl = (parent.get("CommandLine") or "")[:240]
    key = f"{ppid}|{pname}|{pcl}"
    parents[key].append(c["ProcessId"])
for k, kids in sorted(parents.items(), key=lambda x: -len(x[1])):
    print(f"count={len(kids)} parent={k}")
    print(f"  conhost_pids={kids[:30]}")

# Also dump tor / powershell / cmd farm helpers
print("--- TOR / PS / CMD FARM HELPERS ---")
for p in procs:
    name = (p.get("Name") or "").lower()
    cl = (p.get("CommandLine") or "")
    cl_l = cl.lower()
    if name in ("tor.exe", "powershell.exe", "pwsh.exe", "cmd.exe"):
        interesting = False
        if name == "tor.exe":
            interesting = True
        elif any(
            x in cl_l
            for x in (
                "taskkill",
                "adb",
                "tor",
                "reap",
                "connect",
                "pharmflow",
                "pharmflow",
                "farm",
                "suppress",
            )
        ):
            interesting = True
        if interesting:
            print(
                f"pid={p['ProcessId']} ppid={p.get('ParentProcessId')} "
                f"name={p.get('Name')} cl={cl[:300]}"
            )

# Keep-alive targets
print("--- KEEP TARGETS ---")
for p in procs:
    cl = (p.get("CommandLine") or "").lower()
    name = (p.get("Name") or "").lower()
    if "pharmflow" in name or "run_farm_354" in cl or "suppress_console_flash" in cl:
        print(
            f"KEEP pid={p['ProcessId']} name={p.get('Name')} "
            f"cl={(p.get('CommandLine') or '')[:280]}"
        )
