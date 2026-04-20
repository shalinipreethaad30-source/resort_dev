"""
booking_routes.py
─────────────────
All booking/order API endpoints for PMS_IPTV.

HOW TO USE:
  1. Place this file at:  PMS_IPTV/app/booking_routes.py
  2. In PMS_IPTV/app/main.py, add at the top:
       from .booking_routes import router as booking_router
  3. Also in main.py, after `app = FastAPI()`, add:
       app.include_router(booking_router)
  4. Make sure PMS_IPTV_models.py changes are applied to app/models.py first.
"""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date, timedelta
import httpx
import json

from sqlalchemy.orm import Session
from .database import SessionLocal, get_db
from . import models

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# HELPER — resolve current guest for a room
#   Primary:  guest whose check_in <= today <= check_out
#   Fallback: most recent guest by check_in (covers checkout-day
#             edge cases, off-by-one date issues, late checkouts)
# ─────────────────────────────────────────────────────────────────

def _resolve_guest(db, room_no: int):
    today = date.today()
    guest = db.query(models.Guest).filter(
        models.Guest.room_no   == room_no,
        models.Guest.check_in  <= today,
        models.Guest.check_out >= today
    ).first()
    if not guest:
        guest = db.query(models.Guest).filter(
            models.Guest.room_no == room_no
        ).order_by(models.Guest.check_in.desc()).first()
    return guest


def _guest_name(db, room_no: int) -> str:
    guest = _resolve_guest(db, room_no)
    return guest.guest_name if guest else "Guest"


# ─────────────────────────────────────────────────────────────────
# HELPER — auto-confirm pending records older than 10 minutes
# ─────────────────────────────────────────────────────────────────

def _auto_confirm(db, records, time_field: str = "booked_at"):
    """
    For each record in `records`, if status is 'pending' and the
    timestamp at `time_field` is older than 10 minutes, flip it to
    'confirmed' in-place.  Caller must db.commit() after.
    """
    cutoff = datetime.now() - timedelta(minutes=10)
    changed = False
    for r in records:
        if r.status == "pending":
            ts = getattr(r, time_field, None)
            if ts and ts < cutoff:
                r.status = "confirmed"
                changed = True
    return changed


# ─────────────────────────────────────────────────────────────────
# HELPER — push updated bill totals to the PMS system
# ─────────────────────────────────────────────────────────────────

PMS_BASE_URL = "http://localhost:8001"

async def _sync_bill_to_pms(room_no: int):
    db = SessionLocal()
    try:
        # ── Only bill orders placed during the CURRENT guest's stay ──
        current_guest = _resolve_guest(db, room_no)

        if not current_guest:
            return  # No guest record at all — nothing to sync

        guest_name = current_guest.guest_name
        ci = current_guest.check_in
        if not isinstance(ci, datetime):
            ci = datetime.combine(ci, datetime.min.time())
        stay_start = ci

        BILLABLE = ["confirmed", "delivered", "completed"]
        orders = db.query(models.Order).filter(
            models.Order.room_no == room_no,
            models.Order.guest_name == guest_name,
            models.Order.ordered_at >= stay_start,
            models.Order.status.in_(BILLABLE)
        ).all()
        food_total = sum(o.total for o in orders if o.order_type == "food")
        bar_total  = sum(o.total for o in orders if o.order_type == "bar")

        spa_bookings = db.query(models.SpaBooking).filter(
            models.SpaBooking.room_no == room_no,
            models.SpaBooking.guest_name == guest_name,
            models.SpaBooking.booked_at >= stay_start,
            models.SpaBooking.status.in_(BILLABLE)
        ).all()
        spa_total = sum(b.price for b in spa_bookings if hasattr(b, 'price') and b.price)

        ent_bookings = db.query(models.EntertainmentBooking).filter(
            models.EntertainmentBooking.room_no == room_no,
            models.EntertainmentBooking.guest_name == guest_name,
            models.EntertainmentBooking.booked_at >= stay_start,
            models.EntertainmentBooking.status.in_(BILLABLE)
        ).all()
        ent_total = sum(b.price for b in ent_bookings)

        dine_bookings = db.query(models.DineBooking).filter(
            models.DineBooking.room_no == room_no,
            models.DineBooking.guest_name == guest_name,
            models.DineBooking.booked_at >= stay_start,
            models.DineBooking.status.in_(BILLABLE)
        ).all()
        dine_total = sum(getattr(b, 'price', 0) or 0 for b in dine_bookings)

        grand_total = food_total + bar_total + spa_total + ent_total + dine_total

        payload = {
            "room_no":             room_no,
            "food_total":          food_total + bar_total,
            "spa_total":           spa_total,
            "entertainment_total": ent_total,
            "dine_total":          dine_total,
            "grand_total":         grand_total,
        }

        async with httpx.AsyncClient() as client:
            await client.post(f"{PMS_BASE_URL}/pms/bill-update", json=payload, timeout=5.0)

    except Exception as e:
        print(f"[Bill Sync] Failed for room {room_no}: {e}")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 1.  FOOD ORDER  —  POST /api/order
# ═══════════════════════════════════════════════════════════════════

class OrderItem(BaseModel):
    id:    int
    name:  str
    qty:   int
    price: int

class OrderPayload(BaseModel):
    room_no:    int
    items:      List[OrderItem]
    total:      int
    order_type: str = "food"

@router.post("/api/order")
async def place_order(payload: OrderPayload):
    db = SessionLocal()
    try:
        guest_name = _guest_name(db, payload.room_no)
        items_json = str([
            {"id": i.id, "name": i.name, "qty": i.qty, "price": i.price}
            for i in payload.items
        ])
        order = models.Order(
            room_no    = payload.room_no,
            guest_name = guest_name,
            items      = items_json,
            total      = payload.total,
            order_type = payload.order_type,
            status     = "pending",
            ordered_at = datetime.now()
        )
        db.add(order)
        db.commit()
        order_id = order.id
    finally:
        db.close()

    await _sync_bill_to_pms(payload.room_no)

    return {
        "status":   "success",
        "message":  "Order received",
        "order_id": order_id,
        "room_no":  payload.room_no,
        "total":    payload.total
    }


# ═══════════════════════════════════════════════════════════════════
# 2.  SPA BOOKING  —  POST /api/spa-booking
# ═══════════════════════════════════════════════════════════════════

@router.post("/api/spa-booking")
async def place_spa_booking(request: Request):
    data       = await request.json()
    room_no    = int(data.get("room_no", 0))
    item_id    = data.get("item_id")
    item_title = data.get("item_title", "")
    category   = data.get("category", "")
    slot       = data.get("slot", "")

    db = SessionLocal()
    booking_id = None
    try:
        guest_name = _guest_name(db, room_no)

        # look up price from SpaItem table
        price = 0
        if item_id:
            spa_item = db.query(models.SpaItem).filter(
                models.SpaItem.id == item_id
            ).first()
            if spa_item:
                price      = spa_item.price or 0
                item_title = item_title or spa_item.title
                category   = category   or spa_item.category

        booking = models.SpaBooking(
            room_no    = room_no,
            guest_name = guest_name,
            item_id    = item_id,
            item_title = item_title,
            category   = category,
            slot       = slot,
            price      = price,
            status     = "pending",
            booked_at  = datetime.now()
        )
        db.add(booking)
        db.commit()
        booking_id = booking.id

        print(f"\n{'='*40}")
        print(f"SPA BOOKING — Room {room_no}")
        print(f"  {item_title} ({category}) — ₹{price}")
        print(f"  Slot: {slot}")
        print(f"{'='*40}\n")

    except Exception as e:
        db.rollback()
        print(f"Spa booking error: {e}")
    finally:
        db.close()

    await _sync_bill_to_pms(room_no)
    return {"status": "success", "message": "Spa booking confirmed", "booking_id": booking_id}


# ═══════════════════════════════════════════════════════════════════
# 3.  ENTERTAINMENT BOOKING  —  POST /api/entertainment-booking
# ═══════════════════════════════════════════════════════════════════

@router.post("/api/entertainment-booking")
async def place_entertainment_booking(request: Request):
    data       = await request.json()
    room_no    = int(data.get("room_no", 0))
    item_id    = data.get("item_id")
    item_title = data.get("item_title", "")
    category   = data.get("category", "")
    slot       = data.get("slot", "")
    guests_no  = int(data.get("guests", 1))

    db = SessionLocal()
    try:
        guest_name = _guest_name(db, room_no)

        price_per = 0
        venue     = None
        if item_id:
            ent_item = db.query(models.EntertainmentItem).filter(
                models.EntertainmentItem.id == item_id
            ).first()
            if ent_item:
                price_per  = ent_item.price or 0
                venue      = ent_item.venue
                item_title = item_title or ent_item.title
                category   = category   or ent_item.category

        booking = models.EntertainmentBooking(
            room_no      = room_no,
            guest_name   = guest_name,
            item_id      = item_id,
            item_title   = item_title,
            category     = category,
            venue        = venue,
            slot         = slot,
            guests_count = guests_no,
            price        = price_per * guests_no,
            status       = "pending",
            booked_at    = datetime.now()
        )
        db.add(booking)
        db.commit()
        booking_id = booking.id
    finally:
        db.close()

    await _sync_bill_to_pms(room_no)

    return {"status": "success", "message": "Entertainment booking confirmed", "booking_id": booking_id}


# ═══════════════════════════════════════════════════════════════════
# 4.  ACTIVITY BOOKING  —  POST /api/activity-booking
# ═══════════════════════════════════════════════════════════════════

@router.post("/api/activity-booking")
async def place_activity_booking(request: Request):
    data        = await request.json()
    room_no     = int(data.get("room_no", 0))
    activity_id = data.get("activity_id")
    title       = data.get("title", "")
    time_slot   = data.get("time_slot", "")

    db = SessionLocal()
    try:
        guest_name = _guest_name(db, room_no)
        booking = models.ActivityBooking(
            room_no     = room_no,
            guest_name  = guest_name,
            activity_id = activity_id,
            title       = title,
            time_slot   = time_slot,
            status      = "pending",
            booked_at   = datetime.now()
        )
        db.add(booking)
        db.commit()
        booking_id = booking.id
    finally:
        db.close()

    return {"status": "success", "message": "Activity reservation confirmed", "booking_id": booking_id}


# ═══════════════════════════════════════════════════════════════════
# 5.  DINE BOOKING  —  POST /api/dine-booking
# ═══════════════════════════════════════════════════════════════════

@router.post("/api/dine-booking")
async def place_dine_booking(request: Request):
    data       = await request.json()
    room_no    = int(data.get("room_no", 0))
    item_id    = data.get("item_id")
    item_title = data.get("item_title") or data.get("item_name", "")
    occasion   = data.get("occasion", "")
    slot       = data.get("slot", "")

    db = SessionLocal()
    try:
        guest_name = _guest_name(db, room_no)

        # Look up price from DineItem table (same pattern as spa/entertainment)
        price = 0
        if item_id:
            dine_item = db.query(models.DineItem).filter(
                models.DineItem.id == item_id
            ).first()
            if dine_item:
                price      = getattr(dine_item, 'price', 0) or 0
                item_title = item_title or dine_item.title
                occasion   = occasion   or dine_item.occasion

        booking = models.DineBooking(
            room_no    = room_no,
            guest_name = guest_name,
            item_id    = item_id,
            item_title = item_title,
            occasion   = occasion,
            slot       = slot,
            price      = price,
            status     = "pending",
            booked_at  = datetime.now()
        )
        db.add(booking)
        db.commit()
        booking_id = booking.id
    finally:
        db.close()

    await _sync_bill_to_pms(room_no)

    return {"status": "success", "message": "Dining reservation confirmed", "booking_id": booking_id}


# ═══════════════════════════════════════════════════════════════════
# 6.  MY ORDERS  —  GET /api/my-orders/{room_no}
#     TV page calls this to show the guest their current bookings.
# ═══════════════════════════════════════════════════════════════════

@router.get("/api/my-orders/{room_no}")
def my_orders(room_no: int):
    db = SessionLocal()
    try:
        current_guest = _resolve_guest(db, room_no)

        if current_guest:
            # ── Normal path: scope to current guest's stay ──
            guest_name = current_guest.guest_name
            ci = current_guest.check_in
            if not isinstance(ci, datetime):
                ci = datetime.combine(ci, datetime.min.time())
            stay_start = ci

            orders = db.query(models.Order).filter(
                models.Order.room_no == room_no,
                models.Order.guest_name == guest_name,
                models.Order.ordered_at >= stay_start
            ).order_by(models.Order.ordered_at.desc()).all()

            spa = db.query(models.SpaBooking).filter(
                models.SpaBooking.room_no == room_no,
                models.SpaBooking.guest_name == guest_name,
                models.SpaBooking.booked_at >= stay_start
            ).order_by(models.SpaBooking.booked_at.desc()).all()

            ent = db.query(models.EntertainmentBooking).filter(
                models.EntertainmentBooking.room_no == room_no,
                models.EntertainmentBooking.guest_name == guest_name,
                models.EntertainmentBooking.booked_at >= stay_start
            ).order_by(models.EntertainmentBooking.booked_at.desc()).all()

            activities = db.query(models.ActivityBooking).filter(
                models.ActivityBooking.room_no == room_no,
                models.ActivityBooking.guest_name == guest_name,
                models.ActivityBooking.booked_at >= stay_start
            ).order_by(models.ActivityBooking.booked_at.desc()).all()

            dine = db.query(models.DineBooking).filter(
                models.DineBooking.room_no == room_no,
                models.DineBooking.guest_name == guest_name,
                models.DineBooking.booked_at >= stay_start
            ).order_by(models.DineBooking.booked_at.desc()).all()

        else:
            # ── Fallback: no guest record matched (date mismatch etc.)
            #    Query by room_no only so bookings are never invisible. ──
            guest_name = "Guest"

            orders = db.query(models.Order).filter(
                models.Order.room_no == room_no
            ).order_by(models.Order.ordered_at.desc()).all()

            spa = db.query(models.SpaBooking).filter(
                models.SpaBooking.room_no == room_no
            ).order_by(models.SpaBooking.booked_at.desc()).all()

            ent = db.query(models.EntertainmentBooking).filter(
                models.EntertainmentBooking.room_no == room_no
            ).order_by(models.EntertainmentBooking.booked_at.desc()).all()

            activities = db.query(models.ActivityBooking).filter(
                models.ActivityBooking.room_no == room_no
            ).order_by(models.ActivityBooking.booked_at.desc()).all()

            dine = db.query(models.DineBooking).filter(
                models.DineBooking.room_no == room_no
            ).order_by(models.DineBooking.booked_at.desc()).all()

        # ── Resolve meal_plan from guest record, then group booking, else None ──
        meal_plan = None
        if current_guest:
            meal_plan = getattr(current_guest, 'meal_plan', None)
        if not meal_plan:
            today = date.today()
            room_str = str(room_no)
            groups = db.query(models.GroupBooking).filter(
                models.GroupBooking.is_active == 1,
                models.GroupBooking.check_out >= str(today)
            ).all()
            for grp in groups:
                try:
                    rooms = json.loads(grp.room_numbers) if isinstance(grp.room_numbers, str) else grp.room_numbers
                except Exception:
                    rooms = []
                if room_str in rooms:
                    meal_plan = getattr(grp, 'meal_plan', None)
                    break

        BILLABLE   = ["confirmed", "delivered", "completed"]
        food_total = sum(o.total for o in orders if o.order_type == "food" and o.status in BILLABLE)
        bar_total  = sum(o.total for o in orders if o.order_type == "bar"  and o.status in BILLABLE)
        spa_total  = sum(b.price for b in spa if hasattr(b, 'price') and b.price and b.status in BILLABLE)
        ent_total  = sum(b.price for b in ent if b.status in BILLABLE)
        dine_total = sum(getattr(b, 'price', 0) or 0 for b in dine if b.status in BILLABLE)
        grand_total = food_total + bar_total + spa_total + ent_total + dine_total

        return {
            "room_no": room_no,
            "totals": {
                "food":          food_total,
                "bar":           bar_total,
                "spa":           spa_total,
                "entertainment": ent_total,
                "dine":          dine_total,
                "grand":         grand_total,
            },
            "orders": [
                {
                    "id":           o.id,
                    "type":         o.order_type,
                    "items":        o.items,
                    "total":        o.total,
                    "status":       o.status,
                    "ordered_at":   (o.ordered_at.strftime("%d %b %Y, %I:%M %p") if o.ordered_at else "—"),
                    "booked_epoch": int(o.ordered_at.timestamp() * 1000) if o.ordered_at else 0
                }
                for o in orders
            ],
            "spa_bookings": [
                {
                    "id":           b.id,
                    "title":        b.item_title,
                    "category":     b.category,
                    "price":        b.price if hasattr(b, 'price') and b.price else 0,
                    "slot":         b.slot,
                    "status":       b.status,
                    "booked_at":    (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—"),
                    "booked_epoch": int(b.booked_at.timestamp() * 1000) if b.booked_at else 0
                }
                for b in spa
            ],
            "entertainment_bookings": [
                {
                    "id":           b.id,
                    "title":        b.item_title,
                    "category":     b.category,
                    "slot":         b.slot,
                    "venue":        b.venue,
                    "guests":       b.guests_count,
                    "price":        b.price,
                    "status":       b.status,
                    "booked_at":    (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—"),
                    "booked_epoch": int(b.booked_at.timestamp() * 1000) if b.booked_at else 0
                }
                for b in ent
            ],
            "activity_bookings": [
                {
                    "id":           b.id,
                    "title":        b.title,
                    "time_slot":    b.time_slot,
                    "status":       b.status,
                    "booked_at":    (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—"),
                    "booked_epoch": int(b.booked_at.timestamp() * 1000) if b.booked_at else 0
                }
                for b in activities
            ],
            "dine_bookings": [
                {
                    "id":           b.id,
                    "title":        b.item_title,
                    "occasion":     b.occasion,
                    "slot":         b.slot,
                    "price":        getattr(b, 'price', 0) or 0,
                    "status":       b.status,
                    "booked_at":    (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—"),
                    "booked_epoch": int(b.booked_at.timestamp() * 1000) if b.booked_at else 0
                }
                for b in dine
            ],
            "meal_plan": meal_plan or None
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 7.  ADMIN — ALL BOOKINGS  —  GET /api/admin/all-bookings
#     Auto-confirms any pending record whose cancellation window
#     (10 min) has elapsed before returning the list.
# ═══════════════════════════════════════════════════════════════════

@router.get("/api/admin/bookings")
@router.get("/api/admin/all-bookings")
def admin_all_bookings(room_no: Optional[int] = None):
    db = SessionLocal()
    try:
        def q(model):
            query = db.query(model)
            if room_no:
                query = query.filter(model.room_no == room_no)
            return query

        orders     = q(models.Order).order_by(models.Order.ordered_at.desc()).all()
        spa        = q(models.SpaBooking).order_by(models.SpaBooking.booked_at.desc()).all()
        ent        = q(models.EntertainmentBooking).order_by(models.EntertainmentBooking.booked_at.desc()).all()
        activities = q(models.ActivityBooking).order_by(models.ActivityBooking.booked_at.desc()).all()
        dine       = q(models.DineBooking).order_by(models.DineBooking.booked_at.desc()).all()

        # ── AUTO-CONFIRM: flip any pending record whose 10-min window has passed ──
        any_changed = False
        any_changed |= _auto_confirm(db, orders,     time_field="ordered_at")
        any_changed |= _auto_confirm(db, spa,        time_field="booked_at")
        any_changed |= _auto_confirm(db, ent,        time_field="booked_at")
        any_changed |= _auto_confirm(db, activities, time_field="booked_at")
        any_changed |= _auto_confirm(db, dine,       time_field="booked_at")
        if any_changed:
            db.commit()
        # ─────────────────────────────────────────────────────────────────────────

        return {
            "food_orders": [
                {
                    "id":         o.id,
                    "room_no":    o.room_no,
                    "guest_name": o.guest_name,
                    "type":       o.order_type,
                    "items":      o.items,
                    "total":      o.total,
                    "status":     o.status,
                    "ordered_at": (o.ordered_at.strftime("%d %b %Y, %I:%M %p") if o.ordered_at else "—")
                }
                for o in orders
            ],
            "spa_bookings": [
                {
                    "id":         b.id,
                    "room_no":    b.room_no,
                    "guest_name": b.guest_name,
                    "title":      b.item_title,
                    "category":   b.category,
                    "slot":       b.slot,
                    "price":      b.price if hasattr(b, 'price') and b.price else 0,
                    "status":     b.status,
                    "booked_at":  (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—")
                }
                for b in spa
            ],
            "entertainment_bookings": [
                {
                    "id":         b.id,
                    "room_no":    b.room_no,
                    "guest_name": b.guest_name,
                    "title":      b.item_title,
                    "category":   b.category,
                    "slot":       b.slot,
                    "venue":      b.venue,
                    "guests":     b.guests_count,
                    "price":      b.price,
                    "status":     b.status,
                    "booked_at":  (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—")
                }
                for b in ent
            ],
            "activity_bookings": [
                {
                    "id":         b.id,
                    "room_no":    b.room_no,
                    "guest_name": b.guest_name,
                    "title":      b.title,
                    "time_slot":  b.time_slot,
                    "status":     b.status,
                    "booked_at":  (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—")
                }
                for b in activities
            ],
            "dine_bookings": [
                {
                    "id":         b.id,
                    "room_no":    b.room_no,
                    "guest_name": b.guest_name,
                    "title":      b.item_title,
                    "occasion":   b.occasion,
                    "slot":       b.slot,
                    "status":     b.status,
                    "booked_at":  (b.booked_at.strftime("%d %b %Y, %I:%M %p") if b.booked_at else "—")
                }
                for b in dine
            ]
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 8.  ADMIN — UPDATE BOOKING STATUS
# ═══════════════════════════════════════════════════════════════════

class StatusUpdate(BaseModel):
    status: str

@router.patch("/api/admin/order/{order_id}/status")
async def update_order_status(order_id: int, body: StatusUpdate):
    db = SessionLocal()
    room_no = None
    try:
        order = db.query(models.Order).filter(models.Order.id == order_id).first()
        if not order:
            return {"status": "error", "message": "Order not found"}
        order.status = body.status
        room_no = order.room_no
        db.commit()
    finally:
        db.close()
    if room_no:
        await _sync_bill_to_pms(room_no)
    return {"status": "success", "order_id": order_id, "new_status": body.status}

@router.patch("/api/admin/spa-booking/{booking_id}/status")
async def update_spa_status(booking_id: int, body: StatusUpdate):
    db = SessionLocal()
    room_no = None
    try:
        b = db.query(models.SpaBooking).filter(models.SpaBooking.id == booking_id).first()
        if not b:
            return {"status": "error", "message": "Booking not found"}
        b.status = body.status
        room_no = b.room_no
        db.commit()
    finally:
        db.close()
    if room_no:
        await _sync_bill_to_pms(room_no)
    return {"status": "success", "booking_id": booking_id, "new_status": body.status}

@router.patch("/api/admin/entertainment-booking/{booking_id}/status")
async def update_ent_status(booking_id: int, body: StatusUpdate):
    db = SessionLocal()
    room_no = None
    try:
        b = db.query(models.EntertainmentBooking).filter(models.EntertainmentBooking.id == booking_id).first()
        if not b:
            return {"status": "error", "message": "Booking not found"}
        b.status = body.status
        room_no = b.room_no
        db.commit()
    finally:
        db.close()
    if room_no:
        await _sync_bill_to_pms(room_no)
    return {"status": "success", "booking_id": booking_id, "new_status": body.status}

@router.patch("/api/admin/dine-booking/{booking_id}/status")
async def update_dine_status(booking_id: int, body: StatusUpdate):
    db = SessionLocal()
    room_no = None
    try:
        b = db.query(models.DineBooking).filter(models.DineBooking.id == booking_id).first()
        if not b:
            return {"status": "error", "message": "Booking not found"}
        b.status = body.status
        room_no = b.room_no
        db.commit()
    finally:
        db.close()
    if room_no:
        await _sync_bill_to_pms(room_no)
    return {"status": "success", "booking_id": booking_id, "new_status": body.status}

@router.patch("/api/admin/activity-booking/{booking_id}/status")
async def update_activity_status(booking_id: int, body: StatusUpdate):
    db = SessionLocal()
    room_no = None
    try:
        b = db.query(models.ActivityBooking).filter(models.ActivityBooking.id == booking_id).first()
        if not b:
            return {"status": "error", "message": "Booking not found"}
        b.status = body.status
        room_no = b.room_no
        db.commit()
    finally:
        db.close()
    # Activities have no price, but sync anyway to stay consistent
    if room_no:
        await _sync_bill_to_pms(room_no)
    return {"status": "success", "booking_id": booking_id, "new_status": body.status}


# ═══════════════════════════════════════════════════════════════════
# 9.  MANUAL BILL SYNC  —  POST /api/admin/sync-bill/{room_no}
# ═══════════════════════════════════════════════════════════════════

@router.post("/api/admin/sync-bill/{room_no}")
async def manual_sync_bill(room_no: int):
    await _sync_bill_to_pms(room_no)
    return {"status": "success", "message": f"Bill synced to PMS for room {room_no}"}


# ═══════════════════════════════════════════════════════════════════
# 10.  GUEST CANCEL  —  POST /api/cancel/{type}/{id}
#      Called by the TV page within the 10-minute cancellation window.
#      Marks the record as "cancelled" so the amount is deducted from
#      the bill total on the next _sync_bill_to_pms call.
# ═══════════════════════════════════════════════════════════════════

CANCEL_WINDOW_SECONDS = 600  # 10 minutes

@router.post("/api/cancel/{booking_type}/{booking_id}")
async def guest_cancel(booking_type: str, booking_id: int):
    db = SessionLocal()
    room_no = None
    try:
        model_map = {
            "order":         models.Order,
            "spa":           models.SpaBooking,
            "entertainment": models.EntertainmentBooking,
            "activity":      models.ActivityBooking,
            "dine":          models.DineBooking,
        }
        model = model_map.get(booking_type)
        if not model:
            return {"status": "error", "message": f"Unknown booking type: {booking_type}"}

        record = db.query(model).filter(model.id == booking_id).first()
        if not record:
            return {"status": "error", "message": "Booking not found"}

        # Only allow cancelling pending bookings
        if record.status != "pending":
            return {"status": "error", "message": "Only pending bookings can be cancelled"}

        # Enforce 10-minute window — use ordered_at for orders, booked_at for everything else
        booked_field = getattr(record, "ordered_at", None) or getattr(record, "booked_at", None)
        if booked_field:
            elapsed = (datetime.now() - booked_field).total_seconds()
            if elapsed > CANCEL_WINDOW_SECONDS:
                return {"status": "error", "message": "Cancellation window has expired"}

        record.status = "cancelled"
        room_no = record.room_no
        db.commit()

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

    # Sync bill so the cancelled amount is deducted immediately
    if room_no:
        await _sync_bill_to_pms(room_no)

    return {"status": "success", "message": "Booking cancelled and bill updated"}


# ═══════════════════════════════════════════════════════════════════
# 11.  DELETE GUEST  —  POST /delete-guest
#      Removes the active guest record for a given room number.
# ═══════════════════════════════════════════════════════════════════

class DeleteGuestPayload(BaseModel):
    room_no: int

@router.post("/delete-guest")
def delete_guest(payload: DeleteGuestPayload, db: Session = Depends(get_db)):
    guest = db.query(models.Guest).filter(
        models.Guest.room_no == payload.room_no,
        models.Guest.is_active == True   # remove this line if you don't have is_active
    ).first()

    if not guest:
        return {"status": "error", "message": "Guest not found"}

    db.delete(guest)
    db.commit()
    return {"status": "success", "message": f"Guest in room {payload.room_no} deleted"}


# ═══════════════════════════════════════════════════════════════════
# 11b. UPDATE MEAL PLAN  —  POST /api/update-meal-plan
#      Updates the meal_plan field on the active guest record for a
#      given room. Falls back to the active group booking if no
#      individual guest record is found.
# ═══════════════════════════════════════════════════════════════════

@router.post("/api/update-meal-plan")
async def update_meal_plan(request: Request):
    data      = await request.json()
    room_no   = int(data.get("room_no", 0))
    meal_plan = data.get("meal_plan", "")

    db = SessionLocal()
    try:
        today = date.today()

        guest = db.query(models.Guest).filter(
            models.Guest.room_no   == room_no,
            models.Guest.check_in  <= today,
            models.Guest.check_out >= today
        ).first()

        if guest:
            guest.meal_plan = meal_plan
            db.commit()
            return {"status": "success", "meal_plan": meal_plan}

        # No individual guest — check group booking
        groups = db.query(models.GroupBooking).filter(
            models.GroupBooking.is_active == 1,
            models.GroupBooking.check_out >= str(today)
        ).all()
        for group in groups:
            rooms = json.loads(group.room_numbers) if isinstance(group.room_numbers, str) else group.room_numbers
            if str(room_no) in rooms:
                group.meal_plan = meal_plan
                db.commit()
                return {"status": "success", "meal_plan": meal_plan}

        return {"status": "error", "message": "Guest not found"}

    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 12.  GROUP SUMMARY  —  GET /api/group-summary/{room_no}
#      Returns per-room charges for all rooms in the same group
#      booking, plus a group grand total. Used by the TV page's
#      "Group Total" card in My Bookings.
# ═══════════════════════════════════════════════════════════════════

@router.get("/api/group-summary/{room_no}")
def group_summary(room_no: int):
    db = SessionLocal()
    try:
        today = date.today()

        # Find if this room belongs to an active group
        all_groups = db.query(models.GroupBooking).all()
        current_group = None
        for g in all_groups:
            rooms = json.loads(g.room_numbers) if isinstance(g.room_numbers, str) else g.room_numbers
            rooms_int = [int(r) for r in rooms]
            ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
            co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
            if room_no in rooms_int and ci <= today <= co:
                current_group = g
                current_group._room_list = rooms_int
                break

        if not current_group:
            return {"is_group": False}

        # Include "pending" so the group total matches what the TV page shows
        # per-room. Only "cancelled" must be excluded.
        BILLABLE = ["pending", "confirmed", "delivered", "completed"]

        def room_totals(rno: int):
            guest = _resolve_guest(db, rno)

            if guest:
                gname = guest.guest_name
                ci_dt = guest.check_in
                if not isinstance(ci_dt, datetime):
                    ci_dt = datetime.combine(ci_dt, datetime.min.time())

                orders = db.query(models.Order).filter(
                    models.Order.room_no == rno,
                    models.Order.guest_name == gname,
                    models.Order.ordered_at >= ci_dt,
                    models.Order.status.in_(BILLABLE)
                ).all()

                spa_b = db.query(models.SpaBooking).filter(
                    models.SpaBooking.room_no == rno,
                    models.SpaBooking.guest_name == gname,
                    models.SpaBooking.booked_at >= ci_dt,
                    models.SpaBooking.status.in_(BILLABLE)
                ).all()

                ent_b = db.query(models.EntertainmentBooking).filter(
                    models.EntertainmentBooking.room_no == rno,
                    models.EntertainmentBooking.guest_name == gname,
                    models.EntertainmentBooking.booked_at >= ci_dt,
                    models.EntertainmentBooking.status.in_(BILLABLE)
                ).all()

                dine_b = db.query(models.DineBooking).filter(
                    models.DineBooking.room_no == rno,
                    models.DineBooking.guest_name == gname,
                    models.DineBooking.booked_at >= ci_dt,
                    models.DineBooking.status.in_(BILLABLE)
                ).all()

            else:
                # Fallback: guest record missing or date mismatch
                gname = "Guest"

                orders = db.query(models.Order).filter(
                    models.Order.room_no == rno,
                    models.Order.status.in_(BILLABLE)
                ).all()

                spa_b = db.query(models.SpaBooking).filter(
                    models.SpaBooking.room_no == rno,
                    models.SpaBooking.status.in_(BILLABLE)
                ).all()

                ent_b = db.query(models.EntertainmentBooking).filter(
                    models.EntertainmentBooking.room_no == rno,
                    models.EntertainmentBooking.status.in_(BILLABLE)
                ).all()

                dine_b = db.query(models.DineBooking).filter(
                    models.DineBooking.room_no == rno,
                    models.DineBooking.status.in_(BILLABLE)
                ).all()

            food = sum(o.total for o in orders if o.order_type == "food")
            bar  = sum(o.total for o in orders if o.order_type == "bar")
            spa  = sum(b.price or 0 for b in spa_b)
            ent  = sum(b.price or 0 for b in ent_b)
            dine = sum(getattr(b, 'price', 0) or 0 for b in dine_b)

            room_grand = food + bar + spa + ent + dine
            return {
                "room_no":       rno,
                "guest_name":    gname,
                "food":          food,
                "bar":           bar,
                "spa":           spa,
                "entertainment": ent,
                "dine":          dine,
                "total":         room_grand
            }

        per_room = []
        group_grand = 0
        for rno in current_group._room_list:
            data = room_totals(rno)
            per_room.append(data)
            group_grand += data["total"]

        return {
            "is_group":          True,
            "group_id":          current_group.id,
            "group_name":        getattr(current_group, "group_name", f"Group #{current_group.id}"),
            "total_rooms":       len(current_group._room_list),
            "group_grand_total": group_grand,
            "per_room":          per_room
        }
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════
# 13.  DEBUG GUEST  —  GET /api/debug-guest/{room_no}
#      Temporary endpoint — remove after confirming guest dates.
# ═══════════════════════════════════════════════════════════════════

@router.get("/api/debug-guest/{room_no}")
def debug_guest(room_no: int):
    db = SessionLocal()
    try:
        today = date.today()
        all_guests = db.query(models.Guest).filter(
            models.Guest.room_no == room_no
        ).all()
        return {
            "today": str(today),
            "guests": [
                {
                    "id":           g.id,
                    "guest_name":   g.guest_name,
                    "check_in":     str(g.check_in),
                    "check_out":    str(g.check_out),
                    "matches_today": (
                        (g.check_in if isinstance(g.check_in, date)
                         else date.fromisoformat(str(g.check_in)))
                        <= today <=
                        (g.check_out if isinstance(g.check_out, date)
                         else date.fromisoformat(str(g.check_out)))
                    )
                }
                for g in all_guests
            ]
        }
    finally:
        db.close()