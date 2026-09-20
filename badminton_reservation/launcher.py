"""Portable, standard-library bootstrap. Never imports credentials or starts a task."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def environment_python(folder):
    return folder / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def prepare_environment():
    folder = ROOT / '.venv'
    python = environment_python(folder)
    requirements = ROOT / 'requirements.txt'
    stamp = folder / '.badminton-dependencies'
    expected = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not python.is_file():
        print('Creating a private Python environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(folder)
    # Check the environment on every run; copying a Windows venv to Mac is unsupported.
    try:
        result = subprocess.run([str(python), '-c',
            'import sys; assert sys.version_info >= (3,10); print(sys.platform)'],
            capture_output=True, text=True, check=True)
        if result.stdout.strip() != sys.platform:
            raise ValueError
    except (OSError, subprocess.CalledProcessError, ValueError):
        raise RuntimeError('The .venv belongs to another Python or computer. Rename .venv and start again.') from None
    if not stamp.exists() or stamp.read_text(encoding='ascii') != expected:
        print('Installing dependencies (internet required on first start)...', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], check=True)
        stamp.write_text(expected, encoding='ascii')
    ensure_login_browser(python)
    return python


def ensure_login_browser(python):
    check = "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); ready=Path(p.chromium.executable_path).is_file(); p.stop(); raise SystemExit(0 if ready else 1)"
    if subprocess.run([str(python), '-c', check], capture_output=True).returncode:
        print('Installing the isolated login browser (first start may take a few minutes)...', flush=True)
        subprocess.run([str(python), '-m', 'playwright', 'install', '--no-shell', 'chromium'], check=True)


def check_installation():
    names = ['requests', 'cryptography', 'playwright'] + (['keyring'] if sys.platform == 'darwin' else [])
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    files = ['gui/index.html', 'gui/app.js', 'gui/automation.js', 'gui/login.js', 'gui/dashboard.css',
             'gui/assets/concept.png', 'gui/assets/gym.png', 'assets/loader-literals.json',
             'config/booking.json', 'config/booking_data.json', 'state/venues/badminton-courts.json']
    missing_files = [name for name in files if not (ROOT / name).is_file()]
    print(json.dumps({'platform': sys.platform, 'python': sys.version.split()[0],
                      'missingDependencies': missing, 'missingFiles': missing_files,
                      'ok': not missing and not missing_files}, ensure_ascii=False))
    return 1 if missing or missing_files else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Badminton Quest portable launcher')
    parser.add_argument('--check', action='store_true', help='Offline file/dependency check; does not start the server')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        raise RuntimeError('Please install Python 3.10 or newer from https://www.python.org/downloads/')
    if sys.platform not in ('win32', 'darwin'):
        raise RuntimeError('This release supports Windows and macOS.')
    if args.check:
        return check_installation()
    python = prepare_environment()
    print('Keep this terminal open while tasks are running. Press Ctrl+C to stop.', flush=True)
    command = [str(python), '-X', 'utf8', str(ROOT / 'start_gui.py'), '--port', str(args.port)]
    if args.no_open:
        command.append('--no-open')
    process = subprocess.Popen(command, cwd=ROOT)
    try:
        return process.wait()
    except KeyboardInterrupt:
        # Ctrl+C reaches both processes in this console/process group.
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=10)
            return 130


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print('Startup failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
