from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TariffLookupByVA

DEFAULT_TARIFFS = {
    450: 415.0,
    900: 1352.0,
    1300: 1444.7,
    2200: 1444.7,
    3500: 1699.53,
    5500: 1699.53,
}


class TariffService:
    @staticmethod
    def seed_defaults(db: Session) -> None:
        for va, tariff in DEFAULT_TARIFFS.items():
            exists = db.execute(select(TariffLookupByVA).where(TariffLookupByVA.va == va)).scalar_one_or_none()
            if not exists:
                db.add(TariffLookupByVA(va=va, tariff_per_kwh=tariff))
        db.commit()

    @staticmethod
    def get_tariff_by_va(db: Session, va: int) -> float:
        row = db.execute(select(TariffLookupByVA).where(TariffLookupByVA.va == va)).scalar_one_or_none()
        if row:
            return row.tariff_per_kwh
        nearest = db.execute(select(TariffLookupByVA).order_by(TariffLookupByVA.va.desc())).scalars().first()
        if nearest:
            return nearest.tariff_per_kwh
        return DEFAULT_TARIFFS[1300]