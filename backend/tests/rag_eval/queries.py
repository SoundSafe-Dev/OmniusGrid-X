"""
Ground-truth query suites, organized per source document.

The suite runs against a small *corpus* of documents (see corpus.py). Each
document gets its own list of query specs whose ground truth is drawn verbatim
from that document, plus per-query ``gold`` relevant-chunk markers. The public
surface is:

  QUERY_SETS[doc_id]  -> list of specs for one document
  ALL_QUERIES         -> every spec, each stamped with its ``doc_id``
  QUERIES             -> back-compat alias for the SOP-QA-014 set

Each query is a dict with:
  id            stable slug used in the report matrix (unique across all docs)
  doc_id        which corpus document this query is answered from
  label         human summary
  query         the natural-language question sent to /rag/query
  generate      False -> retrieval-only (assert against citation snippets)
                True  -> retrieval + LLM synthesis (assert against the answer)
  concepts      list of {"name", "any": [...]} groups. A group PASSES when any
                of its substrings appears (case-insensitive) in the haystack.
                The query PASSES when EVERY concept group is matched.
  forbid        substrings that must NOT appear (checked against the answer for
                synthesis queries, against snippets for retrieval-only). Used to
                catch the "near-duplicate confusion" failure mode.
  manual        True -> heuristic pass/fail is advisory only; the full answer is
                always printed for a human to eyeball (negative / scope tests,
                where an automated substring check can't fully judge correctness).

Ground truth is drawn verbatim from
  backend/tests/docs/SOP-QA-014_Allergen_Control_Sanitation.md
so the assertions and the corpus can never silently drift apart.
"""

QUERIES = [
    {
        "id": "Q1_atp_threshold",
        "label": "Retrieval precision: ATP verification region ranks in top results",
        "query": "What ATP reading (in RLU) causes a surface to fail post-sanitation verification?",
        "generate": False,
        # Retrieval-only. NOTE: the API returns snippet[:240] (a preview), so the
        # exact "250 RLU" (Section 6.6 item 21) may be truncated out of a preview
        # even when its chunk IS retrieved. So we don't demand the literal number;
        # we assert that a chunk from the §6.6 post-sanitation VERIFICATION region
        # ranks in the top results, detected via markers that sit early in that
        # chunk (heading, step-20/21 wording) or the exact value when it survives.
        # This measures retrieval precision honestly given the preview limit.
        "concepts": [
            {"name": "verification_region", "any": [
                "250",
                "post-sanitation verification",
                "predetermined product contact",
                "at each point",
                "re-swab", "re-swabbing",
                "luminometer",
            ]},
        ],
        "forbid": [],
        "manual": False,
        "note": ("Retrieval-precision check; snippet[:240] preview means the exact "
                 "'250 RLU' can be truncated even when its chunk is retrieved."),
    },
    {
        "id": "Q2_twice_fail_flow",
        "label": "Synthesis: two consecutive ATP failures -> path back to run",
        "query": (
            "A surface fails its ATP swab twice in a row during an allergen "
            "changeover. Walk me through what has to happen before the line can "
            "run again."
        ),
        "generate": True,
        # Multi-hop across §6.6 + §7 + sign-off. In the CSV rendering the
        # corrective-action rows (deviation report / notify PQM) rank just below
        # the default cutoff, so this spans-multiple-sections query needs a
        # deeper retrieval to reach the model (passes on the other 4 formats at
        # default depth).
        "top_n": 8,
        # Multi-hop: Section 6.6 (re-swab/pass <250), Section 7 (re-clean per 6.3;
        # two consecutive failures -> deviation report + notify Plant Quality
        # Manager before a 3rd attempt), and release sign-off (QA Tech signs Line
        # Release Form, Shift Supervisor co-signs).
        # Required = the escalation spine that MUST be right; bonus = the
        # completeness tail (a small model often stops before naming these).
        "concepts": [
            {"name": "reclean", "any": ["re-clean", "reclean", "re-cleaned",
                                        "cleaned again", "section 6.3", "6.3"]},
            {"name": "deviation", "any": ["deviation"]},
            {"name": "escalate_pqm", "any": ["plant quality manager", "quality manager"]},
        ],
        "bonus": [
            {"name": "pass_threshold", "any": ["250", "passing", "pass"]},
            {"name": "release_signoff", "any": ["line release", "co-sign", "cosign",
                                                "shift supervisor", "qa technician"]},
        ],
        "forbid": [],
        "manual": False,
    },
    {
        "id": "Q3_acid_rinse_time",
        "label": "Near-dup numeric: acid rinse contact time (must be 8 min, not 15)",
        "query": "What is the contact time for the acid rinse specifically?",
        "generate": True,
        # Step 10: acid rinse 0.5% w/v for 8 minutes. The detergent step (15 min)
        # sits right above it -> classic retrieval/synthesis confusion trap.
        "concepts": [
            {"name": "eight_min", "any": ["8 minute", "8 min", "eight minute", "8-minute"]},
        ],
        "forbid": ["15 minute", "15 min", "fifteen minute", "15-minute"],
        "manual": False,
    },
    {
        "id": "Q4_signoff_rows",
        "label": "Table-row integrity: line-release signers vs SOP approver",
        "query": "Who signs off on line release, and who approves the SOP itself?",
        "generate": True,
        # Two different tables: Line release = QA Technician signs + Shift
        # Supervisor co-signs (Sec 6.6 #23 / Responsibilities). SOP approver =
        # Plant Quality Manager (header "Approved By" / "Owns this SOP").
        # Core correctness = the two tables are kept DISTINCT: names the SOP
        # approver (PQM) AND at least one line-release signer. Bonus = both
        # signers named. forbid catches the row-scramble where PQM is wrongly
        # pulled into the line-release signing.
        "concepts": [
            {"name": "sop_approver_pqm", "any": ["plant quality manager"]},
            {"name": "line_release_signer", "any": ["qa technician", "shift supervisor"]},
        ],
        "bonus": [
            {"name": "qa_technician", "any": ["qa technician"]},
            {"name": "shift_supervisor", "any": ["shift supervisor"]},
        ],
        "forbid": ["plant quality manager co-sign", "co-signed by the plant quality manager"],
        "manual": False,
    },
    {
        "id": "Q5_cip_definition",
        "label": "Definition vs usage: what does CIP mean?",
        "query": "What does CIP mean?",
        "generate": True,
        # Must pull the Section 3 definition ("Clean-in-Place: Automated
        # circulation ... without disassembly"), not a procedure step that
        # merely mentions CIP.
        # Correct disambiguation = the §3 definition sense, proven by EITHER the
        # expansion ("Clean-in-Place") OR the defining clause ("automated
        # circulation ... without disassembly"). Both mean it pulled the
        # definition, not a procedure step that merely mentions CIP.
        "concepts": [
            {"name": "cip_definition", "any": ["clean-in-place", "clean in place",
                                               "without disassembly",
                                               "enclosed process equipment",
                                               "automated circulation",
                                               "circulation of cleaning"]},
        ],
        "bonus": [
            {"name": "names_expansion", "any": ["clean-in-place", "clean in place"]},
        ],
        "forbid": [],
        "manual": False,
    },
    {
        "id": "Q6_revision_diff",
        "label": "Revision lookup: 3.1 vs 3.2 (two rows, not merged)",
        "query": "What changed in revision 3.1 versus revision 3.2?",
        "generate": True,
        # Rev 3.1: clarified corrective action timeline for failed swab results.
        # Rev 3.2: extended record retention from 2 to 3 years.
        "concepts": [
            {"name": "rev31_corrective", "any": ["corrective action", "swab result",
                                                 "corrective-action"]},
            {"name": "rev32_retention", "any": ["retention", "record retention"]},
            {"name": "rev32_years", "any": ["3 year", "three year", "2 to 3", "two to three"]},
        ],
        "forbid": [],
        "manual": False,
    },
    {
        "id": "Q7_out_of_corpus",
        "label": "Out-of-corpus negative: PM schedule in SOP-ME-002 (must not fabricate)",
        "query": "What is the preventive maintenance schedule in SOP-ME-002?",
        "generate": True,
        # SOP-ME-002 is *referenced* (Scope / Related Documents) but its content
        # is NOT in this corpus. Correct behavior: say it's not covered here.
        # Fabricating a plausible PM cadence is the worst failure for compliance.
        # Correct = defer to SOP-ME-002 / say it's not in this document, WITHOUT
        # inventing a schedule. Either an explicit "not here" OR pointing to
        # SOP-ME-002 as the location counts as safe deferral.
        "concepts": [
            {"name": "defers_or_declines", "any": [
                "sop-me-002", "not in", "does not", "doesn't", "not mentioned",
                "no information", "not covered", "not contain", "not include",
                "not available", "not provided", "not part of", "addressed in",
                "outside the scope", "out of scope", "cannot find", "can't find",
                "unable to", "not found", "separate document", "not specified",
                "not detailed", "provides information",
            ]},
        ],
        # A fabricated PM schedule invents a concrete cadence. If these appear,
        # the model likely hallucinated a schedule -> hard fail. Advisory review
        # stays on (manual=True) because judging fabrication needs a human eye.
        "forbid": [
            "every day", "times per week", "times a week", "once a week",
            "once a month", "daily inspection", "weekly maintenance",
            "monthly maintenance", "quarterly", "annually the",
        ],
        "manual": True,
    },
    {
        "id": "Q8_scope_boundary",
        "label": "Scope boundary: Line 1/2 cleaning (doc is scoped to Line 3/4)",
        "query": "What are the cleaning requirements for Line 1 and Line 2?",
        "generate": True,
        # Doc is scoped to Line 3/4. Correct = decline to give Line 1/2
        # requirements (say they're not in this document / out of scope) rather
        # than misapplying the Line 3/4 parameters. Naming Line 3/4 explicitly is
        # a bonus, not required - a clean "not in this document" is fully safe.
        "concepts": [
            {"name": "declines_out_of_scope", "any": [
                "does not contain", "not contain", "no information", "not in",
                "does not", "doesn't", "not covered", "not include", "out of scope",
                "only applies", "specific to line 3", "scoped to",
                # A "declines" answer often takes the form "no mention of Line 1/2"
                # or "SOP-QA-014 applies to Line 3/4" — recognize both.
                "no mention", "not mention", "does not mention", "doesn't mention",
                "not mentioned", "makes no mention", "applies to line 3",
                "applies to line 4", "applies to \"line 3",
            ]},
        ],
        "bonus": [
            {"name": "names_line34", "any": ["line 3", "line 4", "3 and 4", "3/4"]},
        ],
        "forbid": [],
        "manual": True,
    },
]


# Gold relevant-chunk markers for retrieval metrics (recall@k / MRR). A retrieved
# citation counts as "relevant" if its snippet OR source metadata contains any of
# these. Pure negative tests (correct answer = "not in the corpus") have no gold
# chunk, so they're excluded from retrieval scoring.
GOLD = {
    "Q1_atp_threshold": ["250", "post-sanitation verification",
                         "predetermined product contact", "at each point", "luminometer"],
    "Q2_twice_fail_flow": ["two consecutive failures", "deviation report",
                           "re-cleaned per section 6.3", "corrective action"],
    "Q3_acid_rinse_time": ["acid rinse", "0.5%", "8 minute", "8 min"],
    "Q4_signoff_rows": ["line release form", "co-sign", "owns this sop",
                        "approved by", "plant quality manager"],
    "Q5_cip_definition": ["clean-in-place", "without disassembly",
                          "enclosed process equipment"],
    "Q6_revision_diff": ["record retention", "corrective action timeline",
                         "3.1", "3.2", "revision"],
    "Q7_out_of_corpus": ["sop-me-002"],
    "Q8_scope_boundary": [],  # out-of-corpus negative: no relevant chunk exists
}
for _q in QUERIES:
    _q.setdefault("doc_id", "sop-qa-014")
    _q.setdefault("gold", GOLD.get(_q["id"], []))


# =========================================================================== #
# SOP-WH-021 — Cold-Chain Temperature Control (Distribution Center DC-2)
#
# A second document in a different domain, authored with the SAME trap
# archetypes as SOP-QA-014 so retrieval/synthesis generalization is tested on
# genuinely different content, and so an all-docs-indexed phase can test that
# retrieval cites the RIGHT document (see test_corpus.py). Ground truth is drawn
# verbatim from backend/tests/docs/SOP-WH-021_Cold_Chain_Temperature_Control.md
# (all five formats are generated from one source model — see make_corpus.py).
# =========================================================================== #

# Reused deferral/decline vocabularies for the negative + scope-boundary tests.
_DEFER_ANY = [
    "not in", "does not", "doesn't", "not mentioned", "no mention",
    "does not mention", "doesn't mention", "makes no mention", "no information",
    "not covered", "not contain", "not include", "not available", "not provided",
    "not part of", "addressed in", "outside the scope", "out of scope",
    "cannot find", "can't find", "unable to", "not found", "separate document",
    "not specified", "not detailed", "provides information",
]
# Cadence words that would betray a fabricated schedule (hard fail).
_FABRICATED_CADENCE = [
    "every day", "times per week", "times a week", "once a week", "once a month",
    "daily inspection", "weekly inspection", "weekly maintenance",
    "monthly inspection", "monthly maintenance", "quarterly", "annually the",
]

WH_QUERIES = [
    {
        "id": "W1_preship_pass_temp",
        "label": "Retrieval precision: pre-shipment verification region ranks top",
        "query": ("For a refrigerated shipment, what has to be true of every measured "
                  "case to pass pre-shipment temperature verification?"),
        "generate": False,
        # Retrieval-only. Like Q1, the API returns snippet[:240], so the exact
        # "40 degrees F" can be truncated even when the §6.4 chunk IS retrieved.
        # Anchor on markers unique to the pre-shipment VERIFICATION region so this
        # measures retrieval precision, not preview luck.
        "concepts": [
            {"name": "preship_region", "any": [
                "five cases", "at or below 40", "held and re-evaluated",
                "pre-shipment", "outbound shipment", "cold-chain release record",
            ]},
        ],
        "forbid": [],
        "manual": False,
        "note": ("Retrieval-precision check; snippet[:240] preview can truncate the "
                 "exact '40 degrees F' even when its chunk is retrieved."),
    },
    {
        "id": "W2_twice_fail_flow",
        "label": "Synthesis: two consecutive verification failures -> path to ship",
        "query": ("A refrigerated shipment fails its pre-shipment temperature "
                  "verification twice in a row. Walk me through what has to happen "
                  "before it can ship."),
        "generate": True,
        # Multi-hop: §6.4 (hold + re-evaluate before release), §7 (two consecutive
        # failures -> deviation report + notify Distribution Quality Lead before a
        # 3rd attempt), and §6.4 sign-off (Warehouse QA Technician signs Cold-Chain
        # Release Record, Shift Lead co-signs). Required = the escalation spine;
        # bonus = the completeness tail.
        "concepts": [
            {"name": "hold_disposition", "any": ["hold", "disposition",
                                                 "re-evaluat", "evaluated"]},
            {"name": "deviation", "any": ["deviation"]},
            {"name": "escalate_dql", "any": ["distribution quality lead", "quality lead"]},
        ],
        "bonus": [
            {"name": "pass_threshold", "any": ["40", "passing", "pass"]},
            {"name": "release_signoff", "any": ["cold-chain release", "co-sign",
                                                "cosign", "shift lead", "warehouse qa"]},
        ],
        "forbid": [],
        "manual": False,
    },
    {
        "id": "W3_core_check_interval",
        "label": "Near-dup interval: product core spot-check (4 hours, not 15 min)",
        "query": ("How often is product core temperature spot-checked for product "
                  "staged on the cold dock?"),
        "generate": True,
        # Step 8: product core every 4 hours. Air temperature "every 15 minutes"
        # (step 6) sits right above it -> the near-dup interval confusion trap,
        # mirroring Q3's 8-vs-15-minute trap.
        "concepts": [
            {"name": "four_hours", "any": ["4 hour", "4 hours", "every 4", "four hour"]},
        ],
        "forbid": ["15 minute", "15 minutes", "every 15", "fifteen minute"],
        "manual": False,
    },
    {
        "id": "W4_signoff_rows",
        "label": "Table-row integrity: cold-chain release signers vs SOP approver",
        "query": ("Who signs off on the Cold-Chain Release Record, and who approves "
                  "the SOP itself?"),
        "generate": True,
        # Two-part question spanning two tables: the signers sit in §6.4 while the
        # approver ("Distribution Quality Lead — Owns this SOP") is a Responsibilities
        # row that ranks ~6th, below the default retrieval cutoff. Deepen retrieval
        # so both halves reach the model (Q4, its QA-014 analog, needs no bump —
        # its approver ranks higher).
        "top_n": 8,
        # Two different tables: Cold-Chain Release = Warehouse QA Technician signs +
        # Shift Lead co-signs (§6.4 #16 / Responsibilities). SOP approver =
        # Distribution Quality Lead (header "Approved By" / "Owns this SOP"). forbid
        # catches the row-scramble where the SOP approver is pulled into the signing.
        "concepts": [
            {"name": "sop_approver_dql", "any": ["distribution quality lead"]},
            {"name": "release_signer", "any": ["warehouse qa technician", "shift lead"]},
        ],
        "bonus": [
            {"name": "qa_technician", "any": ["warehouse qa technician"]},
            {"name": "shift_lead", "any": ["shift lead"]},
        ],
        "forbid": ["distribution quality lead co-sign",
                   "co-signed by the distribution quality lead"],
        "manual": False,
    },
    {
        "id": "W5_tor_definition",
        "label": "Definition vs usage: what does TOR mean?",
        "query": "What does TOR mean?",
        "generate": True,
        # Must pull the §3 definition ("Time-Out-of-Refrigeration: cumulative time a
        # refrigerated product spends above 40 degrees F outside controlled cold
        # storage"), not step 9 which merely uses the term.
        "concepts": [
            {"name": "tor_definition", "any": [
                "time-out-of-refrigeration", "time out of refrigeration",
                "cumulative time", "above 40", "outside controlled cold storage",
            ]},
        ],
        "bonus": [
            {"name": "names_expansion", "any": ["time-out-of-refrigeration",
                                                "time out of refrigeration"]},
        ],
        "forbid": [],
        "manual": False,
    },
    {
        "id": "W6_revision_diff",
        "label": "Revision lookup: 2.1 vs 2.2 (two rows, not merged)",
        "query": "What changed in revision 2.1 versus revision 2.2?",
        "generate": True,
        # Rev 2.1: added continuous data-logger monitoring at 15-minute intervals.
        # Rev 2.2: lowered the refrigerated receiving rejection threshold 47 -> 45.
        # The "2.1 vs 2.2" phrasing also disambiguates this doc from SOP-QA-014
        # (whose revisions are 3.1/3.2) when both are indexed together.
        "concepts": [
            {"name": "rev21_logger", "any": ["data logger", "data-logger",
                                             "15-minute", "15 minute", "logger"]},
            {"name": "rev22_threshold", "any": ["rejection threshold", "47 to 45",
                                                "45 degrees", "lowered"]},
        ],
        "forbid": [],
        "manual": False,
    },
    {
        "id": "W7_out_of_corpus",
        "label": "Out-of-corpus negative: pest-control schedule in SOP-SN-005",
        "query": "What is the pest control inspection schedule in SOP-SN-005?",
        "generate": True,
        # SOP-SN-005 is *referenced* (Related Documents) but its content is NOT in
        # this corpus. Correct: defer / say it's not covered here. Fabricating an
        # inspection cadence is the worst failure for compliance.
        "concepts": [
            {"name": "defers_or_declines", "any": ["sop-sn-005"] + _DEFER_ANY},
        ],
        "forbid": _FABRICATED_CADENCE,
        "manual": True,
    },
    {
        "id": "W8_scope_boundary",
        "label": "Scope boundary: ambient dry-goods storage (doc is refrig/frozen)",
        "query": "What are the storage temperature requirements for ambient dry goods?",
        "generate": True,
        # Doc is scoped to refrigerated/frozen storage; ambient dry goods are in
        # SOP-WH-004 (out of corpus). Correct = decline / point out of scope rather
        # than misapplying the cold-storage parameters. Naming the refrigerated/
        # frozen scope is a bonus, not required.
        "concepts": [
            {"name": "declines_out_of_scope", "any": [
                "sop-wh-004", "does not contain", "not contain", "no information",
                "not in", "does not", "doesn't", "not covered", "not include",
                "out of scope", "only applies", "only covers", "scoped to",
                "refrigerated and frozen", "no mention", "does not mention",
                "doesn't mention", "not mentioned", "makes no mention",
            ]},
        ],
        "bonus": [
            {"name": "names_refrigerated", "any": ["refrigerated", "frozen",
                                                   "cold room", "freezer f1"]},
        ],
        "forbid": [],
        "manual": True,
    },
]

WH_GOLD = {
    "W1_preship_pass_temp": ["pre-shipment", "five cases", "cold-chain release",
                             "warehouse qa technician"],
    "W2_twice_fail_flow": ["two consecutive failed", "deviation report",
                           "distribution quality lead", "on hold"],
    "W3_core_check_interval": ["4 hour", "spot-check", "cold dock", "product core"],
    "W4_signoff_rows": ["cold-chain release record", "co-sign", "owns this sop",
                        "distribution quality lead"],
    # "uninterrupted series" is the opening of the Definitions block (where TOR is
    # defined) and occurs exactly once — it lets the metric see that the correct
    # chunk was retrieved even in txt, whose few large chunks push the later
    # markers past the API's 240-char citation preview.
    "W5_tor_definition": ["time-out-of-refrigeration", "above 40", "cumulative time",
                          "uninterrupted series"],
    "W6_revision_diff": ["rejection threshold", "data logger", "2.1", "2.2"],
    # Out-of-corpus negatives have no relevant chunk to retrieve, so they carry no
    # gold and are excluded from recall (matching W8). Their real gate is the
    # no-fabrication content test, not retrieval recall of the absent SOP's name.
    "W7_out_of_corpus": [],
    "W8_scope_boundary": [],
}
for _q in WH_QUERIES:
    _q["doc_id"] = "sop-wh-021"
    _q.setdefault("gold", WH_GOLD.get(_q["id"], []))


# --------------------------------------------------------------------------- #
# Public per-document + flat views
# --------------------------------------------------------------------------- #
QUERY_SETS = {
    "sop-qa-014": QUERIES,
    "sop-wh-021": WH_QUERIES,
}
ALL_QUERIES = [q for specs in QUERY_SETS.values() for q in specs]

