"""Cryptographic primitives for the Smart Voting System.

This module implements the *reference* cryptographic core of a secret-ballot
electronic voting system:

* Ballot confidentiality  -> hybrid encryption (RSA-OAEP + AES-256-GCM). Only a
  tally holder in possession of the election private key can open a ballot.
* Voter PII at rest      -> AES-128/256-CBC (Fernet) using a key stored outside
  the database.
* Anonymity / no backtracking -> a ballot is stored with no reference to the
  voter. Casting requires a one-time anonymous voting token that is validated
  by hash only and can never be mapped back to a voter in persistent storage.
* Tamper evidence        -> an append-only, hash-chained audit log.

IMPORTANT: This is a reference implementation intended for learning and
prototyping. It is NOT certified for a real national election. See
docs/THREAT_MODEL.md and docs/IMPLEMENTATION.md for the full list of gaps
(key custody, threshold trustees, hardware security modules, coercion
resistance, independent audits, ...).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from django.conf import settings


def hash_hex(*parts: str) -> str:
    """Return the hex SHA-256 of the concatenation of the given parts."""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
    return digest.hexdigest()


def _key_dir() -> Path:
    path = Path(settings.ELECTION_KEY_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _private_key_path(name: str) -> Path:
    return _key_dir() / f"{name}_private.pem"


# --- RSA key management ------------------------------------------------------

def load_or_create_rsa_keypair(name: str) -> tuple[rsa.RSAPrivateKey, str]:
    """Load a named RSA keypair, generating it on first use.

    The private key is written as an unencrypted PEM under ``ELECTION_KEY_DIR``
    which is excluded from version control. The public key PEM is returned so
    that it can be published (stored on the Election row).
    """
    path = _private_key_path(name)
    if path.exists():
        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_key, public_pem


def load_private_key(name: str) -> rsa.RSAPrivateKey | None:
    path = _private_key_path(name)
    if not path.exists():
        return None
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def public_key_from_pem(pem: str) -> rsa.RSAPublicKey:
    return serialization.load_pem_public_key(pem.encode("ascii"))


# --- Hybrid ballot encryption ------------------------------------------------

def encrypt_ballot(public_pem: str, payload: dict[str, Any]) -> str:
    """Encrypt a ballot payload to a Base64 token using the election public key.

    Format: base64(rsa_len(2 bytes) || rsa_ciphertext || aes_nonce || aes_ciphertext)
    """
    public_key = public_key_from_pem(public_pem)
    plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    aes_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = AESGCM(aes_key).encrypt(nonce, plaintext, None)

    wrapped_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    blob = len(wrapped_key).to_bytes(2, "big") + wrapped_key + nonce + ciphertext
    return base64.b64encode(blob).decode("ascii")


def decrypt_ballot(private_key: rsa.RSAPrivateKey, token: str) -> dict[str, Any]:
    blob = base64.b64decode(token)
    rsa_len = int.from_bytes(blob[:2], "big")
    wrapped_key = blob[2 : 2 + rsa_len]
    nonce = blob[2 + rsa_len : 2 + rsa_len + 12]
    ciphertext = blob[2 + rsa_len + 12 :]

    aes_key = private_key.decrypt(
        wrapped_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    plaintext = AESGCM(aes_key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))


# --- Encrypted voter PII -----------------------------------------------------

def _fernet() -> Fernet:
    path = _key_dir() / "pii.key"
    if not path.exists():
        path.write_bytes(Fernet.generate_key())
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return Fernet(path.read_bytes())


def encrypt_pii(value: str) -> str:
    if value is None:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_pii(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""


def encrypt_details(details: dict[str, Any]) -> str:
    """Encrypt a structured voter-details dict (EPIC roll row) at rest."""
    if not details:
        return ""
    return encrypt_pii(json.dumps(details, separators=(",", ":"), sort_keys=True))


def decrypt_details(token: str) -> dict[str, Any]:
    raw = decrypt_pii(token)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def epic_hash(epic: str) -> str:
    """Deterministic, one-way key for an EPIC number (for matching/dedupe)."""
    value = (epic or "").strip().upper().replace(" ", "")
    return hash_hex("epic", value)


def mask_epic(epic: str) -> str:
    value = (epic or "").strip().upper()
    if len(value) <= 4:
        return "XXXX"
    return f"{'X' * (len(value) - 4)}{value[-4:]}"


# --- Anonymous, one-time voting tokens ---------------------------------------

def new_voting_token() -> str:
    """Return a fresh, high-entropy, URL-safe anonymous voting token."""
    return secrets.token_urlsafe(32)


def token_fingerprint(token: str) -> str:
    """A one-way fingerprint stored in place of the token itself.

    Because only ``sha256(token)`` is persisted, the token cannot be read back
    or reversed, and - combined with the blind-issuance flow documented in
    docs/IMPLEMENTATION.md - cannot be linked to a voter.
    """
    return hash_hex("voting-token", token)


# --- Auditing ----------------------------------------------------------------

def audit_entry_hash(seq: int, prev_hash: str, data_hash: str) -> str:
    return hash_hex("audit", str(seq), prev_hash, data_hash)


def ballot_receipt(encrypted_ballot: str) -> str:
    """The public receipt a voter can later use to verify inclusion."""
    return hash_hex("receipt", encrypted_ballot)
