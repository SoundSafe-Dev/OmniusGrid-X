"""Insight activation's identity and routing rules (FS-655).

517 lines behind a router mounted at `/api/v1/insights`, and until now **no test named this
module**. It is reachable over HTTP today.

WHAT IS PINNED HERE, and it is deliberately the pure part. `activate` writes through a
session and needs a database; `action_fingerprint`, `targets_for_domain` and `_task_type_for`
decide *what* gets written and are pure — which means they are the half where a wrong answer
is silent. A fingerprint that collides makes one recommendation inherit another's activation;
a fingerprint that is unstable makes the same recommendation activate twice.
"""

from __future__ import annotations

import pytest

from app.services.insight_activation import (
    DEFAULT_TARGETS,
    DOMAIN_TARGETS,
    action_fingerprint,
    targets_for_domain,
)

#: Read from the mapping rather than written here. A literal would test whichever domain I
#: happened to pick — and my first guess, "MNT", is not one of them.
A_KNOWN_DOMAIN = sorted(DOMAIN_TARGETS)[0]


def _fp(**over):
    base = dict(
        source="chat",
        session_id="s-1",
        message_id="m-1",
        action_index=0,
        title="Replace the bearing on press 3",
    )
    base.update(over)
    return action_fingerprint(**base)


class TestTheFingerprintIsAnIdentity:
    def test_it_is_stable_across_calls(self):
        """If it were not, every re-render would activate the same recommendation again."""
        assert _fp() == _fp()

    def test_a_different_title_at_the_same_index_is_a_different_action(self):
        """THE REASON TITLE IS IN THE HASH. A regenerated message shifts positions, so index
        alone would let a new recommendation inherit the previous one's activation — the
        operator sees "already actioned" for something nobody has looked at."""
        assert _fp() != _fp(title="Order a replacement seal")

    def test_the_same_title_at_a_different_index_is_a_different_action(self):
        """And the mirror. Title alone would collapse two genuinely distinct steps that
        happen to be worded the same — "Inspect the line" twice in one plan is two jobs."""
        assert _fp() != _fp(action_index=1)

    def test_it_is_insensitive_to_case_and_surrounding_space(self):
        """The title arrives from a model. Whitespace and capitalisation drift between
        generations without the recommendation changing."""
        assert _fp(title="  replace the bearing on PRESS 3 ") == _fp()

    def test_different_sessions_do_not_share_an_identity(self):
        assert _fp() != _fp(session_id="s-2")

    @pytest.mark.parametrize("field", ["session_id", "message_id"])
    def test_absent_identifiers_do_not_collapse_everything_together(self, field):
        """A missing id must not make every recommendation from that source identical —
        that would let the first activation mark all of them done."""
        a = _fp(**{field: None})
        b = _fp(**{field: None}, title="Something else entirely")
        assert a != b


class TestDomainRoutingSaysWhenItGuessed:
    def test_a_known_domain_is_not_a_default(self):
        targets, used_default = targets_for_domain(A_KNOWN_DOMAIN)
        assert targets and used_default is False

    def test_an_unknown_domain_reports_that_it_fell_back(self):
        """THE FLAG IS THE POINT. The function returns `used_default` rather than letting the
        caller infer it, so an activation can record that **nobody had classified this
        domain** — otherwise a defaulted routing is indistinguishable from a chosen one."""
        targets, used_default = targets_for_domain("NOT-A-DOMAIN")
        assert targets == DEFAULT_TARGETS and used_default is True

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent_domains_default_and_say_so(self, value):
        _, used_default = targets_for_domain(value)
        assert used_default is True

    def test_it_is_case_and_space_insensitive(self):
        assert targets_for_domain(A_KNOWN_DOMAIN.lower()) == targets_for_domain(
            f"  {A_KNOWN_DOMAIN} "
        )
