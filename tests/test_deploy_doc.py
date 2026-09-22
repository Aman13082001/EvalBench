"""The deployment guide, checked against the thing it deploys.

A deploy guide rots faster than anything else in a repo: a setting is
renamed, the README keeps naming the old one, and the person following
it at midnight gets a server that boots with the wrong defaults and no
error. So the guide's environment checklist is read here and every name
in it is looked up on `Settings`. A rename breaks this test, not a
deployment.
"""

import pathlib
import re

from evalbench.config import Settings

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "DEPLOY.md"
DOCKERFILE = ROOT / "Dockerfile"

# Names the guide may use that are not settings: they are read by the
# frontend at build time, or by the platform itself.
NOT_SETTINGS = {
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_GRAFANA_URL",
    "PORT",
    "EVALBENCH_ALLOW_INSECURE",
    # Read by the CLI, not by Settings. Checked by its own test below.
    "EVALBENCH_API_URL",
    # Read by torch and tokenizers, not by us. They are in the checklist
    # because they are part of why the image fits in 512 MB.
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "TOKENIZERS_PARALLELISM",
}


def _env_names(text: str) -> set[str]:
    """Every SCREAMING_SNAKE name the guide sets, from `NAME=value`."""
    return set(
        re.findall(
            r"^\s*(?:[-*]\s*)?(?:export\s+)?`?([A-Z][A-Z0-9_]{3,})`?\s*=", text, re.M
        )
    )


class TestTheGuideExists:
    def test_there_is_a_deploy_guide(self):
        assert DEPLOY.exists(), "DEPLOY.md is the one document a deploy needs"

    def test_it_says_what_the_hosted_demo_does_not_have(self):
        """The hosted instance runs jobs in-process: no queue, no worker,
        no Prometheus. Claiming otherwise on a public site is the kind of
        thing an interviewer checks."""
        text = DEPLOY.read_text(encoding="utf-8").lower()
        assert "inline" in text
        assert "queue" in text or "worker" in text


class TestTheEnvironmentChecklist:
    def test_every_variable_named_is_a_real_setting(self):
        named = _env_names(DEPLOY.read_text(encoding="utf-8")) - NOT_SETTINGS
        fields = {name.upper() for name in Settings.model_fields}
        unknown = sorted(named - fields)
        assert not unknown, f"DEPLOY.md sets variables that do not exist: {unknown}"

    def test_the_dangerous_ones_are_named(self):
        """Three settings turn a safe instance into an open one. The
        guide has to mention each by name, or the default wins silently."""
        text = DEPLOY.read_text(encoding="utf-8")
        for name in ("SECRET_KEY", "TRUST_PROXY", "ALLOW_REGISTRATION"):
            assert name in text, f"{name} is not in the deploy checklist"


class TestTheCommandsItPrints:
    def test_the_cli_reads_the_variable_the_guide_exports(self):
        """The guide tells the reader to point the CLI at the deployed
        instance. If that name is ever renamed, this is where it is
        caught — not by someone's export having no effect."""
        cli = (ROOT / "evalbench" / "cli.py").read_text(encoding="utf-8")
        assert "EVALBENCH_API_URL" in cli
        assert "EVALBENCH_API_URL" in DEPLOY.read_text(encoding="utf-8")

    def test_the_health_check_it_suggests_is_a_real_route(self):
        main = (ROOT / "evalbench" / "api" / "main.py").read_text(encoding="utf-8")
        assert '@app.get("/health")' in main
        assert "/health" in DEPLOY.read_text(encoding="utf-8")


class TestTheImageIsPortable:
    def test_the_port_comes_from_the_environment(self):
        """Hugging Face Spaces serves 7860, Render and Railway inject
        $PORT, compose wants 8000. One image, told which."""
        assert "PORT" in DOCKERFILE.read_text(encoding="utf-8")
