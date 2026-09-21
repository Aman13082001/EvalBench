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

    @patch("evalbench.cli._get_headers", return_value={"X-API-Key": "k"})
    @patch("evalbench.cli.httpx.get")
    def test_it_asks_for_the_provider_and_sends_the_credential(self, mock_get, _hdr):
        """The endpoint requires a user and takes a provider. The command
        sent neither: every call was a 401, and only Ollama was ever
        asked. README promised `--provider` all along."""
        mock_get.return_value = mock_response(200, {"models": ["openai/gpt-oss-20b"], "hidden": ["whisper-large-v3"]})

        result = runner.invoke(app, ["models", "--provider", "groq"])

        assert result.exit_code == 0, result.stdout
        assert "openai/gpt-oss-20b" in result.stdout
        assert "1 hidden" in result.stdout
        kw = mock_get.call_args.kwargs
        assert kw["params"] == {"provider": "groq"}
        assert kw["headers"] == {"X-API-Key": "k"}

    @patch("evalbench.cli._get_headers", return_value={})
    @patch("evalbench.cli.httpx.get")
    def test_without_a_credential_it_says_so(self, mock_get, _hdr):
        mock_get.return_value = mock_response(401, {"detail": "Not authenticated"})
        result = runner.invoke(app, ["models"])
        assert result.exit_code == 1
        assert "evalbench login" in result.stdout


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

    def test_the_scaffold_is_a_valid_suite_in_the_modern_shape(self, tmp_path):
        """A description, a provider line, and an `assert` block: the
        shape the bundled benchmarks use, not the shape from the first
        week. And it must parse as a TestSuite, or `init` hands out a
        file that `run` refuses."""
        import yaml

        from evalbench.db.schemas import TestSuite

        output_file = tmp_path / "suite.yaml"
        runner.invoke(app, ["init", "--output", str(output_file)])
        data = yaml.safe_load(output_file.read_text(encoding="utf-8"))
        suite = TestSuite(**data)
        assert suite.description
        assert data["provider"] == "ollama"
        assert any(t.assert_ for t in suite.tests)
        assert any(a.type == "llm-rubric" for t in suite.tests for a in (t.assert_ or []))


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


class TestTheCliTripFound:
    """Two things a person met on the first walk through the CLI."""

    @patch("evalbench.cli.httpx.get")
    def test_export_writes_utf8_whatever_the_console_is(self, mock_get, tmp_path):
        """A model answer with an em dash crashed `export -f csv` on
        Windows: the file was opened with the console's code page
        (cp1252), which has no "—". Written as UTF-8 always. On a UTF-8
        machine this passes before and after; on Windows it failed."""
        out = tmp_path / "run.csv"
        mock_get.return_value = mock_response(
            200, {"format": "csv", "filename": "r.csv", "content": "test,actual\ncapital,Tokyo — the capital\n"}
        )
        r = runner.invoke(app, ["export", "123", "-f", "csv", "-o", str(out)])
        assert r.exit_code == 0, r.output
        assert "Tokyo — the capital" in out.read_text(encoding="utf-8")

    @patch("evalbench.cli.httpx.post")
    @patch("evalbench.cli.httpx.get")
    def test_baseline_accepts_the_suite_yaml_like_run_does(self, mock_get, mock_post, tmp_path):
        """`run` takes suites/demo.yaml; `baseline` wanted the suite's id,
        which `run` never prints. It now takes the same file: the suite
        is looked up by name, the way `run` imports it (create-or-update
        by name), so the two commands name the same thing."""
        suite = tmp_path / "demo.yaml"
        suite.write_text("name: EvalBench Demo\nmodel: m\ntests:\n  - name: t\n    prompt: p\n    expected: e\n", encoding="utf-8")
        mock_get.return_value = mock_response(200, [
            {"_id": "6ab000000000000000000001", "name": "Something else"},
            {"_id": "6ab000000000000000000002", "name": "EvalBench Demo"},
        ])
        mock_post.return_value = mock_response(200, {"suite_id": "6ab000000000000000000002", "baseline_run_id": "run9"})
        r = runner.invoke(app, ["baseline", str(suite), "run9"])
        assert r.exit_code == 0, r.output
        assert mock_post.call_args[0][0].endswith("/suites/6ab000000000000000000002/baseline")
        assert "EvalBench Demo" in r.output

    @patch("evalbench.cli.httpx.get")
    def test_baseline_says_when_the_file_has_no_suite_yet(self, mock_get, tmp_path):
        suite = tmp_path / "new.yaml"
        suite.write_text("name: Never run\nmodel: m\ntests: []\n", encoding="utf-8")
        mock_get.return_value = mock_response(200, [])
        r = runner.invoke(app, ["baseline", str(suite), "run9"])
        assert r.exit_code == 1
        assert "Never run" in r.output and "evalbench run" in r.output

    @patch("evalbench.cli.httpx.post")
    def test_baseline_still_takes_a_suite_id(self, mock_post):
        mock_post.return_value = mock_response(200, {"suite_id": "6ab000000000000000000002", "baseline_run_id": "run9"})
        r = runner.invoke(app, ["baseline", "6ab000000000000000000002", "run9"])
        assert r.exit_code == 0, r.output
        assert mock_post.call_args[0][0].endswith("/suites/6ab000000000000000000002/baseline")

    @patch("evalbench.cli.httpx.get")
    @patch("evalbench.cli.httpx.post")
    def test_compare_to_baseline_uses_the_baseline_the_server_holds(self, mock_post, mock_get, tmp_path, monkeypatch):
        """`evalbench baseline` stores the baseline on the suite, server
        side. `run --compare-to-baseline` read only the YAML, so a
        baseline set the documented way was never compared against: the
        report said `regression: null` and the gate never ran. Found on
        the first walk through the CLI. The YAML still wins when it names
        one; otherwise the server is asked."""
        import evalbench.cli as cli

        auth = tmp_path / "auth.json"
        auth.write_text(json.dumps({"token": "t"}))
        monkeypatch.setattr(cli, "AUTH_FILE", auth)
        suite = tmp_path / "s.yaml"
        suite.write_text("name: S\nmodel: m\nevaluator: exact\ntests:\n  - name: t\n    prompt: p\n    expected: e\n", encoding="utf-8")

        comparison = {"baseline_mean": 0.9, "current_mean": 0.9, "mean_diff": 0.0, "p_value": 1.0, "regression_detected": False, "per_test": []}
        mock_post.side_effect = [
            mock_response(201, {"id": "suite123"}),      # import
            mock_response(201, {"run_id": "run2"}),      # run
            mock_response(200, comparison),              # /regression
        ]

        def get(url, *a, **k):
            if url.endswith("/runs/run2/status"):
                return mock_response(200, {"status": "completed", "completed_tests": 1, "total_tests": 1})
            if url.endswith("/runs/run2/summary"):
                return mock_response(200, {"model": "m", "evaluator": "exact", "total_tests": 1, "passed": 1, "failed": 0,
                                           "pass_rate": 1.0, "avg_score": 1.0, "avg_latency_ms": 1.0, "total_tokens": 1})
            if url.endswith("/suites/suite123/baseline"):
                return mock_response(200, {"suite_id": "suite123", "baseline_run_id": "run1"})
            raise AssertionError(url)

        mock_get.side_effect = get
        report = tmp_path / "report.json"
        r = runner.invoke(app, ["run", str(suite), "--compare-to-baseline", "--report", str(report)])
        assert r.exit_code == 0, r.output
        regression_call = mock_post.call_args_list[2]
        assert regression_call[1]["json"] == {"baseline_run_id": "run1", "current_run_id": "run2"}
        assert json.loads(report.read_text())["regression"]["regression_detected"] is False
        assert "No baseline set" not in r.output
