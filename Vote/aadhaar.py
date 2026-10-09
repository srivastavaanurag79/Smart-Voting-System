"""Aadhaar verification abstraction.

Real Aadhaar authentication is only available to licensed AUA/KUA agencies via
UIDAI. This module defines the interface the voting app calls and ships an
offline **mock** provider so the flow is testable end-to-end without any UIDAI
account. See docs/AADHAAR_INTEGRATION.md for the production integration path.

Nothing here ever stores the raw Aadhaar number in plaintext: callers persist
``crypto.hash_hex("aadhaar", number)`` and the Fernet-encrypted value only.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from django.conf import settings

# Verhoeff checksum tables (used by real Aadhaar numbers).
_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


@dataclass
class VerificationResult:
    success: bool
    verified: bool = False
    reference_id: str = ""
    message: str = ""


@dataclass
class BiometricResult:
    success: bool
    matched: bool = False
    reference_id: str = ""
    modality: str = ""
    message: str = ""


# Modalities supported by UIDAI Aadhaar biometric authentication.
BIOMETRIC_MODALITIES = {"face", "fingerprint", "iris"}

# In-process stand-in for the UIDAI CIDR (Central Identities Data Repository).
# It exists ONLY so the demo has something to match against. The voting system
# never writes biometrics to its own database; a real provider sends the
# captured biometric to UIDAI and stores nothing.
_MOCK_CIDR: dict[str, dict[str, str]] = {}


def _sample_hash(modality: str, sample: str) -> str:
    return hashlib.sha256(f"{modality}:{sample}".encode("utf-8")).hexdigest()


def _verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _digits(number: str) -> str:
    return re.sub(r"\D", "", number or "")


def is_valid_aadhaar(number: str) -> bool:
    """Strict validation: 12 digits, no leading 0/1, valid Verhoeff check.

    Real Aadhaar numbers satisfy this. Used by tests and optional tooling.
    """
    number = _digits(number)
    if len(number) != 12 or number[0] in "01":
        return False
    return _verhoeff_valid(number)


def is_plausible_aadhaar(number: str) -> bool:
    """Lenient validation used by the mock provider.

    Accepts any 12-digit number that does not begin with 0. This keeps the demo
    usable (a number that merely fails the Verhoeff checksum is still accepted),
    while a real UIDAI provider would perform full validation server-side.
    """
    number = _digits(number)
    return len(number) == 12 and number[0] != "0"


def mask_aadhaar(number: str) -> str:
    number = _digits(number)
    if len(number) != 12:
        return "XXXX-XXXX-XXXX"
    return f"XXXX-XXXX-{number[-4:]}"


def verify_aadhaar_checksum_ok(number: str) -> bool:
    """Alias kept for readability in views/tests."""
    return is_valid_aadhaar(number)


class MockAadhaarProvider:
    """Offline stand-in for UIDAI. Deterministic and safe for demos/tests."""

    name = "mock"

    def verify(self, number: str, otp: str | None = None, name: str = "") -> VerificationResult:
        number = _digits(number)
        if not is_plausible_aadhaar(number):
            return VerificationResult(False, message="Enter a valid 12-digit Aadhaar number.")
        # In mock mode the demo OTP is derived from the number so tests are
        # deterministic without any external service.
        expected = _mock_otp(number)
        if otp is not None and otp != expected:
            return VerificationResult(False, message="Incorrect OTP.")
        ref = hashlib.sha256(f"mock:{number}".encode()).hexdigest()[:24]
        return VerificationResult(
            True,
            verified=True,
            reference_id=f"MOCK-{ref}",
            message="Aadhaar verified (mock provider).",
        )

    def expected_otp(self, number: str) -> str:
        return _mock_otp(number)

    # --- biometric authentication (emulates UIDAI CIDR 1:1 match) -----------
    def enroll_biometric(self, number: str, modality: str, sample: str) -> BiometricResult:
        """Demo helper: register a biometric in the mock CIDR.

        A real flow never does this - UIDAI already holds the citizen's
        biometrics from Aadhaar enrolment. This method only lets the offline
        demo simulate a 1:1 match.
        """
        if not is_plausible_aadhaar(number):
            return BiometricResult(False, message="Enter a valid 12-digit Aadhaar number.")
        if modality not in BIOMETRIC_MODALITIES:
            return BiometricResult(False, message=f"Unsupported modality '{modality}'.")
        if not sample:
            return BiometricResult(False, message="Empty biometric sample.")
        key = hashlib.sha256(number.encode()).hexdigest()
        _MOCK_CIDR.setdefault(key, {})[modality] = _sample_hash(modality, sample)
        return BiometricResult(
            True, matched=True, modality=modality, message="Biometric enrolled in mock CIDR."
        )

    def verify_biometric(self, number: str, modality: str, sample: str) -> BiometricResult:
        """1:1 biometric match, as UIDAI would perform it.

        Returns only whether the captured biometric matches the record held for
        that Aadhaar. The biometric itself is never persisted by the caller.
        """
        if not is_plausible_aadhaar(number):
            return BiometricResult(False, message="Enter a valid 12-digit Aadhaar number.")
        if modality not in BIOMETRIC_MODALITIES:
            return BiometricResult(False, message=f"Unsupported modality '{modality}'.")
        if not sample:
            return BiometricResult(False, message="No biometric captured.")
        if sample == "MISMATCH":
            return BiometricResult(False, modality=modality, message="Biometric did not match.")

        key = hashlib.sha256(number.encode()).hexdigest()
        enrolled = _MOCK_CIDR.get(key, {}).get(modality)
        # CIDR-lookup mode (no local enrollment): accept a valid capture.
        if enrolled is not None and enrolled != _sample_hash(modality, sample):
            return BiometricResult(False, modality=modality, message="Biometric did not match.")

        ref = hashlib.sha256(f"bio:{number}:{modality}".encode()).hexdigest()[:24]
        return BiometricResult(
            True,
            matched=True,
            modality=modality,
            reference_id=f"MOCK-BIO-{ref}",
            message=f"{modality.title()} matched (mock CIDR).",
        )


def _mock_otp(number: str) -> str:
    return str(int(hashlib.sha256(f"otp:{number}".encode()).hexdigest(), 16) % 1000000).zfill(6)


def get_provider():
    provider = getattr(settings, "AADHAAR_PROVIDER", "mock")
    if provider == "mock":
        return MockAadhaarProvider()
    raise NotImplementedError(
        f"Aadhaar provider '{provider}' is not implemented. Real UIDAI "
        "authentication requires AUA/KUA licensing; see docs/AADHAAR_INTEGRATION.md."
    )
