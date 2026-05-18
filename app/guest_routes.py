"""
app/guest_routes.py
Guest & Group Booking management combined.

Guests  : list, delete (REST + POST), send room message, current-guests API
Groups  : list, send group message, current-groups API

NOTE: group_routes.py is now fully replaced by this file. Remove it from main.py.
"""

import json
from datetime import date, datetime
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .database import SessionLocal
from . import models
from .models import GroupBooking
from .utils import room_messages

router    = APIRouter()
templates = Jinja2Templates(directory="templates")


# =============================================================================
# GUESTS
# =============================================================================

@router.get("/admin/guests", response_class=HTMLResponse)
def guest_info(request: Request):
    db    = SessionLocal()
    today = date.today()
    all_guests = db.query(models.Guest).all()

    current_guests     = []
    checked_out_guests = []
    upcoming_guests    = []

    for g in all_guests:
        ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
        co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
        if ci <= today <= co:
            g.days_left = (co - today).days
            current_guests.append(g)
        elif co < today:
            checked_out_guests.append(g)
        else:
            g.days_until = (ci - today).days
            upcoming_guests.append(g)

    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":            request,
        "page":               "guests",
        "current_guests":     current_guests,
        "checked_out_guests": checked_out_guests,
        "upcoming_guests":    upcoming_guests,
    })


# ---------------------------------------------------------------------------
# Delete guest — REST (DELETE /admin/guests/{room_no})
# ---------------------------------------------------------------------------

@router.delete("/admin/guests/{room_no}")
def delete_guest_by_id(room_no: int):
    db = SessionLocal()
    try:
        guest = db.query(models.Guest).filter(models.Guest.room_no == room_no).first()
        if not guest:
            return JSONResponse(status_code=404, content={"message": "Guest not found"})  # ✅ proper 404
        _settle_pending_bookings(db, guest)
        db.delete(guest)
        db.commit()
        return {"message": "Guest deleted successfully"}
    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"message": f"Error: {str(e)}"})  # ✅ proper 500
    finally:
        db.close()

# ---------------------------------------------------------------------------
# Delete guest — POST /delete-guest  (called by frontend JS)
# ---------------------------------------------------------------------------

@router.post("/delete-guest")
async def delete_guest_post(request: Request):
    db = SessionLocal()
    try:
        data    = await request.json()
        room_no = data.get("room_no")

        if room_no is None:
            return JSONResponse(status_code=400, content={"status": "error", "message": "room_no is required"})

        today = date.today()
        guest = (
            db.query(models.Guest)
            .filter(
                models.Guest.room_no   == room_no,
                models.Guest.check_in  <= today,
                models.Guest.check_out >= today,
            )
            .first()
        )
        if not guest:
            guest = db.query(models.Guest).filter(models.Guest.room_no == room_no).first()

        if not guest:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": f"No guest found in room {room_no}"}
            )

        _settle_pending_bookings(db, guest)
        db.delete(guest)
        db.commit()
        return {"status": "success", "message": f"Guest in room {room_no} deleted successfully"}

    except Exception as e:
        db.rollback()
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Send room message
# ---------------------------------------------------------------------------

@router.post("/send-message")
def send_message(room_no: int = Form(...), message: str = Form(...)):
    room_messages[room_no] = message
    return RedirectResponse("/admin/guests", status_code=303)


# ---------------------------------------------------------------------------
# API: current guests (JSON)
# ---------------------------------------------------------------------------

@router.get("/api/guests/current")
def api_current_guests():
    db    = SessionLocal()
    today = date.today()
    all_guests = db.query(models.Guest).all()
    result = []
    for g in all_guests:
        ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
        co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
        if ci <= today <= co:
            result.append({
                "room_no":    g.room_no,
                "guest_name": g.guest_name,
                "check_in":   str(g.check_in),
                "check_out":  str(g.check_out),
                "days_left":  (co - today).days,
            })
    db.close()
    return result


@router.get("/api/guests/upcoming")
def api_upcoming_guests():
    db    = SessionLocal()
    today = date.today()
    all_guests = db.query(models.Guest).all()
    result = []
    for g in all_guests:
        ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
        co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
        if ci > today:
            result.append({
                "room_no":    g.room_no,
                "guest_name": g.guest_name,
                "check_in":   str(g.check_in),
                "check_out":  str(g.check_out),
                "days_until": (ci - today).days,
            })
    db.close()
    return result


# =============================================================================
# GROUPS
# =============================================================================

@router.get("/admin/groups", response_class=HTMLResponse)
def admin_group_bookings(request: Request):
    db    = SessionLocal()
    today = date.today()
    all_groups = db.query(GroupBooking).all()

    active_groups   = []
    past_groups     = []
    upcoming_groups = []

    for g in all_groups:
        ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
        co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
        g.room_numbers_list = json.loads(g.room_numbers) if isinstance(g.room_numbers, str) else g.room_numbers

        if ci <= today <= co:
            g.days_left = (co - today).days
            active_groups.append(g)
        elif co < today:
            past_groups.append(g)
        else:
            g.days_until = (ci - today).days
            upcoming_groups.append(g)

    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":         request,
        "page":            "groups",
        "active_groups":   active_groups,
        "past_groups":     past_groups,
        "upcoming_groups": upcoming_groups,
    })


@router.post("/send-group-message")
def send_group_message(
    group_id:     int = Form(...),
    room_numbers: str = Form(...),
    message:      str = Form(...)
):
    for room in [r.strip() for r in room_numbers.split(",")]:
        try:
            room_messages[int(room)] = message
        except Exception:
            pass
    return RedirectResponse("/admin/groups", status_code=303)


@router.get("/api/groups/current")
def api_current_groups():
    db    = SessionLocal()
    today = date.today()
    all_groups = db.query(GroupBooking).all()
    result = []
    for g in all_groups:
        ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
        co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
        if ci <= today <= co:
            room_numbers_list = json.loads(g.room_numbers) if isinstance(g.room_numbers, str) else g.room_numbers
            result.append({
                "id":                g.id,
                "group_name":        g.group_name,
                "welcome_message":   g.welcome_message or "",
                "room_numbers_list": room_numbers_list,
                "check_in":          str(g.check_in),
                "check_out":         str(g.check_out),
                "days_left":         (co - today).days,
            })
    db.close()
    return result


# =============================================================================
# PRIVATE HELPERS
# =============================================================================

def _settle_pending_bookings(db, guest):
    """Auto-confirm all pending bookings when a guest is checked out / deleted."""
    ci = guest.check_in
    if not isinstance(ci, datetime):
        ci = datetime.combine(ci, datetime.min.time())

    for Model, time_col in [
        (models.Order,                "ordered_at"),
        (models.SpaBooking,           "booked_at"),
        (models.EntertainmentBooking, "booked_at"),
        (models.ActivityBooking,      "booked_at"),
        (models.DineBooking,          "booked_at"),
    ]:
        pending = db.query(Model).filter(
            Model.room_no    == guest.room_no,
            Model.guest_name == guest.guest_name,
            getattr(Model, time_col) >= ci,
            Model.status     == "pending",
        ).all()
        for r in pending:
            r.status = "confirmed"