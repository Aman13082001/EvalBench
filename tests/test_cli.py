"""Unit tests for EvalBench CLI."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from evalbench.cli import app

runner = CliRunner()


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def mock_response(status_code=200, json_data=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.raise_for_status.return_value = None
    return response


# ─────────────────────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────────────────────

class TestAuthHelpers:

    def test_load_auth_when_file_missing(self, tmp_path, monkeypatch):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        assert cli._load_auth() == {}

    def test_save_and_load_auth(self, tmp_path, monkeypatch):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        cli._save_auth({"token": "test-token"})

        assert auth_file.exists()
        assert cli._load_auth() == {"token": "test-token"}

    def test_get_headers_with_api_key(self):
        import evalbench.cli as cli

        headers = cli._get_headers("my-api-key")

        assert headers == {
            "X-API-Key": "my-api-key"
        }

    def test_get_headers_with_token(self, tmp_path, monkeypatch):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        auth_file.write_text(
            json.dumps({"token": "abc123"})
        )

        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        headers = cli._get_headers()

        assert headers == {
            "Authorization": "Bearer abc123"
        }

    def test_get_headers_with_saved_api_key(self, tmp_path, monkeypatch):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        auth_file.write_text(
            json.dumps({"api_key": "saved-key"})
        )

        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        headers = cli._get_headers()

        assert headers == {
            "X-API-Key": "saved-key"
        }

    def test_get_headers_without_auth(self, tmp_path, monkeypatch):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        assert cli._get_headers() == {}


# ─────────────────────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────────────────────

class TestLogin:

    @patch("evalbench.cli.httpx.post")
    def test_login_success(
        self,
        mock_post,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        mock_post.return_value = mock_response(
            200,
            {"access_token": "jwt-token"},
        )

        result = runner.invoke(
            app,
            [
                "login",
                "--username",
                "admin",
                "--password",
                "admin",
            ],
        )

        assert result.exit_code == 0
        assert "Logged in as admin" in result.stdout

        saved = json.loads(auth_file.read_text())
        assert saved["token"] == "jwt-token"

    @patch("evalbench.cli.httpx.post")
    def test_login_invalid_credentials(self, mock_post):
        mock_post.return_value = mock_response(
            401,
            {"detail": "Invalid credentials"},
        )

        result = runner.invoke(
            app,
            [
                "login",
                "--username",
                "admin",
                "--password",
                "wrong",
            ],
        )

        assert result.exit_code == 1
        assert "Invalid username or password" in result.stdout


# ─────────────────────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────────────────────

class TestLogout:

    def test_logout_existing_auth(
        self,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        auth_file.write_text(
            json.dumps({"token": "abc"})
        )

        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        result = runner.invoke(app, ["logout"])

        assert result.exit_code == 0
        assert not auth_file.exists()
        assert "Logged out" in result.stdout

    def test_logout_without_auth(
        self,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        result = runner.invoke(app, ["logout"])

        assert result.exit_code == 0
        assert "Logged out" in result.stdout


# ─────────────────────────────────────────────────────────────
# WHOAMI
# ─────────────────────────────────────────────────────────────

class TestWhoAmI:

    def test_whoami_not_logged_in(
        self,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        result = runner.invoke(app, ["whoami"])

        assert result.exit_code == 0
        assert "Not logged in" in result.stdout

    @patch("evalbench.cli.httpx.get")
    def test_whoami_success(
        self,
        mock_get,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        auth_file.write_text(
            json.dumps({"token": "abc"})
        )

        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        mock_get.return_value = mock_response(
            200,
            {
                "username": "admin",
                "role": "admin",
            },
        )

        result = runner.invoke(app, ["whoami"])

        assert result.exit_code == 0
        assert "admin" in result.stdout
        assert "Role" in result.stdout

    @patch("evalbench.cli.httpx.get")
    def test_whoami_expired_session(
        self,
        mock_get,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        auth_file.write_text(
            json.dumps({"token": "expired"})
        )

        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        mock_get.return_value = mock_response(
            401,
            {"detail": "Unauthorized"},
        )

        result = runner.invoke(app, ["whoami"])

        assert result.exit_code == 0
        assert "Session expired" in result.stdout


# ─────────────────────────────────────────────────────────────
# REGISTER
# ─────────────────────────────────────────────────────────────

class TestRegister:

    @patch("evalbench.cli.httpx.post")
    def test_register_success(
        self,
        mock_post,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        mock_post.return_value = mock_response(
            201,
            {
                "api_key": "abcdef1234567890abcdef"
            },
        )

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "newuser",
                "--password",
                "password123",
            ],
        )

        assert result.exit_code == 0
        assert "Registered as newuser" in result.stdout

        saved = json.loads(auth_file.read_text())
        assert saved["api_key"] == "abcdef1234567890abcdef"

    @patch("evalbench.cli.httpx.post")
    def test_register_existing_user(self, mock_post):
        mock_post.return_value = mock_response(
            400,
            {"detail": "Username already exists"},
        )

        result = runner.invoke(
            app,
            [
                "register",
                "--username",
                "admin",
                "--password",
                "admin",
            ],
        )

        assert result.exit_code == 1
        assert "Username already exists" in result.stdout


# ─────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────

class TestModels:

    @patch("evalbench.cli.httpx.get")
    def test_models(self, mock_get):
        mock_get.return_value = mock_response(
            200,
            {
                "models": [
                    "llama3.1:latest",
                    "qwen3:8b",
                ]
            },
        )

        result = runner.invoke(app, ["models"])

        assert result.exit_code == 0
        assert "llama3.1:latest" in result.stdout
        assert "qwen3:8b" in result.stdout


# ─────────────────────────────────────────────────────────────
# INIT
# ─────────────────────────────────────────────────────────────

class TestInit:

    def test_init_creates_suite(self, tmp_path):
        output_file = tmp_path / "suite.yaml"

        result = runner.invoke(
            app,
            [
                "init",
                "--output",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()
        assert "Created sample suite" in result.stdout

        content = output_file.read_text()

        assert "My Test Suite" in content
        assert "llama3.1" in content
        assert "semantic" in content
        assert "What is 2+2?" in content


# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

class TestRun:

    @patch("evalbench.cli.httpx.get")
    @patch("evalbench.cli.httpx.post")
    def test_run_success(
        self,
        mock_post,
        mock_get,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        auth_file.write_text(
            json.dumps({"token": "test-token"})
        )

        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        suite_file = tmp_path / "suite.yaml"

        suite_file.write_text(
            """
name: Test Suite
model: llama3.1
evaluator: semantic
tests:
  - name: test1
    prompt: What is 2+2?
    expected: "4"
    threshold: 0.8
"""
        )

        mock_post.side_effect = [
            mock_response(
                201,
                {"id": "suite123"},
            ),
            mock_response(
                201,
                {"run_id": "run123"},
            ),
        ]

        mock_get.return_value = mock_response(
            200,
            {
                "model": "llama3.1",
                "evaluator": "semantic",
                "total_tests": 1,
                "passed": 1,
                "failed": 0,
                "pass_rate": 1.0,
                "avg_score": 0.95,
                "avg_latency_ms": 100.0,
                "total_tokens": 10,
            },
        )

        result = runner.invoke(
            app,
            [
                "run",
                str(suite_file),
            ],
        )

        assert result.exit_code == 0
        assert "Run completed" in result.stdout
        assert "run123" in result.stdout

    @patch("evalbench.cli.httpx.get")
    @patch("evalbench.cli.httpx.post")
    def test_run_writes_json_report(
        self, mock_post, mock_get, tmp_path, monkeypatch
    ):
        import evalbench.cli as cli

        monkeypatch.setattr(cli, "AUTH_FILE", tmp_path / "auth.json")
        (tmp_path / "auth.json").write_text(json.dumps({"token": "t"}))

        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(
            "name: S\nmodel: llama3.1\nevaluator: exact\ntests:\n"
            "  - name: t1\n    prompt: p\n    expected: '4'\n    threshold: 0.8\n"
        )

        mock_post.side_effect = [
            mock_response(201, {"id": "suite123"}),
            mock_response(201, {"run_id": "run123"}),
        ]
        mock_get.return_value = mock_response(
            200,
            {
                "model": "llama3.1", "evaluator": "exact", "total_tests": 1,
                "passed": 1, "failed": 0, "pass_rate": 1.0, "avg_score": 0.95,
                "avg_latency_ms": 100.0, "total_tokens": 10,
            },
        )

        report = tmp_path / "report.json"
        result = runner.invoke(
            app, ["run", str(suite_file), "--report", str(report)]
        )

        assert result.exit_code == 0
        data = json.loads(report.read_text())
        assert data["run_id"] == "run123"
        assert data["summary"]["pass_rate"] == 1.0
        assert data["gate"]["passed"] is True
        assert data["gate"]["regression_detected"] is False

    def test_pr_comment_dry_run(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps({
            "suite": "S", "run_id": "x",
            "summary": {
                "model": "m", "total_tests": 1, "passed": 1, "failed": 0,
                "pass_rate": 1.0, "avg_score": 1.0, "avg_latency_ms": 10,
            },
            "regression": None,
            "gate": {"fail_under": 0.75, "passed": True},
        }))
        result = runner.invoke(
            app, ["pr-comment", "--report", str(report), "--dry-run"]
        )
        assert result.exit_code == 0
        assert "EvalBench" in result.stdout

    @patch("evalbench.cli.httpx.post")
    def test_run_authentication_required(
        self,
        mock_post,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        suite_file = tmp_path / "suite.yaml"

        suite_file.write_text(
            """
name: Test Suite
model: llama3.1
evaluator: semantic
tests: []
"""
        )

        mock_post.return_value = mock_response(
            401,
            {"detail": "Unauthorized"},
        )

        result = runner.invoke(
            app,
            [
                "run",
                str(suite_file),
            ],
        )

        assert result.exit_code == 1
        assert "Authentication required" in result.stdout

    @patch("evalbench.cli.httpx.get")
    @patch("evalbench.cli.httpx.post")
    def test_run_fails_quality_gate(
        self,
        mock_post,
        mock_get,
        tmp_path,
        monkeypatch,
    ):
        import evalbench.cli as cli

        auth_file = tmp_path / "auth.json"
        monkeypatch.setattr(cli, "AUTH_FILE", auth_file)

        suite_file = tmp_path / "suite.yaml"

        suite_file.write_text(
            """
name: Test Suite
model: llama3.1
evaluator: semantic
tests: []
"""
        )

        mock_post.side_effect = [
            mock_response(
                201,
                {"id": "suite123"},
            ),
            mock_response(
                201,
                {"run_id": "run123"},
            ),
        ]

        mock_get.return_value = mock_response(
            200,
            {
                "model": "llama3.1",
                "evaluator": "semantic",
                "total_tests": 4,
                "passed": 1,
                "failed": 3,
                "pass_rate": 0.25,
                "avg_score": 0.4,
                "avg_latency_ms": 100.0,
                "total_tokens": 20,
            },
        )

        result = runner.invoke(
            app,
            [
                "run",
                str(suite_file),
            ],
        )

        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────
# COMPARE
# ─────────────────────────────────────────────────────────────

class TestCompare:

    @patch("evalbench.cli.httpx.post")
    def test_compare_no_regression(self, mock_post):
        mock_post.return_value = mock_response(
            200,
            {
                "baseline_mean": 0.9,
                "current_mean": 0.91,
                "mean_diff": 0.01,
                "t_statistic": 0.5,
                "p_value": 0.6,
                "significant": False,
                "regression_detected": False,
            },
        )

        result = runner.invoke(
            app,
            [
                "compare",
                "baseline123",
                "current123",
            ],
        )

        assert result.exit_code == 0
        assert "No Regression Detected" in result.stdout

    @patch("evalbench.cli.httpx.post")
    def test_compare_regression(self, mock_post):
        mock_post.return_value = mock_response(
            200,
            {
                "baseline_mean": 0.9,
                "current_mean": 0.5,
                "mean_diff": -0.4,
                "t_statistic": 5.2,
                "p_value": 0.01,
                "significant": True,
                "regression_detected": True,
            },
        )

        result = runner.invoke(
            app,
            [
                "compare",
                "baseline123",
                "current123",
            ],
        )

        assert result.exit_code == 0
        assert "REGRESSION DETECTED" in result.stdout

    @patch("evalbench.cli.httpx.post")
    def test_compare_auth_required(self, mock_post):
        mock_post.return_value = mock_response(
            401,
            {"detail": "Unauthorized"},
        )

        result = runner.invoke(
            app,
            [
                "compare",
                "baseline123",
                "current123",
            ],
        )

        assert result.exit_code == 1
        assert "Authentication required" in result.stdout


# ─────────────────────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────────────────────

class TestSecurity:

    @patch("evalbench.cli.httpx.get")
    @patch("evalbench.cli.httpx.post")
    def test_security_success(
        self,
        mock_post,
        mock_get,
    ):
        mock_post.side_effect = [
            mock_response(
                201,
                {
                    "id": "security-suite",
                    "test_count": 10,
                    "categories": [
                        "harmful_content",
                        "jailbreak",
                    ],
                },
            ),
            mock_response(
                201,
                {"run_id": "security-run"},
            ),
        ]

        mock_get.return_value = mock_response(
            200,
            {
                "total_tests": 10,
                "passed": 10,
                "failed": 0,
                "pass_rate": 1.0,
            },
        )

        result = runner.invoke(
            app,
            ["security"],
        )

        assert result.exit_code == 0
        assert "Security suite created" in result.stdout
        assert "security-run" in result.stdout
        assert "correctly refused" in result.stdout

    @patch("evalbench.cli.httpx.post")
    def test_security_auth_required(self, mock_post):
        mock_post.return_value = mock_response(
            401,
            {"detail": "Unauthorized"},
        )

        result = runner.invoke(
            app,
            ["security"],
        )

        assert result.exit_code == 1
        assert "Authentication required" in result.stdout

    @patch("evalbench.cli.httpx.get")
    @patch("evalbench.cli.httpx.post")
    def test_security_partial_failure(
        self,
        mock_post,
        mock_get,
    ):
        mock_post.side_effect = [
            mock_response(
                201,
                {
                    "id": "security-suite",
                    "test_count": 10,
                    "categories": ["jailbreak"],
                },
            ),
            mock_response(
                201,
                {"run_id": "security-run"},
            ),
        ]

        mock_get.return_value = mock_response(
            200,
            {
                "total_tests": 10,
                "passed": 7,
                "failed": 3,
                "pass_rate": 0.7,
            },
        )

        result = runner.invoke(
            app,
            ["security"],
        )

        assert result.exit_code == 0
        assert "Review recommended" in result.stdout


# ─────────────────────────────────────────────────────────────
# EXPORT
# ─────────────────────────────────────────────────────────────

class TestExport:

    @patch("evalbench.cli.httpx.get")
    def test_export_json_to_file(
        self,
        mock_get,
        tmp_path,
    ):
        output_file = tmp_path / "result.json"

        mock_get.return_value = mock_response(
            200,
            {
                "format": "json",
                "filename": "run_123.json",
                "data": {
                    "run_id": "123",
                    "model": "llama3.1",
                    "results": [],
                },
            },
        )

        result = runner.invoke(
            app,
            [
                "export",
                "123",
                "--format",
                "json",
                "--output",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        data = json.loads(
            output_file.read_text()
        )

        assert data["run_id"] == "123"
        assert data["model"] == "llama3.1"

    @patch("evalbench.cli.httpx.get")
    def test_export_csv_to_file(
        self,
        mock_get,
        tmp_path,
    ):
        output_file = tmp_path / "results.csv"

        mock_get.return_value = mock_response(
            200,
            {
                "format": "csv",
                "filename": "run_123.csv",
                "content": (
                    "test_name,prompt,score,passed\n"
                    "test1,hello,0.9,TRUE\n"
                ),
            },
        )

        result = runner.invoke(
            app,
            [
                "export",
                "123",
                "--format",
                "csv",
                "--output",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert output_file.exists()

        content = output_file.read_text()

        assert "test_name" in content
        assert "0.9" in content

    @patch("evalbench.cli.httpx.get")
    def test_export_json_to_console(self, mock_get):
        mock_get.return_value = mock_response(
            200,
            {
                "format": "json",
                "filename": "run_123.json",
                "data": {
                    "run_id": "123",
                },
            },
        )

        result = runner.invoke(
            app,
            [
                "export",
                "123",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        assert '"run_id": "123"' in result.stdout

    def test_export_invalid_format(self):
        result = runner.invoke(
            app,
            [
                "export",
                "123",
                "--format",
                "xml",
            ],
        )

        assert result.exit_code == 1
        assert "Format must be 'json' or 'csv'" in result.stdout

    @patch("evalbench.cli.httpx.get")
    def test_export_auth_required(self, mock_get):
        mock_get.return_value = mock_response(
            401,
            {"detail": "Unauthorized"},
        )

        result = runner.invoke(
            app,
            [
                "export",
                "123",
                "--format",
                "csv",
            ],
        )

        assert result.exit_code == 1
        assert "Authentication required" in result.stdout
