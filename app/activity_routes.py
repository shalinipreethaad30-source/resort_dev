"""
app/activity_routes.py
Activity and announcement management.
"""

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .database import SessionLocal
from . import models

router    = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------

@router.get("/admin/activities", response_class=HTMLResponse)
def activities_page(request: Request):
    db         = SessionLocal()
    activities = db.query(models.Activity).all()
    db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "page": "activities", "activities": activities}
    )


# ---------------------------------------------------------------------------
# Add activity
# ---------------------------------------------------------------------------

@router.post("/admin/activities/add")
def add_activity(
    title:           str = Form(...),
    slot1:           str = Form(""),
    slot1_end:       str = Form(""),
    is_announcement: str = Form("off")
):
    is_ann    = (is_announcement == "on")
    time_slot = None
    if not is_ann and slot1 and slot1_end:
        time_slot = f"{slot1} - {slot1_end}"

    db = SessionLocal()
    db.add(models.Activity(title=title, time_slot=time_slot, is_announcement=is_ann))
    db.commit()
    db.close()
    return RedirectResponse("/admin/activities", status_code=303)


# ---------------------------------------------------------------------------
# Delete activity
# ---------------------------------------------------------------------------

@router.delete("/admin/activities/{activity_id}")
def delete_activity(activity_id: int):
    db       = SessionLocal()
    activity = db.query(models.Activity).filter(models.Activity.id == activity_id).first()
    if activity:
        db.delete(activity)
        db.commit()
    db.close()
    return {"message": "Deleted"}


# ---------------------------------------------------------------------------
# API: activities list (TV page)
# ---------------------------------------------------------------------------

@router.get("/api/activities")
def get_activities():
    db         = SessionLocal()
    activities = db.query(models.Activity).all()
    db.close()
    return [
        {"id": a.id, "title": a.title, "time_slot": a.time_slot, "is_announcement": a.is_announcement}
        for a in activities
    ]