# Task List: Hridyansh

Running task list for Hridyansh Sethi (`hriddzz@gmail.com`). Newest week on top.
See also: [PR Review of Hridyansh's branches](PR_REVIEW_hridyansh_branches.md).

---

## Week of July 6–10, 2026

### 1. Land the `opsgrid_agent` package rename (scoped PR) — **priority**

**Why it matters now:** The new industrial-fieldbus collectors (EtherNet/IP,
PROFINET, BACnet, CAN bus) and the HTTP/REST collector are implemented and wired
into `UnifiedCollectorCoordinator` on `main`. That wiring uses relative imports
and is naming-agnostic, but `coordinator.py` (and the other collector modules)
still carry the legacy `omniusgrid_agent` absolute imports. Until those are
fixed, the coordinator module can't fully import on `main`, so the collectors
can't run end-to-end. Your `hridyansh/package-renaming-fix` branch is what
unblocks this.

**The catch:** Per the branch review, `package-renaming-fix` currently bundles
~8,500 lines of unrelated deletions (`+411 / -8,506`) — entire backend modules
(`api_keys.py`, `audit.py`, `compliance.py`, `gdpr.py`, `middleware/`, etc.).
**Do not merge it as-is.**

**Action:**
- [ ] Cut a focused, rename-only PR that changes just the `omniusgrid_agent` →
      `opsgrid_agent` imports (the ~6 collector modules:
      `coordinator.py`, `mqtt.py`, `opcua_collector.py`, `modbus_collector.py`,
      `screen_scraper.py`, `file_watcher.py`, plus any `packml` references).
- [ ] Leave the newer collectors' relative imports untouched (no conflict).
- [ ] After merge, confirm `opsgrid_agent.collectors.coordinator` imports cleanly
      and the five new `collector_type`s (`ethernet_ip`, `profinet`, `bacnet`,
      `can_bus`, `http_rest`) resolve.
- [ ] Handle the unrelated deletions separately (drop them, or open a distinct
      cleanup PR if they were intentional).

**Definition of done:** Rename-only PR merged to `main`; coordinator imports and
registers all collectors; the edge-agent test suite still passes.

### 2. (Follow-on) Install optional collector driver libraries in CI/deploy

- [ ] The four fieldbus collectors import their drivers lazily
      (`pylogix`, `python-snap7`, `BAC0`, `python-can`) — added to
      `edge-agent/requirements.txt`. Confirm the deployment/CI images install the
      ones needed per site, and that a missing driver only disables its own
      collector (already handled in code; verify in a real image).
