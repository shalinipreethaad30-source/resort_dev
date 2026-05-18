"""
app/tv_routes.py
TV data management: add, delete, bind/unbind, WebSocket status updates.
"""

import asyncio
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import SessionLocal
from . import models
from .models import TV
from .utils import check_tv_status, manager

router    = APIRouter()
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Admin page
# ---------------------------------------------------------------------------

@router.get("/admin/tv-data", response_class=HTMLResponse)
def tv_data(request: Request):
    db  = SessionLocal()
    tvs = db.query(TV).all()
    db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "page": "tv_data", "tvs": tvs}
    )


# ---------------------------------------------------------------------------
# Add TV
# ---------------------------------------------------------------------------

@router.post("/add-tv")
def add_tv(
    room_no:     str = Form(...),
    mac_address: str = Form(...),
    ip_address:  str = Form(...)
):
    db     = SessionLocal()
    new_tv = TV(room_no=room_no, mac_address=mac_address, ip_address=ip_address, status="UNKNOWN")
    db.add(new_tv)
    db.commit()
    db.close()
    return RedirectResponse("/admin/tv-data", status_code=303)


# ---------------------------------------------------------------------------
# Delete TV
# ---------------------------------------------------------------------------

@router.delete("/delete_device/{room}")
def delete_device_api(room: str):
    db     = SessionLocal()
    device = db.query(TV).filter(TV.room_no == room).first()
    if not device:
        db.close()
        return {"message": "Room not found"}
    db.delete(device)
    db.commit()
    db.close()
    return {"message": "Device deleted successfully"}


# ---------------------------------------------------------------------------
# Bind / Unbind
# ---------------------------------------------------------------------------

@router.post("/bind_device")
async def bind_device(request: Request):
    data = await request.json()
    room = str(data.get("room"))
    db   = SessionLocal()
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
        return {"status": "success", "message": "Device bound successfully", "room": tv.room_no, "bound": tv.bound}
    finally:
        db.close()


@router.post("/unbind_device")
async def unbind_device(request: Request):
    data = await request.json()
    room = str(data.get("room"))
    db   = SessionLocal()
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
        return {"status": "success", "message": "Device unbound successfully", "room": tv.room_no, "bound": tv.bound}
    finally:
        db.close()


@router.get("/binding_status/{room}")
def binding_status(room: str):
    db = SessionLocal()
    try:
        device = db.query(TV).filter(TV.room_no == room).first()
        if not device:
            return {"status": "error", "message": "Room not found"}
        return {"room": device.room_no, "bound": device.bound, "bound_ip": device.bound_ip, "bound_mac": device.bound_mac}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Live TV page
# ---------------------------------------------------------------------------

@router.get("/live-tv", response_class=HTMLResponse)
def live_tv(request: Request):
    return templates.TemplateResponse("live_tv.html", {"request": request})


# ---------------------------------------------------------------------------
# TV theme/room page
# ---------------------------------------------------------------------------

@router.get("/tv/{room_no}", response_class=HTMLResponse)
def tv_page(request: Request, room_no: int):
    return templates.TemplateResponse("tv.html", {"request": request, "room_no": room_no})


# ---------------------------------------------------------------------------
# WebSocket — real-time TV status
# ---------------------------------------------------------------------------

@router.websocket("/ws/tv-status")
async def websocket_tv_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            db = SessionLocal()
            try:
                tvs  = db.query(models.TV).all()
                data = []
                for tv in tvs:
                    status   = check_tv_status(tv.ip_address)
                    tv.status = status
                    data.append({
                        "room_no":     tv.room_no,
                        "mac_address": tv.mac_address,
                        "ip_address":  tv.ip_address,
                        "status":      status,
                        "bound":       tv.bound
                    })
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"[TV WebSocket] DB error: {e}")
            finally:
                db.close()

            await websocket.send_json(data)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        print("[TV WebSocket] Client disconnected — stopping TV status loop.")
    except Exception as e:
        print(f"[TV WebSocket] Unexpected error: {e}")