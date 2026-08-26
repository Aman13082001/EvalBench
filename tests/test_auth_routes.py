"""Unit tests for auth endpoints."""

from datetime import datetime, timezone

from unittest.mock import AsyncMock


class TestAuthEndpoints:

    def test_register_success(self, client, mock_db):
        mock_db.users.find_one.return_value = None
        mock_db.users.insert_one.return_value = AsyncMock()

        payload = {
            "username": "newuser",
            "password": "secret123",
        }

        response = client.post(
            "/auth/register",
            json=payload,
        )

        assert response.status_code == 201

        data = response.json()

        assert data["username"] == "newuser"
        assert data["api_key"].startswith("eb_")


    def test_register_duplicate(self, client, mock_db):
        mock_db.users.find_one.return_value = {
            "username": "existing"
        }

        payload = {
            "username": "existing",
            "password": "secret123",
        }

        response = client.post(
            "/auth/register",
            json=payload,
        )

        assert response.status_code == 400

        assert (
            "already registered"
            in response.json()["detail"]
        )


    def test_login_success(self, client, mock_db):
        from evalbench.api.auth import get_password_hash

        mock_db.users.find_one.return_value = {
            "username": "testuser",
            "hashed_password": get_password_hash(
                "password123"
            ),
        }

        response = client.post(
            "/auth/login",
            data={
                "username": "testuser",
                "password": "password123",
            },
        )

        assert response.status_code == 200

        assert "access_token" in response.json()


    def test_login_invalid(self, client, mock_db):
        mock_db.users.find_one.return_value = None

        response = client.post(
            "/auth/login",
            data={
                "username": "wrong",
                "password": "wrong",
            },
        )

        assert response.status_code == 401


    def test_me_endpoint(self, client, mock_db):
        mock_db.users.find_one.return_value = {
            "username": "testuser",
            "role": "admin",
            "created_at": datetime.now(
                timezone.utc
            ),
        }

        response = client.get("/auth/me")

        assert response.status_code == 200

        data = response.json()

        assert data["username"] == "testuser"
        assert data["role"] == "admin"


    def test_rotate_api_key(self, client, mock_db):
        mock_db.users.update_one.return_value = AsyncMock()

        response = client.post(
            "/auth/api-key/rotate"
        )

        assert response.status_code == 200

        data = response.json()

        assert data["api_key"].startswith("eb_")

        assert (
            "rotated"
            in data["message"].lower()
        )