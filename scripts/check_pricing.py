"""Flag MODEL_PRICING entries whose `as_of` has gone stale.

Run by hand or in CI:  python scripts/check_pricing.py [--max-months N]
Exits non-zero if any entry is older than the threshold (default 9 months).
"""

from __future__ import annotations

import argparse
from datetime import date

from evalbench.pricing import MODEL_PRICING


def months_between(as_of: str, today: date) -> int:
    y, m = (int(x) for x in as_of.split("-"))
    return (today.year - y) * 12 + (today.month - m)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-months", type=int, default=9)
    args = ap.parse_args()

    today = date.today()
    stale = [
        (name, p.as_of, months_between(p.as_of, today))
        for name, p in MODEL_PRICING.items()
        if months_between(p.as_of, today) > args.max_months
    ]

    for name, as_of, age in sorted(stale, key=lambda r: -r[2]):
        print(f"STALE  {name:32s} as_of {as_of}  ({age} months old)")

    if stale:
        print(
            f"\n{len(stale)} of {len(MODEL_PRICING)} pricing entries are "
            f"older than {args.max_months} months — re-verify against the "
            f"providers' pricing pages and bump `as_of`."
        )
        return 1

    print(
        f"OK — all {len(MODEL_PRICING)} pricing entries verified within "
        f"{args.max_months} months."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
