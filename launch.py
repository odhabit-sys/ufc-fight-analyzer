#!/usr/bin/env python3
"""Cross-platform launcher for the Fight Analyzer web app (Windows, macOS, Linux).

    python launch.py [--port 8000] [--no-browser] [--setup-only] [--reinstall]

run.bat (Windows) and run.sh (macOS/Linux) just find a suitable Python and call this.
On the first run it creates .venv, installs requirements.txt, checks the bundled FFmpeg
and downloads the pose-model weights; later runs only re-check and start the server.
Only the Python standard library is used here, so it works before anything is installed.
"""
import argparse
import hashlib
import os
import platform
import socket
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
CONSTRAINTS = ROOT / "constraints.txt"     # exact versions of every (indirect) dependency
STAMP = VENV / ".requirements.sha256"
MIN_PYTHON = (3, 12)          # numpy 2.5 (pinned) needs Python 3.12+
MAX_PYTHON = (3, 14)          # torch 2.14 (pinned) has no builds for newer Pythons yet
WINDOWS = os.name == "nt"
# Windows without long-path support limits full paths to 259 characters. The deepest file
# PyTorch installs is ~121 characters below .venv\Lib\site-packages\ (25 more), so the
# project folder path itself must stay under ~113 characters.
MAX_WINDOWS_ROOT = 110

MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/{}"


def model_name():
    """The pose model the analyzer loads (relative to the project folder). Imported only
    after the Python version check: config.py uses 3.10+ syntax."""
    sys.path.insert(0, str(ROOT))
    from fight_analyzer.config import Config   # stdlib-only module
    return Config().pose_model

PYTHON_HINT = (
    "Install Python 3.13 (64-bit); 3.12 and 3.14 also work:\n"
    "    Windows: https://www.python.org/downloads/windows/  (tick \"Add python.exe to PATH\")\n"
    "    macOS:   https://www.python.org/downloads/macos/   or   brew install python@3.13\n"
    "    Linux:   your package manager, e.g.  sudo apt install python3.12 python3.12-venv\n"
    "Then run the start script again.")
NEWER_HINT = (
    "Install Python 3.13 as well (several Python versions can be installed side by side):\n"
    "    Windows: https://www.python.org/downloads/windows/ -> \"Python 3.13.x\" -> Windows installer (64-bit),\n"
    "             or, if you use the Python install manager:  py install 3.13\n"
    "    macOS:   https://www.python.org/downloads/macos/   or   brew install python@3.13\n"
    "Then run the start script again; it picks Python 3.13 automatically.")


def too_new(version):
    return f"Python {version} is newer than PyTorch supports (Python 3.12 to 3.14 are supported)."


def say(msg):
    print(f"[setup] {msg}", flush=True)


def fail(msg, hint=None):
    bar = "=" * 74
    print(f"\n{bar}\n  ERROR: {msg}\n", file=sys.stderr)
    if hint:
        print("  " + hint.replace("\n", "\n  ") + "\n", file=sys.stderr)
    print(bar, file=sys.stderr, flush=True)
    sys.exit(1)


def venv_python():
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, **kw)


# ---------------------------------------------------------------------------- checks
def check_platform():
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {platform.python_version()} is too old (3.12 or newer is required).", PYTHON_HINT)
    if sys.version_info[:2] > MAX_PYTHON:
        fail(too_new(platform.python_version()), NEWER_HINT)
    if sys.maxsize <= 2 ** 32:
        fail("This is a 32-bit Python. PyTorch needs 64-bit Python.", PYTHON_HINT)
    machine = platform.machine().lower()
    if WINDOWS and machine in ("arm64", "aarch64"):
        fail("Windows on ARM is not supported (the bundled FFmpeg package has no ARM build).")
    if sys.platform == "darwin" and machine == "x86_64":
        fail("This Python is an Intel (x86_64) build. PyTorch no longer ships Intel-Mac versions.",
             "On an Apple Silicon Mac, install the regular (universal) Python from python.org and run\n"
             "the start script again. Intel Macs are not supported.")


def ensure_venv():
    py = venv_python()
    if not py.exists():
        check_windows_path_length()
        say(f"Creating the Python environment in {VENV.name}{os.sep} ...")
        try:
            venv.EnvBuilder(with_pip=True).create(VENV)
        except Exception as e:  # e.g. Debian/Ubuntu without the python3-venv package
            fail(f"Could not create the Python environment: {e}",
                 "On Debian/Ubuntu install the venv module first, e.g.  sudo apt install python3.12-venv\n"
                 f"then delete the '{VENV.name}' folder and run the start script again.")
    probe = run([py, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], capture_output=True, text=True)
    if probe.returncode != 0:
        fail(f"The existing '{VENV.name}' environment is broken (was Python moved or uninstalled?).",
             f"Delete the '{VENV.name}' folder in {ROOT} and run the start script again.")
    if not MIN_PYTHON <= tuple(int(x) for x in probe.stdout.strip().split(".")) <= MAX_PYTHON:
        fail(f"The existing '{VENV.name}' environment uses Python {probe.stdout.strip()} (3.12 to 3.14 required).",
             f"Delete the '{VENV.name}' folder in {ROOT} and run the start script again.")


def windows_long_paths_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except OSError:
        return False


def check_windows_path_length():
    if WINDOWS and len(str(ROOT)) > MAX_WINDOWS_ROOT and not windows_long_paths_enabled():
        fail(f"The project folder path is too long for Windows ({len(str(ROOT))} characters):\n    {ROOT}",
             "Installing PyTorch would fail part-way. Move the folder somewhere shorter, for example\n"
             "    C:\\ufc-fight-analyzer\n"
             "or enable Windows long paths (search 'Enable Win32 long paths' or see\n"
             "    https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation )\n"
             "then run run.bat again.")


def ensure_requirements(force=False):
    want = hashlib.sha256(REQUIREMENTS.read_bytes() + CONSTRAINTS.read_bytes()).hexdigest()
    if not force and STAMP.exists() and STAMP.read_text().strip() == want:
        return
    check_windows_path_length()
    say("Installing dependencies (first run downloads roughly 1 GB: PyTorch, OpenCV, ...).")
    say("This can take several minutes. Later starts skip this step.")
    py = venv_python()
    if run([py, "-m", "pip", "install", "--upgrade", "pip"]).returncode != 0:
        fail("Could not update pip.", "Check your internet connection and run the start script again.")
    if run([py, "-m", "pip", "install", "-r", REQUIREMENTS, "-c", CONSTRAINTS]).returncode != 0:
        fail("Installing the dependencies failed (see the pip messages above).",
             "Check your internet connection and free disk space (about 3 GB), then run the start\n"
             "script again. Supported: 64-bit Python 3.12-3.14 on Windows x64, Apple Silicon macOS, Linux x64.")
    STAMP.write_text(want)


CHECK_RUNTIME = r"""
import subprocess, sys
try:
    import imageio_ffmpeg
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True,
                         encoding="utf-8", errors="replace").stdout
except Exception as e:
    print("FFMPEG", e); sys.exit(2)
if "libx264" not in out:
    print("FFMPEG", exe, "has no H.264 (libx264) encoder"); sys.exit(2)
import cv2
if not any("FFMPEG" in l and "YES" in l for l in cv2.getBuildInformation().splitlines()):
    print("OPENCV", "OpenCV was built without FFmpeg video support"); sys.exit(3)
print("OK", exe)
"""


def check_runtime():
    r = run([venv_python(), "-c", CHECK_RUNTIME], capture_output=True, encoding="utf-8", errors="replace")
    if r.returncode == 2:
        fail("FFmpeg is not usable: " + (r.stdout.strip() or r.stderr.strip()[-300:]),
             "FFmpeg comes bundled with the 'imageio-ffmpeg' package; reinstall the dependencies with\n"
             "    python launch.py --reinstall\n"
             "If IMAGEIO_FFMPEG_EXE is set in your environment, it must point to a working ffmpeg.")
    if r.returncode != 0:
        fail("The video libraries could not be loaded: " + (r.stdout.strip() or r.stderr.strip()[-300:]),
             "Reinstall the dependencies with:  python launch.py --reinstall")


def ensure_model():
    model = model_name()
    if (ROOT / model).exists():
        return
    say(f"Downloading the pose model {model} (about 40 MB, one time only) ...")
    r = run([venv_python(), "-c", f"from ultralytics import YOLO; YOLO({model!r})"])
    if r.returncode != 0 or not (ROOT / model).exists():
        fail(f"Could not download the model weights '{model}'.",
             f"Check your internet connection, or download it manually from\n    {MODEL_URL.format(model)}\n"
             f"and save it in {ROOT}")


def pick_port(port):
    for p in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    fail(f"Ports {port}-{port + 19} are all in use.", "Close other servers or pass a different --port.")


# ---------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Set up (first run) and start the Fight Analyzer.")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    ap.add_argument("--setup-only", action="store_true", help="prepare everything, don't start the server")
    ap.add_argument("--reinstall", action="store_true", help="reinstall the Python dependencies")
    args = ap.parse_args()

    os.chdir(ROOT)
    check_platform()
    ensure_venv()
    ensure_requirements(force=args.reinstall)
    check_runtime()
    ensure_model()
    if args.setup_only:
        say("Setup complete.")
        return 0

    port = pick_port(args.port)
    if port != args.port:
        say(f"Port {args.port} is busy, using {port} instead.")
    print(f"\n  Starting the Fight Analyzer. Local app address: http://127.0.0.1:{port}\n"
          f"  (it only works on this computer, while this window stays open; Ctrl+C stops it)\n", flush=True)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    cmd = [venv_python(), "-m", "webapp", "--port", str(port)] + (["--no-browser"] if args.no_browser else [])
    proc = subprocess.Popen([str(c) for c in cmd], cwd=ROOT, env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:          # Ctrl+C reaches the server too; let it shut down cleanly
        try:
            return proc.wait(timeout=10)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            proc.kill()
            return 0


if __name__ == "__main__":
    sys.exit(main())
