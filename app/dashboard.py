"""
dashboard.py  (UPDATED — latency instrumented)
────────────────────────────────────────────────
All existing logic is 100% intact.
Every db.query() is now wrapped with timed_query() to produce logs like:

  2026-04-28 11:12:51,607 WARNING pms.selectors MODULE_QUERY: Active Guests = 86.92ms
  2026-04-28 11:12:51,611 WARNING pms.selectors MODULE_QUERY: Food Orders = 4.00ms
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta, datetime
from collections import defaultdict

from .database import get_db
from . import models

import logging
import time

logger = logging.getLogger("pms.selectors")


def timed_query(label: str, query):
    """
    Wraps a SQLAlchemy query with latency logging.
    Returns a proxy so callers can still chain .all(), .first(), .count(), .scalar().

    Logs lines like:
      WARNING pms.selectors MODULE_QUERY: Active Guests = 86.92ms
    """
    class _TimedQuery:
        def __init__(self, q):
            self._q = q

        def _exec(self, fn):
            t0 = time.perf_counter()
            result = fn()
            ms = (time.perf_counter() - t0) * 1000
            logger.warning("MODULE_QUERY: %s = %.2fms", label, ms)
            return result

        def all(self):
            return self._exec(self._q.all)

        def first(self):
            return self._exec(self._q.first)

        def count(self):
            return self._exec(self._q.count)

        def scalar(self):
            return self._exec(self._q.scalar)

        # Support chaining (e.g. timed_query(..., db.query(M)).filter(...).all())
        def __getattr__(self, name):
            attr = getattr(self._q, name)
            if callable(attr):
                def wrapper(*args, **kwargs):
                    self._q = attr(*args, **kwargs)
                    return self
                return wrapper
            return attr

    return _TimedQuery(query)


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def parse_period(period: str, date_from: str = None, date_to: str = None):
    today = date.today()
    if period == "today":
        return today, today
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period == "month":
        return today.replace(day=1), today
    elif period == "custom" and date_from and date_to:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
            try:
                return (
                    datetime.strptime(date_from, fmt).date(),
                    datetime.strptime(date_to, fmt).date(),
                )
            except ValueError:
                continue
    return today, today


def count_rooms_from_string(room_numbers: str) -> int:
    if not room_numbers:
        return 0
    return len([r.strip() for r in room_numbers.split(",") if r.strip()])


def parse_group_date(date_str: str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


@router.get("/stats")
def get_dashboard_stats(
    period: str = "today",
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    start, end = parse_period(period, date_from, date_to)
    today = date.today()

    # ── Active Guests ──
    individual_active = timed_query(
        "Active Individual Guests",
        db.query(models.Guest).filter(
            models.Guest.check_in <= today,
            models.Guest.check_out >= today,
        )
    ).count()

    all_active_groups = timed_query(
        "Active Group Bookings",
        db.query(models.GroupBooking).filter(models.GroupBooking.is_active == 1)
    ).all()

    group_rooms_active = 0
    for grp in all_active_groups:
        ci = parse_group_date(grp.check_in)
        co = parse_group_date(grp.check_out)
        if ci and co and ci <= today and co >= today:
            group_rooms_active += count_rooms_from_string(grp.room_numbers)

    active_guests = individual_active + group_rooms_active

    # ── Check-ins in period ──
    individual_checkins = timed_query(
        "Individual Check-ins",
        db.query(models.Guest).filter(
            models.Guest.check_in >= start,
            models.Guest.check_in <= end,
        )
    ).count()

    all_groups = timed_query("All Group Bookings", db.query(models.GroupBooking)).all()

    group_checkins = 0
    group_checkouts = 0
    group_rooms_checkin = 0
    group_rooms_checkout = 0

    for grp in all_groups:
        ci = parse_group_date(grp.check_in)
        co = parse_group_date(grp.check_out)
        room_count = count_rooms_from_string(grp.room_numbers)
        if ci and start <= ci <= end:
            group_checkins += 1
            group_rooms_checkin += room_count
        if co and start <= co <= end:
            group_checkouts += 1
            group_rooms_checkout += room_count

    checkins = individual_checkins + group_checkins

    individual_checkouts = timed_query(
        "Individual Check-outs",
        db.query(models.Guest).filter(
            models.Guest.check_out >= start,
            models.Guest.check_out <= end,
        )
    ).count()
    checkouts = individual_checkouts + group_checkouts

    # ── Active Theme ──
    active_theme = timed_query(
        "Active Theme",
        db.query(models.Template).filter(models.Template.status == "active")
    ).first()
    theme_name = active_theme.name if active_theme else "—"
    theme_sub = (
        f"{active_theme.start_date} → {active_theme.end_date}"
        if active_theme else "No active theme"
    )

    # ── TV Stats ──
    all_tvs = timed_query("TV List", db.query(models.TV)).all()
    tv_online = sum(1 for t in all_tvs if t.status == "ONLINE")
    tv_bound  = sum(1 for t in all_tvs if t.bound)
    tv_total  = len(all_tvs)

    # ── PMS Bookings ──
    food_orders = timed_query(
        "Food Orders",
        db.query(models.Order).filter(
            func.date(models.Order.ordered_at) >= start,
            func.date(models.Order.ordered_at) <= end,
        )
    ).count()

    spa_bookings = timed_query(
        "Spa Bookings",
        db.query(models.SpaBooking).filter(
            func.date(models.SpaBooking.booked_at) >= start,
            func.date(models.SpaBooking.booked_at) <= end,
        )
    ).count()

    dine_bookings = timed_query(
        "Dine Bookings",
        db.query(models.DineBooking).filter(
            func.date(models.DineBooking.booked_at) >= start,
            func.date(models.DineBooking.booked_at) <= end,
        )
    ).count()

    ent_bookings = timed_query(
        "Entertainment Bookings",
        db.query(models.EntertainmentBooking).filter(
            func.date(models.EntertainmentBooking.booked_at) >= start,
            func.date(models.EntertainmentBooking.booked_at) <= end,
        )
    ).count()

    act_activities = timed_query(
        "Activity Bookings",
        db.query(models.ActivityBooking).filter(
            func.date(models.ActivityBooking.booked_at) >= start,
            func.date(models.ActivityBooking.booked_at) <= end,
        )
    ).count()

    total_orders = (
        timed_query(
            "Total Order Revenue",
            db.query(func.sum(models.Order.total)).filter(
                func.date(models.Order.ordered_at) >= start,
                func.date(models.Order.ordered_at) <= end,
            )
        ).scalar() or 0
    )

    # ── Occupancy ──
    config = timed_query(
        "Hotel Config (total_rooms)",
        db.query(models.HotelConfig).filter_by(key="total_rooms")
    ).first()
    total_rooms = int(config.value) if config else max(tv_total, active_guests)
    occupied  = min(active_guests, total_rooms)
    available = max(0, total_rooms - occupied)

    return {
        "date_from": start.strftime("%d %b %Y"),
        "date_to":   end.strftime("%d %b %Y"),
        "active_guests": active_guests,
        "checkins":  checkins,
        "checkouts": checkouts,
        "checkin_breakdown": {
            "individual":     individual_checkins,
            "group_bookings": group_checkins,
            "group_rooms":    group_rooms_checkin,
        },
        "theme": {"name": theme_name, "sub": theme_sub},
        "tv":    {"online": tv_online, "bound": tv_bound, "total": tv_total},
        "pms_bookings": {
            "food": food_orders, "spa": spa_bookings,
            "dine": dine_bookings, "entertainment": ent_bookings,
        },
        "pms_activity": {
            "checkins":  checkins,
            "checkouts": checkouts,
            "activities": act_activities,
            "total":     total_orders,
        },
        "occupancy": {
            "occupied":    occupied,
            "available":   available,
            "total_rooms": total_rooms,
        },
    }


@router.get("/charts")
def get_dashboard_charts(
    period: str = "today",
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    start, end = parse_period(period, date_from, date_to)

    delta = (end - start).days + 1
    dates  = [start + timedelta(days=i) for i in range(delta)]
    labels = [d.strftime("%m-%d") for d in dates]

    checkin_counts  = defaultdict(int)
    booking_counts  = defaultdict(int)

    guests = timed_query(
        "Guest Checkin Trend",
        db.query(models.Guest).filter(
            models.Guest.check_in >= start,
            models.Guest.check_in <= end,
        )
    ).all()
    for g in guests:
        checkin_counts[str(g.check_in)] += 1

    all_groups_chart = timed_query("Group Checkin Trend", db.query(models.GroupBooking)).all()
    for grp in all_groups_chart:
        ci = parse_group_date(grp.check_in)
        if ci and start <= ci <= end:
            checkin_counts[str(ci)] += 1

    for Model, col, label in [
        (models.Order,                 "ordered_at", "Order Trend"),
        (models.SpaBooking,            "booked_at",  "Spa Trend"),
        (models.DineBooking,           "booked_at",  "Dine Trend"),
        (models.EntertainmentBooking,  "booked_at",  "Entertainment Trend"),
        (models.ActivityBooking,       "booked_at",  "Activity Trend"),
    ]:
        rows = timed_query(
            label,
            db.query(Model).filter(
                func.date(getattr(Model, col)) >= start,
                func.date(getattr(Model, col)) <= end,
            )
        ).all()
        for r in rows:
            dt  = getattr(r, col)
            day = str(dt.date()) if hasattr(dt, "date") else str(dt)[:10]
            booking_counts[day] += 1

    trend_checkins  = [checkin_counts.get(str(d), 0)  for d in dates]
    trend_bookings  = [booking_counts.get(str(d), 0)  for d in dates]

    # ── Recent Activity ──
    recent = []
    for Model, col, label, icon, type_label in [
        (models.Order,                "ordered_at", "Food Order",    "🍽️", "Food"),
        (models.SpaBooking,           "booked_at",  "Spa Booking",   "🧖", "Spa"),
        (models.DineBooking,          "booked_at",  "Dine Booking",  "🕯️", "Dine"),
        (models.EntertainmentBooking, "booked_at",  "Entertainment", "🎮", "Entertain"),
    ]:
        rows = timed_query(
            f"Recent {type_label}",
            db.query(Model).filter(
                func.date(getattr(Model, col)) >= start,
                func.date(getattr(Model, col)) <= end,
            ).order_by(getattr(Model, col).desc()).limit(5)
        ).all()
        for r in rows:
            dt = getattr(r, col)
            recent.append({
                "icon":  icon,
                "label": label,
                "room":  r.room_no or "—",
                "time":  dt.strftime("%I:%M %p") if dt else "—",
                "type":  type_label,
            })

    recent = sorted(recent, key=lambda x: x["time"], reverse=True)[:10]

    return {
        "trend": {
            "labels":   labels,
            "checkins": trend_checkins,
            "bookings": trend_bookings,
        },
        "recent_activity": recent,
    }