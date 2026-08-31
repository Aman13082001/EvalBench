"""Unit tests for JWT and password utilities."""

import pytest
from jose import jwt

from evalbench.config import settings
from evalbench.api.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_token,
    generate_api_key,
    SECRET_KEY,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
)


class TestConfigWiring:
    def test_secret_key_comes_from_settings(self):
        assert SECRET_KEY == settings.secret_key

    def test_token_expiry_comes_from_settings(self):
        assert ACCESS_TOKEN_EXPIRE_MINUTES == settings.token_expire_minutes


class TestPasswordHashing:
    def test_hash_and_verify(self):
        password = "supersecret123"
        hashed = get_password_hash(password)
        assert verify_password(password, hashed) is True
        assert verify_password("wrongpassword", hashed) is False

    def test_different_passwords_different_hashes(self):
        p1 = get_password_hash("pass1")
        p2 = get_password_hash("pass1")
        assert p1 != p2  # bcrypt salts


class TestJWT:
    def test_create_and_decode(self):
        token = create_access_token(data={"sub": "testuser"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"

    def test_decode_invalid_token(self):
        payload = decode_token("totally.invalid.token")
        assert payload is None

    def test_token_expiry(self):
        from datetime import timedelta
        token = create_access_token(
            data={"sub": "testuser"},
            expires_delta=timedelta(seconds=-1),
        )
        payload = decode_token(token)
        assert payload is None  # Expired


class TestAPIKey:
    def test_generate_format(self):
        key = generate_api_key()
        assert key.startswith("eb_")
        assert len(key) > 20

    def test_generate_unique(self):
        keys = {generate_api_key() for _ in range(100)}
        assert len(keys) == 100
