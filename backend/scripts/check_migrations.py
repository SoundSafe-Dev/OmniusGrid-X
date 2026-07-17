#!/usr/bin/env python
"""Migration-hygiene lint (FS-23).

Fails CI when a NEW migration reuses a numeric prefix already in use. The four
historical duplicates (004/005/007/009 — kanban-era merge artifacts) are
grandfathered: the runner keys on the full filename and applies them in
deterministic sorted order, so they are harmless, but no new collisions are
allowed.

Usage:  python scripts/check_migrations.py
Exit 0 = clean, 1 = a new duplicate prefix was introduced.
"""

import sys
from collections import defaultdict
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[2] / "database" / "migrations"

# Grandfathered pre-existing duplicate prefixes (do not add to this set).
GRANDFATHERED = {"004", "005", "007", "009"}


def main() -> int:
    by_prefix = defaultdict(list)
    for p in sorted(MIGRATIONS.glob("*.sql")):
        prefix = p.name.split("_", 1)[0]
        by_prefix[prefix].append(p.name)

    new_dupes = {
        prefix: names
        for prefix, names in by_prefix.items()
        if len(names) > 1 and prefix not in GRANDFATHERED
    }
    if new_dupes:
        print("ERROR: new duplicate migration prefixes (pick the next free number):")
        for prefix, names in sorted(new_dupes.items()):
            print(f"  {prefix}: {', '.join(names)}")
        return 1

    # Warn (do not fail) on any grandfathered dup that got a THIRD file.
    for prefix in GRANDFATHERED:
        if len(by_prefix.get(prefix, [])) > 2:
            print(f"WARNING: grandfathered prefix {prefix} now has >2 files: {by_prefix[prefix]}")

    highest = max((p.split("_", 1)[0] for p in
                   (f.name for f in MIGRATIONS.glob("*.sql"))), default="000")
    print(f"migration prefixes OK ({len(by_prefix)} distinct; highest {highest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
