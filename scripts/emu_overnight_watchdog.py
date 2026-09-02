import os, subprocess, sys, time, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401  — hide adb/emulator consoles
from automation.win_subprocess import hidden_run_kwargs  # noqa: E402

ADB = r"C:\CPharm\bundled\adb.exe"
EMU = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Android\Sdk\emulator\emulator.exe")
AVD = "farmphone0"
LOG = Path(r"C:\CPharm\logs")
HB = LOG / "emu_overnight_watchdog_heartbeat.txt"

def devices():
    try:
        out = subprocess.check_output(
            [ADB, "devices"], text=True, timeout=15, **hidden_run_kwargs()
        )
    except Exception as e:
        return str(e)
    return out

def online():
    return any(line.strip().endswith("\tdevice") and "emulator-" in line for line in devices().splitlines())

def start_emu():
    if not os.path.isfile(EMU):
        return False
    subprocess.Popen(
        [EMU, "-avd", AVD, "-no-snapshot-save", "-no-boot-anim", "-gpu", "swiftshader_indirect", "-memory", "2048"],
        cwd=os.path.dirname(EMU),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return True

def pin(serial="emulator-5554"):
    for args in (
        [ADB, "-s", serial, "reverse", "tcp:8218", "tcp:8218"],
        [ADB, "-s", serial, "reverse", "tcp:8118", "tcp:8118"],
        [ADB, "-s", serial, "shell", "settings", "put", "global", "http_proxy", "127.0.0.1:8218"],
    ):
        try:
            subprocess.run(args, timeout=20, capture_output=True, **hidden_run_kwargs())
        except Exception:
            pass

def main():
    while True:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        ok = online()
        action = "ok"
        if not ok:
            action = "restart"
            start_emu()
            for _ in range(60):
                time.sleep(5)
                if online():
                    pin()
                    action = "restarted"
                    break
            else:
                action = "restart_failed"
        else:
            # soft pin every loop
            try:
                lines = [l for l in devices().splitlines() if "emulator-" in l and l.strip().endswith("device")]
                ser = lines[0].split()[0] if lines else "emulator-5554"
                pin(ser)
            except Exception:
                pass
        HB.write_text(f"{ts} online={int(ok)} action={action}\n", encoding="utf-8")
        time.sleep(45)

if __name__ == "__main__":
    main()
