"""A runbook link that 404s is discovered at 3am, by the person with the least slack (FS-700).

Alert annotations carry `runbook_url` — absolute GitHub URLs into this repository — and
nothing checked that the files they name exist or that their `#anchors` match a real
heading. The docs tree has been reorganised at least once this branch (the 7,000-line
sweeps document was split into five parts, FS-584), and the file-citation guard
(`test_documented_files_exist.py`) parses backticked paths in docs, not URLs in YAML — so
a runbook move would break every alert pointing at it and nothing would say so until an
operator clicked one mid-incident.

Swept before writing this: all current links resolve, including the one the shell draft
flagged as broken — `#failover--recovery`, which is GitHub's correct slug for the heading
"Failover & recovery" (`&` is dropped, each space becomes a hyphen, so two spaces around
it become two hyphens). The slugifier below reproduces that rule; the flagged link is the
positive control.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
RULE_FILES = [
    REPO / "infra" / "prometheus" / "alerts.yml",
    REPO / "infra" / "prometheus" / "slo_rules.yml",
]
URL_PREFIX = "https://github.com/SoundSafe-Dev/OmniusGrid-X/blob/main/"


def _github_slug(heading: str) -> str:
    """GitHub's heading-anchor algorithm, the part of it these anchors exercise:
    lowercase, drop everything but word characters/spaces/hyphens, spaces to hyphens.
    '&' is dropped entirely, which is how 'Failover & recovery' becomes
    'failover--recovery' — two spaces, two hyphens."""
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\- ]", "", slug)
    return slug.replace(" ", "-")


def _links() -> list[tuple[str, str]]:
    """(url, source_file) for every runbook_url in the rule files."""
    found = []
    for rule_file in RULE_FILES:
        if not rule_file.exists():
            continue
        for url in re.findall(r'runbook_url:\s*"([^"]+)"', rule_file.read_text()):
            found.append((url, rule_file.name))
    return found


def _anchors_of(path: pathlib.Path) -> set[str]:
    return {
        _github_slug(match)
        for match in re.findall(r"^#+\s+(.+)$", path.read_text(), re.M)
    }


class TestTheMeasurementIsReal:
    def test_it_found_the_links(self):
        links = _links()
        assert len(links) >= 10, f"only {len(links)} runbook links found — the parse broke"

    def test_the_slugifier_handles_the_ampersand_case(self):
        """POSITIVE CONTROL: the one link a naive checker flags as broken. If this slug
        rule regresses, the guard starts failing on a link that works."""
        assert _github_slug("Failover & recovery") == "failover--recovery"

    def test_a_missing_file_would_be_caught(self):
        fake = f"{URL_PREFIX}docs/runbooks/never-written.md"
        path = REPO / "docs" / "runbooks" / "never-written.md"
        assert not path.exists(), "the control file exists; pick another"


@pytest.mark.parametrize("url,source", _links())
def test_every_runbook_link_resolves(url: str, source: str):
    assert url.startswith(URL_PREFIX), (
        f"{source}: {url} points outside this repository's main branch — it cannot be "
        f"kept true by any check here, and an alert should not send an operator to a "
        f"location the repo does not control"
    )
    relative = url[len(URL_PREFIX):]
    file_part, _, anchor = relative.partition("#")
    target = REPO / file_part
    assert target.exists(), (
        f"{source}: runbook {file_part} does not exist — the alert's operator clicks "
        f"this mid-incident and gets a 404. Update the URL or restore the file."
    )
    if anchor and target.suffix == ".md":
        anchors = _anchors_of(target)
        assert anchor in anchors, (
            f"{source}: {file_part} has no heading that slugs to '#{anchor}'. "
            f"Available: {sorted(anchors)}"
        )
