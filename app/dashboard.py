from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, timedelta, datetime
from collections import defaultdict

from .database import get_db
from . import models

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
        return (
            datetime.strptime(date_from, "%d-%m-%Y").date(),
            datetime.strptime(date_to, "%d-%m-%Y").date(),
        )
    return today, today


@router.get("/stats")
def get_dashboard_stats(
    period: str = "today",
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    start, end = parse_period(period, date_from, date_to)
    today = date.today()

    active_guests = db.query(models.Guest).filter(
        models.Guest.check_in <= today,
        models.Guest.check_out >= today,
    ).count()

    checkins = db.query(models.Guest).filter(
        models.Guest.check_in >= start,
        models.Guest.check_in <= end,
    ).count()

    checkouts = db.query(models.Guest).filter(
        models.Guest.check_out >= start,
        models.Guest.check_out <= end,
    ).count()

    # Active theme
    active_theme = db.query(models.Template).filter(models.Template.status == "active").first()
    theme_name = active_theme.name if active_theme else "—"
    theme_sub  = f"{active_theme.start_date} → {active_theme.end_date}" if active_theme else "No active theme"

    # TV stats
    all_tvs   = db.query(models.TV).all()
    tv_online = sum(1 for t in all_tvs if t.status == "ONLINE")
    tv_bound  = sum(1 for t in all_tvs if t.bound)
    tv_total  = len(all_tvs)

    # PMS Bookings in period
    food_orders = db.query(models.Order).filter(
        func.date(models.Order.ordered_at) >= start,
        func.date(models.Order.ordered_at) <= end,
    ).count()

    spa_bookings = db.query(models.SpaBooking).filter(
        func.date(models.SpaBooking.booked_at) >= start,
        func.date(models.SpaBooking.booked_at) <= end,
    ).count()

    dine_bookings = db.query(models.DineBooking).filter(
        func.date(models.DineBooking.booked_at) >= start,
        func.date(models.DineBooking.booked_at) <= end,
    ).count()

    ent_bookings = db.query(models.EntertainmentBooking).filter(
        func.date(models.EntertainmentBooking.booked_at) >= start,
        func.date(models.EntertainmentBooking.booked_at) <= end,
    ).count()

    act_activities = db.query(models.ActivityBooking).filter(
        func.date(models.ActivityBooking.booked_at) >= start,
        func.date(models.ActivityBooking.booked_at) <= end,
    ).count()

    total_orders = (
        db.query(func.sum(models.Order.total))
        .filter(
            func.date(models.Order.ordered_at) >= start,
            func.date(models.Order.ordered_at) <= end,
        )
        .scalar() or 0
    )

    # Occupancy
    occupied    = active_guests
    total_rooms = tv_total  # one TV per room
    available   = max(0, total_rooms - occupied)

    return {
        "date_from": start.strftime("%d %b %Y"),
        "date_to":   end.strftime("%d %b %Y"),
        "active_guests": active_guests,
        "checkins":  checkins,
        "checkouts": checkouts,
        "theme": {
            "name": theme_name,
            "sub":  theme_sub,
        },
        "tv": {
            "online": tv_online,
            "bound":  tv_bound,
            "total":  tv_total,
        },
        "pms_bookings": {
            "food":          food_orders,
            "spa":           spa_bookings,
            "dine":          dine_bookings,
            "entertainment": ent_bookings,
        },
        "pms_activity": {
            "checkins":   checkins,
            "checkouts":  checkouts,
            "activities": act_activities,
            "total":      total_orders,
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

    # ── Booking Trend: daily check-ins + total bookings per day ──
    # Build date range labels
    delta = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(delta)]
    labels = [d.strftime("%m-%d") for d in dates]

    checkin_counts = defaultdict(int)
    booking_counts = defaultdict(int)

    guests = db.query(models.Guest).filter(
        models.Guest.check_in >= start,
        models.Guest.check_in <= end,
    ).all()
    for g in guests:
        checkin_counts[str(g.check_in)] += 1

    for Model, col in [
        (models.Order,                "ordered_at"),
        (models.SpaBooking,           "booked_at"),
        (models.DineBooking,          "booked_at"),
        (models.EntertainmentBooking, "booked_at"),
    ]:
        rows = db.query(Model).filter(
            func.date(getattr(Model, col)) >= start,
            func.date(getattr(Model, col)) <= end,
        ).all()
        for r in rows:
            day = str(getattr(r, col).date()) if hasattr(getattr(r, col), 'date') else str(getattr(r, col))[:10]
            booking_counts[day] += 1

    trend_checkins  = [checkin_counts.get(str(d), 0) for d in dates]
    trend_bookings  = [booking_counts.get(str(d), 0) for d in dates]

    # ── Recent Activity (last 10 events in period) ──
    recent = []

    orders = db.query(models.Order).filter(
        func.date(models.Order.ordered_at) >= start,
        func.date(models.Order.ordered_at) <= end,
    ).order_by(models.Order.ordered_at.desc()).limit(5).all()
    for o in orders:
        recent.append({
            "icon": "🍽️",
            "label": f"Food Order — {o.guest_name or 'Guest'}",
            "room": o.room_no,
            "time": o.ordered_at.strftime("%I:%M %p") if o.ordered_at else "",
            "type": "Food",
        })

    spas = db.query(models.SpaBooking).filter(
        func.date(models.SpaBooking.booked_at) >= start,
        func.date(models.SpaBooking.booked_at) <= end,
    ).order_by(models.SpaBooking.booked_at.desc()).limit(5).all()
    for s in spas:
        recent.append({
            "icon": "🧖",
            "label": f"{s.item_title} — {s.guest_name or 'Guest'}",
            "room": s.room_no,
            "time": s.booked_at.strftime("%I:%M %p") if s.booked_at else "",
            "type": "Spa",
        })

    dines = db.query(models.DineBooking).filter(
        func.date(models.DineBooking.booked_at) >= start,
        func.date(models.DineBooking.booked_at) <= end,
    ).order_by(models.DineBooking.booked_at.desc()).limit(3).all()
    for d2 in dines:
        recent.append({
            "icon": "🕯️",
            "label": f"{d2.item_title} — {d2.guest_name or 'Guest'}",
            "room": d2.room_no,
            "time": d2.booked_at.strftime("%I:%M %p") if d2.booked_at else "",
            "type": "Dine",
        })

    ents = db.query(models.EntertainmentBooking).filter(
        func.date(models.EntertainmentBooking.booked_at) >= start,
        func.date(models.EntertainmentBooking.booked_at) <= end,
    ).order_by(models.EntertainmentBooking.booked_at.desc()).limit(3).all()
    for e in ents:
        recent.append({
            "icon": "🎮",
            "label": f"{e.item_title} — {e.guest_name or 'Guest'}",
            "room": e.room_no,
            "time": e.booked_at.strftime("%I:%M %p") if e.booked_at else "",
            "type": "Entertainment",
        })

    # Sort by time desc and take top 8
    recent.sort(key=lambda x: x["time"], reverse=True)
    recent = recent[:8]

    # ── Top Performers (booking counts by category) ──
    food_count = db.query(models.Order).filter(
        func.date(models.Order.ordered_at) >= start,
        func.date(models.Order.ordered_at) <= end,
    ).count()
    spa_count = db.query(models.SpaBooking).filter(
        func.date(models.SpaBooking.booked_at) >= start,
        func.date(models.SpaBooking.booked_at) <= end,
    ).count()
    dine_count = db.query(models.DineBooking).filter(
        func.date(models.DineBooking.booked_at) >= start,
        func.date(models.DineBooking.booked_at) <= end,
    ).count()
    ent_count = db.query(models.EntertainmentBooking).filter(
        func.date(models.EntertainmentBooking.booked_at) >= start,
        func.date(models.EntertainmentBooking.booked_at) <= end,
    ).count()

    # ── Most Active Room ──
    from sqlalchemy import union_all, literal, cast, Integer as SAInt

    room_tally = defaultdict(int)
    for Model, col in [
        (models.Order, "ordered_at"),
        (models.SpaBooking, "booked_at"),
        (models.DineBooking, "booked_at"),
        (models.EntertainmentBooking, "booked_at"),
    ]:
        rows = db.query(Model.room_no).filter(
            func.date(getattr(Model, col)) >= start,
            func.date(getattr(Model, col)) <= end,
        ).all()
        for (rno,) in rows:
            if rno:
                room_tally[rno] += 1

    most_active_room = max(room_tally, key=room_tally.get) if room_tally else None

    # ── Total orders count ──
    total_orders_count = food_count + spa_count + dine_count + ent_count

    return {
        "trend": {
            "labels":   labels,
            "checkins": trend_checkins,
            "bookings": trend_bookings,
        },
        "recent_activity": recent,
        "top_performers": {
            "food":          food_count,
            "spa":           spa_count,
            "dine":          dine_count,
            "entertainment": ent_count,
        },
        "most_active_room":  most_active_room,
        "total_orders_count": total_orders_count,
    }