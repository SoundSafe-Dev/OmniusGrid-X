"""Safe, deterministic fleet cohort validation and target resolution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, false, func, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentRelease,
    Asset,
    AssetAgentCollector,
    AssetFleetGroup,
    AssetFleetTag,
    AssetType,
    FleetCohort,
    FleetGroup,
    FleetTag,
    Site,
    Workcell,
)

SEMVER_CORE_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
KEY_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,98}[a-z0-9])?$")

MAX_QUERY_DEPTH = 4
MAX_QUERY_CLAUSES = 50
MAX_LIST_VALUES = 100
MAX_EXPLICIT_ASSETS = 5000

COMBINATORS = frozenset({"all_of", "any_of"})
FIELD_OPERATORS: dict[str, frozenset[str]] = {
    "tag": frozenset({"any", "all"}),
    "group": frozenset({"any", "all"}),
    "site_id": frozenset({"eq", "in"}),
    "workcell_id": frozenset({"eq", "in"}),
    "collector_type": frozenset({"eq", "in", "all"}),
    "asset_type_id": frozenset({"eq", "in"}),
    "asset_category": frozenset({"eq", "in"}),
    "active": frozenset({"eq"}),
    "heartbeat_age_seconds": frozenset({"lt", "lte", "gt", "gte"}),
    "agent_id": frozenset({"eq", "ne", "in"}),
    "agent_version": frozenset({"eq", "ne", "lt", "lte", "gt", "gte"}),
}
UUID_FIELDS = frozenset({"tag", "group", "site_id", "workcell_id", "asset_type_id"})
STRING_FIELDS = frozenset({"collector_type", "asset_category", "agent_id"})


class TargetingValidationError(ValueError):
    """Raised when a selector or cohort query is outside the safe DSL."""


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: str | None = None

    @property
    def normalized(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        return f"{value}-{self.prerelease}" if self.prerelease else value


@dataclass(frozen=True)
class ResolvedFleetTargets:
    selector: dict[str, Any]
    effective_query: dict[str, Any] | None
    assets: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    excluded_assets: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    membership_hash: str

    @property
    def asset_ids(self) -> list[str]:
        return [str(asset["asset_id"]) for asset in self.assets]


def parse_semver(value: Any) -> SemVer | None:
    """Parse strict SemVer, ignoring build metadata for precedence."""
    if not isinstance(value, str) or len(value) > 255:
        return None
    match = SEMVER_CORE_RE.fullmatch(value)
    if not match:
        return None
    prerelease = match.group(4)
    if prerelease:
        for identifier in prerelease.split("."):
            if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                return None
    numeric_parts = [int(match.group(index)) for index in (1, 2, 3)]
    if any(part > 2_147_483_647 for part in numeric_parts):
        return None
    return SemVer(
        major=numeric_parts[0],
        minor=numeric_parts[1],
        patch=numeric_parts[2],
        prerelease=prerelease,
    )


def semver_asset_values(value: Any) -> dict[str, Any]:
    """Return heartbeat persistence values for a possibly legacy version."""
    parsed = parse_semver(value)
    if parsed is None:
        return {
            "agent_version_valid": False,
            "agent_version_major": None,
            "agent_version_minor": None,
            "agent_version_patch": None,
            "agent_version_prerelease": None,
        }
    return {
        "agent_version_valid": True,
        "agent_version_major": parsed.major,
        "agent_version_minor": parsed.minor,
        "agent_version_patch": parsed.patch,
        "agent_version_prerelease": parsed.prerelease,
    }


def normalize_key(value: str) -> str:
    key = value.strip().lower().replace(" ", "-")
    if not KEY_RE.fullmatch(key):
        raise TargetingValidationError(
            "key must be 1-100 lowercase letters, numbers, hyphens, or underscores"
        )
    return key


def normalize_query(query: Any) -> dict[str, Any]:
    """Validate and canonicalize a bounded version-1 cohort query."""
    counter = [0]
    normalized = _normalize_query_node(query, depth=1, counter=counter)
    if counter[0] > MAX_QUERY_CLAUSES:
        raise TargetingValidationError(
            f"cohort query may contain at most {MAX_QUERY_CLAUSES} predicates"
        )
    return normalized


def _normalize_query_node(
    node: Any,
    *,
    depth: int,
    counter: list[int],
) -> dict[str, Any]:
    if depth > MAX_QUERY_DEPTH:
        raise TargetingValidationError(
            f"cohort query nesting may not exceed {MAX_QUERY_DEPTH}"
        )
    if not isinstance(node, dict) or not node:
        raise TargetingValidationError("each cohort query node must be a non-empty object")

    combinators = [key for key in COMBINATORS if key in node]
    if combinators:
        if len(node) != 1 or len(combinators) != 1:
            raise TargetingValidationError(
                "a boolean query node must contain exactly one of all_of or any_of"
            )
        key = combinators[0]
        children = node[key]
        if not isinstance(children, list) or not children:
            raise TargetingValidationError(f"{key} must be a non-empty list")
        if len(children) > MAX_QUERY_CLAUSES:
            raise TargetingValidationError(f"{key} contains too many clauses")
        return {
            key: [
                _normalize_query_node(child, depth=depth + 1, counter=counter)
                for child in children
            ]
        }

    if set(node) != {"field", "operator", "value"}:
        raise TargetingValidationError(
            "predicate nodes require exactly field, operator, and value"
        )
    field = node["field"]
    operator = node["operator"]
    if field not in FIELD_OPERATORS:
        raise TargetingValidationError(f"unsupported cohort field: {field}")
    if operator not in FIELD_OPERATORS[field]:
        raise TargetingValidationError(
            f"operator {operator!r} is not supported for {field}"
        )
    counter[0] += 1
    if counter[0] > MAX_QUERY_CLAUSES:
        raise TargetingValidationError(
            f"cohort query may contain at most {MAX_QUERY_CLAUSES} predicates"
        )
    value = _normalize_predicate_value(field, operator, node["value"])
    return {"field": field, "operator": operator, "value": value}


def _as_bounded_list(value: Any) -> list[Any]:
    values = value if isinstance(value, list) else [value]
    if not values or len(values) > MAX_LIST_VALUES:
        raise TargetingValidationError(
            f"predicate lists must contain 1-{MAX_LIST_VALUES} values"
        )
    return values


def _normalize_predicate_value(field: str, operator: str, value: Any) -> Any:
    expects_list = operator in {"in", "any", "all"}
    values = _as_bounded_list(value) if expects_list else [value]

    if field in UUID_FIELDS:
        try:
            normalized = sorted({str(UUID(str(item))) for item in values})
        except (TypeError, ValueError) as exc:
            raise TargetingValidationError(f"{field} values must be UUIDs") from exc
        return normalized if expects_list else normalized[0]

    if field in STRING_FIELDS:
        normalized_strings: list[str] = []
        for item in values:
            if not isinstance(item, str) or not item.strip() or len(item.strip()) > 255:
                raise TargetingValidationError(
                    f"{field} values must be non-empty strings up to 255 characters"
                )
            normalized_strings.append(item.strip())
        normalized_strings = sorted(set(normalized_strings))
        return normalized_strings if expects_list else normalized_strings[0]

    if field == "active":
        if not isinstance(value, bool):
            raise TargetingValidationError("active requires a boolean value")
        return value

    if field == "heartbeat_age_seconds":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 2_592_000:
            raise TargetingValidationError(
                "heartbeat_age_seconds must be an integer between 0 and 2592000"
            )
        return value

    if field == "agent_version":
        parsed = parse_semver(value)
        if parsed is None:
            raise TargetingValidationError("agent_version requires a strict SemVer value")
        return parsed.normalized

    raise TargetingValidationError(f"unsupported cohort field: {field}")


def normalize_selector(selector: Any) -> dict[str, Any]:
    """Canonicalize exactly one supported selector form."""
    if not isinstance(selector, dict):
        raise TargetingValidationError("target selector must be an object")
    recognized = [key for key in ("all", "asset_ids", "cohort_id", "query") if key in selector]
    if len(recognized) != 1 or len(selector) != 1:
        raise TargetingValidationError(
            "target selector requires exactly one of all, asset_ids, cohort_id, or query"
        )
    kind = recognized[0]
    if kind == "all":
        if selector["all"] is not True:
            raise TargetingValidationError("all selector must be true")
        return {"all": True}
    if kind == "asset_ids":
        values = selector["asset_ids"]
        if not isinstance(values, list) or not values or len(values) > MAX_EXPLICIT_ASSETS:
            raise TargetingValidationError(
                f"asset_ids must contain 1-{MAX_EXPLICIT_ASSETS} UUIDs"
            )
        try:
            asset_ids = sorted({str(UUID(str(value))) for value in values})
        except (TypeError, ValueError) as exc:
            raise TargetingValidationError("asset_ids must contain valid UUIDs") from exc
        return {"asset_ids": asset_ids}
    if kind == "cohort_id":
        try:
            return {"cohort_id": str(UUID(str(selector["cohort_id"])))}
        except (TypeError, ValueError) as exc:
            raise TargetingValidationError("cohort_id must be a UUID") from exc
    return {"query": normalize_query(selector["query"])}


def _uuid_values(value: Any) -> list[UUID]:
    values = value if isinstance(value, list) else [value]
    return [UUID(str(item)) for item in values]


def _membership_exists(model: Any, id_column: Any, ids: list[UUID], org_id: UUID) -> Any:
    return exists(
        select(1).where(
            model.asset_id == Asset.id,
            model.organization_id == org_id,
            id_column.in_(ids),
        )
    )


def _compile_predicate(node: dict[str, Any], org_id: UUID, now: datetime) -> Any:
    field = node["field"]
    operator = node["operator"]
    value = node["value"]

    if field == "tag":
        ids = _uuid_values(value)
        clauses = [
            exists(
                select(1)
                .select_from(AssetFleetTag)
                .join(
                    FleetTag,
                    and_(
                        FleetTag.id == AssetFleetTag.tag_id,
                        FleetTag.organization_id == AssetFleetTag.organization_id,
                    ),
                )
                .where(
                    AssetFleetTag.asset_id == Asset.id,
                    AssetFleetTag.organization_id == org_id,
                    FleetTag.id == tag_id,
                    FleetTag.is_active.is_(True),
                )
            )
            for tag_id in ids
        ]
        return and_(*clauses) if operator == "all" else or_(*clauses)

    if field == "group":
        ids = _uuid_values(value)
        clauses = [
            exists(
                select(1)
                .select_from(AssetFleetGroup)
                .join(
                    FleetGroup,
                    and_(
                        FleetGroup.id == AssetFleetGroup.group_id,
                        FleetGroup.organization_id == AssetFleetGroup.organization_id,
                    ),
                )
                .where(
                    AssetFleetGroup.asset_id == Asset.id,
                    AssetFleetGroup.organization_id == org_id,
                    FleetGroup.id == group_id,
                    FleetGroup.is_active.is_(True),
                )
            )
            for group_id in ids
        ]
        return and_(*clauses) if operator == "all" else or_(*clauses)

    if field == "site_id":
        ids = _uuid_values(value)
        return exists(
            select(1)
            .select_from(Workcell)
            .join(Site, Site.id == Workcell.site_id)
            .where(
                Workcell.id == Asset.workcell_id,
                Workcell.organization_id == org_id,
                Site.organization_id == org_id,
                Site.is_active.is_(True),
                Site.id.in_(ids),
            )
        )

    if field == "workcell_id":
        return Asset.workcell_id.in_(_uuid_values(value))

    if field == "collector_type":
        values = value if isinstance(value, list) else [value]
        clauses = [
            exists(
                select(1).where(
                    AssetAgentCollector.asset_id == Asset.id,
                    AssetAgentCollector.organization_id == org_id,
                    AssetAgentCollector.collector_type == collector_type,
                )
            )
            for collector_type in values
        ]
        return and_(*clauses) if operator == "all" else or_(*clauses)

    if field == "asset_type_id":
        return Asset.asset_type_id.in_(_uuid_values(value))

    if field == "asset_category":
        values = value if isinstance(value, list) else [value]
        return exists(
            select(1).where(
                AssetType.id == Asset.asset_type_id,
                AssetType.category.in_(values),
            )
        )

    if field == "active":
        return Asset.is_active.is_(value)

    if field == "heartbeat_age_seconds":
        threshold = now - timedelta(seconds=value)
        if operator == "lt":
            return Asset.agent_last_heartbeat > threshold
        if operator == "lte":
            return Asset.agent_last_heartbeat >= threshold
        if operator == "gt":
            return or_(
                Asset.agent_last_heartbeat.is_(None),
                Asset.agent_last_heartbeat < threshold,
            )
        return or_(
            Asset.agent_last_heartbeat.is_(None),
            Asset.agent_last_heartbeat <= threshold,
        )

    if field == "agent_id":
        values = value if isinstance(value, list) else [value]
        clause = Asset.agent_id.in_(values)
        return not_(clause) if operator == "ne" else clause

    if field == "agent_version":
        return _compile_semver_predicate(operator, parse_semver(value))

    raise TargetingValidationError(f"unsupported cohort field: {field}")


def _compile_semver_predicate(operator: str, target: SemVer | None) -> Any:
    if target is None:
        return false()
    valid = Asset.agent_version_valid.is_(True)
    core_equal = and_(
        Asset.agent_version_major == target.major,
        Asset.agent_version_minor == target.minor,
        Asset.agent_version_patch == target.patch,
    )
    prerelease_cmp = func.fleet_prerelease_compare(
        Asset.agent_version_prerelease,
        target.prerelease,
    )
    equal = and_(core_equal, prerelease_cmp == 0)
    lower_core = or_(
        Asset.agent_version_major < target.major,
        and_(
            Asset.agent_version_major == target.major,
            Asset.agent_version_minor < target.minor,
        ),
        and_(
            Asset.agent_version_major == target.major,
            Asset.agent_version_minor == target.minor,
            Asset.agent_version_patch < target.patch,
        ),
    )
    greater_core = or_(
        Asset.agent_version_major > target.major,
        and_(
            Asset.agent_version_major == target.major,
            Asset.agent_version_minor > target.minor,
        ),
        and_(
            Asset.agent_version_major == target.major,
            Asset.agent_version_minor == target.minor,
            Asset.agent_version_patch > target.patch,
        ),
    )
    lower = or_(lower_core, and_(core_equal, prerelease_cmp < 0))
    greater = or_(greater_core, and_(core_equal, prerelease_cmp > 0))
    comparison = {
        "eq": equal,
        "ne": not_(equal),
        "lt": lower,
        "lte": or_(lower, equal),
        "gt": greater,
        "gte": or_(greater, equal),
    }[operator]
    return and_(valid, comparison)


def compile_query(query: dict[str, Any], org_id: UUID, now: datetime | None = None) -> Any:
    """Compile a normalized query into bound SQLAlchemy expressions."""
    current_time = now or datetime.now(timezone.utc)

    def compile_node(node: dict[str, Any]) -> Any:
        if "all_of" in node:
            return and_(*(compile_node(child) for child in node["all_of"]))
        if "any_of" in node:
            return or_(*(compile_node(child) for child in node["any_of"]))
        return _compile_predicate(node, org_id, current_time)

    return compile_node(query)


def _query_references(query: dict[str, Any]) -> dict[str, set[UUID]]:
    references = {
        "tag": set(),
        "group": set(),
        "site_id": set(),
        "workcell_id": set(),
        "asset_type_id": set(),
    }

    def visit(node: dict[str, Any]) -> None:
        for combinator in COMBINATORS:
            if combinator in node:
                for child in node[combinator]:
                    visit(child)
                return
        field = node["field"]
        if field in references:
            references[field].update(_uuid_values(node["value"]))

    visit(query)
    return references


async def validate_query_references(
    query: dict[str, Any],
    organization_id: UUID,
    db: AsyncSession,
) -> None:
    """Reject unavailable tenant references without revealing which ID exists."""
    references = _query_references(query)
    checks = (
        (
            "tag",
            FleetTag.id,
            select(FleetTag.id).where(
                FleetTag.organization_id == organization_id,
                FleetTag.is_active.is_(True),
            ),
        ),
        (
            "group",
            FleetGroup.id,
            select(FleetGroup.id).where(
                FleetGroup.organization_id == organization_id,
                FleetGroup.is_active.is_(True),
            ),
        ),
        (
            "site_id",
            Site.id,
            select(Site.id).where(
                Site.organization_id == organization_id,
                Site.is_active.is_(True),
            ),
        ),
        (
            "workcell_id",
            Workcell.id,
            select(Workcell.id).where(Workcell.organization_id == organization_id),
        ),
        (
            "asset_type_id",
            AssetType.id,
            select(AssetType.id),
        ),
    )
    for field, column, statement in checks:
        expected = references[field]
        if not expected:
            continue
        found = {
            str(value)
            for value in (
                (
                    await db.execute(statement.where(column.in_(expected)))
                )
                .scalars()
                .all()
            )
        }
        if found != {str(value) for value in expected}:
            raise TargetingValidationError(
                f"one or more referenced {field} values are unavailable"
            )


class FleetTargetResolver:
    """Resolve selectors with deterministic ordering and process grouping."""

    async def resolve(
        self,
        *,
        selector: dict[str, Any],
        organization_id: UUID,
        release: AgentRelease,
        db: AsyncSession,
        now: datetime | None = None,
    ) -> ResolvedFleetTargets:
        normalized_selector = normalize_selector(selector)
        effective_query: dict[str, Any] | None = None
        condition: Any = true()

        if "asset_ids" in normalized_selector:
            condition = Asset.id.in_(_uuid_values(normalized_selector["asset_ids"]))
        elif "cohort_id" in normalized_selector:
            cohort = (
                await db.execute(
                    select(FleetCohort).where(
                        FleetCohort.id == UUID(normalized_selector["cohort_id"]),
                        FleetCohort.organization_id == organization_id,
                        FleetCohort.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if cohort is None:
                raise TargetingValidationError("saved cohort was not found")
            effective_query = normalize_query(cohort.query)
            await validate_query_references(effective_query, organization_id, db)
            condition = compile_query(effective_query, organization_id, now)
        elif "query" in normalized_selector:
            effective_query = normalized_selector["query"]
            await validate_query_references(effective_query, organization_id, db)
            condition = compile_query(effective_query, organization_id, now)

        rows = (
            await db.execute(
                select(Asset, Workcell, Site, AssetType)
                .join(Workcell, Workcell.id == Asset.workcell_id)
                .outerjoin(Site, Site.id == Workcell.site_id)
                .join(AssetType, AssetType.id == Asset.asset_type_id)
                .where(
                    Asset.organization_id == organization_id,
                    Asset.is_active.is_(True),
                    condition,
                )
                .order_by(Asset.id)
            )
        ).all()

        if "asset_ids" in normalized_selector:
            found = {str(row[0].id) for row in rows}
            if found != set(normalized_selector["asset_ids"]):
                raise TargetingValidationError(
                    "one or more target assets were not found or are inactive"
                )

        matched_ids = [row[0].id for row in rows]
        tags = await self._tag_context(db, organization_id, matched_ids)
        groups = await self._group_context(db, organization_id, matched_ids)
        collectors = await self._collector_context(db, organization_id, matched_ids)

        included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for asset, workcell, site, asset_type in rows:
            context = {
                "asset_id": str(asset.id),
                "name": asset.name,
                "agent_id": asset.agent_id,
                "agent_version": asset.agent_version,
                "workcell_id": str(workcell.id),
                "workcell_name": workcell.name,
                "site_id": str(site.id) if site else None,
                "site_name": site.name if site else None,
                "asset_type_id": str(asset_type.id),
                "asset_type_name": asset_type.name,
                "asset_category": asset_type.category,
                "collector_types": collectors.get(str(asset.id), []),
                "tags": tags.get(str(asset.id), []),
                "groups": groups.get(str(asset.id), []),
            }
            if release.artifact_type == "agent" and not asset.agent_id:
                excluded.append(
                    {
                        "asset_id": str(asset.id),
                        "name": asset.name,
                        "reason": "missing_agent_id",
                    }
                )
                continue
            included.append(context)

        if not included:
            raise TargetingValidationError("no eligible active assets matched the selector")

        agents = self._group_agents(included)
        warnings: list[dict[str, Any]] = []
        for agent in agents:
            site_ids = sorted(
                {
                    asset["site_id"]
                    for asset in agent["assets"]
                    if asset["site_id"] is not None
                }
            )
            if len(site_ids) > 1:
                warnings.append(
                    {
                        "code": "agent_spans_sites",
                        "agent_id": agent["agent_id"],
                        "site_ids": site_ids,
                        "message": "One agent owns assets in multiple sites.",
                    }
                )

        canonical = {
            "selector": normalized_selector,
            "effective_query": effective_query,
            "release_id": str(release.id),
            "assets": [
                {
                    "asset_id": asset["asset_id"],
                    "agent_id": asset["agent_id"],
                    "site_id": asset["site_id"],
                    "agent_version": asset["agent_version"],
                }
                for asset in included
            ],
            "agents": [
                {
                    "agent_key": agent["agent_key"],
                    "route_asset_id": agent["route_asset_id"],
                    "asset_ids": agent["asset_ids"],
                }
                for agent in agents
            ],
        }
        membership_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return ResolvedFleetTargets(
            selector=normalized_selector,
            effective_query=effective_query,
            assets=included,
            agents=agents,
            excluded_assets=excluded,
            warnings=warnings,
            membership_hash=membership_hash,
        )

    @staticmethod
    async def _tag_context(
        db: AsyncSession,
        organization_id: UUID,
        asset_ids: list[UUID],
    ) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}
        if not asset_ids:
            return result
        rows = (
            await db.execute(
                select(AssetFleetTag.asset_id, FleetTag)
                .join(
                    FleetTag,
                    and_(
                        FleetTag.id == AssetFleetTag.tag_id,
                        FleetTag.organization_id == AssetFleetTag.organization_id,
                    ),
                )
                .where(
                    AssetFleetTag.organization_id == organization_id,
                    AssetFleetTag.asset_id.in_(asset_ids),
                    FleetTag.is_active.is_(True),
                )
                .order_by(AssetFleetTag.asset_id, FleetTag.key)
            )
        ).all()
        for asset_id, tag in rows:
            result.setdefault(str(asset_id), []).append(
                {"id": str(tag.id), "key": tag.key, "name": tag.name}
            )
        return result

    @staticmethod
    async def _group_context(
        db: AsyncSession,
        organization_id: UUID,
        asset_ids: list[UUID],
    ) -> dict[str, list[dict[str, str]]]:
        result: dict[str, list[dict[str, str]]] = {}
        if not asset_ids:
            return result
        rows = (
            await db.execute(
                select(AssetFleetGroup.asset_id, FleetGroup)
                .join(
                    FleetGroup,
                    and_(
                        FleetGroup.id == AssetFleetGroup.group_id,
                        FleetGroup.organization_id == AssetFleetGroup.organization_id,
                    ),
                )
                .where(
                    AssetFleetGroup.organization_id == organization_id,
                    AssetFleetGroup.asset_id.in_(asset_ids),
                    FleetGroup.is_active.is_(True),
                )
                .order_by(AssetFleetGroup.asset_id, FleetGroup.key)
            )
        ).all()
        for asset_id, group in rows:
            result.setdefault(str(asset_id), []).append(
                {"id": str(group.id), "key": group.key, "name": group.name}
            )
        return result

    @staticmethod
    async def _collector_context(
        db: AsyncSession,
        organization_id: UUID,
        asset_ids: list[UUID],
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if not asset_ids:
            return result
        rows = (
            await db.execute(
                select(
                    AssetAgentCollector.asset_id,
                    AssetAgentCollector.collector_type,
                )
                .where(
                    AssetAgentCollector.organization_id == organization_id,
                    AssetAgentCollector.asset_id.in_(asset_ids),
                )
                .order_by(
                    AssetAgentCollector.asset_id,
                    AssetAgentCollector.collector_type,
                )
            )
        ).all()
        for asset_id, collector_type in rows:
            result.setdefault(str(asset_id), []).append(collector_type)
        return result

    @staticmethod
    def _group_agents(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            key = asset["agent_id"] or f"asset:{asset['asset_id']}"
            grouped.setdefault(key, []).append(asset)

        agents: list[dict[str, Any]] = []
        for key in sorted(grouped):
            member_assets = sorted(grouped[key], key=lambda item: item["asset_id"])
            agents.append(
                {
                    "agent_key": key,
                    "agent_id": member_assets[0]["agent_id"],
                    "route_asset_id": member_assets[0]["asset_id"],
                    "asset_ids": [asset["asset_id"] for asset in member_assets],
                    "assets": member_assets,
                }
            )
        return agents


fleet_target_resolver = FleetTargetResolver()
