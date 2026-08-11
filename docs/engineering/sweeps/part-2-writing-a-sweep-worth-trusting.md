# Part 2 — writing a sweep that is worth trusting

The method itself: the canonical numbered rules list, and the open observations that were not yet tickets. **Rules 1–21 exist only here**; from rule 22 they also carry a section of their own, in the parts that follow.

*One part of [Defect-class sweeps](../defect-class-sweeps.md), which carries the index of every class and links to the other parts.*

---

## Writing a sweep that is worth trusting

Both false starts above came from the same mistake — trusting the scan instead of testing
one of its findings. The habit that catches it:

1. **Verify one hit empirically before believing the count.** A scan that reports 8
   defects and cannot demonstrate one is a broken scan.
2. **Test the detector first.** If the helper deciding every assertion is wrong, the
   result is meaningless in one direction or the other.
3. **Guard against vacuity.** Assert the sweep discovers something — a rename or a moved
   module otherwise makes it pass while checking nothing.
4. **Mutation-test the guard.** Reintroduce the defect; the test must fail. A mutation
   that lands on the wrong line proves nothing, so check the mutation applied where you
   meant.
5. **Record a negative result.** It is the only thing that stops the next person redoing
   the work.
6. **Ask the system, not the model of the system.** A guard that reads ORM metadata is
   reporting what the declaration claims. This one flagged 158 fields because it trusted
   `column.server_default`, while the database — the thing that actually decides whether
   an INSERT can write NULL — had defaulted 109 of them. Where a real instance is
   reachable, read it.
7. **Distrust a clean result from a detector with exclusions.** Every exclusion is a
   claim about what cannot happen, and class 1's two — "a Python-side default makes a
   column safe" and "a response model lives in its router's module" — were both false.
   A sweep that finds nothing should be read as *"nothing, within these exclusions"*, and
   the exclusions are the part to attack.
8. **Measure the object the code operates on, not one that contains it.** A flaky
   assertion in `test_signed_report_downloads` was "ruled out by measurement" — the
   measurement decoded the whole 480-character JWT rather than its 43-character signature
   segment, compared garbage to garbage, and reported 0/200 collisions. Measuring the
   segment gives 18/400. An HS256 signature is 32 bytes in 43 base64url characters, so the
   final character carries two unused bits and four characters decode identically; the
   test's `token[:-1] + "a"` left the signature valid 4.5% of the time. The form of the
   check was rigorous and it was pointed at the wrong thing, which is indistinguishable
   from rigour until someone re-derives it.
9. **A guard you cannot make precise is worse than a recorded result.** Six false
   positives train the reader to skip the output, and the next real finding goes with it.
   If the mapping the detector needs does not exist, run the sweep, write down what it
   found, and say why it is not enforced — see class 14.
10. **Mutate by reverting, not by reconstructing.** A hand-written "undo" of the
   websocket fix caught nothing, because the reconstruction was not the original — a
   later check still refused the connection and the test passed for the wrong reason.
   Restoring the actual prior file failed exactly the right assertions. If the old code
   is still in git, use it.
11. **Fix forward, not down.** When a corrected sweep surfaces a pile of pre-existing offenders,
   weakening 158 contracts to make the guard pass is the wrong direction. Record a
   shrink-only baseline that fails on a new offender AND on a stale entry, and fix the
   cause — here, server defaults in the database.
12. **A detector's skip count must account for everything it did not check.** The
   query-parameter guard matched two shapes and counted only one of them as skipped;
   anything matching neither fell out of both branches and was invisible. It printed "37
   checked, 1 skipped" while nine calls — holding two live defects — were in the gap. The
   rule is structural, not about regexes: the recogniser and the counter must partition
   the input between them, so that what the sweep cannot read is *reported as unread*
   rather than dropped. A coverage number the guard cannot substantiate is worse than no
   number, because the whole point of a guard is to be believed.
13. **Before flagging a mismatch, check what sits between the two sides.** The same sweep
   was ready to report `historian.query` sending `assetId` to an endpoint declaring
   `asset_id`. An axios interceptor converts request params to snake_case for registered
   URL prefixes, so the code was correct and the finding would have been fabricated — the
   two ends only look mismatched if you ignore the seam in the middle. Comparing endpoints
   of a pipeline means reading the transforms along it.
14. **A substring match on source is satisfied by prose.** The qualifier sweep considered
   `simulated` "read by the frontend" because an unrelated comment said *"simulated GeoTab
   data"* — a sentence about a different feature standing in for code nobody had written.
   Strip comments before matching identifiers, and pin the strip with a test, or the
   result depends on what someone happened to write in English.
15. **Never let a detector's input include its own subject.** The invalidation sweep
   harvested query keys from every `queryKey:` in the tree, including the ones inside the
   `invalidateQueries` calls it was auditing — so each call registered its own key as a
   valid target and vouched for itself. All 18 matched, the sweep reported zero, and a
   dead invalidation sat in the command panel. The failure mode is the dangerous one: it
   comes back clean. Ask what the detector reads, and whether the thing under test is
   inside it.
16. **Read the log noise from your own test runs.** `get_historical_oee` had never once
   returned a row — every column reference was a Python string, and `str >= datetime`
   raised before the query compiled. No sweep found it and no test covered it. It
   surfaced as `health_index_oee_unavailable` warnings scrolling past during an unrelated
   real-DB run, on a service `main.py` starts, which had been emitting them on every
   asset on every pass for as long as it had existed. A warning nobody reads is not a
   signal; it is a place for a defect to live.
17. **Act on the blind spots your guards have already written down.** The tenant-session
   guard's own docstring said "a static guard keyed on one idiom under-counts a file that
   uses two", naming `AsyncSessionLocal()` as the idiom it could not see. That sentence
   was committed and the sweep was never extended. Five live defects were in the gap,
   three of them 404ing on the caller's own asset. A known limitation written into a
   comment is a finding waiting to be re-found; either close it or record it where it
   will be read as debt.
18. **A guard that has already been wrong once is the most likely place to be wrong
   again.** The query-parameter sweep was reopened twice. The first fix taught it to
   resolve variables; the second found that six calls had never matched its call pattern
   at all, because a type argument containing `{` or `;` broke the regex — so they were
   neither checked nor counted, the same failure the first fix was meant to close, one
   layer down. Both times it was reporting full coverage. When a detector turns out to
   have a gap, re-derive its *entry point*, not just the part that failed.
19. **An exemption must not be keyed on something the check itself matches.** A filename
   was allowlisted so one sentence could say "this does not exist" — and that allowlist
   then excused the same name appearing as a factual bullet three paragraphs above, which
   is precisely what it existed to catch. The mutation run passed and looked like proof.
   Scope the exemption to the context, or write the citation so the pattern never sees
   it; an exemption keyed on a bare name is a hole with a comment attached.
20. **Verifying a write through a privileged path proves the write, not the read.** The
   audit tests counted rows with a superuser connection, which bypasses RLS — so they
   showed the INSERT was accepted and said nothing about whether the entry was ever
   visible to the tenant whose trail it belongs to. Under row-level security those are
   different questions, and the one that matters is usually the second. Assert the
   property through the same path the user takes; use the privileged connection to set up
   and to explain a failure, not to conclude one.
21. **Asserting that something is NOT there is satisfied by every reason it might not
   be.** `expect(queryByText('TR-1001')).not.toBeInTheDocument()` passes when the yard is
   empty, when the request failed, when the component crashed, and when the selector is
   simply wrong. Three live defects this week hid behind exactly that shape, in tests
   written specifically to catch them. Assert what the state DOES say — the empty-state
   text, the alert role, the specific message — and pair it with the opposite case, so
   the two branches have to differ. A negative assertion is a control, never a
   conclusion.

   *And twice more while writing the analytics tests.* A negative assertion about a
   chart passed against the defect because **Recharts draws nothing under jsdom** — it
   measures a zero-size container — so "no bar at zero" was true of every possible input.
   Stubbing the chart to expose its `data` prop made the assertion about what the page
   decided to plot. Then the corrected version STILL passed, because it ran before the
   component left its loading branch: no chart existed, so "no availability series" was
   true because nothing had rendered at all. Waiting for the chart to exist first is what
   finally made it fail against the old code, with the exact series it would have drawn.

   *Applied backwards over the existing suite:* 12 tests assert nothing but absences.
   Nine are correct — the property genuinely is an absence (`sends no tenant
   identifier`, `says nothing about truncation when the list is complete`) and each is
   paired with a positive control. **Three were written the same day this rule was, and
   were wrong:** two claimed to show a loading skeleton and an error state while
   asserting only that the data was missing, and one titled *"says so when verification
   itself fails"* checked only that the success text was absent — which was equally true
   before the button was ever pressed, and would have passed against a verifier that did
   nothing at all. All three now assert what the state SAYS.

   The detector needed correcting first, in the usual direction: matching
   `expect\([^)]*\)` cannot see `expect(screen.getByText('x'))`, whose argument
   contains parentheses, so the first run reported 49 negative-only tests of which
   roughly forty had a positive assertion it simply could not read.

   *And again on the backend.* 164 Python tests assert nothing but absences, which is
   mostly correct — refusals, guards and isolation are negative properties. The sharper
   question is whether each isolation suite has a **positive control**, because "org B
   cannot see org A's row" is satisfied by a policy that hides the table from everyone,
   and this codebase has shipped exactly that twice (`audit_logs` and
   `data_processing_records` returned zero rows to their own owners for months).
   `test_compliance_report_migration.py` had no such control: it seeded one job, for org
   B, and asserted three zeros. It now seeds a job for each tenant and asserts org A can
   read and delete its own — with the GUC pointed at an org that owns nothing, the new
   assertion fails and says why.

22. **When a fail-safe stops firing, something it was hiding starts happening.** A
   `try/except` returning the conservative answer, an `or 0`, a `?? []`: each converts a
   defect into survivable behaviour, and survivable behaviour is never investigated. The
   tactical engine's maintenance check failed *safe* for as long as the column was
   missing, so adding it would have flipped suppress-everything into suppress-nothing.
   Work out what the safe branch was standing in for before removing its cause — the
   commit that makes the error go away is the moment of maximum risk. *(Full account:
   § Maintenance mode.)*

23. **A suppression assertion is satisfied by a broken connection.** Four engine tests
   assert `is True`, and `True` is also what the `except` branch returns for a database
   that never answered — three passed on the first run against `role "placeholder" does
   not exist`. Any suite whose assertions all sit on the safe side of a fail-safe needs
   one that produces the *unsafe* side through the same path, or it is only testing that
   the code is unreachable. Rule 21, one layer down.

24. **An error banner does not immunise the rest of the page.** `CloudGateway` handled
   `isError`, rendered a clear red notice, and then laid out four cards asserting the
   opposite of unknown. Marking a failure and *acting* on it are different jobs, and a
   reviewer grepping for `isError` finds the first and assumes the second. Ask not "does
   this component handle the error" but "what does it still claim while the error is on
   screen". Six pages were wrong this way. *(§ The third form.)*

25. **A qualifier nobody renders is a qualifier that does not exist.** A caveat the UI
   never reads leaves the number rendered bare while the backend believes the caveat is
   shown. Wire it, drop it, or record that the field it qualifies is unrendered too — in
   an exemption that expires by itself the moment anything renders it.

26. **A sweep that finds nothing has told you about the sweep.** The emptiness guard
   reported zero offenders tree-wide while three pages were unguarded: a 40-character
   phrase cap hid a hundred-character empty state, and a 2500-character proximity window
   found an *unrelated* mutation's error branch and called the page clean. Control every
   guard against the real pre-fix file restored from git — a synthetic fixture proves the
   function works, only the file proves the walking around it does. *(§ Rule 26.)*

27. **A window is a guess about code shape; bounds are not.** Looking for `onError`
   within 600 characters of a `useMutation` gave two false positives out of four files —
   a long `mutationFn`, and a `try/catch` around `mutateAsync`. The options object has
   exact bounds, so count braces. And treat a parse failure as "cannot tell": a sweep
   that turns one into a finding spends the reader's trust on noise. *(§ Rule 27.)*

28. **A mock more generous than the wire hides the defect it was built to catch.** Every
   test passed while the maintenance panel rendered a fabricated mileage, because the
   fixtures were written from the TypeScript type and the type described fields the API
   had never sent. `VITE_USE_MOCK` is global in `test/setup.ts`, so every unit and
   Playwright test ran against them. Copy a fixture from what the SERIALIZER emits; when
   type and wire disagree, the type is what is wrong. Deleting the field from the
   interface then makes `tsc` name every place the fabrication was propped up.

29. **A create that returns `{id, status}` cannot be checked.** The caller cannot tell
   whether what it sent was stored, which is exactly how a silently dropped `priority`
   survived in a form that posted it on every submission. Return the stored row and the
   round trip becomes assertable in one call.

30. **`.test()` on a global regex is stateful, and a guard that uses it is lying.**
   `RegExp.prototype.test` advances `lastIndex` and resumes there, so consecutive calls
   over different strings alternate on identical content. The emptiness sweep's own
   vacuity check did this and had been passing by luck; editing four unrelated pages
   dropped the count below its threshold and it failed with nothing wrong in the tree.
   Use `.match()`, and assert the count is the same twice — the failure mode is
   inconsistency, which one run cannot see.

31. **A guard that derives its expected value from its own input asserts nothing.** A
   baseline computed at import from the tree it is then compared against yields an empty
   difference by construction. Pin baselines as literals. The tell is that the expected
   and actual values come from the same function call.

32. **A feature is not one thing, and finding one defect in it says nothing about the
   rest.** Maintenance mode was wrong in five places — schema, write, read-under-RLS,
   response model, call site — found by four separate sweeps weeks apart, each fix looking
   complete at the time. A sweep is organised by SHAPE, not by feature, so it sees one seam
   and walks past the others. When a sweep finds a defect in something, walk the whole path
   by hand before believing the feature works. And check the contract from both ends: the
   server not sending what the client reads, and the client not sending what the server
   reads, are different defects that no single sweep finds.

33. **Fixing a correctness defect is where performance and robustness defects get
   introduced.** The join that made the geofence alert readable also added an N+1 and a
   500-on-real-data, and neither was in the code being fixed — both were in the fix. Run
   the whole suite, not the new file.
   *(Fuller account: § Rule 33.)*

34. **A global vocabulary passes a name that is wrong for the entity holding it.** Six
   `DockDoor` fields were declared against a table carrying none of them and the
   wire-vocabulary sweep reported none, because each name is a column on some other table.
   Per-entity audits are a different, narrower job.
   *(Fuller account: § Rule 34.)*

35. **Name the field after the wire, not after the nicer word.** Mapping `active_devices`
   to `vehiclesActive` in a client made the sweep report the new name as unsourced —
   correctly, since nothing produces it, and a reader cannot tell a rename from a
   fabrication either. One name per concept, chosen where the concept lives.
   *(Fuller account: § Rule 35.)*

36. **A request field checked against a response vocabulary is a false positive by
   construction.** `ErrorListParams.sort` sat on a baseline as unsourced while the endpoint
   accepted it: the vocabulary collected class attributes but not function parameters, so
   it was comparing what the backend CONSUMES against what it PRODUCES.
   *(Fuller account: § Rule 36.)*

37. **Prose about a defect gathers around the defect, so strip comments in every source
   assertion.** `assert "currentMileage" not in logistics_ts` failed twice against FIXED
   code — first the comment explaining the deletion, then one citing it as a precedent.
   *(Fuller account: § Rule 37.)*

38. **Prefer the check with a definite answer, even if it covers less.** The broad
   wire-vocabulary sweep produced nine findings and needed three corrections; the narrow
   response-model-versus-table audit was right first time with a two-entry false-positive
   surface.
   *(Fuller account: § Rule 38.)*

39. **Six hand-fixes and no guard is a class that will come back.** The tenant-from-body
   shape had been removed by hand from six handlers, each with a careful comment, while
   fourteen more instances sat in the same three files. A comment records a fix; only a
   guard prevents the next one.
   *(Fuller account: § Rule 39.)*

40. **Never act on truncated diagnostic output.** A guard printed thirteen offenders, `head
   -10` showed nine, nine were fixed, and four "new" ones appeared on the re-run — briefly
   looking like the fix had caused them.
   *(Fuller account: § Rule 40.)*

41. **A migration that enumerates its targets leaves the next arrival unprotected.** 011,
   033 and 051 each named their tables; `vehicles` arrived between them and had no policy,
   which is why it was the one handler whose tenant defect wrote a real cross-tenant row.
   *(Fuller account: § Rule 41.)*

42. **A test asserting emptiness must be given something to find.** `_load_rules(None) ==
   []` passed against a restored fan-out because the test omitted the fixture that seeds
   rows. Rule 21 in ordinary clothing: a fixture left off a parameter list.
   *(Fuller account: § Rule 42.)*

43. **A guard proves the absence of the shape it models, not of the class.** Three guards
   for "the caller decides which tenant" — assignment from a body (14 handlers), a query
   parameter (8), a conditionally-applied filter (4) — each clean while the next variant
   sat in the same three files.
   *(Fuller account: § Rule 43.)*

44. **A hand-maintained number in prose is a claim that will be wrong.** The README said "206
   backend test files" against a measured 201, cited rules 21–38 when the doc had reached 41,
   and said thirty-seven classes when the table had grown past it. A rule range and a class
   count change rarely and are worth asserting; a test count changes every commit and pinning
   it would make every new test fail the suite. Re-measure the rest at each milestone rather
   than trusting them — two of those three were wrong when measured.
   *(Fuller account: § Rule 44.)*

45. **A module-level copy of a patched name is a defect waiting for a new caller.**
   `tenant_session` held `AsyncSessionLocal` captured at import, and the harness rebinds that
   name per module — invisible while the helper was only reached through the dependency the
   suite overrides wholesale, and instant the moment a service called it directly. Resolve such
   names at call time. And simulate the broken state in the test: comparing engines passed under
   the mutation, because whether the copy is patched is exactly what varies.
   *(Fuller account: § Rule 45.)*

46. **A filter added to a read is a claim about the write path.**
   `WHERE organization_id = :org` asserts that something fills that column. Nothing did, so
   `/admin/collectors` was empty for every tenant since the endpoint was written — a leak
   converted into a permanent emptiness by a fix that was otherwise right. Check the writer in
   the same commit, and assert the column from the write side against the database.
   *(Fuller account: § Rule 46.)*

47. **Fixing one half of a defect can arm the other half.**
   One tenant claiming another's `agent_id` was inert while the tenancy column was never
   written; attributing the row made the last heartbeat win the tenancy. Ask what a dormant
   defect was being kept dormant *by*, before removing it.
   *(Fuller account: § Rule 47.)*

48. **A guard answers the question it was asked, so ask the broader one too.**
   The duplicate-tenant-session guard asked "which test files override `get_tenant_db`?" and
   answered it correctly while two production services held copies of the same helper. Asking
   "what in the whole tree binds `app.current_org_id`?" instead returns thirty call sites — and
   the two helpers among them. Re-derive a long-green guard's population from first principles.
   *(Fuller account: § Rule 48.)*

49. **A suite that skipped is not a suite that passed.**
   The four ERP real-DB suites report 25 passed, 29 skipped — and the 29 are every test that
   touches the function migration 058 could break, skipped for want of vendor credentials. Read
   the skip count, not just the pass count; then notice which part actually needed the
   credentials (the vendor HTTP call, and nothing else) and stub only that.
   *(Fuller account: § Rule 49.)*

50. **A fixture in a shape no endpoint produces tests the fixture.**
   The maintenance trend chart labelled its axis with `month.split(' ')[0]` — right for the
   mock's `"Jan 2024"`, and rendering the server's `"2026-01"` as the literal string. The panel
   test used the same fixture, so test and code agreed with each other about a format the wire
   does not send. Fixtures carry what the serializer emits, and nothing else.
   *(Fuller account: § Rule 50.)*

51. **An upper-bound assertion is satisfied by zero.**
   An N+1 guard asserted `len(vehicle_reads) <= 1` and passed against a one-query-per-driver
   mutation, because its matcher wanted `" FROM vehicles"` with a leading space and SQLAlchemy
   puts `FROM` at the start of a line. Assert the exact count: `== 1` fails at zero, so the
   matcher's silence becomes a failure rather than a pass.
   *(Fuller account: § Rule 51.)*

52. **When a fix does not move the baseline, suspect the detector.**
   `Driver.currentVehicleId` stayed on the declared-but-unsent list after the server began
   sending it — `_wire_vocabulary` collected dict-literal keys and not `row["name"] = …`. A
   baseline that does not move when the code does is evidence about one of the two; find out
   which. Widen with both a positive and a negative control.
   *(Fuller account: § Rule 52.)*

53. **A NULL a column can hold is a value the schema has to accept.**
   `Dict[str, Any] = Field(default_factory=dict)` rejects `None` — the factory fires only when
   the key is ABSENT, and `model_validate(orm_row)` supplies the attribute's value. Seventeen
   `meta_data` columns have no DDL default, so one raw INSERT 500s a whole list page. Coerce
   only where the absent value and the empty one genuinely mean the same thing.
   *(Fuller account: § Rule 53.)*

54. **A widening that removes one finding can cost the detector.**
   Crediting every `.get("literal")` key would have cleared `AgentRolloutCreate.all` — a
   genuine false positive — and added 425 names reachable only that way. Measured, then
   declined. Each widening looks like a bug fix on its own, and a detector can be improved
   until it reports nothing.
   *(Fuller account: § Rule 54.)*

55. **A static sweep cannot see what an adapter makes up at runtime.**
   Deleting two fields from `YardTrailer` left `adaptTrailer` synthesising both, with `tsc`
   clean throughout: excess-property checking is relaxed for a literal that spreads an `any`.
   Assert the adapter's OUTPUT against exactly what the serializer emits — the mock branch is
   not the code that ships.
   *(Fuller account: § Rule 55.)*

56. **A fixture on a boundary is a coin flip.**
   An appointment seeded at `now()` sat microseconds outside a window opening at the request's
   `now()`, so the test passed or failed on jitter and looked like cross-test pollution. Put
   fixtures well inside the range under test, unless the edge is the assertion.
   *(Fuller account: § Rule 56.)*

57. **Test each layer with what the layer above it can actually send.**
   `circleRenderableZones` was tested with `center: undefined`; `adaptZone` produced
   `{latitude: 0, longitude: 0}`. Both units were correct about their own contract, neither was
   ever handed the other's output, and a zero-radius circle at 0°N 0°E reached the map with full
   coverage on both sides. Where two units meet, assert on the pair.
   *(Fuller account: § Rule 57.)*

58. **A mock-only defect is a defect with a delay.**
   A mock branch is the specification the next author reads. `createRepairOrder` minted a
   `WO-YYYY-NNNN` in its fixture and a synthesised work-order number ended up as the heading a
   technician quotes to a vendor. Fix the real branch even when nothing calls it, and where the
   fabrication belongs to a fixture, write down what makes it wrong to promote.
   *(Fuller account: § Rule 58.)*

59. **Search for the fix, not the defect.**
   Three HOS endpoints coerced NULL hours to zero and counted an unreported driver as
   compliant; two were fixed months apart by people looking at the endpoint in front of them.
   `(x or 0) >= 11` is unsearchable — it looks like every other guard clause. `unassessable`,
   `missing_data` and `is None` are distinctive. Grep for what you just wrote.
   *(Fuller account: § Rule 59.)*

60. **A non-vacuity check keyed on defect count inverts when you fix them.**
   The no-RLS-claim scan asserted `len(_claims()) >= 5` to prove it still worked, and went red
   the moment the five claims were corrected — because correcting them put them in the past
   tense, which the scan skips by design. Key non-vacuity on a synthetic control in the shape
   of the defect, not on how many of them are left.
   *(Fuller account: § Rule 60.)*

61. **Sweep every name a module exports, not the one that broke.**
   `conftest` rebinds `AsyncSessionLocal` across `sys.modules` because patching a hardcoded
   list let `role "placeholder" does not exist` into the smoke suite. It swept one of the two
   names `app.db.database` exports; six modules bind `engine`, and one of them opens a
   connection on it. The attribute not causing trouble at the time is the one that will.
   *(Fuller account: § Rule 61.)*

62. **A guard's scope is a hypothesis, and it is usually the place you first looked.**
   The failure-is-not-emptiness sweep had been broadened five times — always about the shape of
   the check, never about which files it ran on. Its scope was `useQuery`, the library both
   original findings happened to use; fourteen components fetch by hand and render empty states
   from data that can fail identically. Ask what the class is, then ask what the population is.
   *(Fuller account: § Rule 62.)*

63. **Every component fast and the whole impossible is a feedback loop, not a slow part.**
   The contract job needed ~19 hours for work whose every measured piece was milliseconds. Two
   loops compounded: a new event loop per generated example, and an error path with no delay
   spinning on the failures that caused. Profiling the parts is what kept it broken.
   *(Fuller account: § Rule 63.)*

64. **A fixture that provisions what migrations do not makes the suite an unreliable witness.**
   `conftest` created the pgcrypto extension; no migration did. The real-DB suite exercised a
   working audit trail while a real deployment recorded nothing. The tests were not wrong about
   the code — they were wrong about the database, which is the environment nobody inspects by
   hand. *(Fuller account: § Rule 64.)*

65. **A security claim that has not eliminated the harness is not a finding.**
   A cross-tenant write appeared to succeed; the suite was connecting as a superuser, and a
   superuser bypasses RLS even where FORCE is set. One query against `pg_roles` settled it.
   Run that query before writing the bug report. *(Fuller account: § Rule 65.)*

66. **A guard that cries wolf on compliant code gets loosened until it catches nothing.**
   The tenant-id sweep flagged a file that was already correct, because it overrode via a
   dict-key assignment the pattern missed. Mutation-verify BOTH directions: the real offender
   must fail, and the compliant file must stay unflagged. *(Fuller account: § Rule 66.)*

67. **A test suite has no opinion about what the screen looks like.**
   A badge rendered white-on-white in the default theme and survived 467 unit tests, a
   typecheck and four defect-class guards — the page tests asserted its text content, which
   was in the DOM and correct. Nothing here compares a foreground colour to its background,
   so contrast is not a dimension the suite can fail in. Render it and look at it; that is a
   distinct method, not a weaker substitute. *(Fuller account: § Rule 67.)*

68. **When a new detector reports a surprising number, the detector is the first suspect.**
   Eight instrument errors in one sweep, and every one arrived looking like a finding: a
   contrast checker reporting a heading at 1.0:1 because it read `rgba(…, 0.1)` as solid; an
   FK probe reporting 623 failures because it ran `PRAGMA` against Postgres and poisoned the
   transaction; a theme guard reporting 39 hardcoded colours of which 38 were status swatches
   and complete `dark:` pairs; a click-sweep calling working risk filters dead because two
   filters that both empty a table produce identical DOM. Each cost minutes to disprove and
   would have cost hours to "fix". **The ratio matters more than any one case:** once a
   detector has been wrong twice, its next empty result is not evidence of anything.

69. **Fixing a detector's false positives says nothing about its false negatives.**
   The 2026-08-02 sweep of class 25 corrected two false positives — a casing seam and a
   nested object — and concluded from the corrected run that the class was clean. The
   2026-08-04 sweep hit **the same two**, corrected them the same way, and then found a
   feature that had returned 422 on every call since it was written. Both readers covered a
   seventh of the subject. A detector that has stopped lying to you has not thereby started
   telling you everything.

70. **A floor pulled from the air is a claim about nothing.**
   Three coverage floors were guessed for one guard — 20, then 45, then 35 — against a real
   31. A floor above reality fails on arrival and gets lowered until it passes, which is the
   same as having none; a floor below reality passes forever. Measure it, assert the measured
   number, and state the fraction of the subject it represents so an empty result cannot be
   read as a full one.

71. **A comment describing a check is not a check.**
   A branch in a new guard read `continue`, with a comment saying the case was "reported
   separately below". Nothing below reported it, and that branch was where the live defect
   turned out to be. Rule 17 says a limitation written into a comment is a finding waiting to
   be re-found; this is its sharper cousin — a comment describing behaviour the code does not
   have, written by the same person in the same sitting.

72. **Restarting a service is a claim; verify the port and the process.**
   A fix was reported as still broken because `kill` had not taken, the old server still held
   the port, and the "restart" bound nothing. Checking the process start time turned a wrong
   conclusion into a correct one in ten seconds. The general form: when a verification
   contradicts a change you are confident in, check the verification's premises before the
   change's.

73. **A vacuity guard keyed to a defect population fails on success.**
   Twice in three days a guard written to stop a sweep passing over nothing broke *because
   the sweep worked*: one asserted a current offender existed and failed at zero with the
   message "delete it rather than keeping a guard that guards nothing" — exactly the wrong
   conclusion. Key the vacuity check to the INSTRUMENT (vocabulary size, interface count,
   routes walked), which does not move when the findings do.

74. **A default is a claim.**
   `?? 'violation'` made every alert read "Violation"; `?? []` made every zone report "0
   vehicles inside", a *count*, which reads as a measurement; `|| 'Not assigned'` made every
   shipment report a vehicle it never had. A blank is visibly missing; a default is a
   statement, and a wrong one is indistinguishable from a right one.

75. **A number in a comment is a claim.**
   A registry finding was written up as 41 unfillable and the answer was 38 — the smaller
   set was a subset of the larger, not disjoint. The test caught it before it shipped.
   Corollary: three notes that turned out to be wrong this week were *accurate when
   written*. A note records what someone believed; only a test records what is true now.

76. **Read the DOM before rewriting the locator.**
   Three selector rewrites for a field that was never the problem — all resolved to a real
   element, none could see the input, and the original was correct. Dumping 700 characters
   of `innerHTML` took thirty seconds. When a selector fails, look at what it is selecting
   against; the same applies to a SQL predicate or a regex that matches nothing.

77. **Asking a question before the answer exists returns "no".**
   `isVisible()` right after `goto` answered "not clocked in" about a card whose query was
   still in flight, and the clocked-in card then rendered with no button to press. "Not
   present yet" and "not true" are the same boolean and different facts.

78. **A per-file remedy for a shared resource is a per-file remedy.**
   The suite hit a 10/minute login limit twice, three days apart, in two files — each fixed
   inside itself, so the second could not benefit from the first. A rate limiter, a pool, a
   disk quota and a port are shared; the fix belongs where the sharing is.

79. **A script that writes at the end discards everything if it fails in the middle.**
   Several replacements, then a failing `assert`, so `write_text` never ran and the correct
   earlier edits were lost silently. Same shape as a `kill` that did not take and a build
   piped to `tail`: a step that is not asked whether it succeeded will not volunteer that it
   failed. One edit per script, and assert agreement rather than maintaining it.

80. **A register nobody can trust is worse than no register.**
   One wrong figure and a reader discounts the whole page, including the entries that were
   right. Every number in `open-decisions.md` was correct when audited and every one was
   unasserted — "correct today with nothing keeping it correct" is what every ratchet here
   exists to prevent, applied to prose.

81. **A provenance stamp derived from config is a second guess at a decision already made.**
    The capture knows whether it fabricated; the stamp must come from the capture, not from
    re-reading the same setting one method away. Two conditions that "obviously" complement
    each other — `== "device"` and `== "simulate"` — do not, and everything between them
    fabricates unlabelled.

82. **A fallback is a decision. Make an unrecognised value an error.**
    "Not the hardware value, therefore simulate" turns a typo into a silent change of what
    the system measures. A collector that cannot honour its config should refuse to start.

83. **The loss that only happens during an outage cannot be reported only in logs.**
    An edge device deletes buffered telemetry precisely when it has been unable to reach the
    network — so the log line recording it is on the one box that cannot ship logs. Losses
    need counters, and the loss whose cause is an outage needs one most.

84. **A guard whose window can reach a neighbour's evidence proves nothing.**
    A proximity search for "is there a counter near this call" passed with the fix deleted,
    because the window reached the next call's counter. Bind the variable and follow it.
    Found only by mutating the fix out — which is why that step is not optional.

85. **`| tail` on a test run discards the diagnosis of whatever it reports.**
    A summary line names the failure; the traceback explains it. Piping to `tail` keeps the
    first and throws away the second, so an intermittent that appears once is unreproducible
    by the time you read about it. Write the run to a file and tail the file.

86. **A contract with one side asserted is not asserted.**
    The agent's payload builder and the cloud's handler each had tests, both passed, and
    three fields were transmitted to nobody. Assert the JOIN — every field one side sends is
    read by the other or written down as ignored, with a reason.

87. **A guard that greps for one spelling reports clean on every other spelling.**
    And it reports it in the confident voice of a check that ran. `datetime.utcnow(` was
    matched for months while fourteen equally-naive `datetime.now()` calls sat in the same
    tree. When you write a pattern, assert the pattern: that it matches each form of the
    defect, and does NOT match the correct form.

88. **A defect class does not stop at a repository boundary just because the sweep did.**
    The backend fixed "OEE absence rendered as 0%" months ago. The edge agent computes the
    same metric and had the same defect the whole time. After fixing a class, ask which
    other component computes the same thing.

89. **A fallback into a valid-looking value inherits that value's meaning.**
    Unmapped machine states defaulted to `Idle`, and `Idle` is a downtime category — so
    "we could not read this" was recorded as "the machine was stopped". Pick a value that
    belongs to NO category, or the default silently answers a question nobody asked it.

90. **Dead code that anticipates a case is evidence the case was foreseen and then lost.**
    `get_state_category` had an `"unknown"` branch that nothing could reach, and
    `get_unknown_states()` had no caller. Both were written by someone who saw this
    coming. Unreachable handling for a real condition is a defect report left in the
    source.

91. **Carry a closed class across every component that computes the same quantity.**
    Four consecutive edge-agent defects turned out to be classes the backend had already
    fixed. Finding them one at a time is luck; the systematic version — walk the closed
    classes, ask which other component computes the same thing — is cheap and finishes.

92. **Finding one consumer does not prove there is no other.**
    "This field reaches nobody" is a negative, and a negative needs the whole search, not
    the first path you walked. A heartbeat field was recorded as discarded because one of
    its two consumers was found and the other was not looked for.

93. **Proximity to a correct decision is not protection.**
    `dwell_hours = ... if check_in else 0.0` sat one line above a comment explaining, at
    length, why the sibling field must stay null rather than become zero. Someone reasoned
    carefully about the class and did not look up.

94. **Two producers of one number will disagree about the edge case.**
    The same dwell time was computed in two places. Given a null check-in, one raised and
    one returned 0.0 — so the defect existed in two forms, and fixing either would have
    left the other.

95. **Closing a decision often means deleting, not building.**
    Two of the five open decisions closed by removing something: registries nothing could
    fill are no longer created, heartbeat fields nobody read are no longer sent. Both had
    been framed as work to add.

96. **A too-broad exemption is worse than the entries it removes.**
    The client-constructed exemption, without transitive closure, silenced 34 types
    including several genuinely on the wire — to remove five meaningless ones. When
    exempting, check both directions before believing the count.

97. **A shared utility is only shared if the files that need it point at it.**
    `resilience.py` had a backoff and a circuit breaker, tested, used by three collectors
    since the day they were written. Five later collectors reimplemented the retry loop
    without them — not by deciding against, by not knowing.

98. **Spreading a guess is worse than leaving it in one place.**
    Four tuning constants, copied into five files to fix a real defect, became sixteen
    occurrences across eight modules of a number documented as provisional. A guess in one
    place is a guess; a guess in eight is one nobody can revise, because whoever gets the
    data has to find them all and the ones they miss look tuned.

99. **A fix that copies the pattern should copy the seams too.**
    The five collectors got the instruments and not the injection parameter the three
    originals had, so the newer code was less configurable than the code it imitated. When
    copying a shape, copy what makes it changeable, not only what makes it work.

100. **A plan overstating what is left is harder to catch than one that flatters.**
     A flattering plan gets checked, because someone eventually looks for the thing it
     says is finished. An inflated one does not — nobody investigates a backlog for being
     too long. Two plans in a row overstated, the second written specifically to avoid the
     first's mistake.

101. **Absence is not evidence of a gap until you have checked whether it is deliberate.**
     "This table has no RLS policy" is a fact. "This table is missing an RLS policy" is a
     conclusion, and it needs the second half of the search: whether someone already
     decided it should not have one, and why. The reasoning is often in a test docstring
     rather than the code.

102. **A sweep scoped to one idiom is blind to the same defect in another.**
     The mutation-failure sweep reads `useMutation` options, which is how most of this
     codebase mutates — and could not see five hand-rolled `async` handlers doing the same
     thing with a `console.error` catch. Scope is part of a guard's claim, and an unstated
     scope reads as "everywhere".

103. **Ask of every export what the screen beside it knows that the file does not.**
     A caveat rendered next to a number is not attached to it. The file leaves the building;
     the screen does not. `Historian`'s CSV carried the points and not the cap that produced
     them, so a partial history read as the whole one to everybody downstream.

104. **Clearing the stale view comes before announcing the failure.**
     When a fetch fails after the thing it belongs to has already changed, the first
     obligation is to remove what is now mislabelled. A message beside the wrong content is
     worse than no message, because it invites the reader to look at the content.

105. **A verb list is a scope, and an unlisted verb is an exemption nobody granted.**
     `add` and `remove` were absent from the hand-rolled sweep's verb list, and nothing
     recorded that decision because nobody made it. When a sweep enumerates what it matches,
     the enumeration is the guard's real boundary.

106. **When a failure has to default somewhere, default away from the irreversible side.**
     Every unhandled read lands in some branch; ask which one costs more when it is wrong.
     `ClockTime` defaulted to offering a clock-in, which creates a duplicate payroll record,
     over a clock-out, which is a no-op that fails loudly. Where neither direction is safe,
     show neither and say why.

107. **A fix applied per instance leaves the instances nobody was looking at.**
     `YardManagement` handles the failed-read class on two of its three tabs, in one file,
     under one author — because the fix was made where the bug was reported rather than
     where the class lives. Enumerate a file's other instances before leaving it.

108. **Measure a proposed guard's yield before adding it, and read every hit.**
     A check earns its place by what it finds. The indirect-mutation sweep returned two hits
     across the tree, both false on inspection. Adding it unread would have put two permanent
     lies into a report people are meant to trust; discarding it unread would have left the
     class open. Reading both produced the exemptions, and the exemptions are the guard.

109. **A walk that finds nothing must prove it can find something.**
     Any sweep answering "which are left?" needs a test that it still resolves a known
     member. The FS-364 walk reported zero untested pages twice, because it could not follow
     a barrel import — and "none" is indistinguishable from success, arrives without a
     failure, and is believed.

110. **An exemption belongs beside the guard, with its reason and an expiry check.**
     "Checked and deliberately left" and "never looked at" are indistinguishable afterwards,
     and only one justifies not looking again. `CommandPanel`'s capped history is exempted
     in the sweep's own allowlist, with why, and a second test asserts the exempted call
     still exists — otherwise the allowlist stops describing the code and starts excusing it.

111. **Ask what the interface makes impossible, not only whether it works.**
     Every check that starts from the UI's behaviour is blind to the option it never offers.
     A QuickBooks connector with a sandbox suite shipped unreachable because the create-form
     dropdown was a hand-written array compared against nothing. The absent option produces
     no error, no log line and no failing test.

112. **When absence is the display, absence cannot report failure.**
     A screen whose normal state is "nothing here" has no room left to show that it stopped
     working — the broken rendering and the healthy one are the same pixels. The geofence
     alert feed shows an empty list both when nothing has happened and when the poll has
     died. Streams, alert feeds and live maps need an explicit health signal beside the
     content, because nothing about the content can carry one.

113. **Mock the whole surface or none of it.**
     A demo mode that fakes reads and lets writes through produces a UI that displays,
     accepts input, and then fails — in the half nobody exercised, because everything visible
     worked. `userContext` mocked one read and four writes went to a backend that is not
     running in demo mode.

114. **A two-state read is wrong for as long as the retries last.**
     `isLoading` and `isError` are not the same absence, and with react-query's default
     retries the window between them is seconds. A component branching on `isError` alone
     shows its not-yet-known state as a fact about the world for most of every outage a user
     actually sees — "No assets", "Open errors 0".

115. **A negative assertion needs a positive precondition.**
     "No route claims emptiness" is satisfied by a route that renders nothing at all. The
     browser sweep's first version aborted the dev server's own modules, so React never
     mounted and all 32 assertions passed against a blank document. Assert the page rendered
     before asserting anything about its text.

116. **Count what does not run, not only what does.**
     A pass count answers "how much worked", never "how much was asked", and the gap is
     invisible: every skipped suite is a green line. Six credential-gated suites could have
     become seven with nothing noticing. Any opt-out mechanism needs a register that fails
     when the set grows.

117. **A defect that needs data to appear needs a check that does not.**
     A fractional value, a first null, a string longer than any row so far — some faults are
     invisible to every dynamic test because their trigger has not occurred. `Decimal("12.0")`
     validates against an `int` field and `Decimal("12.5")` does not. Comparing the
     declaration against the storage finds it; testing harder never will.

118. **Ask what a passing gate would still pass with.**
     Point at the property a gate is cited for and ask what would have to break for it to
     notice. The contract gate ran as a superuser, so `FORCE ROW LEVEL SECURITY` did not
     apply and its number could not have moved if every policy had been dropped. A gate that
     cannot fail in a dimension is not weak, it is mute — and its green gets spent on a claim
     it never made.

119. **A subject list belongs in one place, and the guard must read that place.**
     Two copies of "the things we check" drift, and the drift is invisible from either side.
     `controls-do-not-break` kept a private array of 8 routes while the shared list held 33,
     and `everyRouteIsSwept` — the guard for exactly this — was comparing against the other
     one. A private copy is not a shortcut; it is an exemption nobody granted.

120. **A fake is a claim about the real thing, and only the real thing can refute it.**
     A double at a boundary encodes a belief about the contract there; if the belief is wrong
     the test agrees with the caller and the defect survives every run. `FakeProducer` applied
     no serializer and `test_heartbeat` supplied its own key names — two defects, invisible
     for one reason. Make the double do the thing the real collaborator does that could fail.

121. **"It parses" is not "it works", for anything declarative.**
     Alert rules, manifests and schemas each have a validator that checks form and far fewer
     tests that check effect. `EdgeAgentBufferHigh` passed `promtool check rules` for as long
     as it could never fire. Ask what would have to happen for the declaration to *do*
     something, then assert that.

122. **When two components must agree, something has to read both.**
     The backend knew which command ids it dispatched, the agent knew which it registered,
     both were right about themselves, and the fleet answered `unknown_action` to every model
     rollout. The defect is in the absence of a third thing that reads both — and that guard
     is still yours to write when one side is out of your lane.

123. **A test proves the code is correct, never that anything calls it.**
     Three edge-agent modules had passing tests, green coverage and no production caller.
     Nothing in the ordinary signals separates that from a working feature. Whenever a sweep
     asks "is this tested?", ask the second question: **is it reached?**

124. **A commented line documents an intention; it configures nothing.**
     Four edge-agent safety switches were "set" in a commented block headed "Production
     posture". They grep as present, and every deployment ran the permissive default. Parse
     the artefact rather than the text, and treat *unset* as a value: only a default somebody
     chose is safe to ship.

125. **An unreachable path in a fully-swallowing component fails invisibly forever.**
     The HTTP collector catches twice over, so it cannot crash, restart or report — a poll
     that raises every cycle is indistinguishable from one that works. Broad handlers plus
     zero behavioural tests is the pairing to look for: neither alone is alarming, and
     together they mean nothing has ever confirmed the component does its job.

126. **When a convention is documented and unenforced, ask whether the cheap check is wrong.**
     Nobody was ignoring the migration idempotency rule; the obvious detector reported 22
     defects where 4 existed, and a guard with an 80% false-positive rate is a guard nobody
     adds. The reason a written rule has no gate is often not neglect — it is that the
     obvious detector is unusable, and the question worth asking is what a correct one costs.

127. **A detector that must skip a case has to say so, not count it clean.**
     Two statements in the migration chain cannot be retried at all, because Postgres will
     not roll them back. They are recorded as unchecked and the set is asserted not to grow.
     A skipped case counted as a pass is the same lie as an alert that cannot fire.

128. **Moving prose is a code change, and the checks that read it are its callers.**
     Splitting a 7,239-line document disabled three guards; two found none of the sections
     they check and passed over empty sets. Grep for the path the way you would before
     renaming a function. A guard keyed to a filename is a caller — it just fails by passing.

129. **Cite a section, never a line.**
     a citation reading *defect-class-sweeps.md, lines 777–786* was written when those lines held an argument about a
     route prefix; they now hold an unrelated paragraph. Nothing can catch it — the file
     exists and the lines exist — so only a reader who already knows what they expected to
     find can tell. A section heading moves with its text.

130. **`finally` without `catch` is a spinner reset, not error handling.**
     `try { await write() } finally { setSubmitting(false) }` reads like care and guarantees
     the opposite: the UI returns to rest whether the write landed or not, which is exactly
     the state that makes success and failure indistinguishable. Ten task mutations across two
     modals shipped this way; on six of them a rejection and a success were pixel identical.

131. **A store that returns `null` and a store that raises need the same call site.**
     Two modals in one directory over one store handled failure two different ways because the
     store does — `createTask` catches and answers `null`, `updateTask` catches, logs and
     re-raises. A caller cannot get this right by reading its own file. Route every write in a
     component through one helper, so "what happens when this fails" has one answer per
     component rather than one per button.

132. **A poll turns a transient failure into a permanent wrong answer.**
     A one-shot fetch that fails leaves a blank, which is at least a question. A poll that
     fails leaves the last answer forever, with a retry running behind it that keeps not
     working. The question is not "is this handled" but "how long does this state last if
     nobody intervenes" — for a `refetchInterval`, until somebody notices.

133. **`|| 0` on a value that might be absent is a measurement invented from nothing.**
     Zero is not the neutral default for a count you could not obtain; it is the most
     reassuring possible answer, produced precisely when nothing is known. It also swallows a
     genuine zero, so the one case where the number is true is indistinguishable from the case
     where it is invented. `?? null` and an explicit branch.

134. **The numbers a component derives inherit the honesty of their inputs.**
     `Math.max(0, total - (count || 0))` was written as arithmetic, not as a claim, and an
     unavailable count did not default it to zero — it turned the whole page into
     "acknowledged". When a fabricated default flows into a subtraction, a ratio or a
     percentage, look at what it computes before deciding the default was harmless.

135. **When a sweep comes back clean, the reason is the result.**
     Thirty-one hits, one defect. The value is not the fix; it is that the other thirty are
     known-checked with the reason each is acceptable written down. A sweep reported as
     "clean" and nothing else is indistinguishable from one nobody ran, and the next person
     pays for it twice.

136. **Two implementations of one question is a defect before either is wrong.**
     A correct normaliser sat beside the broken one and callers had no way to know which they
     held, so the honest one could be fixed forever and the UI would never benefit. Guard the
     AGREEMENT, not the delegation: "A must call B" passes for any delegation and fails for
     any honest reimplementation, which is backwards.

---

## Open observations, not yet tickets

**The password-reveal toggle on the login page has no accessible name.** It is an
icon-only `<button>` whose meaning lives in a Radix tooltip, which is exposed as a
*description*, not a name — a screen-reader user hears "button". Found while writing
`Login.test.tsx`, which selects it structurally rather than by role+name because of this.

**Deliberately not fixed.** The `htmlFor` / `aria-label` sweep is another lane's first
ticket, and quietly fixing one instance would take the interesting part of that work and
leave the pattern behind. Recorded here so it is not re-found from scratch.



**A TypeScript response type omitting fields the server sends — swept, not enforced.**
The field-level companion to class 9's shape check, restricted to URL prefixes the casing
seam does not touch so names are literal on both sides. **One hit:** `erp.ts`'s
`FieldMapping` omits `created_at` and `updated_at`, which the client has no use for. That
is the whole problem with enforcing this class — a missing field is usually a deliberate
narrowing, and only occasionally a dropped meaning like `simulated` above. Recorded per
the rule that a guard you cannot make precise is worse than a written-down result. The
provenance case, where the omission *is* a defect, is enforced separately by
`test_provenance_flags_are_always_set.py`.



**RESOLVED, as a checked record rather than a fix.** The split is now pinned by
`test_service_lifecycle_is_declared.py`: seven services started by `main.py`, five
recorded as dormant *with the reason for each*. A new singleton nobody starts fails the
test; starting a dormant one without updating the record fails it too, which forces the
consequence to be read rather than discovered.

The sharpest of those consequences has its own assertion. `cloud_gateway` holds a
10,000-entry in-memory list that only its `_flush_loop` drains, and four dormant services
queue into it. That costs nothing today — verified, not assumed: every producer is itself
dormant or unwired. Start any one of them **without** starting `cloud_gateway` and queued
events accumulate and are silently dropped, so the guard fails on exactly that ordering.

Making an invisible state checkable is the point. `tactical_engine` reported dispatches it
never made, and the only reason it never hurt anyone was that nothing started it — a fact
recorded nowhere and discoverable only by grepping.

**Five service singletons have a `start()` that no process calls** — `cloud_gateway`,
`egress_scheduler`, `mlops_pipeline`, `strategic_engine`, `tactical_engine` — against
seven that `main.py` does start. They are the edge-AI stack, so running them in the API
process may well be wrong; the point is that nothing runs them *anywhere*, and the code
around them does not say so. Two consequences are already handled above:
`tactical_engine` now refuses to claim a dispatch (class 5), and the live quarantine
path was fixed independently of `cloud_gateway` (class 6).

The rest is a decision, not a bug fix: either these belong to a process that does not
exist yet, or they should say they are dormant. Until then, anything queued into
`cloud_gateway` accumulates in a 10,000-entry in-memory list that sheds the oldest and
is never flushed.

**`schema_registry` is unwired.** Nothing in the running app imports it, so its
`validate_payload` / `_quarantine_payload` / `_persist_to_dlq` chain never executes.
Worth knowing before anyone wires it: `_persist_to_dlq` is documented *"Persist to dead
letter queue (SQLite or file)"* and does neither — it forwards to `cloud_gateway`, which
nothing drains. Same shape as class 6, one level of indirection deeper.

**Seven ERP modules, ~3,800 lines, imported by nothing.** Measured, not estimated —
`sap_data_extraction` (641), `oracle_data_extraction` (552), `dynamics_data_extraction`
(714), `erp_database_replication` (492), `sap_webhook_integration` (501),
`oracle_correlation_patterns` (492) and `dynamics_correlation_patterns` (404). No module
imports any of them, and no public symbol they define is referenced anywhere else.

**One of them turned out to be finished work that was never plugged in.** Oracle's
`transform_invoice` / `transform_shipment` and its `analyze_invoice_anomalies` /
`analyze_shipment_correlation` are matched pairs — the transformer emits exactly the five
fields the analyzer reads, verified field-by-field. They were simply absent from
`CORRELATION_ROUTES`, so every Oracle sync reported `skipped: unrouted` while the code to
produce its correlations sat unused. Registering them took a per-vendor analyzer-class
lookup and four registry lines. That closes most of task #33 in the current pool.

**All seven have now been checked, and none should simply be deleted.**

| Module | Verdict |
|---|---|
| `oracle_correlation_patterns` | **wired** — matched transformers already existed |
| `dynamics_correlation_patterns` | **wired**, after correcting three field names |
| `erp_database_replication` | already refuses honestly: `start_replication` raises `NotImplementedError` because its CDC helpers are stubs. Nothing to do |
| `sap`/`oracle`/`dynamics` `_data_extraction` | **superseded, annotated in place** |
| `sap_webhook_integration` | **reviewed** — three log-only `_create_alert_*` helpers renamed `_log_*` (class 5 above); the live webhook path remains `api/erp_webhooks.py` |

The three extraction modules are not duplicates of `run_erp_sync` — they store the
**normalised** record, where `run_erp_sync` stores the **raw** one and transforms at
analysis time. Raw storage is the approach that survived, because it is lossless: three
field names in the Dynamics invoice transformer were wrong, and with raw storage that was
a code fix rather than a re-sync. Wiring them back would create a second ingestion path
writing the same table in a different shape, which is worse than either alone. Each now
carries a module-level note saying so, since the risk is not that they sit unused but that
someone starts one.

So the tally is: of seven modules, **two were finished work worth wiring**, one was
already honest, three are superseded and now say so, and the last one carried three
helpers whose names claimed work they never did. All seven are now reviewed. A straight
delete would have discarded the two.

**Dynamics was then registered too — after correcting three field names.**
`transform_dynamics_product` was already correct (all eight columns verified against
Microsoft's product table reference). `transform_dynamics_invoice` was not, and every
error would have failed silently, because an unmapped field is `None`, the analyzer finds
nothing, and the sync reports a clean run over data it never read:

| Was | Problem | Now |
|---|---|---|
| `invoiceid` → `invoice_number` | that is the GUID primary key | `invoicenumber`, falling back to the GUID |
| `invoicedate` | **not a column on invoice** | `datedelivered`, falling back to `createdon` |
| `customerid_account` → `customer_id` | a navigation property for `$expand`, not a scalar | `_customerid_value`, the Web API shape |

Invoices and products are routed. Two Dynamics entities are deliberately not:
`project` is not a base Dataverse table (confirmed absent from a live environment;
Project Operations exposes `msdyn_project`), and `account`'s analyzer takes an account ID
rather than a record — its transformer *is* verified, all six columns real.

**That evaluation exposed a hole in the registry itself.** Field alignment is necessary
but not sufficient: the router calls `analyze(db, normalized_record)`, and an id-taking
analyzer would receive a dict. It would not fail loudly — the per-record `except` catches
it and counts a failure, so a whole sync would report `failed: 500` and look like bad
vendor data rather than a wrong registry entry. `test_erp_sync_correlation.py` now asserts
every registered analyzer's second parameter is a dict, and proves that check can fail by
naming a real id-taking analyzer that must never be registered.

**And registering the routes found two bugs in code that had never run.** Nothing called
these transformers, so nothing exercised them. `transform_manufacturing_order` referenced
`sap_po` while its parameter is `sap_mo` — a `NameError` on every call, in a route that
was **already registered**. It would not have surfaced as a crash: the per-record handler
catches it and counts a failure, so an entire SAP manufacturing sync would have reported
`failed: N` and read as bad vendor data. Its status map also listed `"DLV"` twice, so the
second entry silently won and `"delivered"` was unreachable.

Every registered transformer is now called once with a realistic vendor record, which is
the cheapest possible check that a route's central claim — *this transformer works* — is
true.

---

