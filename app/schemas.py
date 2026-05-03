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
