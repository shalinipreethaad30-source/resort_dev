from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, Depends, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from datetime import date, datetime
from pydantic import BaseModel
from typing import Optional, List
import subprocess
import asyncio
import os
import re
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
from .database import SessionLocal, engine, get_db
from . import models
from app.models import TV
from .models import Template, Service, FoodItem, SpaItem, BarItem, DineItem, EntertainmentItem
from .booking_routes import router as booking_router   # NEW: booking/order endpoints
import httpx 
from .models import GroupBooking  
from fastapi.responses import JSONResponse   
from app.dashboard import router as dashboard_router                                      # NEW: used by booking_routes for PMS sync


models.Base.metadata.create_all(bind=engine)


# Auto-migrate missing columns (runs safely on every startup)
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
            pass   # column already exists — safe to ignore


app = FastAPI()
app.include_router(booking_router)  
app.include_router(dashboard_router) # NEW: registers all /api/order, /api/spa-booking etc.

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

UPLOAD_DIR = "static/images"


# =========================
# TITLE-BASED FILENAME HELPER
# =========================

def title_filename(title: str, original_filename: str) -> str:
    """Return a clean filename based on the item title, e.g. 'masala_dosa.jpg'"""
    ext = os.path.splitext(original_filename)[1].lower() or ".jpg"
    safe = re.sub(r"[^\w\s-]", "", title.strip().lower())
    safe = re.sub(r"[\s_]+", "_", safe)
    safe = safe.strip("_") or "item"
    return safe + ext


# =========================
# WEBSOCKET CONNECTION MANAGER
# =========================

class ConnectionManager:
    def __init__(self):
        self.active_connections = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data):
        for connection in self.active_connections:
            await connection.send_json(data)


manager = ConnectionManager()


# =========================
# CHECK TV STATUS
# =========================

def check_tv_status(ip_address):
    try:
        param = "-n" if os.name == "nt" else "-c"
        result = subprocess.run(
            ["ping", param, "1", ip_address],
            capture_output=True,
            text=True
        )
        if "TTL=" in result.stdout or "ttl=" in result.stdout:
            return "ONLINE"
        else:
            return "OFFLINE"
    except Exception:
        return "OFFLINE"


# =========================
# ROOM MESSAGE STORAGE
# =========================

room_messages = {}


# =========================
# ADMIN DASHBOARD
# =========================
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    db = SessionLocal()
    today = date.today()

    active_guests = db.query(models.Guest).filter(
        models.Guest.check_in <= today,
        models.Guest.check_out >= today
    ).all()

    total_active = len(active_guests)

    # Auto-deactivate expired themes first
    db.execute(text("UPDATE templates SET status='inactive' WHERE end_date < :today"), {"today": today})
    db.commit()

    active_theme = db.query(Template).filter(
        Template.status == "active",
        Template.start_date <= today,
        Template.end_date >= today
    ).first()

    db.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page": "dashboard",
            "total_active": total_active,
            "active_theme_name": active_theme.name if active_theme else None,
            "active_theme_start": active_theme.start_date if active_theme else None,
            "active_theme_end": active_theme.end_date if active_theme else None
        }
    )


# =========================
# BOOKINGS MANAGEMENT PAGE
# =========================

@app.get("/admin/bookings", response_class=HTMLResponse)
def bookings_page(request: Request):
    """Admin bookings management — loads data via /api/admin/bookings JS fetch."""
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page": "bookings"
        }
    )


# =========================
# SEND ROOM MESSAGE
# =========================

@app.post("/send-message")
def send_message(room_no: int = Form(...), message: str = Form(...)):
    room_messages[room_no] = message
    return RedirectResponse("/admin/guests", status_code=303)


# =========================
# LIVE TV SAMPLE VIDEO
# =========================

@app.get("/live-tv", response_class=HTMLResponse)
def live_tv(request: Request):
    return templates.TemplateResponse("live_tv.html", {"request": request})


# =========================
# TV DATA PAGE
# =========================

@app.get("/admin/tv-data", response_class=HTMLResponse)
def tv_data(request: Request):
    db = SessionLocal()
    tvs = db.query(TV).all()
    db.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page": "tv_data",
            "tvs": tvs
        }
    )


# =========================
# ADD TV
# =========================

@app.post("/add-tv")
def add_tv(
    room_no: str = Form(...),
    mac_address: str = Form(...),
    ip_address: str = Form(...)
):
    db = SessionLocal()

    new_tv = TV(
        room_no=room_no,
        mac_address=mac_address,
        ip_address=ip_address,
        status="UNKNOWN"
    )

    db.add(new_tv)
    db.commit()
    db.close()

    return RedirectResponse("/admin/tv-data", status_code=303)


# =========================
# WEBSOCKET FOR REALTIME TV STATUS
# =========================

@app.websocket("/ws/tv-status")
async def websocket_tv_status(websocket: WebSocket):
    await websocket.accept()

    while True:
        db = SessionLocal()
        tvs = db.query(models.TV).all()
        data = []

        for tv in tvs:
            status = check_tv_status(tv.ip_address)
            tv.status = status
            data.append({
                "room_no": tv.room_no,
                "mac_address": tv.mac_address,
                "ip_address": tv.ip_address,
                "status": status,
                "bound": tv.bound
            })

        db.commit()
        db.close()

        await websocket.send_json(data)
        await asyncio.sleep(5)


# =========================
# DELETE DEVICE
# =========================

@app.delete("/delete_device/{room}")
def delete_device_api(room: str):
    db = SessionLocal()
    device = db.query(TV).filter(TV.room_no == room).first()

    if not device:
        db.close()
        return {"message": "Room not found"}

    db.delete(device)
    db.commit()
    db.close()
    return {"message": "Device deleted successfully"}


# =========================
# BIND / UNBIND DEVICE
# =========================

@app.post("/bind_device")
async def bind_device(request: Request):
    data = await request.json()
    room = str(data.get("room"))
    db: Session = SessionLocal()

    try:
        tv = db.query(TV).filter(TV.room_no == room).first()

        if not tv:
            return {"status": "error", "message": "Room not found"}
        if tv.bound:
            return {"status": "warning", "message": "Device already bound"}

        tv.bound     = True
        tv.bound_ip  = tv.ip_address
        tv.bound_mac = tv.mac_address
        db.commit()

        return {
            "status": "success",
            "message": "Device bound successfully",
            "room": tv.room_no,
            "bound": tv.bound
        }
    finally:
        db.close()


@app.post("/unbind_device")
async def unbind_device(request: Request):
    data = await request.json()
    room = str(data.get("room"))
    db: Session = SessionLocal()

    try:
        tv = db.query(TV).filter(TV.room_no == room).first()

        if not tv:
            return {"status": "error", "message": "Room not found"}
        if not tv.bound:
            return {"status": "warning", "message": "Device already unbound"}

        tv.bound     = False
        tv.bound_ip  = None
        tv.bound_mac = None
        db.commit()

        return {
            "status": "success",
            "message": "Device unbound successfully",
            "room": tv.room_no,
            "bound": tv.bound
        }
    finally:
        db.close()


@app.get("/binding_status/{room}")
def binding_status(room: str):
    db: Session = SessionLocal()

    try:
        device = db.query(TV).filter(TV.room_no == room).first()

        if not device:
            return {"status": "error", "message": "Room not found"}

        return {
            "room": device.room_no,
            "bound": device.bound,
            "bound_ip": device.bound_ip,
            "bound_mac": device.bound_mac
        }
    finally:
        db.close()


# =========================
# THEMES
# =========================

@app.get("/themes", response_class=HTMLResponse)
def theme_page(request: Request):
    db = SessionLocal()

    themes = db.query(Template).filter(Template.name != "default").all()

    active_theme = db.execute(
        text("SELECT id FROM templates WHERE status='active' LIMIT 1")
    ).fetchone()

    active_theme_id = active_theme[0] if active_theme else None
    db.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "page": "themes",
            "themes": themes,
            "active_theme_id": active_theme_id
        }
    )


@app.get("/apply_theme/{theme_id}")
def apply_theme_by_id(theme_id: int):
    db = SessionLocal()
    db.execute(text("UPDATE templates SET status='inactive'"))
    db.execute(
        text("UPDATE templates SET status='active' WHERE id=:id"),
        {"id": theme_id}
    )
    db.commit()
    db.close()
    return RedirectResponse(url="/themes", status_code=303)


@app.post("/add_template")
async def add_template(request: Request):
    data = await request.json()
    db = SessionLocal()

    template = Template(
        name=data.get("name"),
        theme_image=data.get("image"),
        start_date=data.get("start_date"),
        end_date=data.get("end_date")
    )

    db.add(template)
    db.commit()
    db.close()
    return {"message": "Template added successfully"}


@app.get("/active_theme")
def active_theme():
    db = SessionLocal()
    today = date.today()

    theme = db.query(Template).filter(
        Template.start_date <= today,
        Template.end_date >= today
    ).first()

     # Auto-deactivate expired themes
    if not theme:
        db.execute(text("UPDATE templates SET status='inactive' WHERE end_date < :today"),
                   {"today": today})
        db.commit()

    db.close()

    if theme:
        return {"theme": theme.theme_image}
    return {"theme": "default.html"}


@app.post("/apply_theme")
def apply_theme(
    theme_name: str = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...)
):
    db = SessionLocal()

    db.execute(text("""
        UPDATE templates
        SET start_date = NULL,
            end_date = NULL
    """))

    db.execute(text("""
        UPDATE templates
        SET start_date = :start_date,
            end_date = :end_date
        WHERE theme_image = :theme_name
    """), {
        "start_date": start_date,
        "end_date": end_date,
        "theme_name": theme_name
    })

    db.commit()
    db.close()
    return RedirectResponse("/themes", status_code=303)


@app.post("/schedule_theme/{theme_id}")
def schedule_theme(
    theme_id: int,
    start_date: str = Form(...),
    end_date: str = Form(...)
):
    db = SessionLocal()

    db.execute(text("UPDATE templates SET status='inactive'"))

    db.execute(text("""
        UPDATE templates
        SET start_date=:start_date,
            end_date=:end_date,
            status='active'
        WHERE id=:theme_id
    """), {
        "start_date": start_date,
        "end_date": end_date,
        "theme_id": theme_id
    })

    db.commit()
    db.close()
    return RedirectResponse("/themes", status_code=303)


@app.get("/api/current-theme")
def get_current_theme():
    db = SessionLocal()
    today = date.today()

    theme = db.execute(text("""
        SELECT theme_image
        FROM templates
        WHERE status='active'
        AND start_date <= :today
        AND end_date >= :today
        LIMIT 1
    """), {"today": today}).fetchone()

    db.close()

    if theme:
        return {"template": theme[0]}


    return {"template": "default.html"}


@app.get("/theme/{template_name}")
def load_theme(request: Request, template_name: str, room_no: int = 0):
    db = SessionLocal()
    today = date.today()

    guest = None
    message = None

    if room_no:
        guest = db.query(models.Guest).filter(
            models.Guest.room_no == room_no,
            models.Guest.check_in <= today,
            models.Guest.check_out >= today
        ).first()
        message = room_messages.get(room_no)

    db.close()

    return templates.TemplateResponse(
        template_name,
        {
            "request": request,
            "guest": guest,
            "room_no": room_no,
            "custom_message": message
        }
    )


@app.get("/tv/{room_no}", response_class=HTMLResponse)
def tv_page(request: Request, room_no: int):
    return templates.TemplateResponse(
        "tv.html",
        {
            "request": request,
            "room_no": room_no
        }
    )


@app.post("/discard_theme/{theme_id}")
def discard_theme(theme_id: int):
    db = SessionLocal()
    db.execute(text("""
        UPDATE templates
        SET status='inactive',
            start_date=NULL,
            end_date=NULL
        WHERE id=:theme_id
    """), {"theme_id": theme_id})
    db.commit()
    db.close()
    return RedirectResponse("/themes", status_code=303)


@app.get("/api/room-data/{room_no}")
async def get_room_data(room_no: int):
    custom_message = room_messages.get(room_no, "Have a beautiful stay.")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"http://localhost:8000/pms/room-info/{room_no}"
            )
            data = response.json()
            return {
                "name": data.get("name", "Guest"),
                "message": custom_message
            }
    except Exception as e:
        print("ERROR:", e)
        return {"name": "Guest", "message": custom_message}  # ← always use room_messages


# =========================
# ACTIVITIES PAGE (ADMIN)
# =========================

@app.get("/admin/activities", response_class=HTMLResponse)
def activities_page(request: Request):
    db = SessionLocal()
    activities = db.query(models.Activity).all()
    db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "page": "activities", "activities": activities}
    )


@app.post("/admin/activities/add")
def add_activity(
    title: str = Form(...),
    slot1: str = Form(""),
    slot1_end: str = Form(""),
    is_announcement: str = Form("off")
):
    db = SessionLocal()

    def to12hr(t):
        if not t:
            return ""
        h, m = t.split(":")
        h = int(h)
        ampm = "PM" if h >= 12 else "AM"
        h = h % 12 or 12
        return f"{h}:{m} {ampm}"

    is_ann = (is_announcement == "on")
    time_slot = None
    if not is_ann and slot1 and slot1_end:
        time_slot = f"{slot1} - {slot1_end}"

    activity = models.Activity(
        title=title,
        time_slot=time_slot,
        is_announcement=is_ann
    )
    db.add(activity)
    db.commit()
    db.close()
    return RedirectResponse("/admin/activities", status_code=303)


@app.delete("/admin/activities/{activity_id}")
def delete_activity(activity_id: int):
    db = SessionLocal()
    activity = db.query(models.Activity).filter(models.Activity.id == activity_id).first()
    if activity:
        db.delete(activity)
        db.commit()
    db.close()
    return {"message": "Deleted"}


# /api/activity-booking is now handled by booking_routes.py


# =========================
# API FOR TV PAGE (ACTIVITIES)
# =========================

@app.get("/api/activities")
def get_activities():
    db = SessionLocal()
    activities = db.query(models.Activity).all()
    db.close()
    return [
        {
            "id": a.id,
            "title": a.title,
            "time_slot": a.time_slot,
            "is_announcement": a.is_announcement
        }
        for a in activities
    ]


# =========================
# SERVICES PAGE (ADMIN)
# =========================

@app.get("/admin/services", response_class=HTMLResponse)
def services_page(request: Request):
    db = SessionLocal()
    services = db.query(models.Service).all()
    db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "page": "services", "services": services}
    )


@app.post("/admin/services/add")
async def add_service(
    title: str = Form(...),
    image: Optional[UploadFile] = File(None)
):
    if not image or not image.filename:
        return RedirectResponse("/admin/services?error=no_image", status_code=303)

    db = SessionLocal()
    service_dir = os.path.join(UPLOAD_DIR, "services")
    os.makedirs(service_dir, exist_ok=True)

    filename  = title_filename(title, image.filename)
    file_path = os.path.join(service_dir, filename)
    with open(file_path, "wb") as f:
        f.write(await image.read())

    image_url = f"/static/images/services/{filename}"

    service = models.Service(title=title, image_url=image_url)
    db.add(service)
    db.commit()
    db.close()
    return RedirectResponse("/admin/services", status_code=303)


@app.delete("/admin/services/{service_id}")
def delete_service(service_id: int):
    db = SessionLocal()
    service = db.query(models.Service).filter(models.Service.id == service_id).first()
    if service:
        db.delete(service)
        db.commit()
    db.close()
    return {"message": "Deleted"}


# =========================
# API FOR TV PAGE (SERVICES)
# =========================

@app.get("/api/services")
def get_services():
    db = SessionLocal()
    services = db.query(models.Service).all()
    db.close()
    return [
        {
            "id": s.id,
            "title": s.title,
            "image_url": s.image_url
        }
        for s in services
    ]


# =========================
# FOOD PAGE (TV)
# =========================

@app.get("/food-page", response_class=HTMLResponse)
def food_page(request: Request):
    return templates.TemplateResponse("food_page.html", {"request": request})


@app.get("/food-menu", response_class=HTMLResponse)
def food_menu(request: Request, category: str = "breakfast"):
    db = SessionLocal()
    items = db.query(models.FoodItem).filter(models.FoodItem.category == category).all()
    db.close()
    return templates.TemplateResponse("food_menu.html", {
        "request": request,
        "category": category,
        "items": items
    })


# =========================
# FOOD ADMIN PAGE
# =========================

@app.get("/admin/food", response_class=HTMLResponse)
def food_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.FoodItem).all()
    else:
        items = db.query(models.FoodItem).filter(models.FoodItem.category == category).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "food",
        "items": items,
        "selected_category": category
    })


@app.post("/admin/food/add")
async def add_food_item(
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(...),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    food_dir = os.path.join(UPLOAD_DIR, "services", "food_menu")
    os.makedirs(food_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(food_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())

        image_url = f"/static/images/services/food_menu/{filename}"

    item = models.FoodItem(title=title, category=category, price=price, image_url=image_url)
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/food?category={category}", status_code=303)


@app.delete("/admin/food/{item_id}")
def delete_food_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.FoodItem).filter(models.FoodItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/food/edit/{item_id}")
async def edit_food_item(
    item_id: int,
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(...),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    item = db.query(models.FoodItem).filter(models.FoodItem.id == item_id).first()

    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title    = title
    item.category = category
    item.price    = price

    if image and image.filename:
        food_dir = os.path.join(UPLOAD_DIR, "services", "food_menu")
        os.makedirs(food_dir, exist_ok=True)

        filename  = title_filename(title, image.filename)
        file_path = os.path.join(food_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/food_menu/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


# =========================
# SPA & WELLNESS PAGE (ADMIN)
# =========================

SPA_CATEGORIES = ["massage", "facial", "body", "other"]

@app.get("/admin/spa", response_class=HTMLResponse)
def spa_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.SpaItem).all()
    else:
        items = db.query(models.SpaItem).filter(models.SpaItem.category == category).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "spa",
        "items": items,
        "selected_category": category,
        "spa_categories": SPA_CATEGORIES
    })


@app.post("/admin/spa/add")
async def add_spa_item(
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(0),
    slot1: str = Form(...),
    slot2: str = Form(""),
    slot3: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    spa_dir = os.path.join(UPLOAD_DIR, "services", "spa")
    os.makedirs(spa_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(spa_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/spa/{filename}"

    item = models.SpaItem(
        title=title, category=category,
        price=price,
        slot1=slot1,
        slot2=slot2 or None,
        slot3=slot3 or None,
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/spa?category={category}", status_code=303)


@app.delete("/admin/spa/{item_id}")
def delete_spa_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.SpaItem).filter(models.SpaItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/spa/edit/{item_id}")
async def edit_spa_item(
    item_id: int,
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(0),
    slot1: str = Form(...),
    slot2: str = Form(""),
    slot3: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    item = db.query(models.SpaItem).filter(models.SpaItem.id == item_id).first()

    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title    = title
    item.category = category
    item.price    = price
    item.slot1    = slot1
    item.slot2    = slot2 or None
    item.slot3    = slot3 or None

    if image and image.filename:
        spa_dir = os.path.join(UPLOAD_DIR, "services", "spa")
        os.makedirs(spa_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(spa_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/spa/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


# /api/spa-booking is now handled by booking_routes.py (saves to DB with price)


@app.get("/api/spa-items")
def api_spa_items(category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.SpaItem).all()
    else:
        items = db.query(models.SpaItem).filter(models.SpaItem.category == category).all()
    db.close()
    return [
        {
            "id": i.id,
            "title": i.title,
            "category": i.category,
            "price": i.price if hasattr(i, 'price') else 0,
            "slot1": i.slot1,
            "slot2": i.slot2,
            "slot3": i.slot3,
            "image_url": i.image_url
        }
        for i in items
    ]


@app.get("/api/food-items")
def api_food_items(category: str = "breakfast"):
    db = SessionLocal()
    items = db.query(models.FoodItem).filter(models.FoodItem.category == category).all()
    db.close()
    return [{"id": i.id, "title": i.title, "price": i.price, "image_url": i.image_url} for i in items]


# =========================
# CATEGORY COVER IMAGES
# =========================

FOOD_CATEGORIES_LIST = ["breakfast", "lunch", "dinner", "snacks", "desserts", "drinks"]
BAR_CATEGORIES_LIST  = ["alcoholic", "non-alcoholic"]

def _find_cover(cover_dir: str, category: str) -> Optional[str]:
    """Return the URL of an existing cover file for this category, or None."""
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        p = os.path.join(cover_dir, category + ext)
        if os.path.exists(p):
            return p
    return None


# ── FOOD ──────────────────────────────────

@app.post("/admin/food/category-cover/{category}")
async def food_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "food_menu", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{category}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/food_menu/covers/{category}{ext}"}


@app.get("/api/category-covers/food")
def food_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "food_menu", "covers")
    result = {}
    for cat in FOOD_CATEGORIES_LIST:
        path = _find_cover(cover_dir, cat)
        if path:
            ext = os.path.splitext(path)[1]
            result[cat] = f"/static/images/services/food_menu/covers/{cat}{ext}"
        else:
            result[cat] = None
    return result


# ── SPA ───────────────────────────────────

@app.post("/admin/spa/category-cover/{category}")
async def spa_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "spa", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{category}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/spa/covers/{category}{ext}"}


@app.get("/api/category-covers/spa")
def spa_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "spa", "covers")
    result = {}
    for cat in SPA_CATEGORIES:
        path = _find_cover(cover_dir, cat)
        if path:
            ext = os.path.splitext(path)[1]
            result[cat] = f"/static/images/services/spa/covers/{cat}{ext}"
        else:
            result[cat] = None
    return result


# ── BAR ───────────────────────────────────

@app.post("/admin/bar/category-cover/{category}")
async def bar_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "bar", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    safe_cat  = category.replace(" ", "_")
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{safe_cat}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/bar/covers/{safe_cat}{ext}"}


@app.get("/api/category-covers/bar")
def bar_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "bar", "covers")
    result = {}
    for cat in BAR_CATEGORIES_LIST:
        safe_cat = cat.replace(" ", "_")
        path = _find_cover(cover_dir, safe_cat)
        if path:
            ext = os.path.splitext(path)[1]
            result[cat] = f"/static/images/services/bar/covers/{safe_cat}{ext}"
        else:
            result[cat] = None
    return result


# =========================
# BAR PAGE (ADMIN)
# =========================

BAR_CATEGORIES = ["alcoholic", "non-alcoholic"]

@app.get("/admin/bar", response_class=HTMLResponse)
def bar_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.BarItem).all()
    else:
        items = db.query(models.BarItem).filter(models.BarItem.category == category).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "bar",
        "items": items,
        "selected_category": category,
        "bar_categories": BAR_CATEGORIES
    })


@app.post("/admin/bar/add")
async def add_bar_item(
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(...),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    bar_dir = os.path.join(UPLOAD_DIR, "services", "bar")
    os.makedirs(bar_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(bar_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/bar/{filename}"

    item = models.BarItem(title=title, category=category, price=price, image_url=image_url)
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/bar?category={category}", status_code=303)


@app.delete("/admin/bar/{item_id}")
def delete_bar_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.BarItem).filter(models.BarItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/bar/edit/{item_id}")
async def edit_bar_item(
    item_id: int,
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(...),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    item = db.query(models.BarItem).filter(models.BarItem.id == item_id).first()

    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title    = title
    item.category = category
    item.price    = price

    if image and image.filename:
        bar_dir = os.path.join(UPLOAD_DIR, "services", "bar")
        os.makedirs(bar_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(bar_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/bar/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@app.get("/api/bar-items")
def api_bar_items(category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.BarItem).all()
    else:
        items = db.query(models.BarItem).filter(models.BarItem.category == category).all()
    db.close()
    return [
        {"id": i.id, "title": i.title, "category": i.category,
         "price": i.price, "image_url": i.image_url}
        for i in items
    ]


# =========================
# DINE-IN PAGE (ADMIN)
# =========================

DINE_OCCASIONS = ["romantic", "birthday", "anniversary", "business", "family"]

@app.get("/admin/dine", response_class=HTMLResponse)
def dine_admin(request: Request, occasion: str = "all"):
    db = SessionLocal()
    if occasion == "all":
        items = db.query(models.DineItem).all()
    else:
        items = db.query(models.DineItem).filter(models.DineItem.occasion == occasion).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "dine",
        "items": items,
        "selected_occasion": occasion,
        "dine_occasions": DINE_OCCASIONS
    })


@app.post("/admin/dine/add")
async def add_dine_item(
    title: str = Form(...),
    occasion: str = Form(...),
    description: str = Form(""),
    slot1: str = Form(""),
    slot2: str = Form(""),
    slot3: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    dine_dir = os.path.join(UPLOAD_DIR, "services", "dine")
    os.makedirs(dine_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(dine_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/dine/{filename}"

    item = models.DineItem(
        title=title, occasion=occasion,
        description=description or None,
        slot1=slot1 or None, slot2=slot2 or None, slot3=slot3 or None,
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/dine?occasion={occasion}", status_code=303)


@app.delete("/admin/dine/{item_id}")
def delete_dine_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.DineItem).filter(models.DineItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/dine/edit/{item_id}")
async def edit_dine_item(
    item_id: int,
    title: str = Form(...),
    occasion: str = Form(...),
    description: str = Form(""),
    slot1: str = Form(""),
    slot2: str = Form(""),
    slot3: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    item = db.query(models.DineItem).filter(models.DineItem.id == item_id).first()
    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title       = title
    item.occasion    = occasion
    item.description = description or None
    item.slot1       = slot1 or None
    item.slot2       = slot2 or None
    item.slot3       = slot3 or None

    if image and image.filename:
        dine_dir = os.path.join(UPLOAD_DIR, "services", "dine")
        os.makedirs(dine_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(dine_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/dine/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@app.get("/api/dine-items")
def api_dine_items(occasion: str = "all"):
    db = SessionLocal()
    if occasion == "all":
        items = db.query(models.DineItem).all()
    else:
        items = db.query(models.DineItem).filter(models.DineItem.occasion == occasion).all()
    db.close()
    return [
        {
            "id": i.id,
            "title": i.title,
            "occasion": i.occasion,
            "description": i.description,
            "slot1": i.slot1,
            "slot2": i.slot2,
            "slot3": i.slot3,
            "image_url": i.image_url
        }
        for i in items
    ]


# /api/dine-booking is now handled by booking_routes.py (saves to DB)


# ── DINE CATEGORY COVER IMAGES ────────────────────────────────

@app.post("/admin/dine/category-cover/{occasion}")
async def dine_category_cover(occasion: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "dine", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{occasion}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/dine/covers/{occasion}{ext}"}


@app.get("/api/category-covers/dine")
def dine_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "dine", "covers")
    result = {}
    for occ in DINE_OCCASIONS:
        path = _find_cover(cover_dir, occ)
        if path:
            ext = os.path.splitext(path)[1]
            result[occ] = f"/static/images/services/dine/covers/{occ}{ext}"
        else:
            result[occ] = None
    return result


# =========================
# ENTERTAINMENT PAGE (ADMIN)
# =========================

ENTERTAINMENT_CATEGORIES = ["indoor", "outdoor", "water", "kids", "night"]
ENTERTAINMENT_CAT_ICONS  = {
    "indoor": "🎮", "outdoor": "⛷️", "water": "🏊", "kids": "🎠", "night": "🌙"
}

@app.get("/admin/entertainment", response_class=HTMLResponse)
def entertainment_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.EntertainmentItem).all()
    else:
        items = db.query(models.EntertainmentItem).filter(
            models.EntertainmentItem.category == category
        ).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "entertainment",
        "items": items,
        "selected_category": category,
        "entertainment_categories": ENTERTAINMENT_CATEGORIES
    })


@app.post("/admin/entertainment/add")
async def add_entertainment_item(
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(0),
    venue: str = Form(""),
    slot1: str = Form(""),
    slot2: str = Form(""),
    slot3: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    ent_dir = os.path.join(UPLOAD_DIR, "services", "entertainment")
    os.makedirs(ent_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(ent_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/entertainment/{filename}"

    item = models.EntertainmentItem(
        title=title, category=category,
        price=price,
        venue=venue or None,
        slot1=slot1 or None,
        slot2=slot2 or None,
        slot3=slot3 or None,
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/entertainment?category={category}", status_code=303)


@app.delete("/admin/entertainment/{item_id}")
def delete_entertainment_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.EntertainmentItem).filter(models.EntertainmentItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/entertainment/edit/{item_id}")
async def edit_entertainment_item(
    item_id: int,
    title: str = Form(...),
    category: str = Form(...),
    price: int = Form(0),
    venue: str = Form(""),
    slot1: str = Form(""),
    slot2: str = Form(""),
    slot3: str = Form(""),
    image: Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    item = db.query(models.EntertainmentItem).filter(models.EntertainmentItem.id == item_id).first()

    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title    = title
    item.category = category
    item.price    = price
    item.venue    = venue or None
    item.slot1    = slot1 or None
    item.slot2    = slot2 or None
    item.slot3    = slot3 or None

    if image and image.filename:
        ent_dir = os.path.join(UPLOAD_DIR, "services", "entertainment")
        os.makedirs(ent_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(ent_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/entertainment/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@app.get("/api/entertainment-items")
def api_entertainment_items(category: str = "all"):
    db = SessionLocal()
    if category == "all":
        items = db.query(models.EntertainmentItem).all()
    else:
        items = db.query(models.EntertainmentItem).filter(
            models.EntertainmentItem.category == category
        ).all()
    db.close()
    return [
        {
            "id": i.id,
            "title": i.title,
            "category": i.category,
            "price": i.price,
            "venue": i.venue,
            "slot1": i.slot1,
            "slot2": i.slot2,
            "slot3": i.slot3,
            "image_url": i.image_url
        }
        for i in items
    ]


# /api/entertainment-booking is now handled by booking_routes.py


# ── ENTERTAINMENT CATEGORY COVER IMAGES ────────────────────────────────

@app.post("/admin/entertainment/category-cover/{category}")
async def entertainment_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "entertainment", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{category}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/entertainment/covers/{category}{ext}"}


@app.get("/api/category-covers/entertainment")
def entertainment_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "entertainment", "covers")
    result = {}
    for cat in ENTERTAINMENT_CATEGORIES:
        path = _find_cover(cover_dir, cat)
        if path:
            ext = os.path.splitext(path)[1]
            result[cat] = f"/static/images/services/entertainment/covers/{cat}{ext}"
        else:
            result[cat] = None
    return result


# =========================
# ROOM SERVICES (ADMIN)
# =========================

ROOM_SERVICE_ICONS = [
    "🍽️", "🛎️", "🧹", "🧺", "🧴",
    "🧖", "🚗", "📺", "📞", "🛌"
]


@app.get("/admin/room-services", response_class=HTMLResponse)
def room_services_admin(request: Request):
    db = SessionLocal()
    items    = db.query(models.RoomServiceItem).all()
    requests = []
    if hasattr(models, 'RoomServiceRequest'):
        requests = db.query(models.RoomServiceRequest).order_by(
            models.RoomServiceRequest.created_at.desc()
        ).limit(50).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "room_services",
        "items": items,
        "requests": requests,
        "rs_icons": ROOM_SERVICE_ICONS
    })


@app.post("/admin/room-services/add")
async def add_room_service_item(
    title:       str           = Form(...),
    description: str           = Form(""),
    icon:        str           = Form("🧹"),
    image:       Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    rs_dir = os.path.join(UPLOAD_DIR, "services", "room_services")
    os.makedirs(rs_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(rs_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/room_services/{filename}"

    item = models.RoomServiceItem(
        title=title,
        description=description or None,
        icon=icon or "🧹",
        image_url=image_url,
        is_active=True
    )
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse("/admin/room-services", status_code=303)


@app.delete("/admin/room-services/{item_id}")
def delete_room_service_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/room-services/edit/{item_id}")
async def edit_room_service_item(
    item_id:     int,
    title:       str           = Form(...),
    description: str           = Form(""),
    icon:        str           = Form("🧹"),
    image:       Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    item = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.id == item_id).first()
    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title       = title
    item.description = description or None
    item.icon        = icon or "🧹"

    if image and image.filename:
        rs_dir = os.path.join(UPLOAD_DIR, "services", "room_services")
        os.makedirs(rs_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(rs_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/room_services/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@app.post("/admin/room-services/toggle/{item_id}")
def toggle_room_service_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.id == item_id).first()
    if item:
        item.is_active = not item.is_active
        db.commit()
    db.close()
    return {"message": "Toggled", "is_active": item.is_active if item else None}


# =========================
# ROOM SERVICE REQUEST (from TV page)
# =========================

@app.post("/api/room-service-request")
async def place_room_service_request(request: Request):
    """Receives a room service request from the TV page."""
    data          = await request.json()
    room_no       = data.get("room_no")
    service_id    = data.get("service_id")
    service_title = data.get("service_title")
    note          = data.get("note", "")

    db = SessionLocal()
    try:
        if hasattr(models, 'RoomServiceRequest'):
            req = models.RoomServiceRequest(
                room_no       = room_no,
                service_id    = service_id,
                service_title = service_title,
                note          = note or None,
                status        = "pending",
                created_at    = datetime.now()
            )
            db.add(req)
            db.commit()
        else:
            print(f"\n{'='*40}")
            print(f"ROOM SERVICE REQUEST — Room {room_no}")
            print(f"  Service : {service_title}")
            if note:
                print(f"  Note    : {note}")
            print(f"  Time    : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*40}\n")
    except Exception as e:
        print(f"Room service request save error: {e}")
    finally:
        db.close()

    return {"status": "success", "message": "Request received. Staff will be with you shortly."}


@app.post("/admin/room-services/request/{req_id}/status")
async def update_request_status(req_id: int, request: Request):
    data   = await request.json()
    status = data.get("status")
    db     = SessionLocal()
    try:
        if hasattr(models, 'RoomServiceRequest'):
            req = db.query(models.RoomServiceRequest).filter(
                models.RoomServiceRequest.id == req_id
            ).first()
            if req:
                req.status = status
                db.commit()
                return {"message": "Status updated", "status": status}
        return {"message": "Model not found"}
    finally:
        db.close()


# =========================
# API: ROOM SERVICE ITEMS (for TV page)
# =========================

@app.get("/api/room-service-items")
def api_room_service_items():
    db = SessionLocal()
    items = db.query(models.RoomServiceItem).filter(
        models.RoomServiceItem.is_active == True
    ).all()
    db.close()
    return [
        {
            "id":          i.id,
            "title":       i.title,
            "description": i.description,
            "icon":        i.icon,
            "image_url":   i.image_url
        }
        for i in items
    ]

# /api/order is now handled by booking_routes.py
# /api/spa-booking is now handled by booking_routes.py
# /api/dine-booking is now handled by booking_routes.py
# /api/entertainment-booking is now handled by booking_routes.py
# /api/activity-booking is now handled by booking_routes.py


# =========================
# GALLERY (ADMIN)
# =========================

@app.get("/admin/gallery", response_class=HTMLResponse)
def gallery_admin(request: Request):
    db = SessionLocal()
    items = db.query(models.GalleryItem).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "page": "gallery",
        "items": items
    })


@app.post("/admin/gallery/add")
async def add_gallery_item(
    title:       str                    = Form(...),
    description: str                    = Form(""),
    image:       Optional[UploadFile]   = File(None)
):
    db = SessionLocal()
    gallery_dir = os.path.join(UPLOAD_DIR, "services", "gallery")
    os.makedirs(gallery_dir, exist_ok=True)

    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(gallery_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/gallery/{filename}"

    item = models.GalleryItem(
        title=title,
        description=description or None,
        image_url=image_url
    )
    db.add(item)
    db.commit()
    db.close()
    return RedirectResponse("/admin/gallery", status_code=303)


@app.delete("/admin/gallery/{item_id}")
def delete_gallery_item(item_id: int):
    db = SessionLocal()
    item = db.query(models.GalleryItem).filter(models.GalleryItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@app.post("/admin/gallery/edit/{item_id}")
async def edit_gallery_item(
    item_id:     int,
    title:       str                    = Form(...),
    description: str                    = Form(""),
    image:       Optional[UploadFile]   = File(None)
):
    db = SessionLocal()
    item = db.query(models.GalleryItem).filter(models.GalleryItem.id == item_id).first()
    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title       = title
    item.description = description or None

    if image and image.filename:
        gallery_dir = os.path.join(UPLOAD_DIR, "services", "gallery")
        os.makedirs(gallery_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(gallery_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/gallery/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


# =========================
# API: GALLERY ITEMS (for TV page)
# =========================

@app.get("/api/gallery-items")
def api_gallery_items():
    db = SessionLocal()
    items = db.query(models.GalleryItem).all()
    db.close()
    return [
        {
            "id":          i.id,
            "title":       i.title,
            "description": i.description,
            "image_url":   i.image_url
        }
        for i in items
    ]

from datetime import date

@app.get("/admin/guests", response_class=HTMLResponse)
def guest_info(request: Request):
    db = SessionLocal()
    today = date.today()
    all_guests = db.query(models.Guest).all()
    
    current_guests = []
    checked_out_guests = []
    upcoming_guests = []

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
        "request": request,
        "page": "guests",
        "current_guests": current_guests,
        "checked_out_guests": checked_out_guests,
        "upcoming_guests": upcoming_guests,
    })

# =========================
# DELETE GUEST BY ROOM (REST-style)
# =========================

@app.delete("/admin/guests/{room_no}")
def delete_guest_by_id(room_no: int):
    db = SessionLocal()
    try:
        guest = db.query(models.Guest).filter(models.Guest.room_no == room_no).first()

        if not guest:
            return {"message": "Guest not found"}

        # ── Settle all pending bookings for this stay before deleting guest ──
        guest_name = guest.guest_name
        ci = guest.check_in
        if not isinstance(ci, datetime):
            ci = datetime.combine(ci, datetime.min.time())
        stay_start = ci

        for Model, time_col in [
            (models.Order,                "ordered_at"),
            (models.SpaBooking,           "booked_at"),
            (models.EntertainmentBooking, "booked_at"),
            (models.ActivityBooking,      "booked_at"),
            (models.DineBooking,          "booked_at"),
        ]:
            pending_records = db.query(Model).filter(
                Model.room_no == room_no,
                Model.guest_name == guest_name,
                getattr(Model, time_col) >= stay_start,
                Model.status == "pending"
            ).all()
            for r in pending_records:
                r.status = "confirmed"  # auto-confirm on checkout

        db.commit()
        # ─────────────────────────────────────────────────────────────────

        db.delete(guest)
        db.commit()
        return {"message": "Guest deleted successfully"}
    except Exception as e:
        db.rollback()
        return {"message": f"Error: {str(e)}"}
    finally:
        db.close()


# =========================
# DELETE GUEST (POST /delete-guest)
# Called by the frontend deleteGuest() JS function
# =========================

@app.post("/delete-guest")
async def delete_guest_post(request: Request):
    """
    Accepts: { "room_no": 101 }
    Deletes the currently active guest in that room and returns JSON.
    """
    db = SessionLocal()
    try:
        data    = await request.json()
        room_no = data.get("room_no")

        if room_no is None:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "room_no is required"}
            )

        today = date.today()

        # Find the active guest for this room (checked-in and not yet checked out)
        guest = (
            db.query(models.Guest)
            .filter(
                models.Guest.room_no == room_no,
                models.Guest.check_in  <= today,
                models.Guest.check_out >= today,
            )
            .first()
        )

        # If no active guest found, try finding any guest with that room number
        if not guest:
            guest = (
                db.query(models.Guest)
                .filter(models.Guest.room_no == room_no)
                .first()
            )

        if not guest:
            return JSONResponse(
                status_code=404,
                content={"status": "error", "message": f"No guest found in room {room_no}"}
            )

        # ── Settle all pending bookings for this stay before deleting guest ──
        guest_name = guest.guest_name
        ci = guest.check_in
        if not isinstance(ci, datetime):
            ci = datetime.combine(ci, datetime.min.time())
        stay_start = ci

        for Model, time_col in [
            (models.Order,                "ordered_at"),
            (models.SpaBooking,           "booked_at"),
            (models.EntertainmentBooking, "booked_at"),
            (models.ActivityBooking,      "booked_at"),
            (models.DineBooking,          "booked_at"),
        ]:
            pending_records = db.query(Model).filter(
                Model.room_no == room_no,
                Model.guest_name == guest_name,
                getattr(Model, time_col) >= stay_start,
                Model.status == "pending"
            ).all()
            for r in pending_records:
                r.status = "confirmed"  # auto-confirm on checkout

        db.commit()
        # ─────────────────────────────────────────────────────────────────

        db.delete(guest)
        db.commit()
        return {"status": "success", "message": f"Guest in room {room_no} deleted successfully"}

    except Exception as e:
        db.rollback()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )
    finally:
        db.close()

@app.get("/admin/groups", response_class=HTMLResponse)
def admin_group_bookings(request: Request):
    db = SessionLocal()
    today = date.today()
    all_groups = db.query(GroupBooking).all()  # ← fixed

    active_groups = []
    past_groups = []
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
        "request": request,
        "page": "groups",
        "active_groups": active_groups,
        "past_groups": past_groups,
        "upcoming_groups": upcoming_groups,
    })


# =========================
# SEND GROUP MESSAGE
# =========================

@app.post("/send-group-message")
def send_group_message(
    group_id: int = Form(...),
    room_numbers: str = Form(...),
    message: str = Form(...)
):
    # Send message to all rooms in the group
    rooms = [r.strip() for r in room_numbers.split(',')]
    for room in rooms:
        try:
            room_messages[int(room)] = message
            print(f"✅ Group message set: room={room}, msg={message}")
        except:
            pass
    return RedirectResponse("/admin/groups", status_code=303)

@app.get("/api/guests/current")
def api_current_guests():
    db = SessionLocal()
    today = date.today()
    all_guests = db.query(models.Guest).all()

    current_guests = []
    for g in all_guests:
        ci = g.check_in  if isinstance(g.check_in,  date) else date.fromisoformat(str(g.check_in))
        co = g.check_out if isinstance(g.check_out, date) else date.fromisoformat(str(g.check_out))
        if ci <= today <= co:
            days_left = (co - today).days
            current_guests.append({
                "room_no":    g.room_no,
                "guest_name": g.guest_name,
                "check_in":   str(g.check_in),
                "check_out":  str(g.check_out),
                "days_left":  days_left
            })

    db.close()
    return current_guests