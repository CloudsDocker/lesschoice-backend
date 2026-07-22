import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from cbor2 import loads as cbor_decode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
from cryptography.x509 import load_der_x509_certificate
from pyattest.assertion import Assertion
from pyattest.attestation import Attestation
from pyattest.configs.apple import AppleConfig
from pyattest.verifiers.apple_assertion import AppleAssertionVerifier

from . import config
from .gcp_clients import firestore_client

CHALLENGE_TTL_SECONDS = 5 * 60
_challenges_collection = "attest_challenges"
_devices_collection = "attested_devices"


class AttestationError(Exception):
    pass


def _app_id() -> str:
    return f"{config.APPLE_TEAM_ID}.{config.APPLE_BUNDLE_ID}"


def _device_doc_id(key_id_b64: str) -> str:
    # App Attest key IDs are standard base64, which can contain "/". Firestore
    # treats "/" in a document ID as a collection/document path separator, so a
    # raw key ID with a slash blows up with "must have an even number of path
    # elements". Standard base64 never emits "_", so swapping "/"->"_" is a
    # collision-free, reversible transform safe to use as the document ID.
    return key_id_b64.replace("/", "_")


async def issue_challenge() -> str:
    challenge = secrets.token_urlsafe(32)
    await firestore_client().collection(_challenges_collection).document(challenge).set({
        "used": False,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=CHALLENGE_TTL_SECONDS),
    })
    return challenge


async def _consume_challenge(challenge: str) -> None:
    ref = firestore_client().collection(_challenges_collection).document(challenge)
    doc = await ref.get()
    if not doc.exists:
        raise AttestationError("unknown or expired challenge")
    data = doc.to_dict()
    if data["used"]:
        raise AttestationError("challenge already used")
    if data["expires_at"] < datetime.now(timezone.utc):
        raise AttestationError("challenge expired")
    await ref.update({"used": True})


def _leaf_public_key_from_attestation(attestation_bytes: bytes) -> EllipticCurvePublicKey:
    decoded = cbor_decode(attestation_bytes)
    leaf_der = decoded["attStmt"]["x5c"][0]
    cert = load_der_x509_certificate(leaf_der)
    public_key = cert.public_key()
    if not isinstance(public_key, EllipticCurvePublicKey):
        raise AttestationError("unexpected public key type in attestation certificate")
    return public_key


async def register_device(key_id_b64: str, attestation_b64: str, challenge: str) -> None:
    await _consume_challenge(challenge)

    try:
        key_id_bytes = base64.b64decode(key_id_b64)
        attestation_bytes = base64.b64decode(attestation_b64)
    except Exception as exc:
        raise AttestationError("malformed base64 input") from exc

    # The client hashes SHA256(UTF-8 bytes of the challenge string) to build
    # clientDataHash, and pyattest's nonce verifier internally does
    # SHA256(nonce_param) to reconstruct that same hash — so nonce_param here
    # must be the challenge string's raw UTF-8 bytes, not its base64 decoding.
    apple_config = AppleConfig(key_id=key_id_bytes, app_id=_app_id(), production=False)
    attestation = Attestation(raw=attestation_bytes, nonce=challenge.encode(), config=apple_config)

    try:
        await attestation.verify()
    except Exception as exc:
        # pyattest can raise its own PyAttestException subclasses, but malformed
        # input (garbage CBOR, truncated certs, etc.) can also surface as raw
        # errors from cbor2/cryptography/asn1crypto — treat all of it the same
        # way: a clean, non-leaky rejection rather than a 500 with a stack trace.
        raise AttestationError(f"attestation verification failed: {type(exc).__name__}: {exc}") from exc

    try:
        public_key = _leaf_public_key_from_attestation(attestation_bytes)
    except Exception as exc:
        raise AttestationError(f"could not extract public key: {exc}") from exc
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    await firestore_client().collection(_devices_collection).document(_device_doc_id(key_id_b64)).set({
        "public_key_pem": public_key_pem,
        "counter": 0,
        "created_at": datetime.now(timezone.utc),
    })


async def verify_assertion(key_id_b64: str, assertion_b64: str, challenge: str) -> None:
    await _consume_challenge(challenge)

    device_ref = firestore_client().collection(_devices_collection).document(_device_doc_id(key_id_b64))
    device_doc = await device_ref.get()
    if not device_doc.exists:
        raise AttestationError("device not registered; call /v1/attest/register first")
    device = device_doc.to_dict()

    try:
        assertion_bytes = base64.b64decode(assertion_b64)
    except Exception as exc:
        raise AttestationError("malformed base64 input") from exc

    public_key = serialization.load_pem_public_key(device["public_key_pem"].encode())
    if not isinstance(public_key, EllipticCurvePublicKey):
        raise AttestationError("stored public key is not an EC key")

    apple_config = AppleConfig(key_id=base64.b64decode(key_id_b64), app_id=_app_id(), production=False)
    expected_hash = hashlib.sha256(challenge.encode()).digest()
    assertion = Assertion(raw=assertion_bytes, expected_hash=expected_hash, public_key=public_key, config=apple_config)

    try:
        assertion.verify()
    except Exception as exc:
        raise AttestationError(f"assertion verification failed: {type(exc).__name__}: {exc}") from exc

    unpacked = AppleAssertionVerifier.unpack(assertion_bytes)
    new_counter = unpacked["counter"]
    if new_counter <= device["counter"]:
        raise AttestationError("assertion counter did not increase; possible replay")

    await device_ref.update({"counter": new_counter})
