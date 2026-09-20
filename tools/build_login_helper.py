"""Package only local login helper sources; exclude profiles and runtime caches."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('Start-Windows.cmd', 'Start-Windows.ps1', 'Start-macOS.command',
         'session-helper.mjs', 'browser-launch.mjs', 'credentials.mjs', 'cdp.mjs', 'README.md')


def build():
    output = ROOT / 'badminton_reservation/web/login-helper.zip'
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            item = zipfile.ZipInfo('badminton-quest-login-helper/' + name, (2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o100755 if name.endswith('.command') else 0o100644) << 16
            content = (ROOT / 'login-helper' / name).read_bytes()
            if name.endswith(('.cmd', '.ps1')):
                content = content.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            archive.writestr(item, content)
    print(output)


if __name__ == '__main__':
    build()
