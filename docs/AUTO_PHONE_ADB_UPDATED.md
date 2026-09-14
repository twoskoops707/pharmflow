> **Superseded:** the product is a single `PharmFlow.exe` in `C:\PharmFlow\` (`--watchdog`, `--agent`, phone setup in-process). Data still lives under `C:\CPharm\`. Ignore EXE names below.

═══════════════════════════════════════════════════════════
  AUTO-CONNECT ALL PHONES — UPDATED
═══════════════════════════════════════════════════════════

✅ UPDATED: Scripts now connect BOTH Docker Redroid + MuMu simultaneously!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 USAGE:

# Connect all phones (Docker + MuMu)
python auto_phone_adb.py

# Docker Redroid only
python auto_phone_adb.py --docker-only

# MuMu emulators only
python auto_phone_adb.py --mumu-only

# PowerShell version (same options)
powershell -ExecutionPolicy Bypass auto_adb_connect.ps1
powershell -ExecutionPolicy Bypass auto_adb_connect.ps1 -DockerOnly
powershell -ExecutionPolicy Bypass auto_adb_connect.ps1 -MumuOnly

# Advanced with JSON output
python auto_adb_mumu.py --json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 WHAT IT CONNECTS:

Docker Redroid (default ports 5555-5562):
  ├─ 127.0.0.1:5555 (redroid-0)
  ├─ 127.0.0.1:5556 (redroid-1)
  ├─ 127.0.0.1:5557 (redroid-2)
  ├─ 127.0.0.1:5558 (redroid-3)
  ├─ 127.0.0.1:5559 (redroid-4)
  ├─ 127.0.0.1:5560 (redroid-5)
  ├─ 127.0.0.1:5561 (redroid-6)
  └─ 127.0.0.1:5562 (redroid-7)

MuMu Emulators (default ports 16384-16393):
  ├─ 127.0.0.1:16384 (phone 0)
  ├─ 127.0.0.1:16385 (phone 1)
  ├─ ...
  └─ 127.0.0.1:16393 (phone 9)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ VERIFIED TEST (8 Docker phones + 0 MuMu):

$ python auto_phone_adb.py --docker-only

[*] Using ADB: C:\CPharm\bundled\adb.exe
[*] Connecting Docker Redroid (ports 5555-5562)...
  [+] 127.0.0.1:5555
  [+] 127.0.0.1:5556
  [+] 127.0.0.1:5557
  [+] 127.0.0.1:5558
  [+] 127.0.0.1:5559
  [+] 127.0.0.1:5560
  [+] 127.0.0.1:5561
  [+] 127.0.0.1:5562
[*] Connecting MuMu emulators (ports 16384-16393)...
  [-] 127.0.0.1:16384 (not running)
  ...
  [-] 127.0.0.1:16393 (not running)

Phones: 8 phones connected
  127.0.0.1:5555
  127.0.0.1:5556
  ...
  127.0.0.1:5562

[OK] All phones verified!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 INTEGRATION OPTIONS:

For wizard preflight_core.py:

  from auto_phone_adb import connect_all_phones, verify_phones
  
  def auto_detect_and_connect():
      """Auto-connect all emulator phones."""
      phones = connect_all_phones(wait_boot=True)
      
      # Wait for ADB to recognize them
      for attempt in range(24):
          if verify_phones(count=len(phones)):
              return phones
          time.sleep(5)
      
      return phones

Or for UI button (Step 4 - Phones):

  def on_auto_connect_clicked():
      try:
          phones = connect_all_phones(
              docker=True,
              mumu=True,
              wait_boot=False,  # User already waited
              timeout_per_connect=5
          )
          self.update_phone_list(phones)
      except Exception as e:
          self.show_error(f"Failed: {e}")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✨ KEY FEATURES:

✓ Auto-detects Docker Redroid containers
✓ Auto-detects MuMu emulator instances
✓ Connects BOTH simultaneously by default
✓ Can filter to Docker-only or MuMu-only
✓ Configurable timeouts per port
✓ Waits for full boot (30s default)
✓ Verifies all connections
✓ JSON output for CI/CD
✓ Cross-platform (Windows, macOS, Linux)
✓ Production-ready, zero dependencies

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 QUICK START:

# If you have MuMu phones running + Docker Redroid:
python auto_phone_adb.py
# Connects all: 8 Docker + up to 10 MuMu

# If you only have Docker Redroid:
python auto_phone_adb.py --docker-only
# Connects: 8 Docker only

# If you only have MuMu:
python auto_phone_adb.py --mumu-only
# Connects: up to 10 MuMu only

# Then verify:
adb devices -l
# Should show all connected phones

# Then start CPharm:
CPharm.exe
# Step 4 (Phones) should auto-populate with all detected

═══════════════════════════════════════════════════════════
