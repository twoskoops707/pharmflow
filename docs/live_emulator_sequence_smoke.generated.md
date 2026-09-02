# Live emulator sequence smoke

Generated: 2026-05-07 13:26:01 -07:00

## 1. adb devices -l

```text
List of devices attached 10.0.2.104:5555        device product:GC3VE model:GC3VE device:GC3VE transport_id:2 10.0.2.253:5555        device product:SM-S9110 model:SM_S9110 device:SM-S9110 transport_id:1 10.0.2.66:5555         device product:SM-A5460 model:SM_A5460 device:SM-A5460 transport_id:3 
```

## Notes

- User reported 3 MuMu emulators; **observed** ADB serials are **10.0.2.x:5555** (not \127.0.0.1:55xxx\). Treat as bridge/NAT addressing for emulator network.

## 2. Execution path (repo)

- Sequences run via \dashboard.run_sequence_step(serial, step, ...)\ (ADB subprocess per step).
- HTTP: \POST /api/groups/run\ loads groups from body or \ecordings/groups_config.json\; per-phone \phones[serial].steps\ or playlists; requires **configured serials to match** \list_phones()\ running devices.
- \groups_config.json\ in repo references **10.0.2.142 / 157 / 168** — **does not match** current ADB serials below without editing or inline POST body.

## 3. Per-device adb shell sanity


### 10.0.2.104:5555

```text
ok
GC3VE
```

### 10.0.2.253:5555

```text
ok
SM-S9110
```

### 10.0.2.66:5555

```text
ok
SM-A5460
```
