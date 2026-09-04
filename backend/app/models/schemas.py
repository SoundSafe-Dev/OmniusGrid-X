"""Pydantic Schemas for API"""

from datetime import datetime
from typing import Annotated, Optional, Dict, Any, List, Literal
from uuid import UUID
from pydantic import computed_field, BeforeValidator, ConfigDict, AliasChoices, BaseModel, Field


def _none_is_empty(value: Any) -> Any:
    """A NULL JSON column is an object with no extra attributes, which is `{}`."""
    return {} if value is None else value


#: `metadata` as it comes off a row, tolerating the NULL the column can actually hold.
#:
#: `Dict[str, Any] = Field(default_factory=dict)` REJECTS None. The factory fires only when the
#: key is ABSENT — and `model_validate(orm_row)` does not omit the key, it supplies the
#: attribute's value, which is `None` for any row not written through the ORM. Seventeen of the
#: twenty-one `meta_data` columns in the migrations are declared with no DEFAULT, so the NULL is
#: not hypothetical: a data import, a partner integration, or a plain `INSERT` produces one, and
#: the whole LIST endpoint then 500s for that tenant — not the one row, the page.
#:
#: Three schemas had already been changed to `Optional[...] = None` for exactly this, one table
#: at a time, after `test_yard_trailer_plate_is_resolved.py` found it on appointments. That
#: changes the wire contract (clients receive `null` where they had `{}`); coercing keeps the
#: contract and covers every schema at once. NULL and `{}` genuinely mean the same thing here,
#: which is what makes the coercion honest rather than a papered-over absence.
JsonMetadata = Annotated[Dict[str, Any], BeforeValidator(_none_is_empty)]


# Asset Schemas
class AssetBase(BaseModel):
    name: str
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    connection_config: Dict[str, Any] = {}
    # Sensor taxonomy (migration 024): machinery | audio | video | environmental | generic.
    sensor_class: Optional[str] = None
    media_config: Dict[str, Any] = {}
    is_active: bool = True


class AssetCreate(AssetBase):
    # FS-523, and these two were found by the GUARD rather than by the sweep that
    # preceded it — the first pass keyed on the handler's own parameter being named
    # `organization_id`, and these derive the tenant under a different parameter name.
    # A detector narrower than the class it checks for is the recurring failure in this
    # repository; the guard reads the imported model and the handler's dependency, so it
    # does not care what anything is called.
    #
    # As with the other twelve: required on the schema, never read by the handler, so a
    # caller who omits it got a 422. `POST /assets` is the core create path of the product.
    # Required: migration 013 made assets.workcell_id NOT NULL. Optional here
    # meant POST /assets without a workcell 500'd (NotNullViolation) instead of
    # returning a clean 422. (FS-90 write-path alignment.)
    workcell_id: UUID
    asset_type_id: UUID


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    serial_number: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    connection_config: Optional[Dict[str, Any]] = None
    sensor_class: Optional[str] = None
    media_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    current_packml_state: Optional[str] = None
    # THE HANDLER WAS ALREADY WRITTEN FOR THESE (FS-672). `update_asset` contains a
    # tenant-scoped `if "workcell_id" in update_data` block — look the workcell up within
    # the caller's organization, 404 if it belongs to someone else — and this schema did
    # not declare the field, so the check has never run and an asset registered against
    # the wrong workcell stayed there for the life of the row. The dead validation is what
    # makes it a defect rather than a missing feature: the intent is in the file.
    #
    # `asset_type_id` is the same omission without the tell. It needs no handler-side
    # check: asset types are a GLOBAL catalog and deliberately not tenant-scoped, and
    # `app/core/errors.py` already turns a foreign-key violation into a 400 naming the
    # column and table. A copy of the create path's check was written here and removed
    # after mutation-testing showed it changed nothing a caller can see.
    workcell_id: Optional[UUID] = None
    asset_type_id: Optional[UUID] = None


class AssetResponse(AssetBase):
    id: UUID
    organization_id: UUID
    workcell_id: Optional[UUID]
    asset_type_id: UUID
    current_packml_state: str
    # THE READ PATH THAT WAS MISSING. Migration 053 added the column, the admin endpoint
    # writes it, and `TacticalEngine._is_maintenance_mode` reads it before dispatching a
    # control command — but this schema did not carry it, so nothing in the product could
    # show which assets were in maintenance. An operator could take a machine out of
    # service, have the engine correctly stop commanding it, and see no sign of either.
    #
    # The frontend even had a name for it: `Asset.isInMaintenance`, declared as a required
    # boolean, populated by the mock fixtures and by nothing else. FastAPI drops whatever
    # the schema does not declare, so adding the column was necessary and not sufficient.
    maintenance_mode: bool = False
    last_seen: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Asset Type Schemas
class AssetTypeCreate(BaseModel):
    name: str
    category: str
    sensor_class: Optional[str] = "generic"
    packml_config: Dict[str, Any] = {}
    telemetry_schema: Dict[str, Any] = {}
    action_space: Dict[str, Any] = {}


class AssetTypeResponse(AssetTypeCreate):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Alarm Schemas
class AlarmCreate(BaseModel):
    asset_id: UUID
    alarm_code: str
    severity: str  # critical, high, medium, low, info
    message: str
    description: Optional[str] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class AlarmResponse(AlarmCreate):
    id: UUID
    is_active: bool
    is_acknowledged: bool
    acknowledged_by: Optional[UUID]
    acknowledged_at: Optional[datetime]
    acknowledged_comment: Optional[str]
    occurred_at: datetime
    cleared_at: Optional[datetime]
    #: Resolved by join, not stored (FS-436). The dashboard's Active Alarms panel renders
    #: `{alarm.assetName} • {occurredAt}` and this was never sent, so every row showed a
    #: bullet with an empty space in front of it. `alarms` carries only `asset_id`.
    #:
    #: Optional and defaulting to None because the two single-row paths (`GET /alarms/{id}`
    #: and the acknowledge/clear responses) do not run the resolver — a null that means
    #: "not resolved here" is honest, and a client rendering it falls back to the id. The
    #: alternative, resolving it on every path, adds a query to writes for a field only the
    #: list views display.
    asset_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class AlarmAcknowledge(BaseModel):
    comment: Optional[str] = None


# Operation Schemas
class OperationCreate(BaseModel):
    asset_id: UUID
    operation_name: str
    job_id: Optional[str] = None
    planned_duration: Optional[int] = None  # seconds
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class OperationResponse(OperationCreate):
    id: UUID
    status: str
    packml_state_durations: Dict[str, Any]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    actual_duration: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Telemetry Schemas
class TelemetryPoint(BaseModel):
    timestamp: datetime
    metric_name: str
    value: float
    unit: Optional[str] = None
    packml_state: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class TelemetryBatch(BaseModel):
    asset_id: UUID
    data: List[TelemetryPoint]


# Dashboard Schemas
class DashboardOverview(BaseModel):
    total_assets: int
    active_assets: int
    assets_by_state: Dict[str, int]
    active_alarms: int
    critical_alarms: int


class OEEMetrics(BaseModel):
    asset_id: UUID
    availability: float
    performance: float
    quality: float
    oee: float
    time_range: str


# Auth Schemas
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    refresh_token: Optional[str] = None


class UserLogin(BaseModel):
    email: str
    password: str


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    organization_id: Optional[UUID] = None
    role: str = "operator"


# ==================== YMS Schemas ====================

class YardTrailerBase(BaseModel):
    trailer_number: str
    trailer_type: Optional[str] = None  # dry_van, reefer, flatbed, etc.
    status: str = "checked_in"  # checked_in, docked, yard, checked_out
    yard_location: Optional[str] = None
    seal_number: Optional[str] = None
    #: Optional, not `str = "intact"` (FS-666). A caller who omits it is saying nothing
    #: about the seal, and the schema used to turn that silence into a report of an intact
    #: seal before the value ever reached the database.
    seal_status: Optional[str] = None  # intact, broken, missing; None = not reported
    weight_lbs: Optional[float] = None
    temperature_setpoint: Optional[float] = None
    temperature_actual: Optional[float] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class YardTrailerCreate(YardTrailerBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    shipment_id: Optional[UUID] = None


class YardTrailerUpdate(BaseModel):
    status: Optional[str] = None
    yard_location: Optional[str] = None
    seal_status: Optional[str] = None
    weight_lbs: Optional[float] = None
    dock_door_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    temperature_actual: Optional[float] = None
    # SET ONCE AND NEVER CORRECTABLE (FS-671). `seal_status` and `temperature_actual` were
    # already editable and `seal_number` and `temperature_setpoint` beside them were not,
    # which is the pairing that makes the omission visible: a seal replaced at the gate
    # could be marked intact WHILE STILL NAMING THE OLD SEAL.
    #
    # `trailer_number` is deliberately absent, for the reason given on `ShipmentUpdate`.
    trailer_type: Optional[str] = None
    seal_number: Optional[str] = None
    temperature_setpoint: Optional[float] = None
    carrier_id: Optional[UUID] = None
    shipment_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')
    check_out_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class YardTrailerResponse(YardTrailerBase):
    id: UUID
    organization_id: UUID
    carrier_id: Optional[UUID]
    driver_id: Optional[UUID]
    shipment_id: Optional[UUID]
    dock_door_id: Optional[UUID]
    check_in_at: datetime
    check_out_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DockDoorBase(BaseModel):
    door_number: str
    door_type: Optional[str] = None  # inbound, outbound, cross_dock
    status: str = "available"  # available, occupied, maintenance
    equipment_capabilities: Dict[str, Any] = {}
    is_active: bool = True


class DockDoorCreate(DockDoorBase):
    # FS-523, and these two were found by the GUARD rather than by the sweep that
    # preceded it — the first pass keyed on the handler's own parameter being named
    # `organization_id`, and these derive the tenant under a different parameter name.
    # A detector narrower than the class it checks for is the recurring failure in this
    # repository; the guard reads the imported model and the handler's dependency, so it
    # does not care what anything is called.
    #
    # As with the other twelve: required on the schema, never read by the handler, so a
    # caller who omits it got a 422. `POST /assets` is the core create path of the product.
    pass


class DockDoorUpdate(BaseModel):
    status: Optional[str] = None
    # `Optional[...] = None`, NOT `Dict[str, Any] = {}` (FS-677). Every other field on every
    # other Update schema in this file is optional-and-None; this one declared a non-optional
    # dict defaulting to empty. `exclude_unset` saves it in the handler below, but a caller
    # reading the schema is told an update must carry the capabilities map, and any future
    # `model_dump()` without `exclude_unset` would wipe the column.
    equipment_capabilities: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    current_trailer_id: Optional[UUID] = None
    # THE SCHEMA EXISTED AND NOTHING SERVED IT (FS-677) — the fifth instance, and the one my
    # own summary missed until the create/update pairing was measured from the OpenAPI
    # document rather than from route paths. A door could be created and never reconfigured:
    # converting a bay from inbound to cross-dock meant deleting it and losing every
    # appointment that referenced it.
    #
    # `door_number` stays immutable, with `shipment_number` and `trailer_number`, and is
    # asserted so it reads as a decision rather than another omission.
    door_type: Optional[str] = None


class DockDoorResponse(DockDoorBase):
    # These five are nullable on `dock_doors` with NO server default, so they override
    # the stricter request-side types in DockDoorBase. Their ORM `default=` is
    # PYTHON-side: it fires only for rows written through SQLAlchemy, so a migration,
    # a seeder or any raw INSERT leaves NULL — and a pydantic default does not save
    # you, because the ORM hands the field an explicit None rather than omitting it.
    #
    # Not hypothetical: a raw-inserted dock door made GET /yard/dock/doors return 500
    # with "equipment_capabilities: Input should be a valid dictionary" — a validation
    # error naming OUR schema rather than the data, so nobody would think to look at
    # the row. Overridden here rather than in DockDoorBase so create/update keep
    # requiring them.
    status: Optional[str] = None
    equipment_capabilities: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

    id: UUID
    organization_id: UUID
    current_trailer_id: Optional[UUID]
    # DENORMALISED, and declared here for a specific reason: `response_model` DROPS
    # anything the schema does not name. The handler now resolves the plate from
    # `yard_trailers` via `current_trailer_id`, and without this line FastAPI would have
    # deleted it from every response and the fix would have done nothing visible — the
    # same way `AssetResponse` silently swallowed `maintenance_mode`.
    trailer_license_plate: Optional[str] = None
    # Declared explicitly so it survives the response model, like the plate above. The door
    # card now shows "Last occupied" instead of an `estimatedReleaseAt` no column produces.
    last_occupied_at: Optional[datetime]
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class YardMoveBase(BaseModel):
    from_location: str
    to_location: str
    move_type: Optional[str] = None  # check_in, dock, yard_relocate, check_out
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class YardMoveCreate(YardMoveBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    trailer_id: UUID
    jockey_driver_id: Optional[UUID] = None


class YardMoveResponse(YardMoveBase):
    # LIFECYCLE STATE LIVES HERE, NOT ON THE BASE (FS-668). `duration_seconds` is computed by `complete_yard_move` from the two timestamps. A
    # caller-supplied duration was accepted and overwritten.
    #
    # Moved rather than made Optional, on the argument FS-523 made for
    # `organization_id`: a field a caller can set that changes nothing is its own
    # small lie, and pydantic ignores extra keys by default, so a client still
    # sending one is unaffected.
    duration_seconds: Optional[float] = None

    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    id: UUID
    organization_id: UUID
    trailer_id: Optional[UUID] = None
    jockey_driver_id: Optional[UUID]
    started_at: datetime
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriverWaitTimeBase(BaseModel):
    check_in_at: datetime
    docked_at: Optional[datetime] = None
    unloaded_at: Optional[datetime] = None
    check_out_at: Optional[datetime] = None
    total_wait_minutes: Optional[float] = None
    detention_minutes: Optional[float] = None
    demurrage_minutes: Optional[float] = None
    detention_rate: Optional[float] = None
    demurrage_rate: Optional[float] = None
    detention_charge: Optional[float] = None
    demurrage_charge: Optional[float] = None
    is_billed: bool = False
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class DriverWaitTimeCreate(BaseModel):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    driver_id: UUID
    trailer_id: Optional[UUID] = None

    # FS-907. Does NOT inherit DriverWaitTimeBase (unlike DriverWaitTimeResponse below,
    # which needs every one of its fields to report them back). Nine of Base's fields —
    # check_out_at, docked_at, unloaded_at, total_wait_minutes, detention_minutes,
    # demurrage_minutes, detention_charge, demurrage_charge, is_billed — are all
    # computed by `close_driver_wait_time` at checkout; nothing in this handler ever
    # read a caller-supplied value for any of them. Declaring them here let a caller
    # believe they could set an arrival time or a billed flag at creation, and the API
    # silently ignored it. Redeclared explicitly instead of inherited-and-dropped: only
    # the fields this route's handler genuinely reads.
    check_in_at: datetime
    detention_rate: Optional[float] = None
    demurrage_rate: Optional[float] = None
    metadata: JsonMetadata = Field(
        default_factory=dict,
        validation_alias=AliasChoices('meta_data', 'metadata'),
        serialization_alias='metadata',
    )


class DriverWaitTimeResponse(DriverWaitTimeBase):
    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    id: UUID
    organization_id: UUID
    driver_id: Optional[UUID] = None
    trailer_id: Optional[UUID]
    updated_at: datetime
    created_at: datetime

    #: THE CAVEAT TRAVELS WITH THE CHARGE (FS-426). `detention_charge` is nullable, and null
    #: means "nobody has assessed this" — a different fact from "assessed at zero". The
    #: dwell-times path already publishes exactly this flag, computed the same way, because
    #: it coerces the charge to a float and would otherwise report an unassessed trailer as
    #: owing nothing. This endpoint sent the charge and not the flag, so the two disagreed
    #: about the same concept, and a reader had to know that null carries meaning here.
    #:
    #: `test_qualifiers_reach_the_frontend` had `detention_assessed` exempted on the
    #: grounds that `detention_charge` was not rendered. It is now, and the guard said so on
    #: the commit that made it true.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def detention_assessed(self) -> bool:
        return self.detention_charge is not None

    model_config = ConfigDict(from_attributes=True)


class YardCheckPointBase(BaseModel):
    checkpoint_type: str  # gate_in, guard_shack, weigh_station, gate_out
    checkpoint_name: Optional[str] = None
    weight_lbs: Optional[float] = None
    inspection_status: Optional[str] = None  # passed, failed, pending
    inspector_id: Optional[UUID] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class YardCheckPointCreate(YardCheckPointBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    trailer_id: UUID


class YardCheckPointResponse(YardCheckPointBase):
    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    id: UUID
    organization_id: UUID
    trailer_id: Optional[UUID] = None
    passed_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== TMS Schemas ====================

class CarrierBase(BaseModel):
    carrier_name: str
    dot_number: Optional[str] = None
    mc_number: Optional[str] = None
    ctpat_certified: bool = False
    ctpat_expires_at: Optional[datetime] = None
    insurance_on_file: bool = False
    insurance_expires_at: Optional[datetime] = None
    safety_rating: Optional[str] = None  # satisfactory, conditional, unsatisfactory
    csa_score: Optional[float] = None
    contract_rate: Dict[str, Any] = {}
    is_active: bool = True
    contact_info: Dict[str, Any] = {}


class CarrierCreate(CarrierBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    pass


class CarrierUpdate(BaseModel):
    carrier_name: Optional[str] = None
    dot_number: Optional[str] = None
    mc_number: Optional[str] = None
    ctpat_certified: Optional[bool] = None
    ctpat_expires_at: Optional[datetime] = None
    insurance_on_file: Optional[bool] = None
    insurance_expires_at: Optional[datetime] = None
    safety_rating: Optional[str] = None
    csa_score: Optional[float] = None
    contract_rate: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    contact_info: Optional[Dict[str, Any]] = None


class CarrierResponse(CarrierBase):
    id: UUID
    organization_id: UUID
    # Migration 042 UI columns (the seam camelizes these for the frontend:
    # compliance_score -> complianceScore, etc.).
    compliance_score: Optional[float] = None
    on_time_performance: Optional[float] = None
    operating_authority: Optional[str] = None
    scac: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriverBase(BaseModel):
    first_name: str
    last_name: str
    license_number: Optional[str] = None
    license_state: Optional[str] = None
    cdl_class: Optional[str] = None  # A, B, C
    hazmat_endorsed: bool = False
    medical_cert_expires: Optional[datetime] = None
    dq_file_complete: bool = False
    current_hos_status: Optional[str] = None  # on_duty, driving, off_duty, sleeper
    # OPTIONAL, AND NOT DEFAULTED TO ZERO. All three columns are nullable, so a driver
    # who has not reported made `model_validate` raise and the whole `/drivers` list
    # answered 500 — one silent driver took the page down for the entire fleet.
    #
    # The `= 0` was the sharper half. Zero is not "unknown", it is "has driven no hours
    # today", which is a clean HOS record; it is the same coercion `check_compliance` was
    # fixed for (`float(x or 0)` turning a driver who never reported into one who drove
    # nothing). A schema default is a claim about the world just as much as a coalesce is.
    hos_drive_hours_today: Optional[float] = None
    hos_on_duty_hours_today: Optional[float] = None
    hos_cycle_hours: Optional[float] = None
    eld_device_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    is_active: bool = True


class DriverCreate(DriverBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    carrier_id: Optional[UUID] = None


class DriverUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_number: Optional[str] = None
    license_state: Optional[str] = None
    cdl_class: Optional[str] = None
    hazmat_endorsed: Optional[bool] = None
    medical_cert_expires: Optional[datetime] = None
    dq_file_complete: Optional[bool] = None
    current_hos_status: Optional[str] = None
    hos_drive_hours_today: Optional[float] = None
    hos_on_duty_hours_today: Optional[float] = None
    hos_cycle_hours: Optional[float] = None
    is_active: Optional[bool] = None
    # SET ONCE AND NEVER CORRECTABLE (FS-671). These four were on `DriverCreate` and not
    # here, so a driver's phone number, email, carrier and ELD device could be entered
    # once and never fixed — on a route that already edits the ten HOS and licence fields
    # above. Safe to add because the handler applies `model_dump(exclude_unset=True)` and
    # `setattr`, so a field omitted by the caller is untouched rather than blanked.
    eld_device_id: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    carrier_id: Optional[UUID] = None


class DriverResponse(DriverBase):
    id: UUID
    organization_id: UUID
    carrier_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriverListItem(DriverResponse):
    """One row of `GET /transportation/drivers`: `DriverResponse` plus the seven keys the
    handler derives, SPELLED EXACTLY AS THE HANDLER SPELLS THEM (FS-702, closing FS-688's
    named to-do).

    The route answered `List[Dict[str, Any]]` for its whole life — an OpenAPI `object`
    with no properties — while `DriverResponse` sat beside it on the single-driver route.
    The reason it was never "just declared" is this model's whole content: the seven
    derived keys are **camelCase** while the base's own keys come out snake_case (no
    alias generator; the client reconciles through `registerTransform`), and FastAPI
    FILTERS any response key the declared model omits. Declare this with one field
    missing and that field silently vanishes from the wire — the first casualty would be
    `hosDriveHoursRemaining`, which the compliance tab reads to count DOT violations.
    Every field here is therefore asserted BY NAME against a real response in
    `test_the_drivers_list_declares_what_it_sends_realdb.py`; the mixed casing is the
    contract, not a mistake to tidy.

    `None` defaults are load-bearing on the three Optionals derived from lookups: a
    driver with no carrier, no assignment, or no HOS report carries `null`, and the
    consumers already distinguish `null` ("unknown") from values — see `_hours_remaining`,
    which refuses to invent a full tank for a driver who never reported.
    """

    carrierName: Optional[str] = None
    currentVehicleId: Optional[str] = None
    currentShipmentId: Optional[str] = None
    endorsements: List[str] = Field(default_factory=list)
    licenseExpiry: Optional[str] = None
    hosDriveHoursRemaining: Optional[float] = None
    hosDutyHoursRemaining: Optional[float] = None


class ShipmentBase(BaseModel):
    shipment_number: str
    pro_number: Optional[str] = None
    bol_number: Optional[str] = None
    shipment_type: str = "outbound"  # inbound, outbound, transfer
    origin: Dict[str, Any] = {}
    destination: Dict[str, Any] = {}
    scheduled_pickup: Optional[datetime] = None
    scheduled_delivery: Optional[datetime] = None
    priority: str = "normal"  # low, normal, high, critical
    total_weight_lbs: Optional[float] = None
    total_pieces: Optional[int] = None
    hazmat: bool = False
    temperature_required: bool = False
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class ShipmentCreate(ShipmentBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    route_id: Optional[UUID] = None


class ShipmentUpdate(BaseModel):
    status: Optional[str] = None
    driver_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    actual_pickup: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None
    priority: Optional[str] = None
    # SET ONCE AND NEVER CORRECTABLE (FS-671). Sixteen fields were on `ShipmentCreate` and
    # not here — a pickup could not be rescheduled, an address could not be fixed, a weight
    # could not be corrected, and these are the most ordinary events in dispatch.
    #
    # `route_id` closes a loop from FS-665: that fix stopped `get_shipment_costs` inventing
    # 500 miles, so a shipment with no route now honestly reports "not estimated" — and
    # nothing could assign it a route afterwards, which made the honest state inescapable
    # short of recreating the shipment.
    #
    # `shipment_number` is deliberately NOT here. It identifies the row, and an API that
    # lets a caller rename the thing it is addressing has a different problem.
    pro_number: Optional[str] = None
    bol_number: Optional[str] = None
    shipment_type: Optional[str] = None
    origin: Optional[Dict[str, Any]] = None
    destination: Optional[Dict[str, Any]] = None
    scheduled_pickup: Optional[datetime] = None
    scheduled_delivery: Optional[datetime] = None
    total_weight_lbs: Optional[float] = None
    total_pieces: Optional[int] = None
    hazmat: Optional[bool] = None
    temperature_required: Optional[bool] = None
    temperature_min: Optional[float] = None
    temperature_max: Optional[float] = None
    carrier_id: Optional[UUID] = None
    route_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class ShipmentResponse(ShipmentBase):
    # LIFECYCLE STATE LIVES HERE, NOT ON THE BASE (FS-668). `status`, `actual_pickup` and
    # `actual_delivery` were on `ShipmentBase`, so `ShipmentCreate` advertised all three —
    # and `create_shipment` writes `status='planned'` and never reads the other two, because
    # they are set by `update_shipment_status` when the events happen. A caller could send an
    # actual delivery date on a shipment that has not been picked up, get a 200, and find it
    # discarded.
    #
    # Moved rather than made Optional, on the argument FS-523 already made for
    # `organization_id` a few lines above: a field a caller can set that changes nothing is
    # its own small lie, and pydantic ignores extra keys by default, so a client still
    # sending one is unaffected. `ShipmentUpdate` carries all three, which is where a
    # lifecycle transition belongs.
    status: str = "planned"  # planned, dispatched, in_transit, delivered, cancelled
    actual_pickup: Optional[datetime] = None
    actual_delivery: Optional[datetime] = None

    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    shipment_type: Optional[str] = None
    id: UUID
    organization_id: UUID
    carrier_id: Optional[UUID]
    driver_id: Optional[UUID]
    trailer_id: Optional[UUID]
    route_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RouteBase(BaseModel):
    route_name: Optional[str] = None
    origin: Dict[str, Any] = {}
    destination: Dict[str, Any] = {}
    waypoints: List[Dict[str, Any]] = []
    total_distance_miles: Optional[float] = None
    estimated_duration_hours: Optional[float] = None
    fuel_cost_estimate: Optional[float] = None
    toll_cost_estimate: Optional[float] = None
    optimization_criteria: str = "balanced"  # fastest, cheapest, balanced
    is_active: bool = True


class RouteCreate(RouteBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    pass


class RouteUpdate(BaseModel):
    route_name: Optional[str] = None
    waypoints: Optional[List[Dict[str, Any]]] = None
    total_distance_miles: Optional[float] = None
    estimated_duration_hours: Optional[float] = None
    is_active: Optional[bool] = None
    # WIDENED, AND THE ROUTE THAT USES IT NOW EXISTS (FS-677). This schema was written and
    # never wired — there was no `PUT /routes/{id}` at all — so a route's endpoints and cost
    # estimates were fixed at creation forever. That matters more here than elsewhere:
    # `get_shipment_costs` prices a shipment from its route's distance (FS-665), so a route
    # entered with the wrong origin priced every shipment on it wrongly, with no correction
    # short of creating a second route and re-pointing each shipment at it.
    origin: Optional[Dict[str, Any]] = None
    destination: Optional[Dict[str, Any]] = None
    fuel_cost_estimate: Optional[float] = None
    toll_cost_estimate: Optional[float] = None
    optimization_criteria: Optional[str] = None


class RouteResponse(RouteBase):
    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    optimization_criteria: Optional[str] = None
    id: UUID
    organization_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoadPlanBase(BaseModel):
    load_sequence: List[Dict[str, Any]] = []
    weight_distribution: Dict[str, Any] = {}
    space_utilization_percent: Optional[float] = None
    temperature_zones: List[Dict[str, Any]] = []
    special_instructions: Optional[str] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class LoadPlanCreate(LoadPlanBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    shipment_id: UUID
    trailer_id: Optional[UUID] = None
    planned_by: Optional[UUID] = None


class LoadPlanUpdate(BaseModel):
    """A load plan that could not be amended (FS-677).

    There was no update schema and no route, so a plan's sequence, weight distribution and
    reefer zones were whatever the first POST said. Loading is iterative — a pallet does not
    fit, a zone is wrong — and the only remedy was to create a second plan for the same
    shipment and leave two contradicting each other on the row.

    `shipment_id` is deliberately absent: a load plan is a plan *for* a shipment, and moving
    it to another one makes it a different plan rather than a corrected one. Asserted in
    `test_what_can_be_created_can_be_corrected.py` so it reads as a decision.
    """

    load_sequence: Optional[List[Dict[str, Any]]] = None
    weight_distribution: Optional[Dict[str, Any]] = None
    space_utilization_percent: Optional[float] = None
    temperature_zones: Optional[List[Dict[str, Any]]] = None
    special_instructions: Optional[str] = None
    trailer_id: Optional[UUID] = None
    planned_by: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class LoadPlanResponse(LoadPlanBase):
    # LIFECYCLE STATE LIVES HERE, NOT ON THE BASE (FS-668). NOTHING IN THE CODEBASE SETS THESE. There is no execute-a-load-plan flow, so the
    # Create schema was advertising a lifecycle that does not exist — worse than an
    # ignored field, because a caller has no way to discover the gap.
    #
    # Moved rather than made Optional, on the argument FS-523 made for
    # `organization_id`: a field a caller can set that changes nothing is its own
    # small lie, and pydantic ignores extra keys by default, so a client still
    # sending one is unaffected.
    is_executed: bool = False
    executed_at: Optional[datetime] = None

    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    id: UUID
    organization_id: UUID
    shipment_id: Optional[UUID] = None
    trailer_id: Optional[UUID]
    planned_by: Optional[UUID]
    planned_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FreightChargeBase(BaseModel):
    charge_type: str  # linehaul, fuel, detention, demurrage, accessorial
    charge_description: Optional[str] = None
    rate_basis: Optional[str] = None  # per_mile, per_pound, flat, hourly
    quantity: Optional[float] = None
    rate: Optional[float] = None
    amount: float
    currency: str = "USD"
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class FreightChargeCreate(FreightChargeBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    shipment_id: UUID
    carrier_id: Optional[UUID] = None
    # `approved_by` was here and is now on the response with its siblings (FS-668/669).
    # Nothing in the codebase approves a freight charge — `approved_at`, `is_billed`,
    # `billed_at` and `invoice_number` moved for the same reason. A Create schema that
    # accepts an approver for a flow that does not exist is the most misleading of the set,
    # because it reads as an audit field.


class FreightChargeUpdate(BaseModel):
    """A billed figure that could never be corrected (FS-677).

    There was no update schema and no route. FS-665 found this same service inventing a
    500-mile default and a $2.50 rate, compounding into a $1,333.33 linehaul charge that was
    presented as computed — and once written, that number could not be amended by any means
    the API offered. A charge you cannot correct is worse than one that is wrong, because the
    wrongness becomes permanent at the moment it is noticed.

    `shipment_id` is deliberately absent, for the reason given on `LoadPlanUpdate`: a charge
    moved to a different shipment is a different charge.
    """

    charge_type: Optional[str] = None
    charge_description: Optional[str] = None
    rate_basis: Optional[str] = None
    quantity: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    carrier_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class FreightChargeResponse(FreightChargeBase):
    approved_by: Optional[UUID] = None
    # LIFECYCLE STATE LIVES HERE, NOT ON THE BASE (FS-668). NOTHING IN THE CODEBASE SETS THESE EITHER. Approval and billing are declared and
    # unimplemented; a caller could mark a charge billed, with an invoice number, on
    # creation. Kept on the response so the fields exist when the flow is built.
    #
    # Moved rather than made Optional, on the argument FS-523 made for
    # `organization_id`: a field a caller can set that changes nothing is its own
    # small lie, and pydantic ignores extra keys by default, so a client still
    # sending one is unaffected.
    is_billed: bool = False
    billed_at: Optional[datetime] = None
    invoice_number: Optional[str] = None
    approved_at: Optional[datetime] = None

    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    id: UUID
    organization_id: UUID
    shipment_id: Optional[UUID] = None
    carrier_id: Optional[UUID]
    approved_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== Correlation Schemas ====================

class DockAppointmentBase(BaseModel):
    appointment_type: str  # pickup, delivery, transfer
    scheduled_start: datetime
    scheduled_end: datetime
    priority: str = "normal"
    compliance_required: bool = False
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class DockAppointmentCreate(DockAppointmentBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    dock_door_id: UUID
    trailer_id: Optional[UUID] = None
    shipment_id: Optional[UUID] = None
    operation_id: Optional[UUID] = None
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None


class DockAppointmentUpdate(BaseModel):
    status: Optional[str] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    priority: Optional[str] = None
    # AN APPOINTMENT THAT COULD NOT BE RESCHEDULED (FS-677). This schema existed and no
    # route took it, so a dock appointment could be started and completed but never MOVED —
    # and rescheduling is the single most common thing that happens to an appointment. The
    # door, the carrier and the driver are the same story: a truck reassigned to another
    # bay meant cancelling and re-booking, losing the appointment's history with it.
    appointment_type: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    compliance_required: Optional[bool] = None
    dock_door_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    shipment_id: Optional[UUID] = None
    operation_id: Optional[UUID] = None
    carrier_id: Optional[UUID] = None
    driver_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class DockAppointmentResponse(DockAppointmentBase):
    # LIFECYCLE STATE LIVES HERE, NOT ON THE BASE (FS-668). `actual_start` and `actual_end` are written by `start_dock_appointment` and
    # `complete_dock_appointment`; `status` moves with them. A caller could declare an
    # appointment already finished at create time and be told 200.
    #
    # Moved rather than made Optional, on the argument FS-523 made for
    # `organization_id`: a field a caller can set that changes nothing is its own
    # small lie, and pydantic ignores extra keys by default, so a client still
    # sending one is unaffected.
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: str = "scheduled"  # scheduled, in_progress, completed, cancelled, no_show

    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    appointment_type: Optional[str] = None
    # THE SAME DEFECT THE COMMENT ABOVE DESCRIBES, one class over. `dock_appointments`
    # declares `meta_data = Column(JSON, default={})` — a PYTHON-side default, so a row
    # written by a migration, a seeder or any raw INSERT holds NULL, and the ORM hands this
    # field an explicit None. `Dict[str, Any]` with a `default_factory` does not save you
    # from an explicit None, so `GET /yard/dock/appointments` answered 500 with
    # "metadata: Input should be a valid dictionary" — a validation error naming OUR schema
    # rather than the row, so nobody would think to look at the data.
    #
    # `DockDoorResponse` was fixed for exactly this (see `equipment_capabilities` there) and
    # the appointment beside it was left. Method rule 18: the second instance is in the
    # nearest neighbour of the first.
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        validation_alias=AliasChoices('meta_data', 'metadata'),
        serialization_alias='metadata',
    )
    status: Optional[str] = None
    priority: Optional[str] = None
    id: UUID
    organization_id: UUID
    dock_door_id: Optional[UUID] = None
    trailer_id: Optional[UUID]
    shipment_id: Optional[UUID]
    operation_id: Optional[UUID]
    carrier_id: Optional[UUID]
    driver_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TruckAssetCorrelationBase(BaseModel):
    truck_arrived_at: Optional[datetime] = None
    asset_ready_at: Optional[datetime] = None
    asset_completion_forecast: Optional[datetime] = None
    readiness_gap_minutes: Optional[float] = None
    load_start_at: Optional[datetime] = None
    load_complete_at: Optional[datetime] = None
    detention_incurred: bool = False
    detention_charge: Optional[float] = None
    efficiency_score: Optional[float] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


# `TruckAssetCorrelationCreate` WAS HERE AND IS DELETED (FS-677).
#
# Nothing referenced it. The entity itself is very much alive — `logistics_correlation_engine`
# reads it twice and writes it once, deriving each row from a dock appointment and the
# operation feeding it — but it is derived, never posted. There is no create endpoint and
# there should not be one.
#
# Every field on the base is COMPUTED: `readiness_gap_minutes`, `efficiency_score`,
# `asset_completion_forecast`, and `detention_charge`, which is billable. A create schema for
# this shape is the FS-668/669 lie in its most expensive form — it advertises that a caller
# may declare how long a truck waited and what to charge for it. It also carried a required
# `organization_id`, the FS-523 shape, in a schema no route ever served.
#
# `TruckAssetCorrelationResponse` stays: `api/logistics_correlation.py` returns it, and
# reading a computed correlation was never the problem.
#
# A CORRECTION IS RECORDED HERE DELIBERATELY. This was first written up as "a table with five
# relationships and no reader and no writer anywhere", which was wrong. The grep that produced
# it ended in `head -6`, and `db/models.py` alone supplies six matching lines — the truncation
# hid every real use, and the truncated output read exactly like a complete answer.
class TruckAssetCorrelationResponse(TruckAssetCorrelationBase):
    id: UUID
    organization_id: UUID
    shipment_id: Optional[UUID]
    trailer_id: Optional[UUID]
    asset_id: Optional[UUID]
    operation_id: Optional[UUID]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LoadQualityLogBase(BaseModel):
    defect_type: Optional[str] = None  # wrong_product, damaged, short, over, temp_excursion
    severity: Optional[str] = None  # minor, major, critical
    quantity_affected: Optional[float] = None
    manufacturing_correlation_score: Optional[float] = None
    carrier_liable: bool = False
    claim_filed: bool = False
    claim_amount: Optional[float] = None
    resolved_at: Optional[datetime] = None
    metadata: JsonMetadata = Field(default_factory=dict, validation_alias=AliasChoices('meta_data', 'metadata'), serialization_alias='metadata')


class LoadQualityLogCreate(LoadQualityLogBase):
    # FS-523. `organization_id` was declared here and REQUIRED, while the handler
    # derives the tenant from the token and never reads the body's value — its own
    # comment says "FROM THE TOKEN, NEVER THE REQUEST". So the schema forced every
    # caller to send a value the server discards, and a caller who omitted it got a
    # 422. The frontend types carry no organization_id, so it omitted it: all twelve
    # of these create endpoints answered 422 to the only client that calls them.
    #
    # Removed rather than made Optional. A field a caller can set that changes nothing
    # is its own small lie, and pydantic ignores extra keys by default, so a client
    # still sending one is unaffected.
    shipment_id: Optional[UUID] = None
    trailer_id: Optional[UUID] = None
    # REQUIRED, because the column is (FS-523). `load_quality_logs.asset_id` is
    # `nullable=False` with no default; declaring it Optional here meant a caller who
    # omitted it reached the INSERT and got a NotNullViolationError — a **500** they
    # cannot act on, where the honest answer is a 422 naming the field.
    #
    # This was masked. Before the spurious `organization_id` above was removed, an
    # incomplete body failed validation on that first, so the endpoint answered 422 for
    # the wrong reason and the real missing field was never reached. Removing a field
    # that should not have been required revealed one that should have been.
    asset_id: UUID
    operation_id: Optional[UUID] = None
    # Same column shape, and NOT required: the service computes it
    # (`logistics_correlation_engine.py:509`, from `_analyze_root_cause`) and never reads
    # a caller's value, so requiring it would ask for something the server overwrites.
    # It is the second NOT NULL column on this table, and `_analyze_root_cause` defaults
    # it to `asset_id` — which is why fixing only the field above is enough.
    root_cause_asset: Optional[UUID] = None
    root_cause_operation: Optional[UUID] = None


class LoadQualityLogResponse(LoadQualityLogBase):
    id: UUID
    organization_id: UUID
    shipment_id: Optional[UUID]
    trailer_id: Optional[UUID]
    asset_id: Optional[UUID]
    operation_id: Optional[UUID]
    root_cause_asset: Optional[UUID]
    root_cause_operation: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ==================== Analytics Schemas ====================

class DwellTimeAnalytics(BaseModel):
    """Yard dwell time metrics"""
    trailer_id: UUID
    trailer_number: str
    check_in_at: datetime
    check_out_at: Optional[datetime]
    #: None when the trailer has no recorded check-in (FS-465) — an unknown dwell, not a
    #: zero one. Mirrors `detention_charge`, which is null until a charge is assessed.
    dwell_hours: Optional[float]
    is_detention: bool
    detention_charge: Optional[float]


class DockScheduleCorrelationResponse(BaseModel):
    """Dock schedule aligned with production"""
    dock_appointment: DockAppointmentResponse
    operation: Optional[OperationResponse]
    asset: Optional[AssetResponse]
    readiness_status: str  # on_time, early, late, at_risk
    estimated_completion: Optional[datetime]
    detention_risk_score: float  # 0-100


class LogisticsCorrelationResponse(BaseModel):
    """Cross-domain correlation data.

    Mirrors exactly what LogisticsCorrelationEngine.get_correlation_dashboard
    computes. It previously required `on_time_arrivals`, `late_arrivals` and
    `safety_incidents_today`, which nothing anywhere produces, so
    GET /logistics/correlation-dashboard raised ResponseValidationError on every
    call — it has never returned a successful response. It also dropped four
    fields the engine does compute (date, at_risk_appointments,
    quality_issues_today, sync_breakdown).

    The three phantom metrics are omitted rather than stubbed to null: add them
    here together with the query that derives them, so the contract keeps
    describing what the endpoint actually returns.
    """
    date: str
    truck_arrivals_today: int
    production_dock_sync_percent: float
    at_risk_appointments: int
    avg_dwell_time_hours: float
    total_detention_charges: float
    hos_violations: int
    quality_issues_today: int
    sync_breakdown: Dict[str, int]


class DetentionRiskPrediction(BaseModel):
    """Predicted detention risk for upcoming appointments"""
    appointment_id: UUID
    risk_score: float  # 0-100
    risk_level: str  # low, medium, high, critical
    factors: List[str]
    predicted_detention_minutes: Optional[float]
    recommended_actions: List[str]


# ==================== Kanban Task Management Schemas ====================

class TaskBoardBase(BaseModel):
    name: str = "Main Operations Board"
    board_type: str = "unified"  # unified, production, maintenance, quality, safety, logistics
    default_view_config: Dict[str, Any] = {}


class TaskBoardCreate(TaskBoardBase):
    organization_id: str


class TaskBoardResponse(TaskBoardBase):
    id: str
    organization_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskColumnBase(BaseModel):
    name: str
    position: int
    wip_limit: int = 5
    column_type: str  # backlog, triage, in_progress, review, rejected, done
    color: str = "#6366F1"
    is_collapsed: bool = False
    auto_archive_days: int = 7


class TaskColumnCreate(TaskColumnBase):
    board_id: str


class TaskColumnResponse(TaskColumnBase):
    id: str
    board_id: str
    created_at: datetime
    updated_at: datetime
    task_count: Optional[int] = 0  # Computed field

    model_config = ConfigDict(from_attributes=True)


class TaskChecklistItem(BaseModel):
    text: str
    completed: bool = False


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str  # production_job, maintenance_pm, maintenance_cm, quality_inspection, safety_check, alarm_response, command_execution, material_request, changeover, custom
    priority: str = "medium"  # low, medium, high, critical, emergency
    status: str = "draft"
    planned_start: Optional[datetime] = None
    planned_duration: Optional[int] = None  # minutes
    due_date: Optional[datetime] = None
    estimated_effort_minutes: Optional[int] = None
    tags: List[str] = []
    checklist_items: List[TaskChecklistItem] = []
    color_code: Optional[str] = None


class TaskCreate(TaskBase):
    board_id: str
    column_id: str
    assigned_to: Optional[str] = None
    asset_id: Optional[str] = None
    operation_id: Optional[str] = None
    alarm_id: Optional[str] = None
    command_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    custom_fields: Dict[str, Any] = {}
    completion_actions: Dict[str, Any] = {}


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_to: Optional[str] = None
    column_id: Optional[str] = None
    position: Optional[int] = None
    progress_percent: Optional[int] = None
    checklist_items: Optional[List[TaskChecklistItem]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    due_date: Optional[datetime] = None
    color_code: Optional[str] = None
    # TWELVE FIELDS A TASK COULD BE CREATED WITH AND NEVER CORRECTED (FS-677). A task's
    # type, its planned start and duration, its effort estimate, its tags, and every link
    # it carries — asset, operation, alarm, command, parent — were settable once and frozen,
    # on a board whose whole purpose is that work changes.
    #
    # UNLIKE THE OTHER UPDATE SCHEMAS IN THIS FILE, widening this one is not sufficient on
    # its own: `update_task` does not apply `model_dump(exclude_unset=True)`, it hand-writes
    # an `if x is not None` block per field so it can build the activity-log changelog. A
    # field added here and not added there is declared, accepted, and silently dropped —
    # which is the defect FS-676 had just finished fixing elsewhere. Both halves are done,
    # and `test_declared_body_fields_reach_the_service.py` is the guard that keeps them
    # together.
    #
    # `board_id` and `parent_task_id` carry constraints the handler enforces: a column must
    # belong to the task's effective board, and a task may not become its own ancestor.
    task_type: Optional[str] = None
    planned_start: Optional[datetime] = None
    planned_duration: Optional[int] = None
    estimated_effort_minutes: Optional[int] = None
    tags: Optional[List[str]] = None
    completion_actions: Optional[Dict[str, Any]] = None
    board_id: Optional[str] = None
    asset_id: Optional[str] = None
    operation_id: Optional[str] = None
    alarm_id: Optional[str] = None
    command_id: Optional[str] = None
    parent_task_id: Optional[str] = None


class TaskResponse(TaskBase):
    id: UUID
    board_id: UUID
    column_id: UUID
    position: int
    assigned_to: Optional[UUID]
    assigned_by: Optional[UUID]
    assigned_at: Optional[datetime]
    actual_start: Optional[datetime]
    actual_end: Optional[datetime]
    asset_id: Optional[UUID]
    operation_id: Optional[UUID]
    alarm_id: Optional[str]
    command_id: Optional[str]
    work_order_id: Optional[str]
    parent_task_id: Optional[UUID]
    rule_id: Optional[UUID]
    progress_percent: int
    time_logged_minutes: int
    custom_fields: Dict[str, Any]
    approval_status: str
    approved_by: Optional[UUID]
    approved_at: Optional[datetime]
    rejection_reason: Optional[str]
    completion_actions: Dict[str, Any]
    completion_result: Dict[str, Any]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    completed_by: Optional[UUID]

    model_config = ConfigDict(from_attributes=True)


class TaskMoveRequest(BaseModel):
    target_column_id: str
    position: Optional[int] = None


class TaskApprovalRequest(BaseModel):
    action: str  # approve, reject
    reason: Optional[str] = None  # Required for reject


class TaskCommentBase(BaseModel):
    content: str
    comment_type: str = "comment"  # comment, system, time_log, status_change, approval_action


class TaskCommentCreate(TaskCommentBase):
    task_id: UUID


class TaskCommentResponse(TaskCommentBase):
    # Mirrors the columns: nullable on the table with NO server default, so a row
    # written outside SQLAlchemy (migration, seeder, raw INSERT) hands these an
    # explicit None. A pydantic default does not help — the ORM passes the None
    # rather than omitting the field. Response-only; create/update keep their
    # stricter types.
    content: Optional[str] = None
    id: UUID
    task_id: UUID
    user_id: Optional[UUID]
    extra_data: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskTimerStart(BaseModel):
    description: Optional[str] = None


class TaskTimerStop(BaseModel):
    description: Optional[str] = None


class TaskTimerResponse(BaseModel):
    id: UUID
    task_id: UUID
    user_id: UUID
    started_at: datetime
    ended_at: Optional[datetime]
    duration_minutes: int
    is_running: bool
    description: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskRuleBase(BaseModel):
    rule_name: str
    description: Optional[str] = None
    trigger_type: str
    trigger_conditions: Dict[str, Any] = {}
    task_template: Dict[str, Any] = {}
    auto_approve_emergency: bool = False
    auto_approve_timeout_minutes: int = 30
    assignee_rule: str = "asset_owner"  # round_robin, asset_owner, supervisor, specific_user
    escalation_config: Dict[str, Any] = {}
    completion_actions: Dict[str, Any] = {}


class TaskRuleCreate(TaskRuleBase):
    # THE THIRTEENTH (FS-677). FS-523 removed a required, server-discarded
    # `organization_id` from twelve create schemas; this one was found by the guard,
    # recorded in `test_declared_body_fields_reach_the_service.py` as another lane's, and
    # left. `create_task_rule` writes `current_user.organization_id` and never reads the
    # body's value, so every caller had to send a tenant id that was thrown away — and the
    # natural client, which carries none, got a 422 on every attempt to create a rule.
    #
    # Removed rather than made Optional, for the reason the other twelve carry: a field a
    # caller can set that changes nothing is its own small lie, and pydantic ignores extra
    # keys, so a client still sending one is unaffected.
    target_board_id: Optional[UUID] = None
    target_column_id: Optional[UUID] = None
    specific_assignee_id: Optional[UUID] = None
    notify_users: List[UUID] = []


class TaskRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    trigger_conditions: Optional[Dict[str, Any]] = None
    task_template: Optional[Dict[str, Any]] = None
    auto_approve_emergency: Optional[bool] = None
    auto_approve_timeout_minutes: Optional[int] = None
    assignee_rule: Optional[str] = None
    escalation_config: Optional[Dict[str, Any]] = None
    # SIX FIELDS A RULE COULD BE CREATED WITH AND NEVER CORRECTED (FS-677). What fires the
    # rule, where the task it creates lands, who it goes to, who gets told, and what happens
    # on completion — every routing decision the rule makes was frozen at creation, while
    # the rule's name and its escalation policy were editable beside them.
    #
    # `organization_id` is deliberately absent and is NOT part of this gap: the tenant comes
    # from the token, and a body field naming it is the IDOR shape `app/core/tenant.py`
    # forbids. It has been removed from the Create schema in the same change.
    trigger_type: Optional[str] = None
    target_board_id: Optional[UUID] = None
    target_column_id: Optional[UUID] = None
    specific_assignee_id: Optional[UUID] = None
    notify_users: Optional[List[UUID]] = None
    completion_actions: Optional[Dict[str, Any]] = None


class TaskRuleResponse(TaskRuleBase):
    id: UUID
    organization_id: UUID
    is_active: bool
    is_system_rule: bool
    target_board_id: Optional[UUID]
    target_column_id: Optional[UUID]
    specific_assignee_id: Optional[UUID]
    notify_users: List[UUID]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskRuleTemplateResponse(TaskRuleBase):
    """A premade rule a user can activate — NOT an activated rule (FS-431).

    `/kanban/rules/premade` declared `List[TaskRuleResponse]` and returned five static
    dicts. `TaskRuleResponse` requires `id: UUID`, `organization_id: UUID`, `is_active`,
    `created_at` and `updated_at`; a template has none of those, and its ids are literals
    like 'template-001'. So response validation raised on every call and the endpoint has
    answered 500 since it was written — on any database, with no data involved.

    The declaration was a category error, not a missing field: a template is a thing you
    could create, so it has no identity, no owner and no history until you do. Modelling it
    as a rule forces five values to be invented before anyone has asked for one.

    `template_id` is deliberately a `str`. Widening `TaskRuleResponse.id` to accept both
    would have made every real rule's id un-typed to spare these five constants.
    """

    template_id: str
    is_system_rule: bool = True


class TaskRuleTestRequest(BaseModel):
    sample_data: Dict[str, Any]  # Simulated trigger data to test against


class TaskRuleTestResponse(BaseModel):
    would_trigger: bool
    matched_conditions: List[str]
    generated_task_preview: Optional[Dict[str, Any]]


class KanbanViewFilter(BaseModel):
    view_type: str = "all"  # all, by_asset, by_workcell, by_type, by_priority, by_assignee
    asset_id: Optional[UUID] = None
    workcell_id: Optional[UUID] = None
    task_type: Optional[str] = None
    priority: Optional[str] = None
    assignee_id: Optional[UUID] = None
    status: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class KanbanBoardData(BaseModel):
    board: TaskBoardResponse
    columns: List[TaskColumnResponse]
    tasks: List[TaskResponse]
    view_config: Dict[str, Any]


class KanbanMetrics(BaseModel):
    total_tasks: int
    tasks_by_column: Dict[str, int]
    tasks_by_priority: Dict[str, int]
    tasks_awaiting_approval: int
    overdue_tasks: int
    avg_cycle_time_minutes: Optional[float]
    tasks_completed_today: int
    active_escalations: int


class KanbanWorkloadItem(BaseModel):
    user_id: UUID
    user_name: str
    assigned_tasks: int
    in_progress_tasks: int
    overdue_tasks: int
    avg_completion_time: Optional[float]


class KanbanWorkloadResponse(BaseModel):
    workloads: List[KanbanWorkloadItem]


class TaskEscalationResponse(BaseModel):
    id: UUID
    task_id: UUID
    rule_id: Optional[UUID]
    escalation_level: int
    triggered_at: datetime
    resolved_at: Optional[datetime]
    notified_users: List[UUID]
    actions_taken: List[str]
    notification_channels: List[str]

    model_config = ConfigDict(from_attributes=True)


# ============ Actionable Registries Schemas ============

class ActionableRegistryBase(BaseModel):
    registry_name: str
    registry_type: str  # safety, quality, environmental, operational, regulatory
    registry_category: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    is_compliance: bool = False
    frequency: Optional[str] = None  # daily, weekly, monthly, quarterly, annually, as_needed
    next_due_date: Optional[datetime] = None
    last_completed_date: Optional[datetime] = None
    compliance_score: int = 0
    priority_level: str = "medium"  # low, medium, high, critical
    assigned_owner_id: Optional[UUID] = None
    assigned_team_id: Optional[UUID] = None
    reference_url: Optional[str] = None
    checklist_requirements: List[Dict[str, Any]] = []
    meta_data: Dict[str, Any] = {}


class ActionableRegistryCreate(ActionableRegistryBase):
    pass


class ActionableRegistryUpdate(BaseModel):
    registry_name: Optional[str] = None
    registry_type: Optional[str] = None
    registry_category: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    is_compliance: Optional[bool] = None
    frequency: Optional[str] = None
    next_due_date: Optional[datetime] = None
    last_completed_date: Optional[datetime] = None
    compliance_score: Optional[int] = None
    priority_level: Optional[str] = None
    assigned_owner_id: Optional[UUID] = None
    assigned_team_id: Optional[UUID] = None
    reference_url: Optional[str] = None
    checklist_requirements: Optional[List[Dict[str, Any]]] = None
    meta_data: Optional[Dict[str, Any]] = None


class ActionableRegistryResponse(ActionableRegistryBase):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionableRegistryItemBase(BaseModel):
    item_code: str
    item_name: str
    item_description: Optional[str] = None
    severity_level: str = "medium"  # low, medium, high, critical
    is_active: bool = True
    is_required: bool = True
    completion_criteria: Optional[str] = None
    verification_method: Optional[str] = None  # inspection, test, documentation, audit
    estimated_effort_minutes: Optional[int] = None
    related_task_id: Optional[UUID] = None
    last_completed_at: Optional[datetime] = None
    next_due_at: Optional[datetime] = None
    completion_frequency: Optional[str] = None  # daily, weekly, monthly, quarterly, annually
    compliance_score: int = 0
    risk_score: int = 0
    meta_data: Dict[str, Any] = {}


class ActionableRegistryItemCreate(ActionableRegistryItemBase):
    registry_id: UUID


class ActionableRegistryItemUpdate(BaseModel):
    item_code: Optional[str] = None
    item_name: Optional[str] = None
    item_description: Optional[str] = None
    severity_level: Optional[str] = None
    is_active: Optional[bool] = None
    is_required: Optional[bool] = None
    completion_criteria: Optional[str] = None
    verification_method: Optional[str] = None
    estimated_effort_minutes: Optional[int] = None
    related_task_id: Optional[UUID] = None
    last_completed_at: Optional[datetime] = None
    next_due_at: Optional[datetime] = None
    completion_frequency: Optional[str] = None
    compliance_score: Optional[int] = None
    risk_score: Optional[int] = None
    meta_data: Optional[Dict[str, Any]] = None


class ActionableRegistryItemResponse(ActionableRegistryItemBase):
    id: UUID
    registry_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DataCorrelationBase(BaseModel):
    correlation_type: str  # task_to_registry, task_to_asset, task_to_alarm, registry_to_asset
    source_type: str  # task, registry_item, asset, alarm, operation
    source_id: Optional[UUID] = None
    target_type: str  # task, registry_item, asset, alarm, operation
    target_id: Optional[UUID] = None
    correlation_strength: int = 50  # 0-100
    correlation_method: str = "manual"  # manual, automated, ai_suggested
    confidence_score: int = 0  # 0-100
    is_active: bool = True
    is_bidirectional: bool = False
    correlation_meta_data: Dict[str, Any] = {}


class DataCorrelationCreate(DataCorrelationBase):
    pass


class DataCorrelationUpdate(BaseModel):
    correlation_strength: Optional[int] = None
    confidence_score: Optional[int] = None
    is_active: Optional[bool] = None
    # A CORRELATION WITH NO ENDPOINTS COULD NEVER BE GIVEN ANY (FS-676). `source_id` and
    # `target_id` are nullable columns and optional on create, so a correlation can be filed
    # between "a task" and "an asset" with neither identified — and these three fields were
    # the whole Update schema, so it could never be completed. That is the shape FS-665 left
    # behind on shipments: an incomplete record with no route back.
    #
    # The rest are plain attributes of the correlation rather than its identity, and the
    # asymmetry had no reason behind it — `correlation_meta_data` in particular is the field
    # a caller is most likely to want to amend.
    correlation_type: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[UUID] = None
    target_type: Optional[str] = None
    target_id: Optional[UUID] = None
    correlation_method: Optional[str] = None
    is_bidirectional: Optional[bool] = None
    correlation_meta_data: Optional[Dict[str, Any]] = None


class DataCorrelationResponse(DataCorrelationBase):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Alarm rules (FS-218)
# ---------------------------------------------------------------------------

COMPARATORS = ("gt", "gte", "lt", "lte", "eq", "ne")
SEVERITIES = ("critical", "high", "medium", "low", "info")


class AlarmRuleBase(BaseModel):
    """Shared fields. Validation mirrors the CHECK constraints in migration 047 so
    a bad rule is rejected at the edge of the API with a 422 naming the field,
    rather than as an opaque IntegrityError from Postgres.
    """

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None

    metric_name: str = Field(min_length=1, max_length=255)
    comparator: Literal["gt", "gte", "lt", "lte", "eq", "ne"]
    threshold: float

    duration_seconds: int = Field(default=0, ge=0)
    hysteresis: float = Field(default=0.0, ge=0)

    severity: Literal["critical", "high", "medium", "low", "info"]
    alarm_code: str = Field(min_length=1, max_length=100)
    # Rendered with {asset_id}, {metric_name}, {value}, {threshold}. Left None to
    # get a generated message.
    message_template: Optional[str] = None

    # Targeting: most specific wins. All None = every asset in the organization.
    asset_id: Optional[UUID] = None
    asset_type_id: Optional[UUID] = None
    workcell_id: Optional[UUID] = None

    is_enabled: bool = True


class AlarmRuleCreate(AlarmRuleBase):
    pass


class AlarmRuleUpdate(BaseModel):
    """All fields optional — PATCH semantics.

    Deliberately NOT `AlarmRuleBase` with defaults: that would make omitting a
    field indistinguishable from resetting it to the default, so a PATCH that only
    changed `threshold` would silently re-enable a disabled rule.
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    metric_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    comparator: Optional[Literal["gt", "gte", "lt", "lte", "eq", "ne"]] = None
    threshold: Optional[float] = None
    duration_seconds: Optional[int] = Field(default=None, ge=0)
    hysteresis: Optional[float] = Field(default=None, ge=0)
    severity: Optional[Literal["critical", "high", "medium", "low", "info"]] = None
    alarm_code: Optional[str] = Field(default=None, min_length=1, max_length=100)
    message_template: Optional[str] = None
    asset_id: Optional[UUID] = None
    asset_type_id: Optional[UUID] = None
    workcell_id: Optional[UUID] = None
    is_enabled: Optional[bool] = None


class AlarmRuleResponse(AlarmRuleBase):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Admin user management (FS-221)
# ---------------------------------------------------------------------------

class UserAdminCreate(BaseModel):
    """Deliberately has NO organization_id field.

    The endpoint derives it from the caller's token, so a client cannot place a
    user into another tenant — the tenant-trust shape already fixed in yard,
    dashboard and alarms.
    """

    # `str` with a pattern, not pydantic's EmailStr: that requires the
    # `email-validator` package, which is not a dependency of this project, and
    # every other schema here (UserLogin, UserCreate) uses a plain str. A new
    # runtime dependency for one field is not worth it; a pattern still rejects
    # the mistakes that matter (missing @, whitespace, no domain).
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    full_name: Optional[str] = Field(default=None, max_length=255)
    password: str = Field(min_length=12, max_length=128)
    # Literal, not str: an unconstrained role stored fine and then matched no
    # require_* dependency, leaving the account with no permissions at all.
    role: Literal["viewer", "operator", "admin"] = "operator"
    department: Optional[str] = Field(default=None, max_length=100)


class UserAdminUpdate(BaseModel):
    """PATCH semantics — every field optional.

    Not `UserAdminCreate` with defaults: that would make omitting `is_active`
    indistinguishable from setting it, so an edit to someone's department could
    silently reactivate a deactivated account.
    """

    full_name: Optional[str] = Field(default=None, max_length=255)
    role: Optional[Literal["viewer", "operator", "admin"]] = None
    department: Optional[str] = Field(default=None, max_length=100)
    is_active: Optional[bool] = None


class UserAdminResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str] = None
    role: str
    department: Optional[str] = None
    organization_id: Optional[UUID] = None
    is_active: bool
    last_login: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # No hashed_password field: response_model filtering is what keeps the hash
    # out of the payload, so this class is a security boundary, not just a shape.
    model_config = ConfigDict(from_attributes=True)
