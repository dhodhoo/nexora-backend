from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DeviceSchedule(BaseModel):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=23)


class ConsumptionEvent(BaseModel):
    community_id: str
    unit_id: str
    device_id: str
    timestamp: datetime
    kwh: Optional[float] = None
    power_watt: Optional[float] = None
    controllable: bool
    schedules: Optional[List[DeviceSchedule]] = None


class UnitSummaryResponse(BaseModel):
    community_id: str
    unit_id: str
    total_kwh: float
    estimated_cost: float
    estimated_emission_kg_co2e: float
    last_timestamp: Optional[datetime]
    is_fresh: bool


class PeakRiskResponse(BaseModel):
    community_id: str
    peak_hour: Optional[str]
    peak_kwh: float
    risk_level: str


class DeviceMetadataResponse(BaseModel):
    device_id: str
    controllable: bool
    schedules: Optional[list]


class UnitVaUpdateRequest(BaseModel):
    va: int = Field(gt=0)


class CommunityCreateRequest(BaseModel):
    community_id: str = Field(min_length=1, max_length=32)
    name: Optional[str] = Field(default=None, max_length=128)


class CommunityUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)


class CommunityResponse(BaseModel):
    community_id: str
    name: Optional[str] = None


class ListMetaResponse(BaseModel):
    total: int
    offset: int
    limit: int
    has_next: bool
    unread_count: Optional[int] = None


class CommunitiesListResponse(BaseModel):
    items: List[CommunityResponse]
    meta: ListMetaResponse


class UnitCreateRequest(BaseModel):
    unit_id: str = Field(min_length=1, max_length=32)
    va: int = Field(gt=0)


class UnitUpdateRequest(BaseModel):
    va: int = Field(gt=0)


class UnitCrudResponse(BaseModel):
    community_id: str
    unit_id: str
    va: int


class UnitsListResponse(BaseModel):
    items: List[UnitCrudResponse]
    meta: ListMetaResponse


class CommunityUnitSummaryItem(BaseModel):
    community_id: str
    unit_id: str
    va: int
    total_kwh: float
    estimated_cost: float
    estimated_emission_kg_co2e: float
    last_timestamp: Optional[datetime]
    is_fresh: bool


class AIStatusResponse(BaseModel):
    community_id: str
    exists: bool
    healthy: bool
    last_run_at: Optional[str] = None
    last_success_at: Optional[str] = None
    stale: bool
    error: str
    source: str


class DashboardCommunitySummary(BaseModel):
    community_id: str
    name: Optional[str] = None
    total_units: int
    total_kwh: float
    estimated_cost: float
    estimated_emission_kg_co2e: float
    last_timestamp: Optional[datetime]
    is_fresh: bool


class DashboardResponse(BaseModel):
    community: DashboardCommunitySummary
    units_summary: List[CommunityUnitSummaryItem]
    load_curve: List[Dict[str, Any]]
    peak_risk: PeakRiskResponse
    ai_status: AIStatusResponse
    unit_ai_recommendations: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    include_simulation_used: bool = False
    generated_at: datetime


class UnitDashboardSummary(BaseModel):
    community_id: str
    unit_id: str
    va: int
    total_kwh: float
    estimated_cost: float
    estimated_emission_kg_co2e: float
    last_timestamp: Optional[datetime]
    is_fresh: bool


class UnitDashboardResponse(BaseModel):
    community_id: str
    unit_id: str
    unit_summary: UnitDashboardSummary
    load_curve: List[Dict[str, Any]]
    peak_risk: PeakRiskResponse
    ai_recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime


class AIRecommendationItem(BaseModel):
    unit_id: Optional[str] = None
    device: Optional[str] = None
    action: Optional[str] = None
    saving: Optional[float] = None
    co2_reduction: Optional[float] = None
    estimated_reduction_kwh: Optional[float] = None
    reasons: List[str] = Field(default_factory=list)


class AIRecommendationsResponse(BaseModel):
    community_id: str
    exists: bool
    analyzed_at: Optional[str] = None
    status: Optional[str] = None
    stale: bool
    source: str
    recommendations: List[AIRecommendationItem] = Field(default_factory=list)


class UnitAIRecommendationsResponse(BaseModel):
    community_id: str
    unit_id: str
    exists: bool
    analyzed_at: Optional[str] = None
    status: Optional[str] = None
    stale: bool
    source: str
    recommendations: List[AIRecommendationItem] = Field(default_factory=list)


class IngestionPerCommunityItem(BaseModel):
    community_id: str
    readings_count: int
    last_ingestion_at: Optional[str] = None


class IngestionStatusResponse(BaseModel):
    mqtt: Dict[str, Any]
    totals: Dict[str, int]
    latest: Dict[str, Optional[str]]
    per_community: List[IngestionPerCommunityItem] = Field(default_factory=list)


class DeadLetterItem(BaseModel):
    id: int
    topic: str
    reason: str
    raw_payload: str
    created_at: str


class DeadLettersResponse(BaseModel):
    total: int
    items: List[DeadLetterItem] = Field(default_factory=list)


class DeadLettersListResponse(BaseModel):
    items: List[DeadLetterItem] = Field(default_factory=list)
    meta: ListMetaResponse


class BulkDeleteUnitsRequest(BaseModel):
    unit_ids: List[str] = Field(min_length=1)


class BulkDeleteUnitsResponse(BaseModel):
    community_id: str
    requested_count: int
    deleted_count: int
    not_found_unit_ids: List[str] = Field(default_factory=list)


class AnalyzeDeviceSchedule(BaseModel):
    hours: Optional[List[int]] = None


class AnalyzeDevice(BaseModel):
    state: Optional[bool] = None
    power: Optional[float] = None
    controllable: Optional[bool] = None
    schedule: Optional[AnalyzeDeviceSchedule] = None


class AnalyzeUnit(BaseModel):
    unit_id: str
    tariff: Optional[float] = None
    base_load_kwh: Optional[float] = None
    consumption_kwh: Optional[float] = None
    devices: Dict[str, AnalyzeDevice] = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    community_id: str
    timestamp: datetime
    units: List[AnalyzeUnit]


class ResetRequest(BaseModel):
    community_id: Optional[str] = None


class StateQuery(BaseModel):
    community_id: Optional[str] = None


JsonDict = Dict[str, Any]


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class AuthMeResponse(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    status: str
    community_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_id: Optional[str] = None


class MeDashboardUser(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    status: str


class MeDashboardScope(BaseModel):
    community_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_id: Optional[str] = None


class MeDashboardResponse(BaseModel):
    user: MeDashboardUser
    scope: MeDashboardScope
    widgets: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class UserCreateRequest(BaseModel):
    user_id: str
    full_name: str
    email: str
    password: str
    role: str
    status: str = "PENDING"
    community_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_id: Optional[str] = None


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    community_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_id: Optional[str] = None


class UserResponse(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    status: str
    community_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_id: Optional[str] = None


class UsersListResponse(BaseModel):
    items: List[UserResponse]
    meta: ListMetaResponse


class CommunityMemberItem(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    status: str
    community_id: Optional[str] = None


class CommunityMembersListResponse(BaseModel):
    items: List[CommunityMemberItem]
    meta: ListMetaResponse


class AddCommunityMemberRequest(BaseModel):
    user_id: str


class CommunityMemberMutationResponse(BaseModel):
    community_id: str
    user_id: str
    status: str


class CommunitySimulationStateResponse(BaseModel):
    community_id: str
    simulation_enabled: bool
    updated_at: Optional[datetime] = None
    source: str


class CommunitySimulationToggleRequest(BaseModel):
    simulation_enabled: bool


class ResetPasswordRequest(BaseModel):
    new_password: str


class BuildingCreateRequest(BaseModel):
    building_id: str
    name: Optional[str] = None


class BuildingUpdateRequest(BaseModel):
    name: Optional[str] = None


class BuildingResponse(BaseModel):
    building_id: str
    name: Optional[str] = None


class BuildingDetailResponse(BaseModel):
    building_id: str
    name: Optional[str] = None


class BuildingsListResponse(BaseModel):
    items: List[BuildingResponse]
    meta: ListMetaResponse


class BroadcastRequest(BaseModel):
    message: str


class BuildingUnitCreateRequest(BaseModel):
    unit_id: str = Field(min_length=1, max_length=32)
    is_active: bool = True
    metadata_json: Optional[Dict[str, Any]] = None


class BuildingUnitUpdateRequest(BaseModel):
    is_active: Optional[bool] = None
    metadata_json: Optional[Dict[str, Any]] = None


class BuildingUnitResponse(BaseModel):
    building_id: str
    unit_id: str
    is_active: bool
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class BuildingUnitsListResponse(BaseModel):
    items: List[BuildingUnitResponse]
    meta: ListMetaResponse


class BuildingReportMetadataResponse(BaseModel):
    building_id: str
    report_type: str
    generated_at: datetime
    period: Dict[str, Optional[str]]
    summary: Dict[str, Any]
    download_url: Optional[str] = None


class BuildingConsumptionPoint(BaseModel):
    bucket: str
    total_kwh: float
    estimated_cost: float


class BuildingConsumptionResponse(BaseModel):
    building_id: str
    series: List[BuildingConsumptionPoint]
    total_kwh: float
    estimated_cost: float
    last_timestamp: Optional[datetime]
    is_fresh: bool


class BuildingPredictionsResponse(BaseModel):
    building_id: str
    exists: bool
    generated_at: Optional[str] = None
    community_context: Dict[str, Any] = Field(default_factory=dict)
    unit_predictions: Dict[str, float] = Field(default_factory=dict)


class BuildingRecommendationItem(BaseModel):
    unit_id: Optional[str] = None
    device: Optional[str] = None
    action: Optional[str] = None
    saving: Optional[float] = None
    co2_reduction: Optional[float] = None
    estimated_reduction_kwh: Optional[float] = None
    reasons: List[str] = Field(default_factory=list)


class BuildingRecommendationsResponse(BaseModel):
    building_id: str
    exists: bool
    generated_at: Optional[str] = None
    items: List[BuildingRecommendationItem] = Field(default_factory=list)


class BuildingConfigResponse(BaseModel):
    building_id: str
    peak_threshold_kwh: float
    source: str


class BuildingConfigUpdateRequest(BaseModel):
    peak_threshold_kwh: float = Field(gt=0)


class NotificationDeliveryItem(BaseModel):
    target_type: str
    target_id: str
    status: str
    delivered_at: Optional[datetime] = None
    error: Optional[str] = None


class NotificationResponse(BaseModel):
    notification_id: str
    scope: str
    community_id: Optional[str] = None
    building_id: Optional[str] = None
    message: str
    created_by_user_id: Optional[str] = None
    created_at: datetime
    is_read: bool = False
    read_at: Optional[datetime] = None
    deliveries: List[NotificationDeliveryItem] = Field(default_factory=list)


class NotificationsListResponse(BaseModel):
    items: List[NotificationResponse]
    meta: ListMetaResponse


class NotificationMarkReadResponse(BaseModel):
    status: str
    notification_id: str
    read_at: datetime


class NotificationMarkAllReadResponse(BaseModel):
    status: str
    affected_count: int


class DeviceCatalogCreateRequest(BaseModel):
    device_key: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    default_power_watt: Optional[float] = Field(default=None, gt=0)
    controllable: bool = True


class DeviceCatalogUpdateRequest(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    default_power_watt: Optional[float] = Field(default=None, gt=0)
    controllable: Optional[bool] = None
    is_active: Optional[bool] = None


class DeviceCatalogResponse(BaseModel):
    device_key: str
    display_name: str
    default_power_watt: Optional[float] = None
    controllable: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DeviceCatalogListResponse(BaseModel):
    items: List[DeviceCatalogResponse]
    meta: ListMetaResponse


class UnitDeviceCreateRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    qty: int = Field(default=1, ge=1)
    controllable: bool = True
    schedules: Optional[List[Dict[str, Any]]] = None


class UnitDeviceUpdateRequest(BaseModel):
    qty: Optional[int] = Field(default=None, ge=1)
    controllable: Optional[bool] = None
    schedules: Optional[List[Dict[str, Any]]] = None


class UnitDeviceResponse(BaseModel):
    device_id: str
    device_name: str
    qty: int
    controllable: bool
    schedules: Optional[List[Dict[str, Any]]] = None


class UnitDevicesListResponse(BaseModel):
    items: List[UnitDeviceResponse]
    meta: ListMetaResponse


class DeviceControlRequest(BaseModel):
    action: str = Field(pattern="^(on|off)$")


class DeviceControlResponse(BaseModel):
    command_id: str
    community_id: str
    unit_id: str
    device_id: str
    action: str
    topic: str
    status: str
    error: Optional[str] = None
    created_at: datetime
