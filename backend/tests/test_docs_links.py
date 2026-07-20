"""Guard: relative links in docs/ must resolve.

docs/runbooks/README.md — the page an operator opens first during an incident —
carried 11 broken relative links: every `dr-*.md` pointed at `../` when those
runbooks live in `docs/deployment/`, and every helper-script link used `../../../`
from a directory two levels deep. Following any of them mid-incident produced a
404.

Only relative links are checked; external URLs and anchors are out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs"

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _relative_links() -> list[tuple[Path, str]]:
    links: list[tuple[Path, str]] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        for target in MARKDOWN_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            links.append((path, target))
    return links


def test_relative_doc_links_resolve():
    broken = []
    for source, target in _relative_links():
        # Strip any anchor; we verify the file exists, not the heading.
        resolved = (source.parent / target.split("#")[0]).resolve()
        if not resolved.exists():
            broken.append(
                f"{source.relative_to(REPO_ROOT)} -> {target}"
            )

    assert not broken, "broken relative links in docs/:\n  " + "\n  ".join(broken)
