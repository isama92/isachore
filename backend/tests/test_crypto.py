import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.crypto import crypto_configured, decrypt, encrypt, generate_key

# A throwaway key generated per test run; never a real secret.
_KEY = Fernet.generate_key().decode()


def test_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_key", _KEY)
    plaintext = "JBSWY3DPEHPK3PXP"  # a TOTP-secret-shaped string
    assert decrypt(encrypt(plaintext)) == plaintext


def test_ciphertext_is_opaque_and_nondeterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_key", _KEY)
    plaintext = "JBSWY3DPEHPK3PXP"
    first = encrypt(plaintext)
    second = encrypt(plaintext)
    # The stored form never contains the plaintext, and Fernet's random IV means
    # encrypting the same value twice yields different ciphertexts.
    assert plaintext not in first
    assert first != second
    assert decrypt(first) == decrypt(second) == plaintext


def test_crypto_configured_reflects_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_key", _KEY)
    assert crypto_configured() is True
    # A missing key reads as not configured, so callers fail closed.
    monkeypatch.setattr(settings, "app_key", None)
    assert crypto_configured() is False
    # A malformed key (not a valid Fernet key) also reads as not configured
    # rather than blowing up later inside encrypt/decrypt.
    monkeypatch.setattr(settings, "app_key", "not-a-valid-fernet-key")
    assert crypto_configured() is False


def test_encrypt_and_decrypt_fail_closed_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_key", None)
    with pytest.raises(RuntimeError, match="Encryption is not configured"):
        encrypt("secret")
    with pytest.raises(RuntimeError, match="Encryption is not configured"):
        decrypt("gAAAAA...")


def test_encrypt_and_decrypt_fail_closed_with_a_malformed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A garbage key must fail exactly like a missing one (RuntimeError), never
    # crash with a raw crypto error or silently proceed.
    monkeypatch.setattr(settings, "app_key", "not-a-valid-fernet-key")
    with pytest.raises(RuntimeError, match="Encryption is not configured"):
        encrypt("secret")
    with pytest.raises(RuntimeError, match="Encryption is not configured"):
        decrypt("gAAAAA...")


def test_decrypt_rejects_garbage_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    # A valid key but a bogus token: Fernet's HMAC/format check rejects it rather
    # than returning junk plaintext.
    monkeypatch.setattr(settings, "app_key", _KEY)
    with pytest.raises(InvalidToken):
        decrypt("not-a-real-token")


def test_generate_key_produces_a_usable_app_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # What `python -m app.cli generate-key` prints must satisfy the same check
    # the startup gate (I1) and the 2FA gates use, or the documented fix for a
    # boot refusal would not actually fix it.
    monkeypatch.setattr(settings, "app_key", generate_key())
    assert crypto_configured() is True
    assert decrypt(encrypt("JBSWY3DPEHPK3PXP")) == "JBSWY3DPEHPK3PXP"


def test_generate_key_is_random() -> None:
    assert generate_key() != generate_key()


def test_decrypt_rejects_ciphertext_from_a_different_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_key", _KEY)
    token = encrypt("secret")
    # Re-key and try to read the old ciphertext: Fernet's HMAC must reject it,
    # so a leaked ciphertext is useless without the exact key it was made with.
    monkeypatch.setattr(settings, "app_key", Fernet.generate_key().decode())
    with pytest.raises(InvalidToken):
        decrypt(token)
