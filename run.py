#!/usr/bin/env python
"""One-command setup and launch.

Creates a virtual environment if needed, installs missing dependencies, applies
migrations, seeds demo data, then starts the development server.

Usage (from the project root, with any Python 3.11+ on PATH):

    python run.py
    python run.py --host 0.0.0.0 --port 8000
    python run.py --no-seed          # skip demo data
    python run.py --setup-only       # install + migrate, do not serve
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIRED_MODULES = ["django", "cv2", "numpy", "PIL", "cryptography"]


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(cmd: list[str], **kwargs) -> None:
    print("  >", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, **kwargs)


def ensure_venv() -> Path:
    python = venv_python()
    if not python.exists():
        print("[1/4] Creating virtual environment in .venv ...")
        run([sys.executable, "-m", "venv", str(VENV)])
    else:
        print("[1/4] Virtual environment already exists.")
    return python


def deps_installed(python: Path) -> bool:
    check = "import " + ", ".join(REQUIRED_MODULES)
    result = subprocess.run(
        [str(python), "-c", check],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def ensure_deps(python: Path) -> None:
    if deps_installed(python):
        print("[2/4] Dependencies already installed.")
        return
    print("[2/4] Installing dependencies (this may take a minute) ...")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=ROOT)
    run([str(python), "-m", "pip", "install", "-r", "requirements.txt"], cwd=ROOT)


def ensure_database(python: Path, seed: bool) -> None:
    print("[3/4] Applying migrations ...")
    run([str(python), "manage.py", "migrate"], cwd=ROOT)
    if seed:
        print("      Seeding demo data ...")
        run([str(python), "manage.py", "seed_demo"], cwd=ROOT)


def serve(python: Path, host: str, port: str) -> None:
    print(f"[4/4] Starting server at http://{host}:{port}/  (Ctrl+C to stop)")
    run([str(python), "manage.py", "runserver", f"{host}:{port}"], cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Set up and run Smart Voting System.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="8000")
    parser.add_argument("--no-seed", action="store_true", help="Skip demo data.")
    parser.add_argument("--setup-only", action="store_true", help="Do not serve.")
    args = parser.parse_args()

    python = ensure_venv()
    ensure_deps(python)
    ensure_database(python, seed=not args.no_seed)

    if args.setup_only:
        print("Setup complete. Start the server with:")
        if os.name == "nt":
            print(f"  .\\.venv\\Scripts\\python.exe manage.py runserver {args.host}:{args.port}")
        else:
            print(f"  ./.venv/bin/python manage.py runserver {args.host}:{args.port}")
        return 0

    serve(python, args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())