"""ed25519 key helpers for replay-envelope signing.

``cryptography`` is added to project dependencies alongside this module (it was
previously only a transitive lock entry). Keys are raw-encoded then base64'd so
an envelope is portable across hosts.
"""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def generate_private_key() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


def _raw_private(key: ed25519.Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _raw_public(pub: ed25519.Ed25519PublicKey) -> bytes:
    return pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def write_key_file(key: ed25519.Ed25519PrivateKey, path: str | Path) -> Path:
    """Persist a private key base64-encoded with 0600 perms. Callers should
    keep this OUT of the repo (``~/.config/bene/`` by convention)."""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(base64.b64encode(_raw_private(key)))
    p.chmod(0o600)
    return p


def load_private_key(path: str | Path) -> ed25519.Ed25519PrivateKey:
    raw = base64.b64decode(Path(path).expanduser().read_bytes())
    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def public_key_b64(key: ed25519.Ed25519PrivateKey) -> str:
    return base64.b64encode(_raw_public(key.public_key())).decode()


def sign(key: ed25519.Ed25519PrivateKey, message: bytes) -> str:
    return base64.b64encode(key.sign(message)).decode()


def verify_signature(public_b64: str, signature_b64: str, message: bytes) -> bool:
    """True iff ``signature_b64`` is a valid ed25519 signature of ``message``
    under ``public_b64``. Never raises — a malformed key/sig returns False."""
    try:
        pub = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(public_b64))
        pub.verify(base64.b64decode(signature_b64), message)
        return True
    except Exception:
        return False
