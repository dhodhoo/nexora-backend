from datetime import datetime, timedelta
import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import AIAnalysisResult, AuditLog, Building, BuildingConfig, BuildingUnit, Community, CommunitySimulationConfig, DeadLetter, Device, DeviceCatalog, DeviceCommand, EnergyReading, Notification, NotificationDelivery, NotificationRead, RevokedToken, Unit, User, UserRole, UserStatus
from app.schemas import (
    AddCommunityMemberRequest,
    AIRecommendationsResponse,
    AIStatusResponse,
    AuthMeResponse,
    BroadcastRequest,
    BuildingCreateRequest,
    BuildingConfigResponse,
    BuildingConfigUpdateRequest,
    BuildingConsumptionPoint,
    BuildingConsumptionResponse,
    BuildingDetailResponse,
    BuildingPredictionsResponse,
    BuildingRecommendationItem,
    BuildingRecommendationsResponse,
    BuildingReportMetadataResponse,
    BuildingUpdateRequest,
    BuildingResponse,
    BuildingUnitCreateRequest,
    BuildingUnitResponse,
    BuildingUnitsListResponse,
    BuildingUnitUpdateRequest,
    BuildingsListResponse,
    BulkDeleteUnitsRequest,
    BulkDeleteUnitsResponse,
    CommunityMemberItem,
    CommunityMemberMutationResponse,
    CommunitySimulationStateResponse,
    CommunitySimulationToggleRequest,
    CommunityMembersListResponse,
    CommunitiesListResponse,
    CommunityCreateRequest,
    CommunityResponse,
    CommunityUnitSummaryItem,
    CommunityUpdateRequest,
    DashboardResponse,
    DeadLetterItem,
    DeadLettersListResponse,
    DeviceEmissionItem,
    DeviceMetadataResponse,
    DeviceCatalogCreateRequest,
    DeviceCatalogListResponse,
    DeviceCatalogResponse,
    DeviceCatalogUpdateRequest,
    DeviceControlRequest,
    DeviceControlResponse,
    IngestionPerCommunityItem,
    IngestionStatusResponse,
    LoginRequest,
    MeDashboardResponse,
    MeDashboardScope,
    MeDashboardUser,
    PeakRiskResponse,
    PeriodComparison,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    UnitCreateRequest,
    UnitDeviceCreateRequest,
    UnitDashboardResponse,
    UnitDailyEmissionPoint,
    UnitDailyEmissionsResponse,
    UnitDeviceResponse,
    UnitDevicesListResponse,
    UnitDeviceUpdateRequest,
    UnitCrudResponse,
    UnitAIRecommendationsResponse,
    UnitsListResponse,
    UnitSummaryResponse,
    UnitUpdateRequest,
    UnitVaUpdateRequest,
    UserCreateRequest,
    UserResponse,
    UsersListResponse,
    UserUpdateRequest,
    NotificationResponse,
    NotificationDeliveryItem,
    NotificationsListResponse,
    NotificationMarkReadResponse,
    NotificationMarkAllReadResponse,
)
from app.services.ai_integration import ai_orchestrator
from app.services.ai_recommendations import get_latest_ai_result, parse_recommendations
from app.services.auth import AuthService, ensure_building_access, ensure_community_access, get_current_user, require_roles
from app.services.dashboard import build_dashboard_snapshot, build_load_curve, build_peak_risk, build_units_summary, build_unit_dashboard_snapshot, resolve_period
from app.services.device_control import publish_device_command
from app.services.ingestion import QueryService
from app.services.rate_limit import broadcast_rate_limiter
from app.services.realtime_ws import dashboard_ws_manager
from app.services.recommendation_compliance import compute_recommendation_compliance
from app.utils.time import assume_utc, utc_now

router = APIRouter()


def _meta(total: int, offset: int, limit: int) -> dict:
    return {"total": total, "offset": offset, "limit": limit, "has_next": (offset + limit) < total}


def _validate_pagination(offset: int, limit: int) -> int:
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be >= 1")
    return min(limit, 200)


def _validate_sort_order(sort_order: str) -> None:
    if sort_order not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'")


def _validate_sort_by(sort_by: str, allowed: set[str]) -> None:
    if sort_by not in allowed:
        raise HTTPException(status_code=400, detail=f"sort_by must be one of: {', '.join(sorted(allowed))}")


def _validate_days(days: int) -> int:
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    return days


def _building_unit_ids(db: Session, building_id: str) -> list[str]:
    rows = db.execute(
        select(BuildingUnit.unit_id).where(
            and_(BuildingUnit.building_id == building_id, BuildingUnit.is_active.is_(True))
        )
    ).all()
    return [r[0] for r in rows]


def _ensure_community_member_manager_access(community_id: str, user: User) -> None:
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.COORDINATOR and user.community_id == community_id:
        return
    raise HTTPException(status_code=403, detail="Forbidden")


def _ensure_unit_access(unit_id: str, user: User) -> None:
    if user.role == UserRole.ADMIN:
        return
    if user.role == UserRole.RESIDENT and user.unit_id == unit_id:
        return
    if user.role == UserRole.COORDINATOR:
        return
    if user.role == UserRole.BUILDING_MANAGER:
        return
    raise HTTPException(status_code=403, detail="Forbidden")


def _ensure_unit_operation_access(db: Session, current_user: User, community_id: str, unit_id: str) -> Unit:
    unit = db.execute(select(Unit).where(and_(Unit.unit_id == unit_id, Unit.community_id == community_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    if current_user.role == UserRole.ADMIN:
        return unit
    if current_user.role == UserRole.RESIDENT:
        if current_user.unit_id != unit_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        return unit
    if current_user.role == UserRole.COORDINATOR:
        ensure_community_access(community_id, current_user)
        return unit
    if current_user.role == UserRole.BUILDING_MANAGER:
        if not current_user.building_id:
            raise HTTPException(status_code=403, detail="Forbidden")
        building_match = db.execute(
            select(BuildingUnit.id).where(
                and_(
                    BuildingUnit.building_id == current_user.building_id,
                    BuildingUnit.unit_id == unit_id,
                    BuildingUnit.is_active.is_(True),
                )
            )
        ).first()
        if not building_match:
            raise HTTPException(status_code=403, detail="Forbidden")
        return unit
    raise HTTPException(status_code=403, detail="Forbidden")


def _validate_user_scope(
    role: UserRole,
    community_id: str | None,
    building_id: str | None,
    unit_id: str | None,
) -> None:
    if community_id and building_id:
        raise HTTPException(status_code=400, detail="community_id and building_id cannot both be set")
    if role == UserRole.ADMIN:
        return
    if role in {UserRole.RESIDENT, UserRole.COORDINATOR, UserRole.BUILDING_MANAGER} and not unit_id:
        raise HTTPException(status_code=400, detail="unit_id is required for this role")


def _apply_notification_scope(stmt, current_user: User):
    if current_user.role == UserRole.COORDINATOR:
        return stmt.where(Notification.community_id == current_user.community_id)
    if current_user.role == UserRole.BUILDING_MANAGER:
        return stmt.where(Notification.building_id == current_user.building_id)
    if current_user.role == UserRole.RESIDENT:
        return stmt.where(Notification.community_id == current_user.community_id)
    return stmt


def _can_access_notification(row: Notification, current_user: User) -> bool:
    if current_user.role == UserRole.ADMIN:
        return True
    if current_user.role == UserRole.COORDINATOR:
        return row.community_id == current_user.community_id
    if current_user.role == UserRole.BUILDING_MANAGER:
        return row.building_id == current_user.building_id
    if current_user.role == UserRole.RESIDENT:
        return row.community_id == current_user.community_id
    return False


def _notification_with_deliveries(
    db: Session,
    row: Notification,
    current_user: User,
    read_lookup: dict[str, datetime] | None = None,
) -> NotificationResponse:
    deliveries = db.execute(
        select(NotificationDelivery)
        .where(NotificationDelivery.notification_id == row.notification_id)
        .order_by(NotificationDelivery.created_at.asc())
    ).scalars().all()
    read_at = None
    if read_lookup is not None:
        read_at = read_lookup.get(row.notification_id)
    else:
        read_row = db.execute(
            select(NotificationRead.read_at).where(
                and_(
                    NotificationRead.notification_id == row.notification_id,
                    NotificationRead.user_id == current_user.user_id,
                )
            )
        ).first()
        read_at = read_row[0] if read_row else None

    return NotificationResponse(
        notification_id=row.notification_id,
        scope=row.scope,
        community_id=row.community_id,
        building_id=row.building_id,
        message=row.message,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        is_read=read_at is not None,
        read_at=read_at,
        deliveries=[
            NotificationDeliveryItem(
                target_type=d.target_type,
                target_id=d.target_id,
                status=d.status,
                delivered_at=d.delivered_at,
                error=d.error,
            )
            for d in deliveries
        ],
    )


def _resolve_device_names(db: Session, device_ids: list[str]) -> dict[str, str]:
    if not device_ids:
        return {}
    rows = db.execute(select(DeviceCatalog).where(DeviceCatalog.device_key.in_(device_ids))).scalars().all()
    return {row.device_key: row.display_name for row in rows}


def _to_unit_device_response(row: Device, device_name: str) -> UnitDeviceResponse:
    return UnitDeviceResponse(
        device_id=row.device_id,
        device_name=device_name,
        qty=row.qty,
        is_active=row.is_active,
        controllable=row.controllable,
        schedules=row.schedules,
    )


def _parse_period(period_start: str | None, period_end: str | None):
    start_dt = assume_utc(datetime.fromisoformat(period_start)) if period_start else None
    end_dt = assume_utc(datetime.fromisoformat(period_end)) if period_end else None
    return start_dt, end_dt


def _build_csv_export(unit_rows: list[dict], total_kwh: float, total_cost: float) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["unit_id", "total_kwh", "estimated_cost"])
    for row in unit_rows:
        writer.writerow([row["unit_id"], f"{row['total_kwh']:.4f}", f"{row['estimated_cost']:.2f}"])
    writer.writerow([])
    writer.writerow(["TOTAL", f"{total_kwh:.4f}", f"{total_cost:.2f}"])
    return output.getvalue()


def _resolve_include_simulation(
    db: Session, community_id: str, current_user: User, include_simulation: bool | None
) -> bool:
    if include_simulation is not None:
        return include_simulation
    # Default behavior locked by requirement: admin sees mixed data, non-admin excludes simulation.
    if current_user.role == UserRole.ADMIN:
        return True
    return False


@router.post("/auth/login", response_model=TokenResponse)
def auth_login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not AuthService.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="Account is not active")
    return TokenResponse(access_token=AuthService.create_token(user, "access"), refresh_token=AuthService.create_token(user, "refresh"))


@router.post("/auth/refresh", response_model=TokenResponse)
def auth_refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    decoded = AuthService.decode(payload.refresh_token)
    if decoded.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh token required")
    revoked = db.execute(select(RevokedToken).where(RevokedToken.jti == decoded.get("jti"))).scalar_one_or_none()
    if revoked:
        raise HTTPException(status_code=401, detail="Token revoked")
    user = db.execute(select(User).where(User.user_id == decoded.get("sub"))).scalar_one_or_none()
    if not user or user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="User not active")
    return TokenResponse(access_token=AuthService.create_token(user, "access"), refresh_token=AuthService.create_token(user, "refresh"))


@router.post("/auth/logout")
def auth_logout(payload: RefreshRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    decoded = AuthService.decode(payload.refresh_token)
    db.add(
        RevokedToken(
            jti=decoded.get("jti"),
            token_type=decoded.get("type", "refresh"),
            expires_at=utc_now(),
        )
    )
    db.commit()
    return {"status": "logged_out"}


@router.get("/auth/me", response_model=AuthMeResponse)
def auth_me(current_user: User = Depends(get_current_user)):
    return AuthMeResponse(
        user_id=current_user.user_id,
        full_name=current_user.full_name,
        email=current_user.email,
        role=current_user.role.value,
        status=current_user.status.value,
        community_id=current_user.community_id,
        building_id=current_user.building_id,
        unit_id=current_user.unit_id,
    )


@router.get("/me/dashboard", response_model=MeDashboardResponse)
def me_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_info = MeDashboardUser(
        user_id=current_user.user_id,
        full_name=current_user.full_name,
        email=current_user.email,
        role=current_user.role.value,
        status=current_user.status.value,
    )
    scope_info = MeDashboardScope(community_id=current_user.community_id, building_id=current_user.building_id, unit_id=current_user.unit_id)
    widgets: dict = {}

    if current_user.role == UserRole.ADMIN:
        ai_last = db.execute(select(func.max(AIAnalysisResult.analyzed_at))).scalar_one_or_none()
        widgets = {
            "global_summary": {
                "communities_count": int(db.execute(select(func.count(Community.id))).scalar_one()),
                "units_count": int(db.execute(select(func.count(Unit.id))).scalar_one()),
                "buildings_count": int(db.execute(select(func.count(Building.id))).scalar_one()),
                "users_count": int(db.execute(select(func.count(User.id))).scalar_one()),
            },
            "ai_overview": {
                "results_count": int(db.execute(select(func.count(AIAnalysisResult.id))).scalar_one()),
                "last_analyzed_at": ai_last.isoformat() if ai_last else None,
            },
        }
    elif current_user.role == UserRole.COORDINATOR:
        if current_user.community_id:
            snapshot = build_dashboard_snapshot(db, current_user.community_id, include_simulation=False)
            widgets = {
                "community_dashboard": snapshot.model_dump() if snapshot else {},
                "ai_status": ai_orchestrator.get_status(current_user.community_id),
            }
        else:
            widgets = {"community_dashboard": {}, "ai_status": {}}
    elif current_user.role == UserRole.BUILDING_MANAGER:
        if current_user.building_id:
            unit_ids = _building_unit_ids(db, current_user.building_id)
            total_kwh_24h = 0.0
            last_timestamp = None
            if unit_ids:
                since = assume_utc(utc_now() - timedelta(hours=24)).replace(tzinfo=None)
                total_kwh_24h = float(
                    db.execute(
                        select(func.coalesce(func.sum(EnergyReading.kwh), 0.0)).where(
                            and_(
                                EnergyReading.unit_id.in_(unit_ids),
                                EnergyReading.timestamp >= since,
                                EnergyReading.is_simulation.is_(False),
                            )
                        )
                    ).scalar_one()
                )
                last_timestamp = db.execute(
                    select(func.max(EnergyReading.timestamp)).where(
                        and_(EnergyReading.unit_id.in_(unit_ids), EnergyReading.is_simulation.is_(False))
                    )
                ).scalar_one_or_none()
            cfg = db.execute(select(BuildingConfig).where(BuildingConfig.building_id == current_user.building_id)).scalar_one_or_none()
            widgets = {
                "building_summary": {
                    "building_id": current_user.building_id,
                    "active_units_count": len(unit_ids),
                    "total_kwh_24h": total_kwh_24h,
                    "last_timestamp": last_timestamp.isoformat() if last_timestamp else None,
                    "is_fresh": QueryService.freshness(last_timestamp),
                },
                "building_config": {
                    "peak_threshold_kwh": float(cfg.peak_threshold_kwh) if cfg else 3.0,
                    "source": "custom" if cfg else "default",
                },
            }
        else:
            widgets = {"building_summary": {}, "building_config": {}}
    else:
        if current_user.community_id:
            snapshot = build_dashboard_snapshot(db, current_user.community_id, include_simulation=False)
            widgets = {
                "community_overview": snapshot.community.model_dump() if snapshot else {},
                "resident_scope": {"community_id": current_user.community_id},
            }
        else:
            widgets = {"community_overview": {}, "resident_scope": {}}

    return MeDashboardResponse(user=user_info, scope=scope_info, widgets=widgets, generated_at=utc_now())


@router.get("/users", response_model=UsersListResponse)
def list_users(
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    limit = _validate_pagination(offset, limit)
    stmt = select(User)
    count_stmt = select(func.count(User.id))
    if q:
        pattern = f"%{q}%"
        condition = or_(User.user_id.ilike(pattern), User.email.ilike(pattern), User.full_name.ilike(pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.order_by(User.user_id).offset(offset).limit(limit)).scalars().all()
    items = [UserResponse(user_id=r.user_id, full_name=r.full_name, email=r.email, role=r.role.value, status=r.status.value, community_id=r.community_id, building_id=r.building_id, unit_id=r.unit_id) for r in rows]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/users", response_model=UserResponse)
def create_user(payload: UserCreateRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    exists = db.execute(select(User).where(or_(User.user_id == payload.user_id, User.email == payload.email))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="User already exists")
    role = UserRole(payload.role)
    status_value = UserStatus(payload.status)
    _validate_user_scope(role=role, community_id=payload.community_id, building_id=payload.building_id, unit_id=payload.unit_id)
    user = User(
        user_id=payload.user_id,
        full_name=payload.full_name,
        email=payload.email,
        password_hash=AuthService.hash_password(payload.password),
        role=role,
        status=status_value,
        community_id=payload.community_id,
        building_id=payload.building_id,
        unit_id=payload.unit_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(user_id=user.user_id, full_name=user.full_name, email=user.email, role=user.role.value, status=user.status.value, community_id=user.community_id, building_id=user.building_id, unit_id=user.unit_id)


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.ADMIN and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    row = db.execute(select(User).where(User.user_id == user_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return UserResponse(user_id=row.user_id, full_name=row.full_name, email=row.email, role=row.role.value, status=row.status.value, community_id=row.community_id, building_id=row.building_id, unit_id=row.unit_id)


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: str, payload: UserUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.execute(select(User).where(User.user_id == user_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if current_user.role != UserRole.ADMIN and current_user.user_id != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if current_user.role != UserRole.ADMIN and any([payload.role, payload.status, payload.community_id, payload.building_id, payload.unit_id]):
        raise HTTPException(status_code=403, detail="Only admin can change role/scope/status")

    if payload.full_name is not None:
        row.full_name = payload.full_name
    if payload.email is not None:
        row.email = payload.email
    if payload.role is not None:
        row.role = UserRole(payload.role)
    if payload.status is not None:
        row.status = UserStatus(payload.status)
    if payload.community_id is not None or payload.building_id is not None or payload.unit_id is not None:
        _validate_user_scope(
            role=UserRole(payload.role) if payload.role else row.role,
            community_id=payload.community_id,
            building_id=payload.building_id,
            unit_id=payload.unit_id,
        )
        row.community_id = payload.community_id
        row.building_id = payload.building_id
        row.unit_id = payload.unit_id
    db.commit()
    db.refresh(row)
    return UserResponse(user_id=row.user_id, full_name=row.full_name, email=row.email, role=row.role.value, status=row.status.value, community_id=row.community_id, building_id=row.building_id, unit_id=row.unit_id)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, payload: ResetPasswordRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    row = db.execute(select(User).where(User.user_id == user_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.password_hash = AuthService.hash_password(payload.new_password)
    db.commit()
    return {"status": "password_reset", "user_id": user_id}


@router.get("/buildings", response_model=BuildingsListResponse)
def list_buildings(offset: int = 0, limit: int = 20, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    limit = _validate_pagination(offset, limit)
    total = int(db.execute(select(func.count(Building.id))).scalar_one())
    rows = db.execute(select(Building).order_by(Building.building_id).offset(offset).limit(limit)).scalars().all()
    items = [BuildingResponse(building_id=r.building_id, name=r.name) for r in rows]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/buildings", response_model=BuildingResponse)
def create_building(payload: BuildingCreateRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    exists = db.execute(select(Building).where(Building.building_id == payload.building_id)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Building already exists")
    b = Building(building_id=payload.building_id, name=payload.name)
    db.add(b)
    db.commit()
    db.refresh(b)
    return BuildingResponse(building_id=b.building_id, name=b.name)


@router.get("/buildings/{building_id}", response_model=BuildingDetailResponse)
def get_building(building_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    row = db.execute(select(Building).where(Building.building_id == building_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return BuildingDetailResponse(building_id=row.building_id, name=row.name)


@router.put("/buildings/{building_id}", response_model=BuildingDetailResponse)
def update_building(
    building_id: str,
    payload: BuildingUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    row = db.execute(select(Building).where(Building.building_id == building_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.name = payload.name
    db.commit()
    db.refresh(row)
    return BuildingDetailResponse(building_id=row.building_id, name=row.name)


@router.delete("/buildings/{building_id}")
def delete_building(building_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    row = db.execute(select(Building).where(Building.building_id == building_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    active_units = int(
        db.execute(
            select(func.count(BuildingUnit.id)).where(and_(BuildingUnit.building_id == building_id, BuildingUnit.is_active.is_(True)))
        ).scalar_one()
    )
    if active_units > 0:
        raise HTTPException(status_code=400, detail="Building has active units; deactivate/delete units first")
    db.execute(BuildingUnit.__table__.delete().where(BuildingUnit.building_id == building_id))
    db.delete(row)
    db.commit()
    return {"status": "deleted", "building_id": building_id}


@router.get("/buildings/{building_id}/units", response_model=BuildingUnitsListResponse)
def list_building_units(
    building_id: str,
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    limit = _validate_pagination(offset, limit)
    stmt = select(BuildingUnit).where(BuildingUnit.building_id == building_id)
    count_stmt = select(func.count(BuildingUnit.id)).where(BuildingUnit.building_id == building_id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(BuildingUnit.unit_id.ilike(pattern))
        count_stmt = count_stmt.where(BuildingUnit.unit_id.ilike(pattern))
    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.order_by(BuildingUnit.unit_id).offset(offset).limit(limit)).scalars().all()
    items = [
        BuildingUnitResponse(
            building_id=r.building_id,
            unit_id=r.unit_id,
            is_active=r.is_active,
            metadata_json=r.metadata_json,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/buildings/{building_id}/units", response_model=BuildingUnitResponse)
def create_building_unit(
    building_id: str,
    payload: BuildingUnitCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    building = db.execute(select(Building).where(Building.building_id == building_id)).scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Not found")
    exists = db.execute(
        select(BuildingUnit).where(and_(BuildingUnit.building_id == building_id, BuildingUnit.unit_id == payload.unit_id))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Building unit already exists")
    row = BuildingUnit(
        building_id=building_id,
        unit_id=payload.unit_id,
        is_active=payload.is_active,
        metadata_json=payload.metadata_json,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return BuildingUnitResponse(
        building_id=row.building_id,
        unit_id=row.unit_id,
        is_active=row.is_active,
        metadata_json=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/buildings/{building_id}/units/{unit_id}", response_model=BuildingUnitResponse)
def update_building_unit(
    building_id: str,
    unit_id: str,
    payload: BuildingUnitUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    row = db.execute(
        select(BuildingUnit).where(and_(BuildingUnit.building_id == building_id, BuildingUnit.unit_id == unit_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.is_active is not None:
        row.is_active = payload.is_active
    if payload.metadata_json is not None:
        row.metadata_json = payload.metadata_json
    db.commit()
    db.refresh(row)
    return BuildingUnitResponse(
        building_id=row.building_id,
        unit_id=row.unit_id,
        is_active=row.is_active,
        metadata_json=row.metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/buildings/{building_id}/units/{unit_id}")
def delete_building_unit(
    building_id: str,
    unit_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    row = db.execute(
        select(BuildingUnit).where(and_(BuildingUnit.building_id == building_id, BuildingUnit.unit_id == unit_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "building_id": building_id, "unit_id": unit_id}


@router.get("/buildings/{building_id}/reports", response_model=BuildingReportMetadataResponse)
def building_reports_metadata(
    building_id: str,
    period_start: str | None = None,
    period_end: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    building = db.execute(select(Building).where(Building.building_id == building_id)).scalar_one_or_none()
    if not building:
        raise HTTPException(status_code=404, detail="Not found")

    total_units = int(
        db.execute(select(func.count(BuildingUnit.id)).where(BuildingUnit.building_id == building_id)).scalar_one()
    )
    active_units = int(
        db.execute(
            select(func.count(BuildingUnit.id)).where(and_(BuildingUnit.building_id == building_id, BuildingUnit.is_active.is_(True)))
        ).scalar_one()
    )
    return BuildingReportMetadataResponse(
        building_id=building_id,
        report_type="building_summary",
        generated_at=utc_now(),
        period={"start": period_start, "end": period_end},
        summary={"total_units": total_units, "active_units": active_units},
        download_url=None,
    )


@router.get("/buildings/{building_id}/reports/export")
def building_reports_export(
    building_id: str,
    format: str = "csv",
    period_start: str | None = None,
    period_end: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Only csv format is supported")
    unit_ids = _building_unit_ids(db, building_id)
    start_dt, end_dt = _parse_period(period_start, period_end)
    unit_rows = []
    total_kwh = 0.0
    total_cost = 0.0
    for uid in unit_ids:
        conditions = [EnergyReading.unit_id == uid]
        if start_dt:
            conditions.append(EnergyReading.timestamp >= start_dt.replace(tzinfo=None))
        if end_dt:
            conditions.append(EnergyReading.timestamp <= end_dt.replace(tzinfo=None))
        if current_user.role != UserRole.ADMIN:
            conditions.append(EnergyReading.is_simulation.is_(False))
        kwh, cost = db.execute(
            select(func.coalesce(func.sum(EnergyReading.kwh), 0.0), func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0)).where(and_(*conditions))
        ).one()
        kwh_f = float(kwh)
        cost_f = float(cost)
        total_kwh += kwh_f
        total_cost += cost_f
        unit_rows.append({"unit_id": uid, "total_kwh": kwh_f, "estimated_cost": cost_f})
    csv_content = _build_csv_export(unit_rows, total_kwh, total_cost)
    filename = f"building_{building_id}_report.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/buildings/{building_id}/consumption", response_model=BuildingConsumptionResponse)
def building_consumption(
    building_id: str,
    window: str = "hourly",
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    if window not in {"hourly", "daily"}:
        raise HTTPException(status_code=400, detail="Invalid window")
    hours = max(1, min(hours, 24 * 30))
    unit_ids = _building_unit_ids(db, building_id)
    if not unit_ids:
        return BuildingConsumptionResponse(
            building_id=building_id, series=[], total_kwh=0.0, estimated_cost=0.0, last_timestamp=None, is_fresh=False
        )
    bucket_expr = (
        func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
        if window == "hourly"
        else func.to_char(func.date_trunc("day", EnergyReading.timestamp), "YYYY-MM-DD")
    )
    since = assume_utc(utc_now() - timedelta(hours=hours)).replace(tzinfo=None)
    conditions = [EnergyReading.unit_id.in_(unit_ids), EnergyReading.timestamp >= since]
    if current_user.role != UserRole.ADMIN:
        conditions.append(EnergyReading.is_simulation.is_(False))
    rows = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
            func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0).label("estimated_cost"),
        )
        .where(and_(*conditions))
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    ).all()
    last_timestamp = db.execute(select(func.max(EnergyReading.timestamp)).where(and_(*conditions))).scalar_one_or_none()
    return BuildingConsumptionResponse(
        building_id=building_id,
        series=[BuildingConsumptionPoint(bucket=r.bucket, total_kwh=float(r.total_kwh), estimated_cost=float(r.estimated_cost)) for r in rows],
        total_kwh=float(sum(float(r.total_kwh) for r in rows)),
        estimated_cost=float(sum(float(r.estimated_cost) for r in rows)),
        last_timestamp=last_timestamp,
        is_fresh=QueryService.freshness(last_timestamp),
    )


@router.get("/buildings/{building_id}/predictions", response_model=BuildingPredictionsResponse)
def building_predictions(building_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    unit_ids = set(_building_unit_ids(db, building_id))
    if not unit_ids:
        return BuildingPredictionsResponse(building_id=building_id, exists=False, generated_at=None, community_context={}, unit_predictions={})
    community_ids = [r[0] for r in db.execute(select(Unit.community_id).where(Unit.unit_id.in_(list(unit_ids))).distinct()).all()]
    if not community_ids:
        return BuildingPredictionsResponse(building_id=building_id, exists=False, generated_at=None, community_context={}, unit_predictions={})
    row = db.execute(
        select(AIAnalysisResult).where(AIAnalysisResult.community_id.in_(community_ids)).order_by(desc(AIAnalysisResult.analyzed_at))
    ).scalars().first()
    if not row or not isinstance(row.result, dict):
        return BuildingPredictionsResponse(building_id=building_id, exists=False, generated_at=None, community_context={"community_ids": community_ids}, unit_predictions={})
    rp = row.result.get("result", row.result)
    up = rp.get("unit_predictions", {}) if isinstance(rp, dict) else {}
    filtered = {k: float(v) for k, v in up.items() if k in unit_ids and isinstance(v, (int, float))}
    return BuildingPredictionsResponse(
        building_id=building_id,
        exists=True,
        generated_at=row.analyzed_at.isoformat(),
        community_context={"community_ids": community_ids, "source_community_id": row.community_id},
        unit_predictions=filtered,
    )


@router.get("/buildings/{building_id}/recommendations", response_model=BuildingRecommendationsResponse)
def building_recommendations(building_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    unit_ids = set(_building_unit_ids(db, building_id))
    if not unit_ids:
        return BuildingRecommendationsResponse(building_id=building_id, exists=False, generated_at=None, items=[])
    community_ids = [r[0] for r in db.execute(select(Unit.community_id).where(Unit.unit_id.in_(list(unit_ids))).distinct()).all()]
    row = db.execute(
        select(AIAnalysisResult).where(AIAnalysisResult.community_id.in_(community_ids)).order_by(desc(AIAnalysisResult.analyzed_at))
    ).scalars().first()
    if not row or not isinstance(row.result, dict):
        return BuildingRecommendationsResponse(building_id=building_id, exists=False, generated_at=None, items=[])
    rp = row.result.get("result", row.result)
    recs = rp.get("recommendations", []) if isinstance(rp, dict) else []
    items: list[BuildingRecommendationItem] = []
    for rec in recs:
        if isinstance(rec, dict) and rec.get("unit_id") in unit_ids:
            reasons = rec.get("reasons")
            items.append(
                BuildingRecommendationItem(
                    unit_id=rec.get("unit_id"),
                    device=rec.get("device"),
                    action=rec.get("action"),
                    saving=float(rec["saving"]) if isinstance(rec.get("saving"), (int, float)) else None,
                    co2_reduction=float(rec["co2_reduction"]) if isinstance(rec.get("co2_reduction"), (int, float)) else None,
                    estimated_reduction_kwh=float(rec["estimated_reduction_kwh"]) if isinstance(rec.get("estimated_reduction_kwh"), (int, float)) else None,
                    reasons=[str(x) for x in reasons if isinstance(x, str)] if isinstance(reasons, list) else [],
                )
            )
    return BuildingRecommendationsResponse(building_id=building_id, exists=True, generated_at=row.analyzed_at.isoformat(), items=items)


@router.post("/buildings/{building_id}/notifications")
def send_building_broadcast(
    building_id: str,
    payload: BroadcastRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    if current_user.role != UserRole.ADMIN:
        broadcast_rate_limiter.check_and_increment(current_user.user_id, limit=5)
    notification_id = str(uuid.uuid4())
    row = Notification(
        notification_id=notification_id,
        scope="building",
        building_id=building_id,
        message=payload.message,
        created_by_user_id=current_user.user_id,
    )
    db.add(row)
    db.add(
        NotificationDelivery(
            notification_id=notification_id,
            target_type="scope",
            target_id=building_id,
            status="queued",
        )
    )
    db.commit()
    return {"status": "queued", "scope": "building", "building_id": building_id, "notification_id": notification_id}


@router.get("/buildings/{building_id}/config", response_model=BuildingConfigResponse)
def get_building_config(building_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    row = db.execute(select(BuildingConfig).where(BuildingConfig.building_id == building_id)).scalar_one_or_none()
    if not row:
        return BuildingConfigResponse(building_id=building_id, peak_threshold_kwh=3.0, source="default")
    return BuildingConfigResponse(building_id=building_id, peak_threshold_kwh=float(row.peak_threshold_kwh), source="custom")


@router.put("/buildings/{building_id}/config", response_model=BuildingConfigResponse)
def update_building_config(
    building_id: str,
    payload: BuildingConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.BUILDING_MANAGER]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_building_access(building_id, current_user)
    row = db.execute(select(BuildingConfig).where(BuildingConfig.building_id == building_id)).scalar_one_or_none()
    if not row:
        row = BuildingConfig(building_id=building_id, peak_threshold_kwh=payload.peak_threshold_kwh)
        db.add(row)
    else:
        row.peak_threshold_kwh = payload.peak_threshold_kwh
    db.commit()
    db.refresh(row)
    return BuildingConfigResponse(building_id=building_id, peak_threshold_kwh=float(row.peak_threshold_kwh), source="custom")


@router.get("/communities", response_model=CommunitiesListResponse)
def list_communities(offset: int = 0, limit: int = 20, q: str | None = None, sort_by: str = "community_id", sort_order: str = "asc", db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    limit = _validate_pagination(offset, limit)
    _validate_sort_order(sort_order)
    _validate_sort_by(sort_by, {"community_id", "name"})
    stmt = select(Community)
    count_stmt = select(func.count(Community.id))
    if q:
        pattern = f"%{q}%"
        condition = or_(Community.community_id.ilike(pattern), Community.name.ilike(pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    sort_map = {"community_id": Community.community_id, "name": Community.name}
    sort_col = sort_map.get(sort_by, Community.community_id)
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)
    rows = db.execute(stmt.order_by(order_expr).offset(offset).limit(limit)).scalars().all()
    total = int(db.execute(count_stmt).scalar_one())
    return {"items": [CommunityResponse(community_id=r.community_id, name=r.name) for r in rows], "meta": _meta(total, offset, limit)}


@router.post("/communities", response_model=CommunityResponse)
def create_community(payload: CommunityCreateRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    exists = db.execute(select(Community).where(Community.community_id == payload.community_id)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Community already exists")
    row = Community(community_id=payload.community_id, name=payload.name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return CommunityResponse(community_id=row.community_id, name=row.name)


@router.get("/communities/{community_id}", response_model=CommunityResponse)
def get_community(community_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_community_access(community_id, current_user)
    row = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return CommunityResponse(community_id=row.community_id, name=row.name)


@router.get("/communities/{community_id}/members", response_model=CommunityMembersListResponse)
def list_community_members(
    community_id: str,
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_community_member_manager_access(community_id, current_user)
    limit = _validate_pagination(offset, limit)
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Not found")
    stmt = select(User).where(User.community_id == community_id)
    count_stmt = select(func.count(User.id)).where(User.community_id == community_id)
    if q:
        pattern = f"%{q}%"
        condition = or_(User.user_id.ilike(pattern), User.full_name.ilike(pattern), User.email.ilike(pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.order_by(User.user_id).offset(offset).limit(limit)).scalars().all()
    items = [
        CommunityMemberItem(
            user_id=r.user_id,
            full_name=r.full_name,
            email=r.email,
            role=r.role.value,
            status=r.status.value,
            community_id=r.community_id,
        )
        for r in rows
    ]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/communities/{community_id}/members", response_model=CommunityMemberMutationResponse)
def add_community_member(
    community_id: str,
    payload: AddCommunityMemberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_community_member_manager_access(community_id, current_user)
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Not found")
    user = db.execute(select(User).where(User.user_id == payload.user_id)).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.building_id:
        raise HTTPException(status_code=400, detail="User already assigned to building scope")
    if user.community_id and user.community_id != community_id:
        raise HTTPException(status_code=400, detail="User already assigned to another community")
    if user.community_id == community_id:
        return CommunityMemberMutationResponse(community_id=community_id, user_id=user.user_id, status="already_member")
    user.community_id = community_id
    db.commit()
    return CommunityMemberMutationResponse(community_id=community_id, user_id=user.user_id, status="added")


@router.delete("/communities/{community_id}/members/{user_id}", response_model=CommunityMemberMutationResponse)
def remove_community_member(
    community_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_community_member_manager_access(community_id, current_user)
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Not found")
    user = db.execute(select(User).where(User.user_id == user_id)).scalar_one_or_none()
    if not user or user.community_id != community_id:
        raise HTTPException(status_code=404, detail="Member not found")
    user.community_id = None
    db.commit()
    return CommunityMemberMutationResponse(community_id=community_id, user_id=user.user_id, status="removed")


@router.get("/communities/{community_id}/simulations", response_model=CommunitySimulationStateResponse)
def get_community_simulation_state(
    community_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.COORDINATOR]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_community_access(community_id, current_user)
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Not found")
    row = db.execute(
        select(CommunitySimulationConfig).where(CommunitySimulationConfig.community_id == community_id)
    ).scalar_one_or_none()
    if not row:
        return CommunitySimulationStateResponse(
            community_id=community_id,
            simulation_enabled=False,
            updated_at=None,
            source="default",
        )
    return CommunitySimulationStateResponse(
        community_id=community_id,
        simulation_enabled=bool(row.simulation_enabled),
        updated_at=row.updated_at,
        source="custom",
    )


@router.post("/communities/{community_id}/simulations/toggle", response_model=CommunitySimulationStateResponse)
def toggle_community_simulation_state(
    community_id: str,
    payload: CommunitySimulationToggleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in [UserRole.ADMIN, UserRole.COORDINATOR]:
        raise HTTPException(status_code=403, detail="Forbidden")
    ensure_community_access(community_id, current_user)
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Not found")
    row = db.execute(
        select(CommunitySimulationConfig).where(CommunitySimulationConfig.community_id == community_id)
    ).scalar_one_or_none()
    if not row:
        row = CommunitySimulationConfig(
            community_id=community_id,
            simulation_enabled=payload.simulation_enabled,
            updated_at=utc_now(),
        )
        db.add(row)
    else:
        row.simulation_enabled = payload.simulation_enabled
        row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return CommunitySimulationStateResponse(
        community_id=community_id,
        simulation_enabled=bool(row.simulation_enabled),
        updated_at=row.updated_at,
        source="custom",
    )


@router.put("/communities/{community_id}", response_model=CommunityResponse)
def update_community(community_id: str, payload: CommunityUpdateRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    row = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.name = payload.name
    db.commit()
    db.refresh(row)
    return CommunityResponse(community_id=row.community_id, name=row.name)


@router.delete("/communities/{community_id}")
def delete_community(community_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    row = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    unit_count = db.execute(select(func.count(Unit.id)).where(Unit.community_id == community_id)).scalar_one()
    if unit_count > 0:
        raise HTTPException(status_code=400, detail="Community has units; delete units first")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "community_id": community_id}


@router.get("/communities/{community_id}/units", response_model=UnitsListResponse)
def list_units(community_id: str, offset: int = 0, limit: int = 20, q: str | None = None, va_min: int | None = None, va_max: int | None = None, sort_by: str = "unit_id", sort_order: str = "asc", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_community_access(community_id, current_user)
    limit = _validate_pagination(offset, limit)
    _validate_sort_order(sort_order)
    _validate_sort_by(sort_by, {"unit_id", "va"})
    stmt = select(Unit).where(Unit.community_id == community_id)
    count_stmt = select(func.count(Unit.id)).where(Unit.community_id == community_id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(Unit.unit_id.ilike(pattern))
        count_stmt = count_stmt.where(Unit.unit_id.ilike(pattern))
    if va_min is not None:
        stmt = stmt.where(Unit.va >= va_min)
        count_stmt = count_stmt.where(Unit.va >= va_min)
    if va_max is not None:
        stmt = stmt.where(Unit.va <= va_max)
        count_stmt = count_stmt.where(Unit.va <= va_max)
    sort_map = {"unit_id": Unit.unit_id, "va": Unit.va}
    sort_col = sort_map.get(sort_by, Unit.unit_id)
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)
    rows = db.execute(stmt.order_by(order_expr).offset(offset).limit(limit)).scalars().all()
    total = int(db.execute(count_stmt).scalar_one())
    return {"items": [UnitCrudResponse(community_id=r.community_id, unit_id=r.unit_id, va=r.va) for r in rows], "meta": _meta(total, offset, limit)}


@router.post("/communities/{community_id}/units", response_model=UnitCrudResponse)
def create_unit(community_id: str, payload: UnitCreateRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    exists = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == payload.unit_id))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Unit already exists")
    unit = Unit(community_id=community_id, unit_id=payload.unit_id, va=payload.va)
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return UnitCrudResponse(community_id=unit.community_id, unit_id=unit.unit_id, va=unit.va)


@router.get("/communities/{community_id}/units/{unit_id}", response_model=UnitCrudResponse)
def get_unit(community_id: str, unit_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_community_access(community_id, current_user)
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    return UnitCrudResponse(community_id=unit.community_id, unit_id=unit.unit_id, va=unit.va)


@router.put("/communities/{community_id}/units/{unit_id}", response_model=UnitCrudResponse)
def update_unit(community_id: str, unit_id: str, payload: UnitUpdateRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    unit.va = payload.va
    db.commit()
    db.refresh(unit)
    return UnitCrudResponse(community_id=unit.community_id, unit_id=unit.unit_id, va=unit.va)


@router.delete("/communities/{community_id}/units/{unit_id}")
def delete_unit(community_id: str, unit_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    db.execute(Device.__table__.delete().where(Device.unit_id == unit.id))
    db.delete(unit)
    db.commit()
    return {"status": "deleted", "community_id": community_id, "unit_id": unit_id}


@router.post("/communities/{community_id}/units/bulk-delete", response_model=BulkDeleteUnitsResponse)
def bulk_delete_units(community_id: str, payload: BulkDeleteUnitsRequest, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    requested_ids = list(dict.fromkeys(payload.unit_ids))
    rows = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id.in_(requested_ids)))).scalars().all()
    found_map = {u.unit_id: u for u in rows}
    not_found = [u for u in requested_ids if u not in found_map]
    deleted_count = 0
    for unit_id in requested_ids:
        unit = found_map.get(unit_id)
        if not unit:
            continue
        db.execute(Device.__table__.delete().where(Device.unit_id == unit.id))
        db.delete(unit)
        deleted_count += 1
    db.commit()
    return BulkDeleteUnitsResponse(community_id=community_id, requested_count=len(requested_ids), deleted_count=deleted_count, not_found_unit_ids=not_found)


@router.get("/units/{unit_id}/summary", response_model=UnitSummaryResponse)
def unit_summary(
    unit_id: str,
    community_id: str,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        period_used, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ensure_community_access(community_id, current_user)
    conditions = [EnergyReading.unit_id == unit_id, EnergyReading.community_id == community_id]
    if period_start:
        conditions.append(EnergyReading.timestamp >= period_start.replace(tzinfo=None))
    if period_end:
        conditions.append(EnergyReading.timestamp <= period_end.replace(tzinfo=None))
    if current_user.role != UserRole.ADMIN:
        conditions.append(EnergyReading.is_simulation.is_(False))
    total_kwh, estimated_cost, last_timestamp = db.execute(
        select(func.coalesce(func.sum(EnergyReading.kwh), 0.0), func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0), func.max(EnergyReading.timestamp)).where(and_(*conditions))
    ).one()
    device_rows = db.execute(
        select(
            EnergyReading.device_id,
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*conditions))
        .group_by(EnergyReading.device_id)
        .order_by(EnergyReading.device_id)
    ).all()
    device_ids = [str(r.device_id) for r in device_rows]
    display_name_map: dict[str, str] = {}
    if device_ids:
        catalog_rows = db.execute(
            select(DeviceCatalog.device_key, DeviceCatalog.display_name).where(DeviceCatalog.device_key.in_(device_ids))
        ).all()
        display_name_map = {str(r.device_key): str(r.display_name) for r in catalog_rows}
    device_emissions = [
        DeviceEmissionItem(
            device_id=str(r.device_id),
            device_name=display_name_map.get(str(r.device_id), str(r.device_id)),
            total_kwh=float(r.total_kwh),
            estimated_emission_kg_co2e=QueryService.emission(float(r.total_kwh)),
        )
        for r in device_rows
    ]
    comparison = None
    current_compliance = compute_recommendation_compliance(
        db=db,
        community_id=community_id,
        period_start=period_start,
        period_end=period_end,
        unit_id=unit_id,
        window_hours=24,
    )
    if period_used in {"week", "month"} and period_start and period_end:
        delta = period_end - period_start
        prev_start = period_start - delta
        prev_end = period_start
        prev_conditions = [EnergyReading.unit_id == unit_id, EnergyReading.community_id == community_id]
        prev_conditions.append(EnergyReading.timestamp >= prev_start.replace(tzinfo=None))
        prev_conditions.append(EnergyReading.timestamp < prev_end.replace(tzinfo=None))
        if current_user.role != UserRole.ADMIN:
            prev_conditions.append(EnergyReading.is_simulation.is_(False))
        prev_kwh, prev_cost = db.execute(
            select(
                func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
            ).where(and_(*prev_conditions))
        ).one()
        prev_kwh_f = float(prev_kwh)
        prev_cost_f = float(prev_cost)
        current_kwh_f = float(total_kwh)
        current_cost_f = float(estimated_cost)
        current_emission = QueryService.emission(current_kwh_f)
        prev_emission = QueryService.emission(prev_kwh_f)
        comparison = PeriodComparison(
            previous_period_start=prev_start,
            previous_period_end=prev_end,
            consumption_pct=((current_kwh_f - prev_kwh_f) / prev_kwh_f * 100.0) if prev_kwh_f != 0 else None,
            cost_pct=((current_cost_f - prev_cost_f) / prev_cost_f * 100.0) if prev_cost_f != 0 else None,
            emission_pct=((current_emission - prev_emission) / prev_emission * 100.0) if prev_emission != 0 else None,
            compliance_pct_point_delta=None,
        )
        previous_compliance = compute_recommendation_compliance(
            db=db,
            community_id=community_id,
            period_start=prev_start,
            period_end=prev_end,
            unit_id=unit_id,
            window_hours=24,
        )
        if current_compliance.compliance_pct is not None and previous_compliance.compliance_pct is not None:
            comparison.compliance_pct_point_delta = current_compliance.compliance_pct - previous_compliance.compliance_pct
    return UnitSummaryResponse(
        community_id=community_id,
        unit_id=unit_id,
        total_kwh=float(total_kwh),
        estimated_cost=float(estimated_cost),
        estimated_emission_kg_co2e=QueryService.emission(float(total_kwh)),
        device_emissions=device_emissions,
        last_timestamp=last_timestamp,
        is_fresh=QueryService.freshness(last_timestamp),
        period_used=period_used,
        period_start=period_start,
        comparison=comparison,
        recommendation_compliance=current_compliance.to_schema(window_hours=24),
    )


@router.get("/units/{unit_id}/emissions/daily", response_model=UnitDailyEmissionsResponse)
def unit_daily_emissions(
    unit_id: str,
    community_id: str,
    days: int = 30,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    days = _validate_days(days)
    try:
        period_used, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ensure_community_access(community_id, current_user)
    _ensure_unit_access(unit_id, current_user)
    community_exists = db.execute(select(Community.id).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community_exists:
        raise HTTPException(status_code=404, detail="Not found")
    unit_exists = db.execute(select(Unit.id).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit_exists:
        raise HTTPException(status_code=404, detail="Not found")

    now = utc_now()
    days_start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    effective_start = days_start if not period_start else max(days_start, period_start)
    effective_end = period_end or now

    conditions = [
        EnergyReading.community_id == community_id,
        EnergyReading.unit_id == unit_id,
        EnergyReading.timestamp >= effective_start.replace(tzinfo=None),
        EnergyReading.timestamp <= effective_end.replace(tzinfo=None),
    ]
    if current_user.role != UserRole.ADMIN:
        conditions.append(EnergyReading.is_simulation.is_(False))

    rows = db.execute(
        select(
            func.date(EnergyReading.timestamp).label("day"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*conditions))
        .group_by(func.date(EnergyReading.timestamp))
        .order_by(func.date(EnergyReading.timestamp))
    ).all()

    last_timestamp = db.execute(
        select(func.max(EnergyReading.timestamp)).where(and_(*conditions))
    ).scalar_one_or_none()

    series = [
        UnitDailyEmissionPoint(
            date=str(r.day),
            total_kwh=float(r.total_kwh),
            estimated_emission_kg_co2e=QueryService.emission(float(r.total_kwh)),
        )
        for r in rows
    ]
    total_emission = sum(point.estimated_emission_kg_co2e for point in series)

    return UnitDailyEmissionsResponse(
        community_id=community_id,
        unit_id=unit_id,
        period_used=period_used,
        period_start=period_start,
        series=series,
        total_emission_kg_co2e=float(total_emission),
        last_timestamp=last_timestamp,
        is_fresh=QueryService.freshness(last_timestamp),
    )


@router.get("/communities/{community_id}/units-summary", response_model=list[CommunityUnitSummaryItem])
def community_units_summary(
    community_id: str,
    include_simulation: bool | None = None,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        period_used, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ensure_community_access(community_id, current_user)
    resolved_include_sim = _resolve_include_simulation(db, community_id, current_user, include_simulation)
    return build_units_summary(
        db,
        community_id,
        include_simulation=resolved_include_sim,
        period_start=period_start,
        period_end=period_end,
        period_used=period_used,
    )


@router.get("/communities/{community_id}/dashboard", response_model=DashboardResponse)
def community_dashboard(
    community_id: str,
    include_simulation: bool | None = None,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        period_used, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ensure_community_access(community_id, current_user)
    resolved_include_sim = _resolve_include_simulation(db, community_id, current_user, include_simulation)
    snapshot = build_dashboard_snapshot(
        db,
        community_id,
        include_simulation=resolved_include_sim,
        period_start=period_start,
        period_end=period_end,
        period_used=period_used,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Not found")
    return snapshot


@router.get("/communities/{community_id}/units/{unit_id}/dashboard", response_model=UnitDashboardResponse)
def unit_dashboard(
    community_id: str,
    unit_id: str,
    include_simulation: bool | None = None,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        period_used, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    resolved_include_sim = _resolve_include_simulation(db, community_id, current_user, include_simulation)
    snapshot = build_unit_dashboard_snapshot(
        db,
        community_id,
        unit_id,
        include_simulation=resolved_include_sim,
        period_start=period_start,
        period_end=period_end,
        period_used=period_used,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Not found")
    return snapshot


@router.get("/communities/{community_id}/load-curve")
def load_curve(
    community_id: str,
    include_simulation: bool | None = None,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ensure_community_access(community_id, current_user)
    resolved_include_sim = _resolve_include_simulation(db, community_id, current_user, include_simulation)
    return build_load_curve(
        db,
        community_id,
        include_simulation=resolved_include_sim,
        period_start=period_start,
        period_end=period_end,
    )


@router.get("/communities/{community_id}/peak-risk", response_model=PeakRiskResponse)
def peak_risk(
    community_id: str,
    include_simulation: bool | None = None,
    period: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        period_used, period_start, period_end = resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ensure_community_access(community_id, current_user)
    resolved_include_sim = _resolve_include_simulation(db, community_id, current_user, include_simulation)
    return build_peak_risk(
        db,
        community_id,
        include_simulation=resolved_include_sim,
        period_start=period_start,
        period_end=period_end,
        period_used=period_used,
    )


@router.get("/communities/{community_id}/reports/export")
def community_reports_export(
    community_id: str,
    format: str = "csv",
    period_start: str | None = None,
    period_end: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_community_access(community_id, current_user)
    if format.lower() != "csv":
        raise HTTPException(status_code=400, detail="Only csv format is supported")
    units = db.execute(select(Unit).where(Unit.community_id == community_id).order_by(Unit.unit_id)).scalars().all()
    start_dt, end_dt = _parse_period(period_start, period_end)
    unit_rows = []
    total_kwh = 0.0
    total_cost = 0.0
    for unit in units:
        conditions = [EnergyReading.community_id == community_id, EnergyReading.unit_id == unit.unit_id]
        if start_dt:
            conditions.append(EnergyReading.timestamp >= start_dt.replace(tzinfo=None))
        if end_dt:
            conditions.append(EnergyReading.timestamp <= end_dt.replace(tzinfo=None))
        if current_user.role != UserRole.ADMIN:
            conditions.append(EnergyReading.is_simulation.is_(False))
        kwh, cost = db.execute(
            select(func.coalesce(func.sum(EnergyReading.kwh), 0.0), func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0)).where(and_(*conditions))
        ).one()
        kwh_f = float(kwh)
        cost_f = float(cost)
        total_kwh += kwh_f
        total_cost += cost_f
        unit_rows.append({"unit_id": unit.unit_id, "total_kwh": kwh_f, "estimated_cost": cost_f})

    csv_content = _build_csv_export(unit_rows, total_kwh, total_cost)
    filename = f"community_{community_id}_report.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/devices", response_model=DeviceCatalogListResponse)
def list_global_devices(
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    limit = _validate_pagination(offset, limit)
    stmt = select(DeviceCatalog)
    count_stmt = select(func.count(DeviceCatalog.id))
    if q:
        pattern = f"%{q}%"
        condition = or_(DeviceCatalog.device_key.ilike(pattern), DeviceCatalog.display_name.ilike(pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.order_by(DeviceCatalog.device_key).offset(offset).limit(limit)).scalars().all()
    items = [
        DeviceCatalogResponse(
            device_key=r.device_key,
            display_name=r.display_name,
            default_power_watt=r.default_power_watt,
            controllable=r.controllable,
            is_active=r.is_active,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/devices", response_model=DeviceCatalogResponse)
def create_global_device(
    payload: DeviceCatalogCreateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    exists = db.execute(select(DeviceCatalog).where(DeviceCatalog.device_key == payload.device_key)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Device key already exists")
    row = DeviceCatalog(
        device_key=payload.device_key,
        display_name=payload.display_name,
        default_power_watt=payload.default_power_watt,
        controllable=payload.controllable,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return DeviceCatalogResponse(
        device_key=row.device_key,
        display_name=row.display_name,
        default_power_watt=row.default_power_watt,
        controllable=row.controllable,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.put("/devices/{device_key}", response_model=DeviceCatalogResponse)
def update_global_device(
    device_key: str,
    payload: DeviceCatalogUpdateRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    row = db.execute(select(DeviceCatalog).where(DeviceCatalog.device_key == device_key)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if payload.display_name is not None:
        row.display_name = payload.display_name
    if payload.default_power_watt is not None:
        row.default_power_watt = payload.default_power_watt
    if payload.controllable is not None:
        row.controllable = payload.controllable
    if payload.is_active is not None:
        row.is_active = payload.is_active
    db.commit()
    db.refresh(row)
    return DeviceCatalogResponse(
        device_key=row.device_key,
        display_name=row.display_name,
        default_power_watt=row.default_power_watt,
        controllable=row.controllable,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.delete("/devices/{device_key}")
def delete_global_device(
    device_key: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
):
    row = db.execute(select(DeviceCatalog).where(DeviceCatalog.device_key == device_key)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.is_active = False
    db.commit()
    return {"status": "disabled", "device_key": device_key}


@router.get("/units/{unit_id}/devices", response_model=UnitDevicesListResponse)
def unit_devices(
    unit_id: str,
    community_id: str,
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = _validate_pagination(offset, limit)
    unit = _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    total = int(db.execute(select(func.count(Device.id)).where(Device.unit_id == unit.id)).scalar_one())
    rows = db.execute(select(Device).where(Device.unit_id == unit.id).order_by(Device.device_id).offset(offset).limit(limit)).scalars().all()
    device_ids = [r.device_id for r in rows]
    name_map = _resolve_device_names(db, device_ids)
    items = [_to_unit_device_response(r, name_map.get(r.device_id, r.device_id)) for r in rows]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/units/{unit_id}/devices", response_model=UnitDeviceResponse)
def unit_device_create(
    unit_id: str,
    community_id: str,
    payload: UnitDeviceCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    exists = db.execute(select(Device).where(and_(Device.unit_id == unit.id, Device.device_id == payload.device_id))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Device already exists on this unit")
    row = Device(
        unit_id=unit.id,
        device_id=payload.device_id,
        qty=payload.qty,
        is_active=payload.is_active,
        controllable=payload.controllable,
        schedules=payload.schedules,
    )
    db.add(row)
    db.commit()
    name_map = _resolve_device_names(db, [row.device_id])
    return _to_unit_device_response(row, name_map.get(row.device_id, row.device_id))


@router.put("/units/{unit_id}/devices/{device_id}", response_model=UnitDeviceResponse)
def unit_device_update(
    unit_id: str,
    device_id: str,
    community_id: str,
    payload: UnitDeviceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    row = db.execute(select(Device).where(and_(Device.unit_id == unit.id, Device.device_id == device_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if (
        payload.qty is None
        and payload.is_active is None
        and payload.controllable is None
        and payload.schedules is None
    ):
        raise HTTPException(status_code=400, detail="No updatable fields provided")
    if payload.qty is not None:
        row.qty = payload.qty
    if payload.is_active is not None:
        row.is_active = payload.is_active
    if payload.controllable is not None:
        row.controllable = payload.controllable
    if payload.schedules is not None:
        row.schedules = payload.schedules
    db.commit()
    name_map = _resolve_device_names(db, [row.device_id])
    return _to_unit_device_response(row, name_map.get(row.device_id, row.device_id))


@router.delete("/units/{unit_id}/devices/{device_id}")
def unit_device_delete(
    unit_id: str,
    device_id: str,
    community_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    row = db.execute(select(Device).where(and_(Device.unit_id == unit.id, Device.device_id == device_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "unit_id": unit_id, "device_id": device_id}


@router.post("/units/{unit_id}/devices/{device_id}/control", response_model=DeviceControlResponse)
def unit_device_control(
    unit_id: str,
    device_id: str,
    community_id: str,
    payload: DeviceControlRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    row = db.execute(select(Device).where(and_(Device.unit_id == unit.id, Device.device_id == device_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if not row.is_active:
        raise HTTPException(status_code=400, detail="Device is inactive")
    if not row.controllable:
        raise HTTPException(status_code=400, detail="Device is not controllable")

    command_id = str(uuid.uuid4())
    topic = f"energy/{community_id}/{unit_id}/control/{device_id}"
    command_payload = {
        "command_id": command_id,
        "community_id": community_id,
        "unit_id": unit_id,
        "device_id": device_id,
        "device_qty": row.qty,
        "action": payload.action,
        "requested_at": utc_now().isoformat(),
    }
    sent, error_msg = publish_device_command(topic=topic, payload=command_payload)
    cmd = DeviceCommand(
        command_id=command_id,
        community_id=community_id,
        unit_id=unit_id,
        device_id=device_id,
        action=payload.action,
        topic=topic,
        status="sent" if sent else "failed",
        error=error_msg,
        created_by_user_id=current_user.user_id,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return DeviceControlResponse(
        command_id=cmd.command_id,
        community_id=cmd.community_id,
        unit_id=cmd.unit_id,
        device_id=cmd.device_id,
        action=cmd.action,
        topic=cmd.topic,
        status=cmd.status,
        error=cmd.error,
        created_at=cmd.created_at,
    )


@router.put("/units/{unit_id}/va")
def update_unit_va(unit_id: str, payload: UnitVaUpdateRequest, community_id: str, db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    unit = db.execute(select(Unit).where(and_(Unit.unit_id == unit_id, Unit.community_id == community_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    unit.va = payload.va
    db.commit()
    db.refresh(unit)
    return {"community_id": community_id, "unit_id": unit_id, "va": unit.va}


@router.post("/communities/{community_id}/notifications")
def send_community_broadcast(
    community_id: str,
    payload: BroadcastRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_community_access(community_id, current_user)
    if current_user.role not in [UserRole.ADMIN, UserRole.COORDINATOR]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if current_user.role != UserRole.ADMIN:
        broadcast_rate_limiter.check_and_increment(current_user.user_id, limit=5)
    notification_id = str(uuid.uuid4())
    row = Notification(
        notification_id=notification_id,
        scope="community",
        community_id=community_id,
        message=payload.message,
        created_by_user_id=current_user.user_id,
    )
    db.add(row)
    db.add(
        NotificationDelivery(
            notification_id=notification_id,
            target_type="scope",
            target_id=community_id,
            status="queued",
        )
    )
    db.commit()
    return {"status": "queued", "scope": "community", "community_id": community_id, "notification_id": notification_id}


@router.get("/notifications", response_model=NotificationsListResponse)
def list_notifications(
    offset: int = 0,
    limit: int = 20,
    status: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = _validate_pagination(offset, limit)
    status_value = (status or "all").lower()
    if status_value not in {"all", "read", "unread"}:
        raise HTTPException(status_code=400, detail="status must be one of: all, read, unread")

    base_stmt = _apply_notification_scope(select(Notification), current_user)
    base_count_stmt = _apply_notification_scope(select(func.count(Notification.id)), current_user)

    read_exists = (
        select(NotificationRead.id)
        .where(
            and_(
                NotificationRead.notification_id == Notification.notification_id,
                NotificationRead.user_id == current_user.user_id,
            )
        )
        .exists()
    )
    if status_value == "read":
        base_stmt = base_stmt.where(read_exists)
        base_count_stmt = base_count_stmt.where(read_exists)
    elif status_value == "unread":
        base_stmt = base_stmt.where(~read_exists)
        base_count_stmt = base_count_stmt.where(~read_exists)

    total = int(db.execute(base_count_stmt).scalar_one())
    rows = db.execute(base_stmt.order_by(desc(Notification.created_at)).offset(offset).limit(limit)).scalars().all()
    notif_ids = [r.notification_id for r in rows]
    read_rows = []
    if notif_ids:
        read_rows = db.execute(
            select(NotificationRead.notification_id, NotificationRead.read_at).where(
                and_(
                    NotificationRead.user_id == current_user.user_id,
                    NotificationRead.notification_id.in_(notif_ids),
                )
            )
        ).all()
    read_lookup = {r.notification_id: r.read_at for r in read_rows}
    items = [_notification_with_deliveries(db, row, current_user, read_lookup=read_lookup) for row in rows]

    unread_count_stmt = _apply_notification_scope(select(func.count(Notification.id)), current_user).where(~read_exists)
    unread_count = int(db.execute(unread_count_stmt).scalar_one())
    meta = _meta(total, offset, limit)
    meta["unread_count"] = unread_count
    return {"items": items, "meta": meta}


@router.get("/notifications/{notification_id}", response_model=NotificationResponse)
def get_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.execute(select(Notification).where(Notification.notification_id == notification_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if not _can_access_notification(row, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _notification_with_deliveries(db, row, current_user)


@router.post("/notifications/{notification_id}/mark-read", response_model=NotificationMarkReadResponse)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.execute(select(Notification).where(Notification.notification_id == notification_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    if not _can_access_notification(row, current_user):
        raise HTTPException(status_code=403, detail="Forbidden")

    existing = db.execute(
        select(NotificationRead).where(
            and_(
                NotificationRead.notification_id == notification_id,
                NotificationRead.user_id == current_user.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"status": "ok", "notification_id": notification_id, "read_at": existing.read_at}

    read_at = utc_now()
    db.add(NotificationRead(notification_id=notification_id, user_id=current_user.user_id, read_at=read_at))
    db.commit()
    return {"status": "ok", "notification_id": notification_id, "read_at": read_at}


@router.post("/notifications/mark-all-read", response_model=NotificationMarkAllReadResponse)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_rows = db.execute(_apply_notification_scope(select(Notification.notification_id), current_user)).all()
    notification_ids = [r.notification_id for r in visible_rows]
    if not notification_ids:
        return {"status": "ok", "affected_count": 0}

    existing_rows = db.execute(
        select(NotificationRead.notification_id).where(
            and_(
                NotificationRead.user_id == current_user.user_id,
                NotificationRead.notification_id.in_(notification_ids),
            )
        )
    ).all()
    existing_ids = {r.notification_id for r in existing_rows}
    to_insert = [nid for nid in notification_ids if nid not in existing_ids]
    now = utc_now()
    for nid in to_insert:
        db.add(NotificationRead(notification_id=nid, user_id=current_user.user_id, read_at=now))
    if to_insert:
        db.commit()
    return {"status": "ok", "affected_count": len(to_insert)}


@router.get("/ai/health")
def ai_health(current_user: User = Depends(get_current_user)):
    return ai_orchestrator.client.health()


@router.get("/ai/last-result")
def ai_last_result(community_id: str, current_user: User = Depends(get_current_user)):
    ensure_community_access(community_id, current_user)
    return ai_orchestrator.get_last_result(community_id=community_id)


@router.get("/communities/{community_id}/ai-recommendations", response_model=AIRecommendationsResponse)
def ai_recommendations(community_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_community_access(community_id, current_user)
    row = get_latest_ai_result(db, community_id)
    if not row:
        return AIRecommendationsResponse(community_id=community_id, exists=False, analyzed_at=None, status=None, stale=True, source="unknown", recommendations=[])
    recommendations = parse_recommendations(row)
    return AIRecommendationsResponse(community_id=community_id, exists=True, analyzed_at=row.analyzed_at.isoformat(), status=row.status, stale=bool(row.stale), source=row.source or "unknown", recommendations=recommendations)


@router.get("/units/{unit_id}/ai-recommendations", response_model=UnitAIRecommendationsResponse)
def unit_ai_recommendations(
    unit_id: str,
    community_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    unit = _ensure_unit_operation_access(db, current_user, community_id, unit_id)
    row = get_latest_ai_result(db, community_id)
    if not row:
        return UnitAIRecommendationsResponse(
            community_id=community_id,
            unit_id=unit.unit_id,
            exists=False,
            analyzed_at=None,
            status=None,
            stale=True,
            source="unknown",
            recommendations=[],
        )
    recommendations = [item for item in parse_recommendations(row) if item.unit_id == unit_id]
    return UnitAIRecommendationsResponse(
        community_id=community_id,
        unit_id=unit.unit_id,
        exists=True,
        analyzed_at=row.analyzed_at.isoformat(),
        status=row.status,
        stale=bool(row.stale),
        source=row.source or "unknown",
        recommendations=recommendations,
    )


@router.get("/ai/status", response_model=AIStatusResponse)
def ai_status(community_id: str, current_user: User = Depends(get_current_user)):
    ensure_community_access(community_id, current_user)
    return AIStatusResponse(**ai_orchestrator.get_status(community_id=community_id))


@router.get("/ops/ingestion-status", response_model=IngestionStatusResponse)
def ops_ingestion_status(db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    total_readings = int(db.execute(select(func.count(EnergyReading.id))).scalar_one())
    total_dead_letters = int(db.execute(select(func.count(DeadLetter.id))).scalar_one())
    communities_with_data = int(db.execute(select(func.count(func.distinct(EnergyReading.community_id)))).scalar_one())
    last_ingestion = db.execute(select(func.max(EnergyReading.timestamp))).scalar_one_or_none()
    last_dead_letter = db.execute(select(func.max(DeadLetter.created_at))).scalar_one_or_none()
    rows = db.execute(select(EnergyReading.community_id, func.count(EnergyReading.id).label("readings_count"), func.max(EnergyReading.timestamp).label("last_ingestion_at")).group_by(EnergyReading.community_id).order_by(EnergyReading.community_id)).all()
    per_community = [IngestionPerCommunityItem(community_id=r.community_id, readings_count=int(r.readings_count), last_ingestion_at=r.last_ingestion_at.isoformat() if r.last_ingestion_at else None) for r in rows]
    return IngestionStatusResponse(mqtt={"enabled": settings.enable_mqtt, "host": settings.mqtt_host, "port": settings.mqtt_port}, totals={"energy_readings_count": total_readings, "dead_letters_count": total_dead_letters, "communities_with_data": communities_with_data}, latest={"last_ingestion_at": last_ingestion.isoformat() if last_ingestion else None, "last_dead_letter_at": last_dead_letter.isoformat() if last_dead_letter else None}, per_community=per_community)


@router.get("/ops/dead-letters", response_model=DeadLettersListResponse)
def ops_dead_letters(offset: int = 0, limit: int = 20, topic: str | None = None, reason_q: str | None = None, sort_by: str = "created_at", sort_order: str = "desc", db: Session = Depends(get_db), _: User = Depends(require_roles(UserRole.ADMIN))):
    limit = _validate_pagination(offset, limit)
    _validate_sort_order(sort_order)
    _validate_sort_by(sort_by, {"created_at", "id"})
    stmt = select(DeadLetter)
    count_stmt = select(func.count(DeadLetter.id))
    if topic:
        stmt = stmt.where(DeadLetter.topic == topic)
        count_stmt = count_stmt.where(DeadLetter.topic == topic)
    if reason_q:
        pattern = f"%{reason_q}%"
        stmt = stmt.where(DeadLetter.reason.ilike(pattern))
        count_stmt = count_stmt.where(DeadLetter.reason.ilike(pattern))
    sort_map = {"created_at": DeadLetter.created_at, "id": DeadLetter.id}
    sort_col = sort_map.get(sort_by, DeadLetter.created_at)
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)
    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.order_by(order_expr).offset(offset).limit(limit)).scalars().all()
    items = [DeadLetterItem(id=r.id, topic=r.topic, reason=r.reason, raw_payload=r.raw_payload, created_at=r.created_at.isoformat()) for r in rows]
    return {"items": items, "meta": _meta(total, offset, limit)}


@router.post("/ai/run-now")
def ai_run_now(community_id: str | None = None, current_user: User = Depends(get_current_user)):
    if current_user.role not in [UserRole.ADMIN, UserRole.COORDINATOR]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if current_user.role != UserRole.ADMIN:
        broadcast_rate_limiter.check_and_increment(
            current_user.user_id,
            limit=12,
            bucket="ai_run_now",
            error_message="AI run-now limit exceeded",
        )
    if community_id:
        ensure_community_access(community_id, current_user)
        try:
            return ai_orchestrator.run_once_for_community(community_id=community_id, source="manual")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    if current_user.role == UserRole.ADMIN:
        return ai_orchestrator.run_once_all(source="manual")
    return ai_orchestrator.run_once_for_community(community_id=current_user.community_id or "", source="manual")


@router.websocket("/ws/communities/{community_id}/dashboard")
async def ws_community_dashboard(websocket: WebSocket, community_id: str):
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    payload = AuthService.decode(token)
    role = payload.get("role")
    token_community = payload.get("community_id")
    if role != UserRole.ADMIN.value and token_community != community_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await dashboard_ws_manager.connect(community_id, websocket)
    try:
        sent = await dashboard_ws_manager.send_snapshot(websocket, community_id)
        if not sent:
            await websocket.send_json({"error": "Not found"})
            await websocket.close(code=1008)
            return
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await dashboard_ws_manager.disconnect(community_id, websocket)


@router.websocket("/ws/communities/{community_id}/units/{unit_id}/dashboard")
async def ws_unit_dashboard(websocket: WebSocket, community_id: str, unit_id: str):
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:]
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = AuthService.decode(token)
    user_id = payload.get("sub")
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.user_id == user_id)).scalar_one_or_none()
        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        try:
            _ensure_unit_operation_access(db, user, community_id, unit_id)
        except HTTPException:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    finally:
        db.close()

    await dashboard_ws_manager.connect_unit(community_id, unit_id, websocket)
    try:
        sent = await dashboard_ws_manager.send_unit_snapshot(websocket, community_id, unit_id)
        if not sent:
            await websocket.send_json({"error": "Not found"})
            await websocket.close(code=1008)
            return
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await dashboard_ws_manager.disconnect_unit(community_id, unit_id, websocket)
