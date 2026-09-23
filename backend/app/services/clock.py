"""Dates as the institution sees them.

Exams are scheduled, started and printed on notices in local time
(INSTITUTION_TIMEZONE); timestamps are stored in UTC.
"""
from __future__ import annotations

from datetime import date, datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import settings


@lru_cache(maxsize=1)
def institution_zone() -> ZoneInfo:
    return ZoneInfo(settings.institution_timezone)


def institution_now() -> datetime:
    return datetime.now(institution_zone())


def institution_today() -> date:
    return institution_now().date()


def local_date(moment: datetime) -> date:
    return moment.astimezone(institution_zone()).date()


def hhmm(value: time | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None
