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

137. **A gate that is never reached and a gate that does not exist are the same gate.**
     Paid for three times here: a branch pattern for a branch that never existed, coverage
     thresholds no job passed `--coverage` to, and two blocking checks living only in the
     workflow that skips branch pushes. None announces itself — every job is green and "we
     have a typecheck" is true and useless. Ask not "is it blocking" but **"which pushes
     reach it"**, against the branches people actually use.

138. **The check you skipped is the one that finds your mistake.**
     `tsc`, then an edit, then only `vitest`. Every check that ran passed, and the one already
     run was the one that mattered. Compile last, after the final edit — and when a run is
     green, ask which tools did not look at what you just changed.

139. **A smoke test that only ever fails has not tested the success path.**
     `route_walk` drives every route looking for 5xx, which reads as complete coverage of
     "does it crash". With generated inputs most write routes reject before doing anything, so
     what is proven is that the REFUSAL path does not crash. An undefined name on a dispatch
     route's success path survived it for months. Ask which branch the smoke test reached.

140. **Fixing the caller closes the instance and preserves the class.**
     Three times a query-parameter-vs-body mismatch was closed by correcting the client, each
     time for a good reason — the route was in another lane. The instance really was fixed,
     and the server still publishes a contract nobody would guess, in 22 places. When the
     cheap fix is on the other side of a seam, record what the expensive one would have been
     and guard the seam, because that is what the cheap fix leaves undefended.

141. **Before writing a walker, look for the one that already exists.**
     Three detectors failed in a row reaching one finding: an inverted prefix matcher, a module
     name read as `split(".")[-1]` (which is `"router"` every time), and a hand-rolled route
     walk reporting SIX routes for an app with 524 — `app.routes` holds lazy `_IncludedRouter`
     entries whose children carry relative paths. `tests/_route_tree.py` had existed the whole
     time and its docstring opens by naming that pitfall. The second wrong answer was a clean
     tree, which is the kind that gets believed.

142. **A declared field that is dropped is worse than one that is refused.**
     A refused field is a 422 the caller can read. A dropped field is a 200, an echo of the
     default, and an empty column — both ends of the round trip report success and the middle
     loses the value. `inspector_id` and `metadata` were declared on the way in, declared on
     the way out, and connected to nothing. Follow a declared field to storage before assuming
     the wiring exists, and let "does it have somewhere to land" decide whether to store it or
     refuse it.

143. **When a boolean is stored, find the field that bounds it.**
     Three instances in one day: an inspection with no inspector, a seal with no status, a
     certification with no expiry. Each keeps a flag and discards the field saying what the
     flag is worth, and each reads as the more reassuring of the two possible answers. The
     carrier case had a reader already computing `certified AND expires_at AND expires_at >
     now`, so every carrier created through the API reported invalid. Whenever a handler
     passes a boolean, look for the adjacent qualifier — expiry, status, actor, timestamp.

144. **Assert the round trip through the reader, not the hand-off.**
     `assert kwargs["expires_at"] is not None` passes for a value the reader still cannot use.
     Run the reader's own expression over what the writer stored — and assert the negative
     case too, because a fix that makes everything valid is worse than the defect it replaced.

145. **Read the reader before deciding which way a dropped field is wrong.**
     Class 99 has two opposite fixes. Wire it through when something already depends on the
     value (`ctpat_expires_at`, the HOS hours). Take it off the schema when something else
     already PRODUCES it — `detention_charge` is computed at checkout, and honouring a
     caller's would let an operator bill their own figure. The discriminator is not severity
     or whether the column exists; it is whether the value has another producer.

146. **A field name is not a field; check the module before believing the reader.**
     A "has a reader" ranking reported `approved_at` read by `kanban.py` — a task's approval,
     not a freight charge's — plus `duration_seconds` by `dashboard.py` and `priority` by
     `data_shedding.py`. Common column names live on a dozen models. Same-module readers were
     the only signal that survived. Third name-collision false positive this week.

147. **Defaults compound, and no single site looks wrong.**
     A nominal 500 miles for an unrouted shipment and a list rate of $2.50 for an uncontracted
     carrier are each defensible alone, and neither function can see the other. The product was
     a $1,333.33 invoice no reader of either would predict. Do not rank fabricated defaults
     individually — follow the call chain and ask what the caller does with the result.

148. **Turn your own regression into the guard that would have caught it.**
     `temperature_zones or {}` on a list column stored an object, the response model refused
     the row, and every load-plan create 500'd — on the SUCCESS path, where `route_walk`
     cannot look. The sweep afterwards found eighteen sites and zero other disagreements: the
     tree was clean and I was the defect, which is the argument for the guard rather than
     against it. A bug you just made is the best-specified guard you will ever write — you
     know the line, you know why the existing checks missed it, and the line itself is your
     positive control. Write it when the sweep comes back clean, because that is when it is
     cheapest.

149. **When a fix trips a guard, ask whether the premise broke or only the string test did.**
     Widening `ShipmentUpdate` failed a guard asserting every declaration of `origin` reads
     `Dict[str, Any]` — because the new one reads `Optional[Dict[str, Any]]`. The guard's
     premise is *the backend contracts no keys for this field*, and an optional untyped dict
     contracts no keys either: the premise was intact and only the literal `startswith` was
     too narrow. The opposite reading — loosen the guard because the fix is obviously fine —
     is how a guard dies, so the repair strips exactly one `Optional[...]` wrapper and
     nothing else, and was mutation-verified with `Optional[Location]`, which still fails.
     A guard written against one spelling of a type will meet the second spelling eventually;
     the fix is to name the property, not to widen the pattern until it stops complaining.

150. **`git checkout <file>` to undo a mutation test throws away everything uncommitted in it.**
     Reverting a one-line mutation took the whole FS-671 widening with it, silently — the
     mutation test passed, and the fix it was verifying no longer existed. `git status`
     after a revert is one command; noticing at commit time is luck. Better: mutate a copy,
     or `git stash` first, or re-apply from the diff you still have on screen.

151. **A validation block that cannot run is a defect report someone else already filed.**
     `update_asset` checks that a caller-supplied `workcell_id` belongs to the caller's own
     organization; `AssetUpdate` has no such field, so the check has never executed and an
     asset could never be moved between workcells. The dead branch is the evidence: a missing
     feature has nobody's intent behind it, and this had a tenant-scoped lookup and a 404
     written out in full. When a handler reaches for a key its schema cannot carry, read the
     branch before deleting it — it usually describes the capability that is missing.

152. **Mutation-test the justification, not just the guard.**
     Two claims went into this fix and both were false. *"Without an existence check a bad
     foreign key is a 500"* — removing the check changed nothing, because the platform's error
     handler already answers 400 with a better message, so the check was deleted. *"This test
     proves the lookup is tenant-scoped"* — deleting the tenant predicate left every test
     green, because RLS shadows it. A mutation that does not fail is not a formality passed;
     it is the reason you gave being wrong, and the fix is to change the code or change the
     claim, never to keep both.

153. **A control that another control shadows can only be held statically.**
     The workcell tenant predicate is real — RLS holding depends on the database ROLE, and a
     BYPASSRLS connection turns the same request into a cross-tenant write — but no behavioural
     test can distinguish it while RLS is also blocking. Defence in depth is precisely the
     situation where each layer is individually unobservable, so asserting the second layer
     exists in the source is not a weaker test, it is the only one available.

154. **Read the runner's own output, not only the pass count.**
     1,056 passed and `Errors 1` underneath it — an unhandled rejection the runner reported
     and no assertion covered. It had been there for as long as the test had, and a run that
     is green except for a line nobody reads is where the next real error goes to hide. The
     pass count is a summary of what you asserted; the error line is what the runtime noticed
     on its own, and it is strictly more informative for being uninvited.

155. **`() => Promise<void>` is assignable to `() => void`, and that is where rejections go.**
     An async handler passed to a JSX prop returns a promise the DOM discards. The compiler
     permits it by design, so nothing flags it — and a comment claiming "the error propagates
     to the caller" can sit above it for months while the caller is an event dispatcher that
     never looks. When a handler is async, find who awaits it before believing any claim
     about where its failure goes.

156. **A scripted bulk edit needs a per-file compile check, not a satisfying diff.**
     Inserting an import after "the last import line" put it inside a multi-line
     `from x import (`, and the file stopped parsing. Nothing said so — the migration script
     printed `patched` eight times — and it surfaced only when the new guard's AST walk
     crashed with a `SyntaxError` naming a line I had not looked at. Seven of eight files were
     fine, which is exactly the ratio that makes a bulk edit feel finished. Parse every file
     you touched before you believe the edit.

157. **Carry a class across runtimes, not just across files.**
     An unowned promise rejection in the browser and a discarded `asyncio` task on the server
     are the same defect — a failure whose owner is nobody — and the second was found by
     asking what the first looks like in Python, twenty minutes after fixing it. Ten sites,
     including one fired per request on the ingest path. The carry-across usually moves
     sideways through a codebase; it moves just as well through a runtime boundary, and the
     far side is where nobody has looked because it is somebody else's language.

158. **After finding the shape, ask per site: which thread calls this?**
     The sweep for discarded `create_task` calls found six in the edge agent and classified
     them all as "may be garbage collected" — a hazard. Asking who invokes each handler turned
     three of them into a total failure: paho's `loop_start()` and watchdog's `Observer` both
     dispatch from their own threads, where `create_task` **raises** rather than schedules.
     Every MQTT reading was being dropped. The structural sweep finds the candidates; only the
     call path tells you which are theoretical and which are costing data today, and reporting
     six equal hazards would have buried the three that mattered.

159. **A test for threaded code that does not use a thread proves nothing.**
     The first version of the new test called `_on_message` directly, from the test's own
     coroutine — which is on the loop, where the broken code works perfectly. It passed
     against the defect. The reproduction has to reproduce the *conditions*, not just the
     call, and for anything a third-party library dispatches that means a real
     `threading.Thread`.

160. **Excluding a file to suppress self-matches suppresses its real uses too.**
     The sweep for write schemas nothing references searched every file except `schemas.py`,
     so that `class AlarmCreate(BaseModel):` would not count as a use of `AlarmCreate`. It
     also stopped `class AlarmResponse(AlarmCreate)` counting — inheritance, in the same file,
     the only use there is. Two of three reported defects were artefacts. Exclude the
     *definition*, never the file: parse it and skip the one node, rather than deleting the
     whole haystack because the needle looks like the hay.

161. **A schema with no caller is a design decision that was written down and dropped.**
     `DataCorrelationUpdate` existed, was complete enough to be obviously intended, and no
     route referenced it — while the route it belonged to took query parameters and silently
     ignored bodies. That combination is not dead code; it is a plan someone made, half
     executed, and nobody finished. Worth its own sweep, because the schema is the only
     surviving evidence of the intent and reads to the next person as a promise the API keeps.

162. **A detector that names ninety-five defects in a tree with five is not a first pass.**
     "Every collection POST should have a sibling PUT" reported 95 of 123 POSTs, because most
     POSTs are actions and because `/assets/` and `/assets/{id}` differ by a trailing slash.
     The fix was not to tune it — it was to pair by SCHEMA instead of by path, using the
     OpenAPI request bodies, which has no heuristic in it at all: an action endpoint has no
     `*Create` model, so it never enters the comparison. The precise version found a fifth
     instance my own hand-written summary had missed. When a detector's output is mostly
     noise, look for the join that makes the question exact rather than the filter that makes
     the noise smaller.

163. **`head` truncates evidence, and truncated evidence reads like a complete answer.**
     `grep -rn TruckAssetCorrelation app/ | grep -v models.py | head -6` returned six lines
     from `db/models.py` and nothing else, so I wrote down "no reader and no writer anywhere"
     and put it in a register with a reason. The entity is read twice and written once; the
     class definition plus its five relationships had filled the limit exactly. Count first,
     or drop the limit when the question is *does anything use this* — an empty tail is the
     one part of that output you actually need.

164. **Widening a schema whose handler does not use `exclude_unset` reintroduces the last bug.**
     Every update handler in this codebase applies `model_dump(exclude_unset=True)` — except
     `update_task`, which hand-writes a block per field to build its changelog. Adding twelve
     fields to `TaskUpdate` alone would have declared, accepted, validated and silently
     dropped all twelve: FS-676's defect, created by the fix for FS-671. Before widening,
     read the handler; the safe mechanical change is only mechanical where the handler is
     generic.

165. **Assert the denominator, not just the absence of findings.**
     A sweep that reports "nothing wrong" and a sweep that examined nothing produce identical
     output. This one nearly shipped in the second state: run as a script file rather than
     through stdin, its `import_module` calls all raised, its `except Exception` swallowed
     them, and it checked zero of 211 accesses while printing a clean result. Every guard
     that resolves anything at runtime needs a test that the resolution happened — the count,
     not the verdict.

166. **A mutation that produces no failure is the detector confessing.**
     The vacuity above was invisible in the passing run and obvious the moment the real bug
     was put back and nothing fired. That is the single most informative thing a mutation test
     does: not confirming the guard catches the defect, but revealing that the guard was never
     looking. Run it against the original line, not a synthetic one, and treat silence as a
     result about the detector rather than the tree.

167. **Ask the compiler before writing the detector.**
     Three passes went into deciding whether a nullable value could be formatted as a date: a
     name-based one that reported eighteen false positives, a TypeScript compiler-API one that
     examined 236 sites and reported zero without a working positive control, and finally the
     one that settled it — plant the defect in a scratch file and run `tsc --noEmit`. It
     errored in one command. When the language already has an analyser for the property you
     are about to detect, borrow its answer; a hand-written detector for something the type
     system enforces is a re-implementation with worse calibration.

168. **Mutate both ends of a contract, not just the side you were looking at.**
     A background task breaks if the call site gains an argument *or* if the target gains a
     required parameter. Same consequence, opposite edits, and a guard tested against only one
     of them is half a guard — the untested direction is exactly the one a future refactor
     will take, because changing a function's signature feels like changing the function, not
     its callers. Both mutations were run; both fail.

169. **"Untested" and "untestable here" look identical in a coverage report.**
     Four mutating routes in this lane had no test naming them. Two were simply never driven.
     Two create a Redis-tracked job before doing anything, and this harness has no Redis — so
     their success path is unreachable rather than neglected. Left unstated, the next person
     to look sees four gaps and spends their time discovering the distinction again. Write
     which is which, in the test file, and pin whatever IS reachable — the validation ahead of
     the unreachable part usually is.

170. **A test that asserts on a random draw is flaky by construction — seed it, do not relax it.**
     `get_exceptions` fabricates `range(random.randint(0, 10))` rows, so a provenance test
     asserting `rows` is non-empty failed roughly one run in eleven. The tempting repair is to
     drop the emptiness assertion, and it is wrong: "every one of zero rows carries provenance"
     is vacuously true, so the test would go green permanently while checking nothing. Seed the
     generator instead, state the seed and what it draws, and the test keeps its teeth.

171. **When an unrelated test fails, read its source before reaching for `git stash`.**
     A full-suite failure in a file this work had not touched looked like a regression. Stashing
     made it pass — which is exactly what a 9%-flaky test does about ninety percent of the time,
     and it would have "confirmed" a phantom regression in my own changes. The bisect instinct is
     right for a deterministic failure and actively misleading for a flaky one; ten seconds of
     reading the assertion distinguishes them, and no amount of stashing does.

172. **Some classes are not statically sweepable, and saying so is a result.**
     Every non-null assertion in the frontend whose operand type includes `null` — 24 of 27 —
     is correct, because the guard sits upstream of a boundary TypeScript's narrowing cannot
     cross: a `filter` before a `map`, a closure that captures after an `&&`, a short-circuit
     chain. A detector keyed on the type alone reports all 24 as defects. To be useful it would
     have to reimplement control-flow analysis and then beat it. Write down that the class was
     examined and why no guard exists, or the next person builds the noisy version and spends
     a day dismissing it.

173. **Key the guard on the property, not on the API the defect happened to use.**
     FS-675 swept for discarded `asyncio.create_task` calls and found two broken collectors.
     It was structurally blind to a third with the identical shape — `sparkplug_b.py`, which
     registers a paho callback and calls `loop_start()` — because that file uses
     `run_coroutine_threadsafe` instead. It was correct; the guard would not have known if it
     were not. The property is *a driver thread calls back into us*, and the guard now keys on
     the thread markers rather than on any one delivery API.

174. **Before building the fix, grep for someone who already built it.**
     `sparkplug_b.py` captured its loop in `start()` and delivered through
     `run_coroutine_threadsafe`, with a docstring naming the thread boundary — the exact
     pattern FS-675 needed, sitting one directory entry away from the two files that lacked it.
     A grep for `run_coroutine_threadsafe` would have produced both the fix and the precedent
     in a single step. This is rule 141 again, and it keeps recurring because the reflex when
     you understand a defect is to write the cure rather than to look for it.

175. **A measurement taken while something else is writing is not a measurement.**
     Three concurrent coverage runs sharing `coverage/.tmp` produced twelve failures and four
     timeouts, which read exactly like a broken CI gate — and I reported it as one. Vitest had
     printed the cause in the same output. Earlier in the same session, two pytest suites
     against one database produced the same class of phantom. Before believing any failure,
     check what else is touching the resource: the tool usually says so, in the part of the
     output you skip when you already have a hypothesis.

176. **A ratchet with no margin fails on the next unrelated change, and that trains people to
     lower it.** Statements cleared the gate by 0.02 points against a config documenting ~1
     point of intended slack. Nothing was broken and nothing would have reported it until a
     one-line change turned the build red for a reason that had nothing to do with that line.
     The repair is tests, not a threshold edit — and after adding them, deliberately NOT
     raising the threshold to the new floor, which would recreate exactly the state you just
     left.

177. **A test that only runs in one environment is a test nobody has watched run.**
     `authenticated.spec.ts` died on `ReferenceError: EMAIL is not defined` every single
     execution, and had done since it was written. It skips without a live backend, so no
     laptop run showed it; the failure was only ever visible in a job whose output nobody
     reads when it is green overall. Anything gated behind an environment flag needs one
     deliberate run under that flag before you may count it as coverage.

178. **An assertion that can be satisfied by the state *before* the action is not an assertion.**
     `click()` then `expect(page).toHaveURL(/\/login/)` passes because, a quarter-second after
     the click, the URL has not changed yet — whatever the server is about to say. It passed
     identically with the correct password. Assert on something only the outcome produces: the
     response status, the rendered error, the navigation that did or did not happen.

179. **Rendering more correctly can break a test that was passing by racing.**
     Adding a `<main>` landmark to a page — a plain accessibility improvement — broke a guard
     whose locator `main, body` matches two elements once React mounts, a strict-mode
     violation. It had passed everywhere only by evaluating in the instant before `<main>`
     existed. When a correct change breaks a test, check whether the test was relying on the
     defect's timing before assuming the change is wrong.

180. **Check that every directory of code you own is read by some compiler.**
     `tsconfig.json` included `src` and nothing else, so `e2e/` — six Playwright specs making
     the most security-relevant claims in the repository — was typechecked by nobody, and
     `vitest run` does not typecheck. A `ReferenceError` sat in one of them for its entire
     life. The gap is invisible from inside the directory: the files import cleanly, the tests
     run, the suite is green. Ask instead, from the config outward, which paths any compiler
     actually reads.

181. **A guard whose subject list is hand-typed is blind exactly where nobody was looking.**
     `test_branch_pushes_reach_the_gates.py` exists to refuse "a check that only runs in the
     wrong workflow", and it passed while 386 edge-agent tests ran on `main` only — because
     its `REQUIRED_ON_BRANCH_PUSH` named five gates and not that one. The repair is not a
     sixth entry; it is a second check DERIVED from the other workflow, so a gate nobody
     thought of cannot hide behind a list nobody updated.

182. **A comment describing an intention is not the intention being carried out.**
     The flake8 step's own note argued for covering `backend/tests` and
     `edge-agent/opsgrid_agent`, called the moment cheap, and explained why it mattered — and
     the command under it covered neither. The prose was right, persuasive, and false, and it
     read as evidence the work had been done. When a comment states a scope, check the line
     below it against the claim.

183. **Point the question at the configuration, not at the code.**
     Three consecutive findings — a `ReferenceError` living for years in `e2e/`, a whole
     codebase with no branch-push gate, and 528 Python files no linter read — all came from
     asking *which paths does a checker actually read?* and never from opening a source file.
     From inside an unchecked directory nothing looks wrong: imports resolve, tests run, the
     suite is green. The gap is only visible from the config outward, and it hides best where
     it costs most, because a directory nobody checks is usually a directory nobody visits.

184. **A citation is a claim, and claims decay.**
     Two comments named guard files that do not exist — one of them a file that never has.
     Both guards were real; only the trail was broken, which is worse than no comment, because
     the reader who follows it must choose between "the protection was deleted" and "I
     searched wrongly". In a codebase that explains itself by cross-reference, the references
     need the same treatment as any other number in prose: something has to check them.

185. **Narrow the scope until the detector is right, rather than adding exclusions until it is quiet.**
     The citation checker first flagged thirteen lines, including its own explanation of the
     defect and the sentence that corrects the original. An exclusion list would have grown
     with every future explanation. The fix was a principle instead: source comments are claims
     about the present, tests and documents narrate history — so check source only. Scope is a
     reason; an allowlist is a record of the times the reason was absent.

186. **Writing up a defect can trip the guard for that defect — and that is the guard working.**
     Documenting two stale filename citations meant naming both files, and the existing
     documentation guard failed on that prose in the same run. The reflex is to treat the
     failure as noise from an over-eager check; it is not. The register of deliberate
     exceptions is the designed answer, and using it leaves the exception stated with a reason
     instead of silently widened. If a guard fires on your explanation, the explanation is a
     real instance of the shape — write it down as one.

187. **A ratchet that counts correct code names a change that would do harm.**
     The swallow ratchet excludes handlers that re-raise but not handlers that return the
     error as a value, so twelve correct health checks read as the largest block of debt in
     their file. The cheapest way to shrink that number is to raise instead — turning a
     per-component readiness report into a 500 whenever any dependency is slow. Before
     reducing a ratchet, ask what the cheapest reduction would do; if the answer is "harm",
     the population is wrong and the property needs pinning rather than the number reducing.

188. **Stub the failing state the code actually has, not the one you imagine.**
     Testing that a health aggregator survives a broken dependency, I stubbed the checker to
     raise. Every assertion failed, and it looked like a finding for about a minute. The
     aggregator deliberately does not wrap its checkers — each catches its own failure and
     returns it — so a raising stub removes the behaviour under test and reports its absence
     as a defect. Read how the real thing fails before writing the double that stands in for
     failure.

189. **A document that states the same quantity twice will eventually disagree with itself.**
     The README claimed `~3,200 pass` in its run-command block and `4,090+ tests` two hundred
     lines below, where a guard asserts the second. The guarded figure stayed true and the
     unguarded one drifted by thirteen hundred, so the document contradicted itself in a way
     no check could see. When the same number appears twice, either guard both or make one of
     them point at the other — a reader who finds two answers stops trusting the one that is
     right.

190. **Guard the number a newcomer meets first.**
     The frontend line — `~525 across 73 files`, against 1,089 across 133 — was the figure a
     developer compares their very first `vitest run` against, and it was the only major count
     in the document with no guard at all. Staleness costs most where it is met earliest: the
     newcomer cannot tell a stale doc from a broken checkout, and the natural conclusion is
     that they broke something.

191. **A fix verified against a double is a claim about the double.**
     FS-675 was proven with a `threading.Thread` standing in for paho's network thread — which
     asserts that Python raises off-loop, not that paho behaves as assumed. Against a real
     mosquitto broker the numbers are 0 readings before the fix and 3 after, with the same
     `no running event loop` error a production log would have shown. Where the infrastructure
     is one container away, run it: the double proves the mechanism, the real thing proves the
     defect.

192. **A guard that reads state written after an `await` can never win.**
     `on_modified` skipped files already in `_processed_files`, and `_process_gcode` added to
     that set at its end — after `await _wait_for_file_stable(...)`. A single write emits both
     `on_created` and `on_modified`, so both coroutines were in flight before either marked
     anything, and every sliced file was emitted twice. Claim the resource synchronously,
     before the first await; a check-then-act split across a suspension point is not a check.

193. **Run the real thing twice: once to prove the fix, once to see what else it does.**
     Driving the file watcher against a real `Observer` confirmed FS-675 (0 files processed
     before the fix, 2 after) and, in the same output, revealed that 2 was itself wrong. The
     unit tests could not have shown it — they deliver one synthetic event, which is exactly
     what the code handles correctly. The live run answers a question the double never asks:
     *what does the environment actually send?*

194. **Count a metric's call sites against what it claims to cover — one is not zero, and
     one is the tell.** The obvious version of this check is "find metrics nobody emits",
     and it would *not* have found FS-691: `errors_total` had a caller, in the coordinator.
     Exactly one, for an error counter labelled per collector across fifteen collector
     types. That disproportion is the signal — a metric whose label set promises per-asset,
     per-type resolution and whose emission happens at a single site is being fed by one
     path out of many. Run the zero-call-site sweep too (it found `COLLECTOR_MESSAGES`,
     reachable only through a helper nothing calls), but do not mistake it for this one.

195. **A shared seam covers one direction only; ask what the failing case looks like there.**
     `metrics.py` claimed the coordinator/adapter seam covered every collector "without
     editing individual collectors", and for deliveries that was true — every reading funnels
     through it. A *failed* poll produces no reading, so it never arrives at the seam at all.
     The property that made the seam attractive is exactly the property that made it blind:
     it is on the success path. When a design routes everything through one point, check
     whether the error path reaches that point, or merely the happy one.

196. **Liveness derived from the worker is not liveness of the work.**
     `connection_state` was set from `task is not None and not task.done()`. A collector
     polling a device that answers 500 forever has a perfectly healthy task — it is the
     device that is dead — so the gauge read *up* while the asset produced nothing for as
     long as you cared to wait. And the alert that should have caught the silence was
     silenced by it: `EdgeAgentBufferHigh` watches buffer depth, which stays at zero
     *because* nothing was collected. Health derived from the mechanism will report the
     mechanism; measure the output.

197. **`task.exception()` on a cancelled task raises; ask `cancelled()` first.**
     The health monitor inspected done collector tasks with `task.exception()` inside
     `except Exception` — and for a cancelled task that call *raises* CancelledError, a
     BaseException since 3.8, which no `except Exception` can catch. One config hot-reload
     could therefore kill all collector supervision permanently: the liveness gauge frozen,
     auto-restart gone, one unexplained traceback as the only trace. The sweep across both
     codebases found the two `spawn` helpers already asking `cancelled()` first and exactly
     one raw site — the monitor. The general form: any code that inspects a task it did not
     just create must treat cancellation as a state, not an error to catch.

198. **Sweep for endpoints nobody calls before sweeping for features nobody built.**
     Surveying all 37 pages against their routers found the dominant gap was not missing
     capability but UNREACHED capability: export schedules (nine endpoints, zero frontend
     references), all of `logistics_correlation.py`, all of `model_monitoring.py`, OEE
     losses, alarm and asset filters, SSO, the telemetry metrics list. Twelve shipped
     enhancements needed **two** new backend routes between them; everything else was a
     wire. A product can be a full release behind its own API, and the cheapest large
     wins are always on that boundary — so enumerate routes-versus-callers before
     designing anything.

199. **Assert the request, not the rendering, when what you care about is what the system
     does.** A `<select>` displays its first option as its value whether or not state
     followed it, so a test reading `select.value` passed with the state-sync effect
     deleted. The metric the historian is actually *asked for* is the thing that matters,
     and only asserting on the outgoing call could see it. Wherever a control's display
     is derived rather than bound, the display is a weaker witness than the effect.

200. **When the right answer's text is not unique, assert the absence of the wrong one.**
     A row for a paused schedule shows "paused" in its status badge AND should show it in
     place of a next-run date, so `findAllByText(/paused/)` passed while the cell still
     printed the stale date. Asserting that no date is rendered — with a negative control
     that a live schedule does show one — is the check that distinguishes them.

201. **A mutation that survives is not automatically a hole in the test; ask which layer
     caught it.** Deleting the explicit `organization_id` filter from a handler did not
     fail its tenancy tests, because a migration had since given the table an RLS policy —
     the row was invisible to the query either way. That is defence in depth working.
     Both layers were kept for different reasons (RLS is the one a new handler cannot
     forget; the explicit filter is the one that survives a session opened without the
     GUC), and the test file now says which one it is actually proving. The wrong move is
     to conclude the test is weak and add an assertion that pins the redundant layer.

202. **An unused client carrying a guessed shape is the defect you sweep for, written by
     the sweeper.** A speculative `getHistorical` was added with a `points` array of a
     declared row type; the endpoint sends `data` with open rows, and
     `test_frontend_fields_exist_on_the_wire.py` refused it. The method was deleted rather
     than corrected: an accurate type for a function nothing calls is still a claim
     nothing checks. Write the client when the screen needs it.

203. **A guard that rejects your work is usually right; fix the detector only after
     proving it wrong.** In one arc, four guards refused good-looking changes — a
     per-call `onError` that read as silent at the mutation, a hand-rolled header read
     that bypassed the shared truncation helper, an inline `toLocaleString`, an
     unreviewed role policy — and each was a genuine correction. One was the detector's
     fault: the truncation sweep recognised its idiom only *before* the `api.get` call,
     flagging the equally-correct capture-then-wrap shape needed to read a second header
     off the same response. Widening that window was right; widening it before checking
     the other four would have been four regressions.

204. **A register entry that says "deliberate" about a field the service does honour is
     worse than no entry.** The declared-body-fields extractor read the handler body only,
     so five correlation routes that hand the whole request to a shared executor — the
     natural shape once three routes want the same work, one synchronous, one queued, one
     preview — measured as reading *nothing*. Registering all five would have recorded
     `POST /answer`'s `question`, the entire point of the route, as a reviewed drop. The
     extractor now follows a forward two hops, across a `from app.api.… import` as well as
     within a module, and the `model_dump()` exemption is checked against the *followed*
     reads rather than the handler text. Before registering a batch, ask whether the
     detector can see the shape the code is actually written in.

205. **Ask what the cheapest reduction of a ratchet would do — and then notice when you
     have just done it.** Twenty new routes wanted `response_model`, their payload keys are
     chosen by the engine per request, and a closed model would delete tomorrow's keys
     silently. `response_model=Dict[str, Any]` looked like the honest answer to that: it is
     precedented in the tree, it does not filter, and it satisfies the coverage ratchet. It
     is also exactly what `test_a_permissive_response_model_is_not_a_contract.py` exists to
     refuse (rule 187), and that guard caught it about an hour later. The real answer was a
     model with `extra="allow"`: named fields in the schema, the SDK and the contract gate,
     and every undeclared key still passing through — **verified against a live response
     rather than taken from the docs**, and the verification kept as a test, because an
     exemption resting on framework behaviour nobody measured is how a real drop gets waved
     through.

206. **A guard can pass its own mutation test for the wrong reason.** A new rule accepted a
     JSX gate as safe when the failure path cleared it, implemented as "a `setX(null)`
     within 600 characters of the word `catch`". Deleting the real fix changed nothing —
     a reset helper elsewhere in the file called `setEvidenceResult(null)` shortly after an
     unrelated `catch`, so the rule had been reading the wrong evidence all along and the
     mutation could not move it. Brace-matching the actual catch body fixed it, and the
     mutation then failed exactly where it should. **Run the mutation; if it does not fail,
     that is a finding about the guard, not a formality that passed.**

207. **A line break can empty a sweep's population, and only the vacuity check will say
     so.** `idKeyedFetchesDoNotGoStale` matched a fetch with `Api\.`, requiring the receiver
     and the dot to be adjacent. The tree's one id-keyed fetch is a wrapped promise chain —
     `transportationApi\n  .getShipmentCosts(…)` — so the population fell to zero and every
     id-keyed detail view went unchecked. No code changed; formatting did. The count-based
     honesty check is the only thing between that and a permanently green guard over an
     empty list.

208. **Scope a per-file sweep to the component, not the file.** `failureIsNotEmptiness`
     already held the principle — a presentational list given its rows as props cannot fail
     a request — and tested it, but applied the query check per FILE. A 1,900-line page
     module that declares its own drawer beside it therefore put every phrase in that
     drawer in scope, because the *page* fetches. Two more false positives in the same run
     came from matching the argument of `setEvidenceError(...)`: the string *is* the
     failure branch, and reporting it as an empty state inverts the finding.

209. **A session handed across a module boundary is still your session, and a file-local
     tenant check cannot see it.** `operations_assistant.py` took `Depends(get_db)` and
     named no RLS-backed model anywhere — it passes the session to a helper imported from
     the correlation router, which reads `intake_items` under FORCE ROW LEVEL SECURITY. So
     the static guard cleared it and **both operations endpoints answered 404 for the
     caller's own uploads**. The same blindness one layer down cost more: the async job's
     `AsyncSessionLocal()` sits in a nested `async def run(report)` whose entire body is a
     call, so it named nothing either, and **every queued evidence job failed** with an
     error that reads as "you passed bad ids". A background task is where this always
     hides — it has no request to take a dependency from, so it builds its own session, and
     the query is always somewhere else. Both halves of the guard now follow the call.

210. **The same bug can live in two halves of one file, and fixing one half does not fix
     the other.** This guard learned in FS-431 that prose is not code: it stripped comments
     before counting `Depends(get_db)`, because a comment explaining that a handler no
     longer takes the unscoped session had been counted as a handler that does. The
     `AsyncSessionLocal` half of the same file still read raw source. Reverting a fix left a
     comment saying why the GUC matters, the word `current_org_id` appeared in the function
     body, and the guard exempted the very function whose session had no GUC — so the
     mutation test passed and reported the guard as working. When you fix a detector flaw,
     grep the file for the other places that make the same assumption.

211. **Recognise the extracted helper, or the false positive teaches someone to add an
     exemption.** Stripping comments made the inline check honest and immediately flagged
     `run_erp_sync`, which binds its tenant correctly through `_set_tenant_guc(db, org)` —
     the extraction any file makes once it does the thing twice. Only the inline spelling
     was recognised. The natural response to a false positive is an exemption entry, and
     that is how a guard quietly loses the ability to see the real thing; following the
     call one hop keeps both the check and the list honest.

212. **A table with no `organization_id` column has no RLS, and the tenant session is
     doing nothing for it.** `operations` is tenanted through its ASSET — there is no org
     column, so no policy of the usual shape exists and `get_tenant_db` protects it not at
     all. Four of the router's five handlers wrote `select(Operation).where(id == …)` or,
     worse, a bare `select(Operation)`: any authenticated operator could read, summarise
     and **complete another organisation's production run**, and `GET /operations/`
     returned every tenant's rows. The fifth handler joined `assets` under a comment saying
     the join "is no longer optional" after this same defect had been fixed *there* — one
     handler of five. When a fix is a JOIN somebody must remember, put it behind a helper
     so the shortest way to write the query is the correct one.

213. **Belt-and-braces that a mutation cannot distinguish is still worth keeping, if you
     say why.** The scoped query carries both a join to `assets` and an explicit
     `Asset.organization_id == :org`. Deleting the predicate alone fails no test, because
     `assets` is FORCE RLS and the join inherits that filtering — so by the usual standard
     it is dead weight. It stays because that protection is a property of the SESSION, not
     of the query, and the defect above existed precisely because someone assumed the
     session was doing the work. The comment records the mutation result, so the next
     reader deletes it deliberately or not at all.

214. **A gate that can hang reports nothing, which is strictly worse than a gate that
     fails.** The contract suite's `call_and_validate()` had no request timeout, so one
     unresponsive operation stopped the whole job: no junit XML, no conformance count, and
     the ratchet step then reading "collected 1 operations" and blaming the schema. It
     presents as SLOWNESS — a run sat for over an hour having used one minute of CPU in the
     last ten — which is why nobody had looked. A 30-second per-request timeout turns the
     same surface into a 15-minute run that fails ONE test with the operation's name on it.
     Any long-running check that talks to something should be asked what it does when the
     other side never answers.

215. **When a guard refuses your number, take the measurement instead of doing the
     arithmetic.** Raising the without-broker floor to 436 left the with-broker floor at 393,
     and a guard failed: the configuration that reaches MORE operations cannot be held to a
     lower bar. The tempting fix is to write 445-something in the higher slot, which is
     arithmetic dressed as a floor. The run with a broker took seventeen minutes and gave
     449 — and it also **corrected the reasoning that would have justified the guess**: the
     broker-dependent set had been described as "~20 operations" across three documents, and
     is worth four. A number inherited and never re-measured is the same defect whether it
     sits in a README, a ratchet or a comment.

216. **A foreign key is checked below RLS, so a WRITE can name a row you cannot read.**
     Three shop-floor writes took an `asset_id` and never asked whose asset it was. The
     column is a foreign key to `assets`, which is FORCE ROW LEVEL SECURITY — and the
     database performs referential integrity at a level the policy does not filter, so the
     reference was accepted and org B logged downtime against org A's machine with a 201.
     Reading is protected and REFERENCING is not; the row lands in the writer's own tenancy
     carrying a pointer across the boundary, which is why no tenancy test looking for
     leaked reads would see it. Ask of every caller-supplied id what proved it belongs to
     the caller — the answer "the foreign key would have failed" is only true for ids that
     exist nowhere.

217. **Reasoning about a library's failure modes lists the ones you thought of.** A
     timezone validator caught `ZoneInfoNotFoundError`, so an empty name — which raises
     `ValueError` — answered 500 where every other bad value answered 400. The fix caught
     `ValueError` too, having reasoned about it. Then its own test, which included a
     300-character name because that is the shape a fuzzer sends rather than because
     anybody predicted it, found a THIRD: `OSError: File name too long`. `ZoneInfo`
     resolves a name to a file, so the failure modes are the filesystem's, and the list of
     them is not derivable by thinking about timezones. Put the hostile shapes in the test
     and let it tell you what the library does.

218. **Fix every door onto the field, not the one the report named.** A subscription's
     `asset_id` could be pointed at another tenant's asset by the CREATE — and equally by
     the PATCH, which this same arc had added. Fixing the create alone would have left the
     newer route reintroducing the older defect the week after it was closed. When a field
     is the defect, enumerate the routes that can set it.

219. **A route can be half-fixed and look wholly fixed, if the probe never got past
     validation.** The sweep that typed three shop-floor `asset_id` fields sent ONE body
     shape to every route. `quality-events` requires `description`, so it answered 422 and
     read as already-correct — while its ownership check was reached and its malformed-id
     path still returned 500. A 4xx from a probe means "this input was refused", never
     "this route is fine": give each route the minimum body its own model demands, or the
     result measures the probe rather than the route.

220. **The error shape a client is most likely to parse is the one worth checking hardest.**
     Every error in this API is problem+json; the rate limiter alone answered plain
     `{"detail": ...}`, so 429 was the single response the generated SDK could not handle
     generically — and 429 is the one whose correct handling is automatic (back off, retry).
     A special case is worst where the client is a program rather than a person.

221. **A comment explaining why something is excluded is half a rule; the other half is a
     check.** `common_responses` omits 409 with an argued reason — most routes cannot
     conflict, and over-promising misleads a generated SDK as much as under-promising. That
     reasoning was correct and unenforced, so the 45 routes that CAN conflict did not
     declare it either. When a design note says "these belong on the routes that raise
     them", the routes that raise them are a derivable set: derive it and assert both
     directions.

222. **Measure the artefact, not a grep of its log.** A failure taxonomy reported "60
     Content-Type failures" in a contract run. There were none: the count came from
     schemathesis's own curl reproduction lines, every one carrying
     `-H 'Content-Type: application/json'`. The junit XML has the failures structured and
     was right there. A grep over a log measures the log — including the parts of it that
     are examples, prose, or someone else's command line.

223. **Check a generated edit against the thing it generates.** Scripting one keyword into
     45 route decorators failed three times, each on a decorator SHAPE: a trailing comma
     before the closing paren, a `)` alone on its own line, and four routes that already had
     a `responses=` map and needed a merge. Reading the diff would have shown plausible
     lines; `import app.main` after each attempt named the file and the line. When a change
     is machine-written, the machine that consumes it is the reviewer.

224. **A negative result from a fixture missing the state the path needs is not a negative
     result.** Probing whether an activation could reference another tenant's asset returned
     201 and ZERO rows written — which reads as "no defect". The row is a Kanban task, and
     the task is only created when the caller's board exists; a fresh test tenant has none,
     while every real deployment does. Bootstrapping the board produced the cross-tenant
     write immediately. Before believing a probe found nothing, ask what state the code path
     needs and whether the fixture has it.

225. **An id can cross the boundary one object after the route that accepted it.**
     `insight_activations` has no `asset_id` column, so a sweep matching request fields
     against the columns of the table a route writes to clears that route completely. The
     value is carried into the Kanban `Task` the activation creates, and `tasks.asset_id` is
     the foreign key. Follow the value to where it is STORED, not to the table the route is
     named after.

226. **Reading only the tail of a command's output is the same defect as hiding it — and
     this session committed it three times.** Sixteen `git push`es looked like they had
     failed because their output was suppressed (the cause was a shell quoting bug). A
     contract-gate run failed invisibly because `migrate.py` was piped to `/dev/null`. Then,
     pushing a security notice to fifteen branches, the success check read `tail -1` of each
     push — and a legitimately rejected non-fast-forward on an active branch was counted as
     a success, leaving the one developer most likely to pull without the warning. It was
     caught by the verification pass afterwards, which is the only reason it is a footnote
     rather than the finding. **Check the outcome, never the transcript.**

227. **Put the recovery refs down before you touch anything.** A malicious force-push
     replaced seventeen branches, and nothing was lost — the attacker overwrote REFS while
     every original object was still local. The first action was writing all seventeen
     pre-attack tips to `refs/rescue/*`, before a single restorative push, so that no `gc`
     and no later mistake could drop them. The restore itself then used
     `--force-with-lease=<ref>:<attacker-commit>`, which pins each push to the state being
     replaced: if anything had arrived in between, the push fails instead of destroying it.
     Recovery from a destructive event is itself a destructive operation.

228. **A locator matches text; it does not match meaning — and a filter control repeats
     every value on the page.** Two e2e tests asserted
     `getByText(/CNC Mill|Conveyor|…/).first()`, which held only while nothing else on the
     page carried an asset name. The page-enhancement arc then added filter bars to
     `/assets` (P6) and `/alarms` (P1), whose dropdowns list exactly those names, so
     `.first()` resolved to an `<option>` inside a closed `<select>` — hidden by definition
     — and both tests failed against pages rendering correctly. **Adding a control that
     repeats data invalidates every test that searched for that data by text.** Ask for the
     element that carries the meaning: the card's heading, the row's link.

229. **A test that passes alone and fails in the suite is asserting the ordering, not the
     property.** The `/alarms` locator above did exactly that: whether the filter dropdown
     had finished loading decided which element `.first()` picked. It would equally have
     passed while the rows rendered nothing. This is the second instance in one session —
     the first was a handler test driving `asyncio.get_event_loop().run_until_complete`,
     green alone and red once another test had closed that loop. Both were found only by
     running everything, which is the argument for doing that before every commit rather
     than after the interesting ones.

230. **A reporter built for a terminal is a transcript, not an artefact — and piping it
     invents findings.** Two runs of the same 131-test e2e suite accounted for 131 and 105.
     The shortfall looked like tests silently not running, which is a serious class
     (FS-490). It was the `line` reporter: it redraws its progress line with terminal
     control codes, and its final tally does not survive redirection to a file. A
     `--reporter=json` run attributed all 131, all passing. The suspicion was recorded
     rather than asserted and the next step was named, which is what kept a fictional
     coverage gap out of the permanent record — but the cheaper move is to reach for the
     structured reporter the first time, exactly as rule 222 says of logs.

231. **A comment that states an invariant is a place to check whether the code keeps it.**
     Rule 221 says a design note naming a derivable set specifies a test. The stronger
     version: a note asserting *"X must never happen"* is a claim to verify on the spot.
     Three lines below `# a webhook caller must never mutate another tenant's trip via a
     device-id collision` sat `if org_id:` — a conditional that made absence mean
     unrestricted. Grepping `must never` across `app/` took a minute and found six such
     claims; five were kept, and this one was not.

232. **The denominator test is where the bigger defect lives.** The cross-tenant assertions
     for that webhook passed immediately — the interesting one was "and the owner's own
     position still works", which failed with `new row violates row-level security policy`.
     Every table those handlers write is FORCE RLS and the route binds no tenant, so the
     receiver had never stored anything on any deployment. **The test that proves the
     feature works is the one that finds it does not** — and it is the test most easily
     skipped, because the defect being chased is about somebody else's data.

233. **State the population a sweep covered, not the population it was about.** FS-729
     ended with *"of 12 request models accepting a tenant-owned foreign key, all 12 verify
     the id"*. True, and about a fifth of the subject: the scan iterated `app/api/*.py`,
     and most request models in this codebase live in `app/models/schemas.py` — 62 more
     fields the detector never saw. Rule 102 says a sweep scoped to one IDIOM is blind to
     the same defect in another; this is the same failure scoped to one DIRECTORY, and it
     is harder to notice because the scan looks exhaustive within its own loop. Before
     writing "complete", print the denominator and ask where else that thing is declared.

234. **A guard that exempts on the PRESENCE of a construct exempts on a coincidence.**
     `test_declared_body_fields_reach_the_service.py` skipped any route whose handler
     mentioned `model_dump()`, on the reasoning that a forwarded body cannot drop a field.
     Adding an ownership check to `create_task` — `supplied = task_data.model_dump(...)`,
     then five lookups — removed the route from the sweep entirely and left its register
     entry stale. A handler that dumps the body to INSPECT it drops exactly as much as one
     that never dumped it. Measured: 31 of 101 body-taking routes took the exemption, 17
     by binding the dump to a local. Exempt on the USE — splatted or iterated, every key
     is applied; bound and read key by key, only the named keys count — and state what
     the exemption covers. A guard weakened by an unrelated change is the failure a
     register exists to prevent, so the exemption must be as specific as its own argument.

235. **When a field is validated on one verb, check the other verb before believing it.**
     `update_task` refused a `parent_task_id` in another tenant; `create_task`, thirty
     lines above it on the same model, accepted it. Create and update are read as a pair,
     which is exactly why an inconsistency between them survives review: whichever path a
     reader opens first answers the question they arrived with. Put the per-field check in
     a helper both call, rather than in whichever handler the report named.

236. **A second entrance to a guarded surface starts with none of its guards.** The
     command API performs three checks — asset ownership, remote operations belong to the
     Fleet API, `emergency_stop` needs an admin — and all three live in its ROUTE. So
     `completion_actions.execute_command` on a kanban task reached `submit_command` with
     none of them, and an operator could queue an emergency stop by completing a card.
     Ask what else calls the service, and put the invariant where the surface is rather
     than where the report came from.

---

## Open observations, not yet tickets

**CLOSED (FS-703).** The observation below was fixed the session after it was recorded: the
monitor now defers to a held `_restart_locks` entry (`restart_deferred_to_operator`), and a
failed operator restart is still recovered because it leaves a done task for the next pass.
Kept for the record of how it was found:

**The health monitor's auto-restart and `restart_collector` can race on a crashed task.**
The monitor restarts any done-and-not-cancelled task whose config is enabled
(`coordinator.py`, the FS-698 block), calling `_start_collector` directly; `restart_collector`
serialises itself through `_restart_locks`, which the monitor never takes. A collector that
crashes moments before an operator triggers an API restart can get two `_start_collector`
calls: the second overwrites the first's dict entries and the first's task runs orphaned —
two collectors polling one device. Needs the monitor to honour `_restart_locks` (skip a
collector whose lock is held), which touches restart semantics and deserves its own change
rather than a rider on FS-698. The cancel-window half of this race no longer exists —
cancelled tasks are skipped, not restarted.

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

