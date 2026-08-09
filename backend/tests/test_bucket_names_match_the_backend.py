"""The bucket names the frontend can send are the ones the backend accepts (FS-488).

`src/api/dashboardAnalytics.ts` declares `BucketName` as a string union and passes it
straight into `?bucket=`. `app/core/time_buckets.py` declares `BUCKET_SECONDS` and
`resolve_bucket` raises on anything not in it:

    if name not in BUCKET_SECONDS:
        raise ValueError(f"unsupported bucket '{name}'; expected one of {sorted(...)}")

So a name in the union and not in the table is a **500 on a dashboard chart**, and a name in
the table and not in the union is a bucket size nobody can select — the same pair of failures
as the ERP connector list (FS-486), with a louder first half.

This is the better-behaved of the two range parameters this codebase has. `kpi`'s `range`
falls back with `_RANGE_DAYS.get(value, 30)`, so every mistake there becomes a thirty-day
answer under whatever label was chosen and nothing anywhere says so. Raising is the correct
choice, and the reason `bucket` needed no fix — only a guard that the two lists stay the same
list.
"""

from __future__ import annotations

import pathlib
import re

from app.core.time_buckets import BUCKET_SECONDS, DEFAULT_BUCKET

REPO = pathlib.Path(__file__).resolve().parents[2]
CLIENT = REPO / "frontend" / "src" / "api" / "dashboardAnalytics.ts"


def _union_members() -> list[str]:
    source = CLIENT.read_text()
    decl = re.search(r"export type BucketName\s*=\s*([^;]+);", source)
    assert decl, (
        "`BucketName` could not be read out of dashboardAnalytics.ts, so the comparison "
        "below would run over an empty list and pass"
    )
    return re.findall(r"'([^']+)'", decl.group(1))


class TestTheReaderIsNotVacuous:
    def test_the_union_parses(self):
        members = _union_members()
        assert len(members) >= 3, f"only {members} parsed from BucketName"
        assert DEFAULT_BUCKET in members, (
            f"the backend's default bucket {DEFAULT_BUCKET!r} is not even in the union the "
            f"frontend can send, which means the reader is wrong or the default is unusable"
        )

    def test_the_backend_table_is_populated(self):
        assert len(BUCKET_SECONDS) >= 3


class TestTheTwoListsAreTheSameList:
    def test_the_frontend_offers_no_bucket_the_backend_rejects(self):
        unsupported = sorted(set(_union_members()) - set(BUCKET_SECONDS))
        assert not unsupported, (
            f"`BucketName` allows {unsupported}, which `resolve_bucket` raises on — a chart "
            f"that asks for one gets a 500, not a different bucket size"
        )

    def test_the_backend_supports_no_bucket_the_frontend_cannot_ask_for(self):
        unreachable = sorted(set(BUCKET_SECONDS) - set(_union_members()))
        assert not unreachable, (
            f"the backend buckets by {unreachable} and no frontend caller can select them, "
            f"so the resolution ships and nobody can reach it"
        )
