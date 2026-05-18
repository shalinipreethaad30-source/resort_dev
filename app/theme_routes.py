"""
app/theme_routes.py
Theme/template management: apply, schedule, discard, active-theme API.
"""

import httpx
from datetime import date
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from .database import SessionLocal
from . import models
from .models import Template
from .utils import room_messages

router    = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Admin themes page
# ---------------------------------------------------------------------------

@router.get("/themes", response_class=HTMLResponse)
def theme_page(request: Request):
    db = SessionLocal()
    theme_list = db.query(Template).filter(Template.name != "default").all()
    active     = db.execute(text("SELECT id FROM templates WHERE status='active' LIMIT 1")).fetchone()
    active_id  = active[0] if active else None
    db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "page": "themes", "themes": theme_list, "active_theme_id": active_id}
    )


# ---------------------------------------------------------------------------
# Apply / schedule / discard
# ---------------------------------------------------------------------------

@router.get("/apply_theme/{theme_id}")
def apply_theme_by_id(theme_id: int):
    from fastapi.responses import JSONResponse
    db = SessionLocal()
    active = db.execute(
        text("SELECT id, name FROM templates WHERE status='active' AND id != :id LIMIT 1"),
        {"id": theme_id}
    ).fetchone()
    if active:
        db.close()
        return JSONResponse(
            status_code=409,
            content={"conflict": True, "active_theme_name": active[1]}
        )
    db.execute(text("UPDATE templates SET status='inactive'"))
    db.execute(text("UPDATE templates SET status='active' WHERE id=:id"), {"id": theme_id})
    db.commit()
    db.close()
    return RedirectResponse(url="/themes", status_code=303)


@router.post("/add_template")
async def add_template(request: Request):
    data = await request.json()
    db   = SessionLocal()
    t    = Template(
        name=data.get("name"),
        theme_image=data.get("image"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
    )
    db.add(t)
    db.commit()
    db.close()
    return {"message": "Template added successfully"}


@router.get("/active_theme")
def active_theme():
    db    = SessionLocal()
    today = date.today()
    theme = db.query(Template).filter(
        Template.start_date <= today,
        Template.end_date   >= today
    ).first()
    if not theme:
        db.execute(text("UPDATE templates SET status='inactive' WHERE end_date < :today"), {"today": today})
        db.commit()
    db.close()
    return {"theme": theme.theme_image if theme else "default.html"}


@router.post("/apply_theme")
def apply_theme_form(
    theme_name: str  = Form(...),
    start_date: date = Form(...),
    end_date:   date = Form(...)
):
    db = SessionLocal()
    db.execute(text("UPDATE templates SET start_date = NULL, end_date = NULL"))
    db.execute(
        text("UPDATE templates SET start_date=:s, end_date=:e WHERE theme_image=:n"),
        {"s": start_date, "e": end_date, "n": theme_name}
    )
    db.commit()
    db.close()
    return RedirectResponse("/themes", status_code=303)


@router.post("/schedule_theme/{theme_id}")
def schedule_theme(theme_id: int, start_date: str = Form(...), end_date: str = Form(...)):
    db = SessionLocal()

    # Block if a *different* theme is already active
    active = db.execute(
        text("SELECT id, name FROM templates WHERE status='active' AND id != :id LIMIT 1"),
        {"id": theme_id}
    ).fetchone()
    if active:
        db.close()
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=409,
            content={"conflict": True, "active_theme_name": active[1]}
        )

    db.execute(text("UPDATE templates SET status='inactive'"))
    db.execute(
        text("UPDATE templates SET start_date=:s, end_date=:e, status='active' WHERE id=:id"),
        {"s": start_date, "e": end_date, "id": theme_id}
    )
    db.commit()
    db.close()
    return RedirectResponse("/themes", status_code=303)


@router.post("/discard_theme/{theme_id}")
def discard_theme(theme_id: int):
    db = SessionLocal()
    db.execute(
        text("UPDATE templates SET status='inactive', start_date=NULL, end_date=NULL WHERE id=:id"),
        {"id": theme_id}
    )
    db.commit()
    db.close()
    return RedirectResponse("/themes", status_code=303)


# ---------------------------------------------------------------------------
# API: current theme (used by TV/guest pages)
# ---------------------------------------------------------------------------

@router.get("/api/current-theme")
def get_current_theme():
    db    = SessionLocal()
    today = date.today()
    theme = db.execute(text("""
        SELECT theme_image FROM templates
        WHERE status='active' AND start_date <= :today AND end_date >= :today
        LIMIT 1
    """), {"today": today}).fetchone()
    db.close()
    return {"template": theme[0] if theme else "default.html"}


@router.get("/theme/{template_name}")
def load_theme(request: Request, template_name: str, room_no: int = 0):
    db    = SessionLocal()
    today = date.today()
    guest   = None
    message = None
    if room_no:
        guest = db.query(models.Guest).filter(
            models.Guest.room_no   == room_no,
            models.Guest.check_in  <= today,
            models.Guest.check_out >= today
        ).first()
        message = room_messages.get(room_no)
    db.close()
    return templates.TemplateResponse(
        template_name,
        {"request": request, "guest": guest, "room_no": room_no, "custom_message": message}
    )


# ---------------------------------------------------------------------------
# Room data API (used by TV page to get guest name + message)
# ---------------------------------------------------------------------------

@router.get("/api/room-data/{room_no}")
async def get_room_data(room_no: int):
    custom_message = room_messages.get(room_no, "Have a beautiful stay.")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"http://localhost:8000/pms/room-info/{room_no}")
            data     = response.json()
            return {"name": data.get("name", "Guest"), "message": custom_message}
    except Exception as e:
        print("ERROR:", e)
        return {"name": "Guest", "message": custom_message}