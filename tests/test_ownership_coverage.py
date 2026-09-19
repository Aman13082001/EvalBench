"""Every query against user-owned data must be scoped to the caller.

`test_ownership.py` proves specific endpoints behave. This file is the
net underneath it: it reads the API source and fails if *any* handler
touches `db.suites` or `db.test_runs` without an ownership guard nearby.

It exists because of a real bug. `GET /suites/{id}/regression-history`
shipped with a bare ``{"suite_id": suite_id}`` query while its reachable
sibling used ``{**owner_filter(user)}``. Nothing called the orphan, so no
behavioural test covered it and the hardening pass walked past it. A
per-endpoint test could never have caught an endpoint nobody thought
about — only a rule applied to the whole file can.
"""

import ast
import pathlib

import pytest

API_DIR = pathlib.Path(__file__).resolve().parents[1] / "evalbench" / "api"

# Collections holding rows that belong to one user.
OWNED_COLLECTIONS = {"suites", "test_runs"}

# Any of these inside the handler means access was scoped deliberately.
# `get_current_admin` counts: an admin route is *meant* to read across
# users, and depending on it is how that intent is declared. Listing it
# here rather than exempting admin.py by name means a new admin endpoint
# that forgets the dependency still fails this test.
# `mine` is the write-side guard: strictly the caller's own documents,
# admin included, for create-or-update by name.
GUARDS = {"owner_filter", "require_owner", "owns", "get_current_admin", "mine"}

# Handlers with no request user at all. Each needs a reason.
EXEMPT = {
    # Startup: creates indexes and fails runs orphaned by a crash. Runs
    # before any request exists, so there is no caller to scope to.
    ("main.py", "lifespan"),
    # Housekeeping, not a request: fails runs whose executor has died,
    # across every account. Scoping it to a caller would leave other
    # users' runs stuck for ever. It only ever writes `failed` to runs
    # that are already abandoned — see evalbench/reaper.py.
    ("main.py", "reap_abandoned_runs"),
    # Startup migration: counts judged tests on suites stored before the
    # field existed, across every account, once. Reads tests, writes a
    # count; touches nothing a user can see as theirs or not.
    ("main.py", "_backfill_judged_tests"),
    # Startup migration: gives pre-job-model runs (results, no status)
    # the status they earned, across every account, once.
    ("main.py", "_backfill_run_status"),
}


def _handlers():
    """Yield (file, function_name, ast node) for every def in the API."""
    for path in sorted(API_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path.name, node.name, node


def _touches_owned_data(node) -> bool:
    """True if the function queries an owned collection."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Attribute):
            continue
        # matches db.<collection>.find / .find_one / .update_one / ...
        inner = sub.value
        if (
            isinstance(inner, ast.Attribute)
            and inner.attr in OWNED_COLLECTIONS
            and sub.attr.startswith(("find", "update", "delete", "count"))
        ):
            return True
    return False


OWNED_HANDLERS = [
    (f, n, node)
    for f, n, node in _handlers()
    if _touches_owned_data(node) and (f, n) not in EXEMPT
]


def test_the_scan_finds_handlers():
    """Guard the guard: if the AST walk silently matches nothing, this
    whole file would pass vacuously and protect us from nothing."""
    assert len(OWNED_HANDLERS) >= 10, (
        f"only found {len(OWNED_HANDLERS)} handlers touching owned data — "
        "the scan is probably broken, not the code"
    )


@pytest.mark.parametrize(
    "filename,func,node",
    OWNED_HANDLERS,
    ids=[f"{f}::{n}" for f, n, _ in OWNED_HANDLERS],
)
def test_handler_scopes_query_to_the_caller(filename, func, node):
    source = ast.unparse(node)
    assert any(g in source for g in GUARDS), (
        f"{filename}::{func} queries user-owned data with no ownership "
        f"guard. Add owner_filter(user) to the query, or require_owner(...) "
        f"on the fetched document. If it is genuinely meant to read across "
        f"all users, add it to EXEMPT in this file with a reason."
    )
