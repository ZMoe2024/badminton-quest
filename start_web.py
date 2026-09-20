"""Install the web edition in its own environment, then start the server."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv


def main():
    root=Path(__file__).resolve().parent
    env=root/'.web-venv'
    python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not python.exists():venv.EnvBuilder(with_pip=True).create(env)
    fingerprint=hashlib.sha256((root/'requirements-web.txt').read_bytes()+(root/'badminton_reservation/requirements.txt').read_bytes()).hexdigest()
    stamp=env/'requirements.sha256'
    if not stamp.exists() or stamp.read_text()!=fingerprint:
        subprocess.run([str(python),'-m','pip','install','-r',str(root/'requirements-web.txt')],check=True)
        subprocess.run([str(python),'-m','playwright','install','--no-shell','chromium'],check=True)
        stamp.write_text(fingerprint)
    args=sys.argv[1:]
    if not args:args=['--open']
    raise SystemExit(subprocess.call([str(python),'-m','badminton_reservation.web_server',*args],cwd=root))


if __name__=='__main__':main()
