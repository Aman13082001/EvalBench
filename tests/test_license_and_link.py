"""The repository ships what it claims, and points at what it runs.

Two small things a reader checks in the first ten seconds: is there a
licence, and can I see it working. Both were claimed in prose and
neither was true — MIT was named in `pyproject.toml` and the README's
License section with no LICENSE file to grant it, and the deployed
instance existed with nothing in the repository linking to it.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
LICENSE = ROOT / "LICENSE"
README = ROOT / "README.md"
PYPROJECT = ROOT / "pyproject.toml"


class TestTheLicenceIsShippedNotJustNamed:
    def test_there_is_a_licence_file(self):
        """A bare mention grants nothing: the MIT licence requires its
        own text and the copyright line to travel with the code."""
        assert LICENSE.exists(), "pyproject and README both say MIT; ship it"

    def test_it_is_the_licence_the_metadata_claims(self):
        text = LICENSE.read_text(encoding="utf-8")
        claimed = re.search(r'license\s*=\s*\{\s*text\s*=\s*"([^"]+)"',
                            PYPROJECT.read_text(encoding="utf-8"))
        assert claimed, "pyproject no longer declares a licence"
        assert claimed.group(1).lower() in text.lower()

    def test_it_carries_a_copyright_line_with_a_holder(self):
        text = LICENSE.read_text(encoding="utf-8")
        m = re.search(r"Copyright \(c\) (\d{4})\s+(\S.*)", text)
        assert m, "no copyright line — the permission has no grantor"
        assert len(m.group(2).strip()) > 2

    def test_the_grant_and_the_disclaimer_are_both_there(self):
        """Half an MIT licence is not one: the permission without the
        warranty disclaimer leaves the author exposed."""
        text = LICENSE.read_text(encoding="utf-8").lower()
        assert "permission is hereby granted" in text
        assert "without warranty of any kind" in text


class TestTheReadmePointsAtTheRunningThing:
    def test_it_links_to_the_deployed_instance(self):
        """Someone landing on the repo should be one click from seeing
        it work, not from a screenshot of it working."""
        text = README.read_text(encoding="utf-8")
        assert re.search(r"https://[a-z0-9.-]*vercel\.app", text), (
            "the README does not link to the live instance"
        )
