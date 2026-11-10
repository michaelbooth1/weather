"""Public-key-only seal using Windows CNG RSA-OAEP-SHA256 (no new package).

The custodian supplies a JSON PUBLIC key. There is deliberately no keygen,
private-key loader or decrypt function here. Fixed-size plaintext padding
prevents ciphertext lengths from disclosing fills versus skips.
"""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path

from .contracts import canonical, digest, exact, json_bytes, require

PADDED_BYTES = 4 * 1024 * 1024
LABEL = b"LOW-ASK-1/v1"
BCRYPT_PAD_OAEP = 4


def read_public_key(path: Path) -> dict:
    with path.open("rb") as handle:
        raw = handle.read(8193)
    require(len(raw) <= 8192, "public_key_bytes")
    key = json_bytes(raw)
    exact(key, "n_hex e")
    require(isinstance(key["n_hex"], str) and len(key["n_hex"]) in (768, 1024), "public_key_size")
    try:
        modulus = int(key["n_hex"], 16)
    except (ValueError, TypeError):
        require(False, "public_key")
    require(modulus.bit_length() in (3072, 4096) and modulus % 2 == 1 and key["e"] == 65537, "public_key")
    return key


def encrypt(payload: bytes, public_key: dict, *, padded_bytes: int = PADDED_BYTES) -> bytes:
    """BCryptEncrypt with the native OAEP padding; random padding and label bound.

    padded_bytes is injectable only for small synthetic unit tests. The runner
    always uses PADDED_BYTES. Payload length and replay digest are inside the
    ciphertext, never on its public receipt.
    """
    require(os.name == "nt", "windows_cng_required")
    require(len(payload) + 8 <= padded_bytes <= PADDED_BYTES, "seal_budget")
    exact(public_key, "n_hex e")
    modulus = int(public_key["n_hex"], 16)
    bits = modulus.bit_length()
    require(bits in (3072, 4096) and modulus % 2 == 1 and public_key["e"] == 65537, "public_key")
    k = bits // 8
    chunk_size = k - 2 * 32 - 2
    plain = struct.pack(">Q", len(payload)) + payload
    plain += os.urandom(padded_bytes - len(plain))
    # Each block is exactly the OAEP maximum, including the final block.
    plain += os.urandom((-len(plain)) % chunk_size)
    u32, pointer = ctypes.c_uint32, ctypes.c_void_p

    class Padding(ctypes.Structure):
        _fields_ = [("algorithm", ctypes.c_wchar_p), ("label", pointer), ("label_size", u32)]

    api = ctypes.WinDLL("bcrypt.dll")
    api.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(pointer), ctypes.c_wchar_p, ctypes.c_wchar_p, u32]
    api.BCryptImportKeyPair.argtypes = [pointer, pointer, ctypes.c_wchar_p, ctypes.POINTER(pointer), pointer, u32, u32]
    api.BCryptEncrypt.argtypes = [pointer, pointer, u32, pointer, pointer, u32, pointer, u32, ctypes.POINTER(u32), u32]
    api.BCryptDestroyKey.argtypes = [pointer]
    api.BCryptCloseAlgorithmProvider.argtypes = [pointer, u32]

    def check(status):
        require(status == 0, "cng_encryption")

    provider, key_handle = pointer(), pointer()
    check(api.BCryptOpenAlgorithmProvider(ctypes.byref(provider), "RSA", None, 0))
    try:
        exponent = (65537).to_bytes(3, "big")
        blob = struct.pack("<6I", 0x31415352, bits, len(exponent), k, 0, 0)
        blob += exponent + modulus.to_bytes(k, "big")
        blob_buffer = ctypes.create_string_buffer(blob)
        check(api.BCryptImportKeyPair(provider, None, "RSAPUBLICBLOB", ctypes.byref(key_handle), blob_buffer, len(blob), 0))
        label = ctypes.create_string_buffer(LABEL)
        padding = Padding("SHA256", ctypes.cast(label, pointer), len(LABEL))
        output = bytearray(b"LA1\x01" + struct.pack(">II", k, len(plain) // chunk_size))
        for offset in range(0, len(plain), chunk_size):
            source = ctypes.create_string_buffer(plain[offset:offset + chunk_size])
            target, written = ctypes.create_string_buffer(k), u32()
            check(api.BCryptEncrypt(key_handle, source, chunk_size, ctypes.byref(padding), None, 0,
                                   target, k, ctypes.byref(written), BCRYPT_PAD_OAEP))
            require(written.value == k, "cng_length")
            output.extend(target.raw)
        return bytes(output)
    finally:
        if key_handle:
            api.BCryptDestroyKey(key_handle)
        api.BCryptCloseAlgorithmProvider(provider, 0)


def seal_payload(value: dict, key: dict) -> tuple[bytes, dict]:
    ciphertext = encrypt(canonical(value), key)
    return ciphertext, {"ciphertext_sha256": digest(ciphertext),
                        "public_key_sha256": digest(canonical(key)), "bytes": len(ciphertext)}
