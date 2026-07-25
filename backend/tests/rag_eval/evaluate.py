"""
Assertion + retrieval-metric engine for the RAG suite.

Two independent things live here:

  * evaluate(spec, resp) -> (passed, detail): concept/forbid grading of a query
    response (shared by the pytest content tests and the matrix runner). Bonus
    concepts are reported but never gate the verdict.

  * retrieval metrics (rank_of_gold / recall_at_k / mrr): a model-agnostic score
    of whether the *relevant* chunk was retrieved, using per-query ``gold``
    markers. Matching is done against each citation's snippet AND its ``source``
    metadata (heading / section / page / row), so a structured format's heading
    counts even when the 240-char snippet preview truncates the key fact.
"""

import json
from typing import Any, Dict, List, Optional, Tuple


# Cues that a forbidden value is being explicitly CONTRASTED or negated rather
# than asserted as the answer — e.g. "8 minutes, NOT 15 minutes", "UNLIKE the
# 15-minute detergent step". When one of these immediately precedes a forbidden
# substring, that occurrence is a disambiguation, not the near-duplicate
# confusion the `forbid` list exists to catch. A bare, unqualified occurrence is
# still a hard violation (e.g. "the acid rinse is 15 minutes").
_CONTRAST_CUES = (
    "not ", "n't ", "n't,", "rather than ", "instead of ", "unlike ",
    "as opposed to ", "opposed to ", "but not ", "never ", "other than ",
    "different from ", "distinct from ", "as against ", "whereas ",
    "versus ", " vs ", "vs. ", "compared to ", "compared with ", "as compared",
    "not to be confused with ", "which is not", "and not ", "is not ",
)
_CONTRAST_WINDOW = 40  # chars before a forbidden hit to scan for a cue


def _forbidden_violations(hay: str, forbid: List[str]) -> List[str]:
    """Forbidden substrings that appear ASSERTED (not in an explicit contrast).

    A forbidden term counts as a violation if *any* of its occurrences is not
    immediately preceded by a contrast/negation cue. This stops a correct answer
    that disambiguates against the near-duplicate ("8 min, not 15 min") from
    being failed, while a bare wrong assertion still fails.
    """
    violations: List[str] = []
    for f in forbid:
        fl = f.lower()
        idx = hay.find(fl)
        while idx != -1:
            before = hay[max(0, idx - _CONTRAST_WINDOW):idx]
            if not any(cue in before for cue in _CONTRAST_CUES):
                violations.append(f)  # a bare, asserted occurrence -> violation
                break
            idx = hay.find(fl, idx + 1)
    return violations


def _citation_text(cit: Dict[str, Any]) -> str:
    parts = [cit.get("snippet", "") or ""]
    src = cit.get("source", {})
    if isinstance(src, dict):
        parts.append(" ".join(str(v) for v in src.values()))
    return " ".join(parts).lower()


def haystack(resp: Dict[str, Any], generate: bool) -> Tuple[str, str]:
    """(assert_text, forbid_text). For synthesis, assert against the answer; for
    retrieval-only, against citation snippet+source. forbid checks the answer for
    synthesis (a wrong *stated* fact) and the citations otherwise."""
    retrieval_text = " \n ".join(_citation_text(c) for c in resp.get("citations", []))
    if generate and resp.get("answer"):
        return resp["answer"], retrieval_text
    return retrieval_text, retrieval_text


def evaluate(spec: Dict[str, Any], resp: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    answer_text, retrieval_text = haystack(resp, spec["generate"])
    hay = answer_text.lower()
    forbid_hay = (answer_text if spec["generate"] else retrieval_text).lower()

    def match(groups):
        got, miss = [], []
        for grp in groups:
            hit = next((s for s in grp["any"] if s.lower() in hay), None)
            (got if hit else miss).append(grp["name"])
        return got, miss

    matched, missing = match(spec["concepts"])
    bonus_matched, bonus_missing = match(spec.get("bonus", []))
    forbidden_hits = _forbidden_violations(forbid_hay, spec.get("forbid", []))

    passed = not missing and not forbidden_hits
    detail = {
        "matched": matched,
        "missing": missing,
        "bonus_matched": bonus_matched,
        "bonus_missing": bonus_missing,
        "forbidden_hits": forbidden_hits,
        "num_citations": len(resp.get("citations", [])),
        "top_score": round(resp.get("citations", [{}])[0].get("score", 0.0), 3)
        if resp.get("citations") else None,
        "generated": resp.get("generated"),
        "used_context": resp.get("used_context"),
        "answer": resp.get("answer"),
        "citations": [
            {
                "filename": ct.get("filename"),
                "source": ct.get("source"),
                "score": round(ct.get("score", 0.0), 3),
                "snippet": (ct.get("snippet") or "")[:220],
            }
            for ct in resp.get("citations", [])[:4]
        ],
    }
    return passed, detail


# --------------------------------------------------------------------------- #
# Retrieval metrics (model-agnostic)
# --------------------------------------------------------------------------- #
def rank_of_gold(resp: Dict[str, Any], gold: List[str]) -> Optional[int]:
    """1-based rank of the first citation whose snippet+source contains any gold
    marker, or None if no retrieved citation is relevant."""
    if not gold:
        return None
    lowered = [g.lower() for g in gold]
    for i, cit in enumerate(resp.get("citations", []), start=1):
        text = _citation_text(cit)
        if any(g in text for g in lowered):
            return i
    return None


def recall_at_k(resp: Dict[str, Any], gold: List[str], k: int) -> float:
    rank = rank_of_gold(resp, gold)
    return 1.0 if (rank is not None and rank <= k) else 0.0


def mrr(rank: Optional[int]) -> float:
    return 1.0 / rank if rank else 0.0
