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
