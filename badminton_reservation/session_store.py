"""Local session encryption: Windows DPAPI or a macOS Keychain-backed key."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import sys
import uuid

from cryptography.fernet import Fernet, InvalidToken

MAGIC = b'BADMINTON-DPAPI-1\n'
MAC_MAGIC = b'BADMINTON-KEYCHAIN-1\n'
KEYCHAIN_SERVICE = 'cn.badminton-quest.session'


def platform_name():
    return sys.platform


def mac_keychain():
    # Choose Apple's backend explicitly; never fall back to plaintext storage.
    try:
        from keyring.backends.macOS import Keyring
        return Keyring()
    except Exception:
        raise ValueError('无法连接 macOS 钥匙串，请安装依赖并解锁当前用户的登录钥匙串') from None


def mac_parts(encrypted):
    try:
        identifier, ciphertext = encrypted[len(MAC_MAGIC):].split(b'\n', 1)
        identifier = identifier.decode('ascii')
        if str(uuid.UUID(identifier)) != identifier or not ciphertext:
            raise ValueError
        return identifier, ciphertext
    except (ValueError, UnicodeError):
        raise ValueError('macOS 会话文件损坏，请重新导入登录会话') from None


def keychain_key(identifier, create=False):
    try:
        backend = mac_keychain()
        key = backend.get_password(KEYCHAIN_SERVICE, identifier)
        if key is None and create:
            key = Fernet.generate_key().decode('ascii')
            backend.set_password(KEYCHAIN_SERVICE, identifier, key)
        if key is None:
            raise ValueError
        return Fernet(key.encode('ascii'))
    except Exception:
        raise ValueError('无法读取或保存会话密钥，请解锁并允许访问 macOS 钥匙串；换机器后请重新导入会话') from None


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise ValueError('本地加密会话库目前只支持Windows当前用户')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    operation = library.CryptUnprotectData if decrypt else library.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ValueError('Windows会话解密或加密失败；请用保存会话时的Windows账号运行')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


def save(path, credentials):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(credentials, ensure_ascii=False).encode('utf-8')
    if platform_name() == 'win32':
        encrypted = MAGIC + crypt(raw)
    elif platform_name() == 'darwin':
        previous = path.read_bytes() if path.exists() else b''
        if previous.startswith(MAC_MAGIC):
            identifier, _ = mac_parts(previous)
        else:
            identifier = str(uuid.uuid4())
        cipher = keychain_key(identifier, create=True)
        encrypted = MAC_MAGIC + identifier.encode('ascii') + b'\n' + cipher.encrypt(raw)
    else:
        raise ValueError('加密会话存储目前支持 Windows 和 macOS')
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(encrypted)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def load(path):
    encrypted = Path(path).read_bytes()
    if encrypted.startswith(MAGIC):
        if platform_name() != 'win32':
            raise ValueError('Windows 加密会话不能在 Mac 解密，请在此电脑重新导入登录会话')
        raw = crypt(encrypted[len(MAGIC):], decrypt=True)
    elif encrypted.startswith(MAC_MAGIC):
        if platform_name() != 'darwin':
            raise ValueError('macOS 加密会话需要原用户的钥匙串，请在此电脑重新导入登录会话')
        identifier, ciphertext = mac_parts(encrypted)
        try:
            raw = keychain_key(identifier).decrypt(ciphertext)
        except InvalidToken:
            raise ValueError('会话文件损坏或密钥不匹配，请重新导入登录会话') from None
    else:
        raise ValueError('会话文件不是本模块的加密格式')
    return json.loads(raw.decode('utf-8'))
