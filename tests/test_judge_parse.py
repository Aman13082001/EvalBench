"""The judge's worst verdict must not parse as its best.

Every judge prompt asks for `{"score": <1-5>}`. The parser then treated
any score <= 1.0 as "already a fraction" and returned it as-is — so a
score of 1, the lowest a judge can give, came back as 1.0, the highest.
A rubric check on an answer the judge called "violates the rubric"
passed with a perfect score. Found by scoring a hand-written answer that
deliberately did the wrong thing.

Only a *non-integer* strictly between 0 and 1 is a fraction a model
returned despite instructions. An integer is on the 1-5 scale it was
asked for.
"""

import pytest

from evalbench.core.evaluators.judge import parse_judge_output


@pytest.mark.parametrize("raw,expected", [
    ('{"score": 1, "reason": "violates the rubric"}', 0.2),   # the bug
    ('{"score": 2, "reason": "weak"}', 0.4),
    ('{"score": 3, "reason": "ok"}', 0.6),
    ('{"score": 5, "reason": "perfect"}', 1.0),
    ('{"score": 1.0, "reason": "lowest, as a float"}', 0.2),
    ('{"score": 0, "reason": "disobeyed the scale"}', 0.2),   # clamped to 1
    ('{"score": 0.8, "reason": "returned a fraction"}', 0.8),  # tolerated
    ('```json\n{"score": 1, "reason": "fenced"}\n```', 0.2),
    ("SCORE: 1\nREASON: plain text", 0.2),
])
def test_scores_map_onto_the_scale_they_were_asked_for(raw, expected):
    score, _ = parse_judge_output(raw)
    assert score == pytest.approx(expected)


def test_the_reason_survives():
    _, reason = parse_judge_output('{"score": 1, "reason": "violates the rubric"}')
    assert reason == "violates the rubric"


def test_a_one_fails_a_rubric_at_the_default_cutoff():
    """The whole point: the lowest verdict must fail the check."""
    score, _ = parse_judge_output('{"score": 1, "reason": "no"}')
    assert score < 0.6
