"""
app/main.py
Application entry point — only app setup, middleware, and router registration.
All business logic lives in the individual *_routes.py modules.
"""

import time
import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from .database import SessionLocal, engine
from . import models
from .models import Template

# ── existing routers (already split before this refactor) ──────────────────
from .booking_routes import router as booking_router
from .dashboard      import router as dashboard_router

# ── routers ────────────────────────────────────────────────────────────────
from .auth_routes     import router as auth_router
from .tv_routes       import router as tv_router
from .theme_routes    import router as theme_router
from .guest_routes    import router as guest_router    # guests + groups
from .activity_routes import router as activity_router
from .service_routes  import router as service_router  # services + food + spa + bar + dine + entertainment + room_services + gallery


# =============================================================================
# Middleware
# =============================================================================

class ServerTimingMiddleware(BaseHTTPMiddleware):
    """Adds Server-Timing header to every response for latency visibility."""
    async def dispatch(self, request: Request, call_next):
        start       = time.perf_counter()
        response    = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["Server-Timing"] = f'app;desc="Server";dur={duration_ms:.2f}'
        return response


# =============================================================================
# App creation
# =============================================================================

app = FastAPI()

app.add_middleware(SessionMiddleware, secret_key="b755357017fd3100fca04f7955592dda46c2e78415ab769562ba6f272fe56d6a")
app.add_middleware(ServerTimingMiddleware)


# =============================================================================
# DB bootstrap (create tables + safe migrations)
# =============================================================================

models.Base.metadata.create_all(bind=engine)

with engine.connect() as _conn:
    for _sql in [
        "ALTER TABLE orders ADD COLUMN order_type VARCHAR(20) DEFAULT 'food'",
        "ALTER TABLE spa_bookings ADD COLUMN price INT DEFAULT 0",
        "ALTER TABLE guests ADD COLUMN meal_plan VARCHAR(10) DEFAULT NULL",
    ]:
        try:
            _conn.execute(text(_sql))
            _conn.commit()
        except Exception:
            pass  # column already exists — safe to ignore


# =============================================================================
# Static files & templates
# =============================================================================

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# =============================================================================
# Register all routers
# =============================================================================

app.include_router(booking_router)    # /api/order, /api/spa-booking, etc.
app.include_router(dashboard_router)  # PMS sync, dashboard data

app.include_router(auth_router)       # /api/admin/login|logout|session
app.include_router(tv_router)         # /admin/tv-data, /ws/tv-status, bind/unbind
app.include_router(theme_router)      # /themes, /api/current-theme
app.include_router(guest_router)      # /admin/guests, /admin/groups, /delete-guest, /api/guests/current, /api/groups/current
app.include_router(activity_router)   # /admin/activities, /api/activities
app.include_router(service_router)    # /admin/services|food|spa|bar|dine|entertainment|room-services|gallery + all /api/* variants


# =============================================================================
# Remaining page routes that rely on dashboard template + active-theme logic
# =============================================================================

from datetime import date as _date

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    db    = SessionLocal()
    today = _date.today()

    active_guests = db.query(models.Guest).filter(
        models.Guest.check_in  <= today,
        models.Guest.check_out >= today
    ).all()
    total_active = len(active_guests)

    db.execute(text("UPDATE templates SET status='inactive' WHERE end_date < :today"), {"today": today})
    db.commit()

    active_theme = db.query(Template).filter(
        Template.status     == "active",
        Template.start_date <= today,
        Template.end_date   >= today
    ).first()
    db.close()

    return templates.TemplateResponse("dashboard.html", {
        "request":            request,
        "page":               "dashboard",
        "total_active":       total_active,
        "active_theme_name":  active_theme.name       if active_theme else None,
        "active_theme_start": active_theme.start_date if active_theme else None,
        "active_theme_end":   active_theme.end_date   if active_theme else None,
    })


@app.get("/admin/bookings", response_class=HTMLResponse)
def bookings_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "page": "bookings"})