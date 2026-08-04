"""The nine allowlisted 5xx endpoints stay fixed (FS-431).

`_lane_failures.py` is empty. Both real-database walks assert in both directions, so a
regression there is caught — **but they skip without Docker**, and on a laptop an emptied
register and a worked-down one look exactly alike. That is the gap this file closes: every
assertion here is structural and runs with no database, no server and no network.

WHAT WAS ACTUALLY WRONG, since four of the five recorded causes were not:

  * **Name shadowing, not a bad `select()`.** `nlp_correlation.py` defines a Pydantic
    `IntakeItem` for its response body and imports the ORM class as `IntakeItemModel`. One
    read reached for the Pydantic one. The register said "select() is given the class rather
    than a column expression" — but `select(SomeModel)` is correct SQLAlchemy 2.0, so the
    recorded reason described working code.
  * **A category error, not three missing fields.** `/kanban/rules/premade` declared
    `List[TaskRuleResponse]`; a template has no id, no organisation and no timestamps until
    someone creates one, so ten required fields were absent, not three.
  * **A relative path, not a missing request body.** `POST /engines/correlation/generate`
    takes no body. `StateSpaceLoader("state_space")` resolved against the working directory,
    loaded nothing, and said nothing — `random.choice` failed on an empty sequence several
    frames later. Run by hand from `backend/` it passed, which is how it stayed misdiagnosed.
  * **A guard that could not fire, not a missing decision.** The RAG entries were held for
    "a decision on whether an absent store is degraded or fatal". `document_link` had
    already made it — 503. What defeated it is that `DocumentStore.available` is
    `aioboto3 is not None`, a package-installed check that is True everywhere and can never
    observe an unreachable store.

Only the write-on-read cause was recorded correctly, and it was correct about all four of
its endpoints.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from app.main import app
from tests._route_tree import http_routes

API_DIR = Path(__file__).resolve().parent.parent / "app" / "api"

#: Prose is not code — the same rule three other guards in this directory learned the hard
#: way. Every comment written above these fixes NAMES `get_db`, so a substring search over
#: raw source would find the thing it is asserting is gone.
_DOCSTRING = re.compile(r'("""|\'\'\')(?:.|\n)*?\1')
_COMMENT = re.compile(r"#[^\n]*")


def _code_only(source: str) -> str:
    return _COMMENT.sub("", _DOCSTRING.sub("", source))


class TestTheSweepIsNotVacuous:
    def test_prose_naming_get_db_is_not_counted(self):
        assert "get_db" not in _code_only(
            'def f():\n    """uses get_db"""\n    # Depends(get_db)\n    pass\n'
        )

    def test_a_real_call_is_counted(self):
        assert "get_db" in _code_only("def f(s = Depends(get_db)):\n    pass\n")


class TestTheWriteOnReadCause:
    """One unbound tenant session, four allowlisted endpoints, plus five nobody probed."""

    @pytest.mark.parametrize("module", ["kanban.py", "nlp_correlation.py"])
    def test_no_handler_takes_the_unscoped_session(self, module):
        code = _code_only((API_DIR / module).read_text())
        assert "Depends(get_db)" not in code, (
            f"{module} takes the unscoped session again. Its tables are under FORCE ROW "
            f"LEVEL SECURITY, so a read returns zero rows regardless of any explicit "
            f"organization_id filter — RLS removes the row before the filter sees it — and "
            f"a write is refused outright. This 500'd four endpoints and silently emptied "
            f"the rest"
        )

    @pytest.mark.parametrize("module", ["kanban.py", "nlp_correlation.py"])
    def test_the_unscoped_session_is_not_even_imported(self, module):
        """Out of scope, not merely unused: a new handler cannot reach for it by habit."""
        code = _code_only((API_DIR / module).read_text())
        assert not re.search(r"^from .* import .*\bget_db\b", code, re.M), (
            f"{module} imports get_db again; leaving the name unimportable is what stops "
            f"the next handler from repeating this"
        )

    def test_the_out_of_request_path_binds_the_tenant_itself(self):
        """`execute_completion_actions` runs outside a request, so no dependency binds the
        GUC for it. Without it the task lookup found nothing and every completion action
        silently did not happen — absence arriving as success, on a path that exists only
        for its side effects."""
        from app.api.kanban import execute_completion_actions

        code = _code_only(inspect.getsource(execute_completion_actions))
        assert "set_config" in code and "app.current_org_id" in code, (
            "execute_completion_actions opens its own session and no longer binds "
            "app.current_org_id; its tables are all FORCE RLS, so it will read zero rows "
            "and report a clean run having done nothing"
        )


class TestTheShadowedModel:
    def test_the_intake_read_uses_the_orm_class(self):
        from app.api.nlp_correlation import get_intake_item

        code = _code_only(inspect.getsource(get_intake_item))
        assert "select(IntakeItemModel)" in code, (
            "the intake read selects `IntakeItem` again — the PYDANTIC class this module "
            "defines for its response body, not the ORM model it imports as "
            "`IntakeItemModel`. Both names are in scope and both look plausible at the call "
            "site; only one is mapped, and passing the other 500s every request"
        )

    def test_both_names_really_are_in_scope(self):
        """The premise. If the shadowing is ever removed, the test above is guarding a
        condition that can no longer occur and should be deleted rather than believed."""
        import app.api.nlp_correlation as mod
        from pydantic import BaseModel

        assert issubclass(mod.IntakeItem, BaseModel), (
            "`IntakeItem` is no longer the Pydantic response model in this module; the "
            "shadowing this guards against may be gone"
        )
        assert hasattr(mod.IntakeItemModel, "__table__"), (
            "`IntakeItemModel` is no longer the ORM class"
        )


class TestThePremadeTemplates:
    def _route(self):
        hits = [r for r, path, _ in http_routes(app) if path.endswith("/rules/premade")]
        assert hits, "/kanban/rules/premade is no longer routed"
        return hits[0]

    def test_it_declares_a_template_model_not_a_rule_model(self):
        from app.models.schemas import TaskRuleResponse, TaskRuleTemplateResponse

        declared = self._route().response_model
        assert getattr(declared, "__args__", (None,))[0] is TaskRuleTemplateResponse, (
            f"declared {declared}; a template is not a rule. TaskRuleResponse requires a "
            f"UUID id, an organization_id and timestamps that a template cannot have before "
            f"someone creates one, so response validation raised on every call"
        )
        assert declared is not TaskRuleResponse

    def test_every_template_validates_against_what_is_declared(self):
        """The assertion the 500 was: FastAPI validates each item on the way out."""
        import app.api.kanban as kanban
        from app.models.schemas import TaskRuleTemplateResponse

        rows = _template_constants(kanban)
        assert len(rows) >= 5, f"only {len(rows)} templates found; the reader is broken"
        for row in rows:
            TaskRuleTemplateResponse.model_validate(row)

    def test_the_old_model_would_still_reject_them(self):
        """Mutation check. If TaskRuleResponse ever accepts these, the test above stops
        distinguishing the fix from the defect."""
        import app.api.kanban as kanban
        from pydantic import ValidationError
        from app.models.schemas import TaskRuleResponse

        with pytest.raises(ValidationError):
            TaskRuleResponse.model_validate(_template_constants(kanban)[0])

    def test_it_asks_for_no_database(self):
        """Five constants. It took `Depends(get_db)` and never used it."""
        from app.api.kanban import get_premade_rules

        params = set(inspect.signature(get_premade_rules).parameters)
        assert "session" not in params, (
            f"get_premade_rules takes a session again for five static constants: {params}"
        )


def _template_constants(kanban_module) -> list[dict]:
    """The premade list, read out of the source as literals."""
    tree = ast.parse(inspect.getsource(kanban_module.get_premade_rules).strip())
    lists = [n for n in ast.walk(tree) if isinstance(n, ast.List) and len(n.elts) >= 5]
    assert lists, "no template list found in get_premade_rules"
    return ast.literal_eval(lists[0])


class TestTheStateSpacePath:
    def test_it_is_not_resolved_against_the_working_directory(self):
        from app.services.correlation_ai_engine import CorrelationAIEngine

        code = _code_only(inspect.getsource(CorrelationAIEngine.generate_synthetic_scenarios))
        assert 'StateSpaceLoader("state_space")' not in code, (
            "the state space is loaded from a relative path again, so this endpoint works "
            "or 500s depending on where the server process was started"
        )
        assert "__file__" in code, (
            "the state-space path is no longer anchored to this file; a relative path here "
            "is the whole defect"
        )

    def test_a_loader_that_finds_nothing_says_so(self):
        """`Path.glob` on a directory that does not exist yields no entries and no error,
        so the wrong path produced a loader holding an empty dict and reporting success.
        Nothing failed until `random.choice` was handed an empty sequence several frames
        later, under a message naming neither the directory nor its absence."""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_dataset import StateSpaceLoader

        with pytest.raises(FileNotFoundError) as excinfo:
            StateSpaceLoader("/nonexistent/state_space")
        assert "state_space" in str(excinfo.value)

    def test_the_real_directory_still_loads(self):
        """Anchoring the path is only a fix if the anchored path is right."""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_dataset import StateSpaceLoader

        loader = StateSpaceLoader(
            str(Path(__file__).resolve().parent.parent / "state_space")
        )
        assert loader.data, "the anchored state-space directory loaded nothing"

    def test_the_nested_state_space_shape_does_not_break_a_draw(self):
        """`random.choice` indexes with an integer, so on a DICT it raises `KeyError: 2`.

        26 of the 487 top-level keys map to a dict of grouped lists (`liability_types` is
        `{"driver": [...], "carrier": [...]}`); the rest map to a flat list. So ~5% of draws
        raised, which is why `POST /engines/correlation/generate` failed at its default
        `count=100` and passed every time it was tried by hand with a handful.

        A defect whose reproduction probability rises with volume looks like flakiness from
        underneath and like a hard failure from the endpoint. 200 draws makes it certain.
        """
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_dataset import StateSpaceLoader

        loader = StateSpaceLoader(
            str(Path(__file__).resolve().parent.parent / "state_space")
        )
        nested = [
            (f, k) for f, cats in loader.data.items()
            for k, v in cats.items() if isinstance(v, dict)
        ]
        assert nested, "no nested keys left in the state space; this guard is now vacuous"
        for file_name, key in nested:
            for _ in range(5):
                assert loader.get_random(file_name, key) is not None, (
                    f"{file_name}/{key} draws nothing"
                )

    def test_group_names_are_not_returned_as_assets(self):
        """`get_random_asset` did `assets.extend(items)`, and extending a list with a dict
        adds its KEYS — so the pool gained 'driver', 'carrier' and every other group name
        and returned them as asset names. No exception, no wrong type, just occasional
        nonsense in generated training data."""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        from generate_dataset import StateSpaceLoader

        loader = StateSpaceLoader(
            str(Path(__file__).resolve().parent.parent / "state_space")
        )
        group_names = {
            k for cats in loader.data.values()
            for v in cats.values() if isinstance(v, dict)
            for k in v
        }
        assert group_names, "no grouped keys found; this guard is now vacuous"
        drawn = {loader.get_random_asset() for _ in range(2000)}
        assert not (group_names & drawn), (
            f"group names are being returned as assets: {sorted(group_names & drawn)[:5]}"
        )

    def test_the_count_is_bounded(self):
        """Generation is a synchronous loop and `count` was a bare `int = 100` with no
        ceiling — one request could occupy the process indefinitely. `ge=1` matters too:
        a negative count ran zero iterations and reported success."""
        route = [r for r, p, _ in http_routes(app) if p.endswith("/correlation/generate")]
        assert route, "/engines/correlation/generate is no longer routed"
        count = [p for p in route[0].dependant.query_params if p.name == "count"]
        assert count, "`count` is no longer a declared query parameter"
        meta = count[0].field_info.metadata
        bounds = {type(m).__name__: getattr(m, "ge", getattr(m, "le", None)) for m in meta}
        assert "Ge" in bounds and "Le" in bounds, (
            f"`count` has no lower and upper bound: {meta}"
        )


class TestTheUnreachableStore:
    def test_an_unreachable_store_is_translated(self):
        """botocore's `EndpointConnectionError` — what a dead SeaweedFS actually raises."""
        from botocore.exceptions import EndpointConnectionError

        from app.api.rag import _StoreTransportError

        exc = EndpointConnectionError(endpoint_url="http://seaweedfs:8333")
        assert isinstance(exc, _StoreTransportError), (
            "a connection failure to the object store is no longer caught, so it reaches "
            "the caller as a 500 — telling them this API is broken about a dependency "
            "being down"
        )

    def test_a_configuration_fault_is_not_translated(self):
        """Deliberate exclusion. A missing bucket or a rejected signature is a defect in
        THIS service, and 'try again later' would hide a broken deployment."""
        from botocore.exceptions import ClientError

        from app.api.rag import _StoreTransportError

        exc = ClientError({"Error": {"Code": "NoSuchBucket"}}, "ListObjectsV2")
        assert not isinstance(exc, _StoreTransportError), (
            "ClientError is now caught and returned as 503; a misconfigured bucket would "
            "be reported to callers as a transient outage"
        )

    def test_the_vector_store_is_covered_too(self):
        """The register named SeaweedFS. The DELETE actually failed on QDRANT first —
        `vectors.delete_by_doc` runs before any blob is touched — so a fix covering only the
        object store leaves the endpoint 500ing, which is exactly what the write walk said
        the first time this was called done."""
        from qdrant_client.http.exceptions import ResponseHandlingException

        from app.api.rag import _StoreTransportError

        assert issubclass(ResponseHandlingException, _StoreTransportError), (
            "a connection failure to the vector store is not translated; DELETE "
            "/rag/documents/{doc_id} will 500 when Qdrant is unreachable"
        )

    def test_a_vector_store_refusal_is_not_translated(self):
        """`UnexpectedResponse` means Qdrant ANSWERED and refused — a defect here, not an
        outage there. Same exclusion as botocore's ClientError."""
        from qdrant_client.http.exceptions import UnexpectedResponse

        from app.api.rag import _StoreTransportError

        assert not issubclass(UnexpectedResponse, _StoreTransportError)

    def test_available_on_the_vector_store_is_also_only_a_config_check(self):
        import inspect as _inspect

        from app.services.vector_store import VectorStore

        code = _code_only(_inspect.getsource(VectorStore.available.fget))
        assert "is not None" in code and "self.url" in code, (
            "VectorStore.available changed meaning; re-check the 503 translation in rag.py"
        )

    @pytest.mark.parametrize("handler", ["list_documents", "delete_document", "health"])
    def test_the_store_calls_are_wrapped(self, handler):
        import app.api.rag as rag

        code = _code_only(inspect.getsource(getattr(rag, handler)))
        assert "_StoreTransportError" in code, (
            f"rag.{handler} calls the object store without translating a connection "
            f"failure; `DocumentStore.available` is a package-installed check and cannot "
            f"tell you the store is unreachable"
        )

    def test_available_is_still_only_a_package_check(self):
        """The premise, asserted so it cannot quietly stop being true. If `available` ever
        becomes a real reachability probe, the wrapping above may be redundant — and that
        is a decision to make deliberately, not to discover."""
        from app.services.document_store import DocumentStore

        code = _code_only(inspect.getsource(DocumentStore.available.fget))
        assert "_session is not None" in code, (
            "DocumentStore.available changed meaning; re-check whether the 503 translation "
            "in rag.py is still the right shape"
        )
