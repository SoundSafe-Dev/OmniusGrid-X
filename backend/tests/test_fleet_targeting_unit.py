from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import Asset
from app.services.fleet_targeting import (
    FleetTargetResolver,
    TargetingValidationError,
    compile_query,
    normalize_query,
    normalize_selector,
    parse_semver,
    semver_asset_values,
)


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("2.1.0", "2.1.0"),
        ("2.10.0", "2.10.0"),
        ("2.1.0-rc.1", "2.1.0-rc.1"),
        ("2.1.0+build.7", "2.1.0"),
    ],
)
def test_parse_semver_accepts_strict_versions(value, normalized):
    parsed = parse_semver(value)
    assert parsed is not None
    assert parsed.normalized == normalized


@pytest.mark.parametrize(
    "value",
    [
        "2.1",
        "v2.1.0",
        "02.1.0",
        "2.1.0-01",
        "2.1.0-",
        "2147483648.0.0",
        " 2.1.0 ",
        "legacy",
        None,
    ],
)
def test_parse_semver_rejects_invalid_or_unqueryable_versions(value):
    assert parse_semver(value) is None
    values = semver_asset_values(value)
    assert values == {
        "agent_version_valid": False,
        "agent_version_major": None,
        "agent_version_minor": None,
        "agent_version_patch": None,
        "agent_version_prerelease": None,
    }


def test_query_normalization_is_bounded_and_canonical():
    site_id = uuid4()
    query = normalize_query(
        {
            "all_of": [
                {
                    "field": "collector_type",
                    "operator": "eq",
                    "value": "video",
                },
                {
                    "field": "site_id",
                    "operator": "in",
                    "value": [str(site_id), str(site_id)],
                },
                {
                    "field": "agent_version",
                    "operator": "lt",
                    "value": "2.1.0+ignored",
                },
            ]
        }
    )
    assert query["all_of"][1]["value"] == [str(site_id)]
    assert query["all_of"][2]["value"] == "2.1.0"


@pytest.mark.parametrize(
    "query",
    [
        {"sql": "agent_version < '2.1.0'"},
        {"field": "agent_version", "operator": "like", "value": "%"},
        {"field": "unknown", "operator": "eq", "value": "x"},
        {"all_of": []},
        {
            "all_of": [
                {
                    "all_of": [
                        {
                            "all_of": [
                                {
                                    "all_of": [
                                        {
                                            "field": "active",
                                            "operator": "eq",
                                            "value": True,
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    ],
)
def test_query_normalization_rejects_untrusted_or_unbounded_shapes(query):
    with pytest.raises(TargetingValidationError):
        normalize_query(query)


def test_query_normalization_stops_at_global_predicate_limit():
    predicate = {"field": "active", "operator": "eq", "value": True}
    with pytest.raises(
        TargetingValidationError,
        match="at most 50 predicates",
    ):
        normalize_query(
            {
                "all_of": [
                    {"any_of": [dict(predicate) for _ in range(50)]},
                    {"any_of": [dict(predicate) for _ in range(50)]},
                ]
            }
        )


def test_semver_query_compiles_to_bound_sqlalchemy_expression():
    query = normalize_query(
        {
            "field": "agent_version",
            "operator": "lt",
            "value": "2.10.0-rc.1",
        }
    )
    statement = select(Asset.id).where(compile_query(query, uuid4()))
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "fleet_prerelease_compare" in sql
    assert "2.10.0-rc.1" not in sql
    assert "agent_version_valid" in sql


@pytest.mark.parametrize(
    ("field", "membership_table", "resource_table"),
    [
        ("tag", "asset_fleet_tags", "fleet_tags"),
        ("group", "asset_fleet_groups", "fleet_groups"),
    ],
)
def test_membership_any_compiles_one_tenant_scoped_active_exists(
    field,
    membership_table,
    resource_table,
):
    resource_ids = [uuid4(), uuid4(), uuid4()]
    query = normalize_query(
        {
            "field": field,
            "operator": "any",
            "value": [str(value) for value in resource_ids],
        }
    )
    compiled = select(Asset.id).where(
        compile_query(query, uuid4())
    ).compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert sql.count("EXISTS") == 1
    assert f"FROM {membership_table} JOIN {resource_table}" in sql
    assert f"{membership_table}.organization_id" in sql
    assert f"{resource_table}.organization_id" in sql
    assert f"{resource_table}.is_active IS true" in sql
    membership_id_sets = [
        value
        for value in compiled.params.values()
        if isinstance(value, list)
    ]
    assert len(membership_id_sets) == 1
    assert {str(value) for value in membership_id_sets[0]} == {
        str(value) for value in resource_ids
    }


@pytest.mark.parametrize("field", ["tag", "group"])
def test_membership_all_compiles_one_exists_per_required_resource(field):
    resource_ids = [uuid4(), uuid4()]
    query = normalize_query(
        {
            "field": field,
            "operator": "all",
            "value": [str(value) for value in resource_ids],
        }
    )
    compiled = select(Asset.id).where(
        compile_query(query, uuid4())
    ).compile(dialect=postgresql.dialect())

    assert str(compiled).count("EXISTS") == len(resource_ids)
    membership_id_sets = [
        value
        for value in compiled.params.values()
        if isinstance(value, list)
    ]
    assert len(membership_id_sets) == len(resource_ids)
    assert all(len(values) == 1 for values in membership_id_sets)
    assert {str(values[0]) for values in membership_id_sets} == {
        str(value) for value in resource_ids
    }


def test_selector_requires_exactly_one_supported_form():
    asset_ids = [uuid4(), uuid4()]
    normalized = normalize_selector(
        {"asset_ids": [str(asset_ids[1]), str(asset_ids[0]), str(asset_ids[0])]}
    )
    assert normalized["asset_ids"] == sorted({str(value) for value in asset_ids})

    with pytest.raises(TargetingValidationError):
        normalize_selector({"all": True, "asset_ids": [str(asset_ids[0])]})


def test_agent_grouping_uses_stable_route_and_flags_unreported_agents_separately():
    first_id, second_id, third_id = sorted(str(uuid4()) for _ in range(3))
    assets = [
        {"asset_id": second_id, "agent_id": "agent-a"},
        {"asset_id": first_id, "agent_id": "agent-a"},
        {"asset_id": third_id, "agent_id": None},
    ]
    groups = FleetTargetResolver._group_agents(assets)

    shared = next(group for group in groups if group["agent_id"] == "agent-a")
    assert shared["route_asset_id"] == first_id
    assert shared["asset_ids"] == [first_id, second_id]
    assert len(groups) == 2
