═══════════════════════════════════════════════════════════
  CPHARM WIZARD INTEGRATION GUIDE
  Auto-Connect All Phones to ADB
═══════════════════════════════════════════════════════════

✓ CREATED: Three scripts to auto-connect phones in CPharm wizard

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📦 SCRIPTS AVAILABLE:

1. auto_phone_adb.py (Recommended)
   ├─ Python-based, most portable
   ├─ Usage: python auto_phone_adb.py --docker
   ├─ Returns: List of connected phone addresses
   └─ Integrates directly into CPharm preflight checks

2. auto_adb_connect.ps1 (Windows PowerShell)
   ├─ Fast native PowerShell
   ├─ Usage: powershell -ExecutionPolicy Bypass auto_adb_connect.ps1 -Docker
   └─ Good for standalone use or CI/CD

3. auto_adb_mumu.py (Advanced, CLI-focused)
   ├─ Full-featured with JSON output
   ├─ Usage: python auto_adb_mumu.py --docker --json
   └─ Best for CI/CD and programmatic usage

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔧 INTEGRATION POINTS IN WIZARD:

Option 1: Call from Python (Recommended)
─────────────────────────────────────────

In: C:\CPharm\wizard\preflight_core.py or mumu_setup_core.py

Add this function:

  def discover_and_connect_phones(docker_mode=False, timeout=120):
      """Auto-connect all phones and wait for ADB to recognize them."""
      sys.path.insert(0, str(Path(__file__).parent.parent))
      from auto_phone_adb import connect_all_phones, verify_phones
      
      phones = connect_all_phones(docker=docker_mode)
      
      # Wait up to 2 min for ADB to fully initialize
      for attempt in range(24):  # 24 * 5s = 120s
          if verify_phones(count=len(phones)):
              return phones
          time.sleep(5)
      
      return phones  # Return even if verification incomplete


Usage in wizard:
  
  phones = discover_and_connect_phones(docker_mode=True)
  if phones:
      print(f"Connected {len(phones)} phones")
  else:
      print("No phones found")


Option 2: Call from Shell (CLI Integration)
────────────────────────────────────────────

In: setup_wizard.py or cpharm_mumu_setup.py

  import subprocess
  result = subprocess.run(
      [sys.executable, "auto_phone_adb.py", "--docker"],
      capture_output=True,
      text=True,
      timeout=120,
      cwd=Path(__file__).parent.parent,
  )
  
  if result.returncode == 0:
      print(f"Phones connected: {result.stdout}")


Option 3: UI Button in Wizard (Tkinter/WebView)
────────────────────────────────────────────────

In: cpharm_app_webview.py or mumu_setup_webview.py

Add a button in Step 4 (Phones):

  def on_auto_connect_phones(self):
      """User clicks 'Auto-Connect All Phones'"""
      try:
          # Disable button during connection
          self.auto_connect_btn.config(state="disabled", text="Connecting...")
          
          # Run connection script
          result = subprocess.run(
              [sys.executable, "auto_phone_adb.py", "--docker"],
              capture_output=True,
              text=True,
              timeout=120,
              cwd=cpharm_root(),
          )
          
          # Show result
          if result.returncode == 0:
              self.status_label.config(
                  text=f"✓ Connected phones",
                  fg="green"
              )
              self.refresh_phone_list()
          else:
              self.status_label.config(
                  text=f"✗ Connection failed: {result.stderr}",
                  fg="red"
              )
      finally:
          self.auto_connect_btn.config(
              state="normal",
              text="Auto-Connect All Phones"
          )


HTML/JS for WebView:

  <button id="auto-connect-btn" class="btn btn-primary">
    Auto-Connect All Phones
  </button>
  
  <script>
  document.getElementById("auto-connect-btn").addEventListener("click", async () => {
      const response = await fetch("/api/phones/auto-connect?mode=docker", {
          method: "POST"
      });
      const result = await response.json();
      if (result.success) {
          alert(`Connected ${result.phones.length} phones`);
          refreshPhoneList();
      } else {
          alert(`Failed: ${result.error}`);
      }
  });
  </script>


━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🚀 IMPLEMENTATION CHECKLIST:

For CPharm Maintainers:

 □ Step 1: Add auto_phone_adb.py to C:\CPharm\wizard\
 
 □ Step 2: Patch preflight_core.py:
   ├─ Import: from auto_phone_adb import connect_all_phones
   ├─ Add function: discover_adb_phones_auto()
   └─ Call from: build_checklist() when showing "Phones" step

 □ Step 3: Add UI element in wizard (Step 4 - Phones):
   ├─ Button: "Auto-Connect All Phones"
   ├─ Calls: discover_adb_phones_auto(docker=True/False)
   └─ Shows: Live progress + device count

 □ Step 4: Wire into existing checklist:
   ├─ "Set up my phones" → calls auto_connect first
   ├─ Falls back to manual detection if auto fails
   └─ Shows connected count

 □ Step 5: Add to preflight_check for Launch step:
   ├─ "Fix phone connections" → re-run auto_connect
   └─ Helpful when phones drop offline

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 ENVIRONMENT DETECTION:

The scripts auto-detect your setup:
  ✓ Docker Redroid (ports 5555-5562)
  ✓ MuMu emulators (ports 16384-16393)
  ✓ Hybrid (both Docker + MuMu)

You can force a mode:
  python auto_phone_adb.py --docker        # Docker only
  python auto_phone_adb.py                 # MuMu only (default)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 KNOWN ISSUES & WORKAROUNDS:

Issue: "ADB reports 0 devices even though connections succeeded"
Fix:   This is normal on first boot. ADB daemon takes 10-30s to 
       recognize Docker containers. The script waits 30s automatically.

Issue: "Only 1-2 phones show online, rest are offline"
Fix:   Containers are still booting. Wait 60s and run script again.
       Each Redroid container takes 45-60s to fully initialize.

Issue: "Port already in use"
Fix:   Another process is holding the port. Run:
       netstat -ano | findstr :5555
       taskkill /PID <PID> /F

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ QUICK START:

1. Verify Redroid containers running:
   docker ps | grep redroid
   
2. Run auto-connect:
   cd C:\CPharm
   python auto_phone_adb.py --docker
   
3. Verify connections:
   C:\CPharm\bundled\adb.exe devices
   
4. Start CPharm wizard:
   PharmFlow.exe
   → Go to Launch → Preflight should show all phones

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 CUSTOMIZATION:

Modify connect timeouts:
  python auto_phone_adb.py --docker --timeout 20  (20s per port)

Add custom ports (in auto_phone_adb.py):
  ports = [5555, 5556, 16384, 16385]  # Mix Docker + MuMu
  for port in ports:
      addr = f"127.0.0.1:{port}"
      # ... connect logic

Auto-detect and connect both:
  # In Python:
  docker_phones = connect_all_phones(docker=True, wait_boot=False)
  mumu_phones = connect_all_phones(docker=False, wait_boot=False)
  all_phones = docker_phones + mumu_phones

═══════════════════════════════════════════════════════════
