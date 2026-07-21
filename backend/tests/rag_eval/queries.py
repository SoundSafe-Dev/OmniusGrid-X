"""
Ground-truth query suite for SOP-QA-014 (Allergen Control & Sanitation).

Each query is a dict with:
  id            stable slug used in the report matrix
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
    _q.setdefault("gold", GOLD.get(_q["id"], []))

