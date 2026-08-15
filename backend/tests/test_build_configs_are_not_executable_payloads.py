"""A build config must not be able to run a subprocess or reach the network (FS-730).

WRITTEN AFTER A REAL COMPROMISE, 2026-08-15. Every branch on `origin` — all seventeen — was
force-pushed to one commit that changed exactly two files:

  * `.gitignore`, to hide `temp_auto_push.bat`, `temp_interactive_push.bat` and
    `branch_structure.json` — the attacker's own tooling, kept out of `git status`;
  * `frontend/postcss.config.js`, from **80 bytes to 31 KB**.

The payload added `createRequire(import.meta.url)` — the shim an ESM file needs before it can
`require()` Node builtins — and then an obfuscated blob referencing `child_process`,
`eth_blockNumber` / `eth_getBlockByNumber` / `eth_getTransaction*` against public Ethereum RPC
hosts, and `POST` to `:443/0x/...`. That combination is a dropper whose command-and-control
address is read FROM THE BLOCKCHAIN, so there is no domain to take down.

WHY THIS FILE, AND WHY THAT FILE. `postcss.config.js` is not application code that a reviewer
reads — it is four lines that nobody has looked at since the project began, and **Node
executes it on every `npm run dev`, `npm run build`, and vitest run**. A build config is the
ideal host: always executed, never read, and excluded from the sweeps that cover `src/`.

WHAT THIS ASSERTS. Not "the file has not changed" — a hash pin would fail on every legitimate
tailwind tweak and be silenced within a month. It asserts the two properties a build config
has no reason to violate: it must not be able to spawn a process or open a socket, and it must
stay small enough for a human to read in full. A config that needs `child_process` is a config
that needs a conversation.

This cannot detect a clever payload that avoids every listed primitive. It detects THIS class
— arbitrary code hidden in a file nobody reads — cheaply and on every run, which is what was
missing.
"""

from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"

#: Config files Node loads and EXECUTES as part of a build. Each is small by nature.
BUILD_CONFIGS = [
    "postcss.config.js",
    "tailwind.config.js",
    "vite.config.ts",
    "vitest.config.ts",
    "playwright.config.ts",
    "eslint.config.js",
]

#: Primitives that let a build config reach outside the build. `createRequire` earns its
#: place from the incident: in an ESM config it exists for exactly one reason, which is to
#: get at CommonJS builtins the module system would otherwise deny.
FORBIDDEN = (
    "child_process",
    "createRequire",
    "eval(",
    "Function(",
    "atob(",
    "fromCharCode",
    "XMLHttpRequest",
    "globalThis.fetch",
    "require('http",
    'require("http',
    "net.Socket",
    "dns.",
)

#: MEASURED, not guessed. The first draft of this file set 8 KB and asserted "this repo's
#: largest is well under it" — and its own run refused `vitest.config.ts`, which is 10,446
#: bytes of coverage thresholds and the reasoning behind each. Sizes today:
#:
#:     10,446  vitest.config.ts        1,628  tailwind.config.js
#:      1,689  vite.config.ts          1,386  playwright.config.ts
#:                                        80  postcss.config.js
#:
#: 16 KB sits above the real maximum with room for that file to grow, and well below the
#: 31,473 bytes the payload took `postcss.config.js` to. A limit chosen from a belief about
#: the tree rather than a reading of it is a limit that fails on the first honest change and
#: gets raised in irritation — which is how a guard stops meaning anything.
MAX_BYTES = 16384


def _present() -> list[pathlib.Path]:
    return [FRONTEND / name for name in BUILD_CONFIGS if (FRONTEND / name).exists()]


class TestTheSweepIsNotVacuous:
    def test_the_configs_are_found(self):
        """If the frontend moves or is renamed, this file must fail rather than pass over an
        empty list — the shape every sweep in this repository has been bitten by."""
        found = _present()
        assert len(found) >= 3, (
            f"only {len(found)} build configs found under {FRONTEND}; expected at least "
            f"postcss, tailwind and vite"
        )

    def test_the_detector_would_catch_the_real_payload(self):
        """The exact opening of the commit that was pushed to all seventeen branches. If a
        refactor ever softens `FORBIDDEN`, this fails before the real files do."""
        sample = (
            "import { createRequire } from 'module';\n"
            "const require = createRequire(import.meta.url);\n"
            "export default { plugins: {} };\n"
            'global.i="A8-2330";const _0xb40cd9=_0x4963;'
        )
        assert any(marker in sample for marker in FORBIDDEN), (
            "the forbidden list no longer matches the payload this file was written for"
        )


@pytest.mark.parametrize("path", _present(), ids=lambda p: p.name)
class TestABuildConfigStaysAConfig:
    def test_it_cannot_reach_outside_the_build(self, path: pathlib.Path):
        source = path.read_text()
        found = sorted({marker for marker in FORBIDDEN if marker in source})
        assert not found, (
            f"{path.name} contains {found}. A build config is executed by Node on every "
            f"`npm run dev`, `npm run build` and vitest run, and nobody reads it — which is "
            f"why a compromise put a blockchain-C2 dropper in `postcss.config.js` on "
            f"2026-08-15. If a build genuinely needs one of these, it needs a conversation "
            f"first."
        )

    def test_it_stays_small_enough_to_read(self, path: pathlib.Path):
        size = path.stat().st_size
        assert size <= MAX_BYTES, (
            f"{path.name} is {size:,} bytes (limit {MAX_BYTES:,}). The payload took "
            f"postcss.config.js from 80 bytes to 31,473. A build config that cannot be read "
            f"in one sitting is a place to hide things."
        )
