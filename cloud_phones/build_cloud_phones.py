"""Build CloudPhones.exe using PyInstaller.

Usage:
    python cloud_phones/build_cloud_phones.py

Produces: CloudPhones.exe in the cloud_phones/ directory.

Requirements:
    pip install pyinstaller
"""

import subprocess
import sys
import shutil
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
CLOUD_DIR = ROOT / "cloud_phones"
BUNDLED_DIR = ROOT / "bundled"
ADB_PATH = BUNDLED_DIR / "adb.exe"

CLI_ENTRY = CLOUD_DIR / "cloud_phones_cli.py"

DIST_DIR = CLOUD_DIR / "dist"
BUILD_DIR = CLOUD_DIR / "build"
EXE_NAME = "CloudPhones"


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"✓ PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("✗ PyInstaller not installed")
        print("  Install with: pip install pyinstaller")
        return False


def check_sources():
    ok = True
    if not CLI_ENTRY.exists():
        print(f"✗ Missing: {CLI_ENTRY}")
        ok = False
    else:
        print(f"✓ Entry point: {CLI_ENTRY.name}")

    if ADB_PATH.exists():
        print(f"✓ ADB: {ADB_PATH}")
    else:
        print(f"  ⚠ ADB not found at {ADB_PATH} (will use system ADB)")

    return ok


def build():
    datas = []
    if ADB_PATH.exists():
        datas.append(f"--add-data={BUNDLED_DIR / 'adb.exe'};bundled")
        datas.append(f"--add-data={BUNDLED_DIR / 'AdbWinApi.dll'};bundled")
        datas.append(f"--add-data={BUNDLED_DIR / 'AdbWinUsbApi.dll'};bundled")

    hidden = [
        "--hidden-import=json",
        "--hidden-import=secrets",
        "--hidden-import=string",
        "--hidden-import=random",
    ]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", EXE_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(CLOUD_DIR),
        "--noconfirm",
        "--clean",
        *datas,
        *hidden,
        str(CLI_ENTRY),
    ]

    print(f"\nBuilding {EXE_NAME}.exe...")
    print(f"  Command: {' '.join(cmd[:6])} ...")
    print()

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        print(f"\n✗ Build failed (exit code {result.returncode})")
        return False

    exe_path = DIST_DIR / f"{EXE_NAME}.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n✓ Build successful!")
        print(f"  Output: {exe_path}")
        print(f"  Size: {size_mb:.1f} MB")

        root_exe = ROOT / f"{EXE_NAME}.exe"
        shutil.copy2(exe_path, root_exe)
        print(f"  Copied to: {root_exe}")
        return True
    else:
        print(f"\n✗ EXE not found at {exe_path}")
        return False


def main():
    print("=" * 60)
    print("  CloudPhones.exe Builder")
    print("=" * 60)
    print()

    if not check_pyinstaller():
        return 1

    print()
    if not check_sources():
        print("\n✗ Cannot build: missing source files")
        return 1

    if not build():
        return 1

    print(f"\n{'=' * 60}")
    print(f"  CloudPhones.exe is ready!")
    print(f"  Usage:")
    print(f"    CloudPhones.exe connect --host <IP>")
    print(f"    CloudPhones.exe stealth --host <IP> --count 8")
    print(f"    CloudPhones.exe tor --host <IP> --verify")
    print(f"    CloudPhones.exe setup --host <IP>")
    print(f"    CloudPhones.exe status")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
