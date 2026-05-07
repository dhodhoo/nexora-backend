from __future__ import annotations

import calendar
import csv
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import DeviceCatalog, EnergyReading
from app.services.ingestion import QueryService
from app.utils.time import assume_utc


@dataclass
class UnitMonthlyHistoryItem:
    period: str
    total_kwh: float
    estimated_cost: float
    estimated_emission_kg_co2e: float
    last_timestamp: Optional[datetime]
    is_fresh: bool


def parse_period_yyyy_mm(period: str) -> tuple[datetime, datetime]:
    try:
        year_s, month_s = period.split("-")
        year = int(year_s)
        month = int(month_s)
        if month < 1 or month > 12:
            raise ValueError
    except Exception as exc:
        raise ValueError("period must use YYYY-MM format") from exc

    start = datetime(year, month, 1, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start, end


def list_unit_report_history(
    db: Session,
    community_id: str,
    unit_id: str,
    include_simulation: bool,
    offset: int,
    limit: int,
) -> tuple[list[UnitMonthlyHistoryItem], int]:
    month_expr = func.to_char(EnergyReading.timestamp, "YYYY-MM")
    conditions = [EnergyReading.community_id == community_id, EnergyReading.unit_id == unit_id]
    if not include_simulation:
        conditions.append(EnergyReading.is_simulation.is_(False))

    grouped = (
        select(
            month_expr.label("period"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
            func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0).label("estimated_cost"),
            func.max(EnergyReading.timestamp).label("last_timestamp"),
        )
        .where(and_(*conditions))
        .group_by(month_expr)
    ).subquery()

    total = int(db.execute(select(func.count()).select_from(grouped)).scalar_one())
    rows = db.execute(
        select(
            grouped.c.period,
            grouped.c.total_kwh,
            grouped.c.estimated_cost,
            grouped.c.last_timestamp,
        )
        .order_by(grouped.c.period.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    items = [
        UnitMonthlyHistoryItem(
            period=r.period,
            total_kwh=float(r.total_kwh or 0.0),
            estimated_cost=float(r.estimated_cost or 0.0),
            estimated_emission_kg_co2e=QueryService.emission(float(r.total_kwh or 0.0)),
            last_timestamp=r.last_timestamp,
            is_fresh=QueryService.freshness(r.last_timestamp),
        )
        for r in rows
    ]
    return items, total


def compute_unit_period_report(
    db: Session,
    community_id: str,
    unit_id: str,
    period_start: datetime,
    period_end: datetime,
    include_simulation: bool,
) -> dict:
    conditions = [
        EnergyReading.community_id == community_id,
        EnergyReading.unit_id == unit_id,
        EnergyReading.timestamp >= period_start.replace(tzinfo=None),
        EnergyReading.timestamp <= period_end.replace(tzinfo=None),
    ]
    if not include_simulation:
        conditions.append(EnergyReading.is_simulation.is_(False))

    total_kwh, estimated_cost, last_timestamp = db.execute(
        select(
            func.coalesce(func.sum(EnergyReading.kwh), 0.0),
            func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
            func.max(EnergyReading.timestamp),
        ).where(and_(*conditions))
    ).one()
    total_kwh_f = float(total_kwh or 0.0)
    estimated_cost_f = float(estimated_cost or 0.0)

    device_rows = db.execute(
        select(
            EnergyReading.device_id,
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*conditions))
        .group_by(EnergyReading.device_id)
        .order_by(EnergyReading.device_id.asc())
    ).all()
    device_ids = [r.device_id for r in device_rows]
    name_map = {}
    if device_ids:
        catalog_rows = db.execute(
            select(DeviceCatalog.device_key, DeviceCatalog.display_name).where(DeviceCatalog.device_key.in_(device_ids))
        ).all()
        name_map = {r.device_key: r.display_name for r in catalog_rows}

    breakdown = [
        {
            "device_id": r.device_id,
            "device_name": name_map.get(r.device_id, r.device_id),
            "total_kwh": float(r.total_kwh or 0.0),
            "estimated_emission_kg_co2e": QueryService.emission(float(r.total_kwh or 0.0)),
        }
        for r in device_rows
    ]

    return {
        "community_id": community_id,
        "unit_id": unit_id,
        "total_kwh": total_kwh_f,
        "estimated_cost": estimated_cost_f,
        "estimated_emission_kg_co2e": QueryService.emission(total_kwh_f),
        "last_timestamp": last_timestamp,
        "is_fresh": QueryService.freshness(last_timestamp),
        "breakdown": breakdown,
    }


def build_unit_report_csv(period: str, data: dict) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["community_id", "unit_id", "period", "total_kwh", "estimated_cost", "estimated_emission_kg_co2e"])
    writer.writerow(
        [
            data["community_id"],
            data["unit_id"],
            period,
            f"{data['total_kwh']:.4f}",
            f"{data['estimated_cost']:.2f}",
            f"{data['estimated_emission_kg_co2e']:.4f}",
        ]
    )
    writer.writerow([])
    writer.writerow(["device_id", "device_name", "total_kwh", "estimated_emission_kg_co2e"])
    for row in data["breakdown"]:
        writer.writerow([row["device_id"], row["device_name"], f"{row['total_kwh']:.4f}", f"{row['estimated_emission_kg_co2e']:.4f}"])
    return output.getvalue().encode("utf-8")


def build_unit_report_xlsx(period: str, data: dict) -> bytes:
    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "summary"
    ws_summary.append(["community_id", "unit_id", "period", "total_kwh", "estimated_cost", "estimated_emission_kg_co2e"])
    ws_summary.append(
        [
            data["community_id"],
            data["unit_id"],
            period,
            data["total_kwh"],
            data["estimated_cost"],
            data["estimated_emission_kg_co2e"],
        ]
    )

    ws_breakdown = wb.create_sheet("device_breakdown")
    ws_breakdown.append(["device_id", "device_name", "total_kwh", "estimated_emission_kg_co2e"])
    for row in data["breakdown"]:
        ws_breakdown.append([row["device_id"], row["device_name"], row["total_kwh"], row["estimated_emission_kg_co2e"]])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_unit_report_pdf(period: str, data: dict) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 20 * mm

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(20 * mm, y, f"Nexora Unit Report - {period}")
    y -= 10 * mm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, y, f"Community: {data['community_id']}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Unit: {data['unit_id']}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Total kWh: {data['total_kwh']:.4f}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Estimated Cost: {data['estimated_cost']:.2f}")
    y -= 6 * mm
    pdf.drawString(20 * mm, y, f"Estimated Emission (kg CO2e): {data['estimated_emission_kg_co2e']:.4f}")
    y -= 10 * mm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(20 * mm, y, "Device Breakdown")
    y -= 8 * mm
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, y, "Device")
    pdf.drawString(90 * mm, y, "kWh")
    pdf.drawString(125 * mm, y, "Emission (kg CO2e)")
    y -= 5 * mm

    for row in data["breakdown"]:
        if y < 20 * mm:
            pdf.showPage()
            y = height - 20 * mm
        pdf.drawString(20 * mm, y, f"{row['device_name']} ({row['device_id']})")
        pdf.drawRightString(118 * mm, y, f"{row['total_kwh']:.4f}")
        pdf.drawRightString(180 * mm, y, f"{row['estimated_emission_kg_co2e']:.4f}")
        y -= 5 * mm

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
