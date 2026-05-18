"""
app/service_routes.py
All service management consolidated.

Covers:
  - Services          (generic tiles: add, delete, update image, duplicate check, API list)
  - Food menu         (admin CRUD, category covers, menu card upload/SSE, TV API)
  - Spa & wellness    (admin CRUD, category covers, TV API)
  - Bar menu          (admin CRUD, category covers, TV API)
  - Dine-in           (admin CRUD, category covers, TV API)
  - Entertainment     (admin CRUD, category covers, TV API)
  - Room services     (admin CRUD, guest requests, status update, TV API)
  - Gallery           (admin CRUD, TV API)

NOTE: food_routes.py, spa_routes.py, bar_routes.py, dine_routes.py,
      entertainment_routes.py, room_service_routes.py, gallery_routes.py
      are now fully replaced by this file. Remove them from main.py and
      include only this router.
"""

import os
import re
import uuid
import asyncio
import json as _json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from . import models
from .utils import (
    UPLOAD_DIR, BASE_DIR, MENU_CARD_DIR,
    title_filename, get_menu_card_url, find_cover,
)

router    = APIRouter()
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# Category / option constants
# ---------------------------------------------------------------------------

FOOD_CATEGORIES_LIST     = ["breakfast", "lunch", "dinner", "snacks", "desserts", "drinks"]
SPA_CATEGORIES           = ["massage", "facial", "body", "other"]
BAR_CATEGORIES           = ["alcoholic", "non-alcoholic"]
DINE_OCCASIONS           = ["romantic", "birthday", "anniversary", "business", "family"]
ENTERTAINMENT_CATEGORIES = ["indoor", "outdoor", "water", "kids", "night"]
ENTERTAINMENT_CAT_ICONS  = {
    "indoor": "🎮", "outdoor": "⛷️", "water": "🏊", "kids": "🎠", "night": "🌙"
}
ROOM_SERVICE_ICONS = ["🍽️", "🛎️", "🧹", "🧺", "🧴", "🧖", "🚗", "📺", "📞", "🛌"]


# =============================================================================
# SERVICES  (generic tiles)
# =============================================================================

@router.get("/admin/services", response_class=HTMLResponse)
def services_page(request: Request):
    db       = SessionLocal()
    services = db.query(models.Service).all()
    db.close()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "page": "services", "services": services}
    )


def _word_tokens(title: str):
    return set(w.lower() for w in re.split(r"[\s\-&,/]+", title.strip()) if len(w) >= 3)


@router.get("/api/services/check-duplicate")
def check_service_duplicate(title: str, db: Session = Depends(get_db)):
    new_words = _word_tokens(title)
    for svc in db.query(models.Service).all():
        if new_words & _word_tokens(svc.title):
            return {"duplicate": True, "conflict_with": svc.title}
    return {"duplicate": False, "conflict_with": None}


@router.post("/admin/services/add")
async def add_service(
    title: str                  = Form(...),
    image: Optional[UploadFile] = File(None)
):
    if not image or not image.filename:
        return RedirectResponse("/admin/services?error=no_image", status_code=303)

    db        = SessionLocal()
    new_words = _word_tokens(title)
    for svc in db.query(models.Service).all():
        if new_words & _word_tokens(svc.title):
            db.close()
            return RedirectResponse(f"/admin/services?error=duplicate&conflict={svc.title}", status_code=303)

    service_dir = os.path.join(UPLOAD_DIR, "services")
    os.makedirs(service_dir, exist_ok=True)
    filename  = title_filename(title, image.filename)
    file_path = os.path.join(service_dir, filename)
    with open(file_path, "wb") as f:
        f.write(await image.read())

    db.add(models.Service(title=title, image_url=f"/static/images/services/{filename}"))
    db.commit()
    db.close()
    return RedirectResponse("/admin/services", status_code=303)


@router.delete("/admin/services/{service_id}")
def delete_service(service_id: int):
    db      = SessionLocal()
    service = db.query(models.Service).filter(models.Service.id == service_id).first()
    if service:
        db.delete(service)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.patch("/admin/services/{service_id}/image")
async def update_service_image(
    service_id: int,
    image:      UploadFile = File(...),
    db:         Session    = Depends(get_db)
):
    service = db.query(models.Service).filter(models.Service.id == service_id).first()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    if not image or not image.filename:
        raise HTTPException(status_code=400, detail="No image provided")

    if service.image_url:
        old_path = os.path.join(BASE_DIR, "static", service.image_url.lstrip("/static/"))
        if os.path.exists(old_path):
            os.remove(old_path)

    service_dir = os.path.join(UPLOAD_DIR, "services")
    os.makedirs(service_dir, exist_ok=True)
    filename  = title_filename(service.title, image.filename)
    file_path = os.path.join(service_dir, filename)
    with open(file_path, "wb") as f:
        f.write(await image.read())

    service.image_url = f"/static/images/services/{filename}"
    db.commit()
    return {"success": True, "image_url": service.image_url}


@router.get("/api/services")
def get_services():
    db       = SessionLocal()
    services = db.query(models.Service).all()
    db.close()
    return [{"id": s.id, "title": s.title, "image_url": s.image_url} for s in services]


# =============================================================================
# FOOD MENU
# =============================================================================

# TV-facing pages
@router.get("/food-page", response_class=HTMLResponse)
def food_page(request: Request):
    return templates.TemplateResponse("food_page.html", {"request": request})


@router.get("/food-menu", response_class=HTMLResponse)
def food_menu(request: Request, category: str = "breakfast"):
    db    = SessionLocal()
    items = db.query(models.FoodItem).filter(models.FoodItem.category == category).all()
    db.close()
    return templates.TemplateResponse("food_menu.html", {"request": request, "category": category, "items": items})


# Admin page
@router.get("/admin/food", response_class=HTMLResponse)
def food_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    items = db.query(models.FoodItem).all() if category == "all" else \
            db.query(models.FoodItem).filter(models.FoodItem.category == category).all()
    db.close()
    menu_card_url, menu_card_updated_at = get_menu_card_url()
    return templates.TemplateResponse("dashboard.html", {
        "request":              request,
        "page":                 "food",
        "items":                items,
        "selected_category":    category,
        "menu_card_url":        menu_card_url,
        "menu_card_updated_at": menu_card_updated_at,
    })


@router.post("/admin/food/add")
async def add_food_item(
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(...),
    image:    Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.FoodItem).filter(models.FoodItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/food?category={category}&error=duplicate&conflict={existing.title}", status_code=303)

    food_dir  = os.path.join(UPLOAD_DIR, "services", "food_menu")
    os.makedirs(food_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(food_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/food_menu/{filename}"

    db.add(models.FoodItem(title=title, category=category, price=price, image_url=image_url))
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/food?category={category}", status_code=303)


@router.delete("/admin/food/{item_id}")
def delete_food_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.FoodItem).filter(models.FoodItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/food/edit/{item_id}")
async def edit_food_item(
    item_id:  int,
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(...),
    image:    Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
    item = db.query(models.FoodItem).filter(models.FoodItem.id == item_id).first()
    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title    = title
    item.category = category
    item.price    = price

    if image and image.filename:
        food_dir  = os.path.join(UPLOAD_DIR, "services", "food_menu")
        os.makedirs(food_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(food_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/food_menu/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@router.get("/api/food-items")
def api_food_items(category: str = "breakfast"):
    db    = SessionLocal()
    items = db.query(models.FoodItem).filter(models.FoodItem.category == category).all()
    db.close()
    return [{"id": i.id, "title": i.title, "price": i.price, "image_url": i.image_url} for i in items]


@router.post("/admin/food/category-cover/{category}")
async def food_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "food_menu", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{category}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/food_menu/covers/{category}{ext}"}


@router.get("/api/category-covers/food")
def food_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "food_menu", "covers")
    result    = {}
    for cat in FOOD_CATEGORIES_LIST:
        path = find_cover(cover_dir, cat)
        result[cat] = f"/static/images/services/food_menu/covers/{cat}{os.path.splitext(path)[1]}" if path else None
    return result


# Menu card
@router.post("/admin/food/menu-card/upload")
async def upload_menu_card(menu_card: UploadFile = File(...)):
    if not menu_card:
        return JSONResponse(status_code=400, content={"error": "No file provided"})
    ext       = os.path.splitext(menu_card.filename)[1].lower()
    safe_name = f"menu_card{ext}"
    os.makedirs(MENU_CARD_DIR, exist_ok=True)
    save_path = os.path.join(MENU_CARD_DIR, safe_name)
    with open(save_path, "wb") as f:
        f.write(await menu_card.read())
    return JSONResponse(content={"url": f"/static/uploads/menu_card/{safe_name}"})


@router.get("/admin/food/menu-card/view")
def view_menu_card():
    url, _ = get_menu_card_url()
    if not url:
        raise HTTPException(status_code=404, detail="No menu card uploaded")
    return RedirectResponse(url)


@router.post("/admin/food/menu-card/delete")
async def delete_menu_card():
    for ext in [".pdf", ".jpg", ".jpeg", ".png", ".webp"]:
        path = os.path.join(MENU_CARD_DIR, f"menu_card{ext}")
        if os.path.exists(path):
            os.remove(path)
    return JSONResponse(content={"success": True})


@router.get("/api/menu-card")
def api_menu_card():
    url, updated_at = get_menu_card_url()
    if not url:
        return JSONResponse(status_code=404, content={"error": "No menu card uploaded"})
    file_type = "pdf" if url.endswith(".pdf") else "image"
    return JSONResponse(content={"url": url, "updated_at": updated_at, "type": file_type})


@router.get("/api/menu-card/events")
async def menu_card_events(request: Request):
    """SSE stream — guest panel subscribes to receive live menu-card updates."""
    async def event_generator():
        last_url = None
        while True:
            if await request.is_disconnected():
                break
            url, updated_at = get_menu_card_url()
            if url != last_url:
                last_url = url
                data     = _json.dumps({"url": url, "updated_at": updated_at})
                yield f"data: {data}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# SPA & WELLNESS
# =============================================================================

@router.get("/admin/spa", response_class=HTMLResponse)
def spa_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    items = db.query(models.SpaItem).all() if category == "all" else \
            db.query(models.SpaItem).filter(models.SpaItem.category == category).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":           request,
        "page":              "spa",
        "items":             items,
        "selected_category": category,
        "spa_categories":    SPA_CATEGORIES,
    })


@router.post("/admin/spa/add")
async def add_spa_item(
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(0),
    slot1:    str                  = Form(...),
    slot2:    str                  = Form(""),
    slot3:    str                  = Form(""),
    image:    Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.SpaItem).filter(models.SpaItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/spa?category={category}&error=duplicate&conflict={existing.title}", status_code=303)

    spa_dir   = os.path.join(UPLOAD_DIR, "services", "spa")
    os.makedirs(spa_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(spa_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/spa/{filename}"

    db.add(models.SpaItem(
        title=title, category=category, price=price,
        slot1=slot1, slot2=slot2 or None, slot3=slot3 or None, image_url=image_url
    ))
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/spa?category={category}", status_code=303)


@router.delete("/admin/spa/{item_id}")
def delete_spa_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.SpaItem).filter(models.SpaItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/spa/edit/{item_id}")
async def edit_spa_item(
    item_id:  int,
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(0),
    slot1:    str                  = Form(...),
    slot2:    str                  = Form(""),
    slot3:    str                  = Form(""),
    image:    Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
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
        spa_dir   = os.path.join(UPLOAD_DIR, "services", "spa")
        os.makedirs(spa_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(spa_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/spa/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@router.get("/api/spa-items")
def api_spa_items(category: str = "all"):
    db = SessionLocal()
    items = db.query(models.SpaItem).all() if category == "all" else \
            db.query(models.SpaItem).filter(models.SpaItem.category == category).all()
    db.close()
    return [
        {"id": i.id, "title": i.title, "category": i.category,
         "price": i.price if hasattr(i, "price") else 0,
         "slot1": i.slot1, "slot2": i.slot2, "slot3": i.slot3, "image_url": i.image_url}
        for i in items
    ]


@router.post("/admin/spa/category-cover/{category}")
async def spa_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "spa", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{category}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/spa/covers/{category}{ext}"}


@router.get("/api/category-covers/spa")
def spa_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "spa", "covers")
    result    = {}
    for cat in SPA_CATEGORIES:
        path = find_cover(cover_dir, cat)
        result[cat] = f"/static/images/services/spa/covers/{cat}{os.path.splitext(path)[1]}" if path else None
    return result


# =============================================================================
# BAR MENU
# =============================================================================

@router.get("/admin/bar", response_class=HTMLResponse)
def bar_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    items = db.query(models.BarItem).all() if category == "all" else \
            db.query(models.BarItem).filter(models.BarItem.category == category).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":           request,
        "page":              "bar",
        "items":             items,
        "selected_category": category,
        "bar_categories":    BAR_CATEGORIES,
    })


@router.post("/admin/bar/add")
async def add_bar_item(
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(...),
    image:    Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.BarItem).filter(models.BarItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/bar?category={category}&error=duplicate&conflict={existing.title}", status_code=303)

    bar_dir   = os.path.join(UPLOAD_DIR, "services", "bar")
    os.makedirs(bar_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(bar_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/bar/{filename}"

    db.add(models.BarItem(title=title, category=category, price=price, image_url=image_url))
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/bar?category={category}", status_code=303)


@router.delete("/admin/bar/{item_id}")
def delete_bar_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.BarItem).filter(models.BarItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/bar/edit/{item_id}")
async def edit_bar_item(
    item_id:  int,
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(...),
    image:    Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
    item = db.query(models.BarItem).filter(models.BarItem.id == item_id).first()
    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title    = title
    item.category = category
    item.price    = price

    if image and image.filename:
        bar_dir   = os.path.join(UPLOAD_DIR, "services", "bar")
        os.makedirs(bar_dir, exist_ok=True)
        ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
        filename  = f"{title_filename(title, image.filename).rsplit('.', 1)[0]}_{uuid.uuid4().hex[:8]}{ext}"
        file_path = os.path.join(bar_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        # Delete old image file if it exists and isn't the default
        if item.image_url and "default.jpg" not in item.image_url:
            old_path = os.path.join(BASE_DIR, "static", item.image_url.lstrip("/static/"))
            if os.path.exists(old_path):
                os.remove(old_path)
        item.image_url = f"/static/images/services/bar/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@router.get("/api/bar-items")
def api_bar_items(category: str = "all"):
    db = SessionLocal()
    items = db.query(models.BarItem).all() if category == "all" else \
            db.query(models.BarItem).filter(models.BarItem.category == category).all()
    db.close()
    return [{"id": i.id, "title": i.title, "category": i.category, "price": i.price, "image_url": i.image_url} for i in items]


@router.post("/admin/bar/category-cover/{category}")
async def bar_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "bar", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    safe_cat  = category.replace(" ", "_")
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{safe_cat}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/bar/covers/{safe_cat}{ext}"}


@router.get("/api/category-covers/bar")
def bar_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "bar", "covers")
    result    = {}
    for cat in BAR_CATEGORIES:
        safe_cat = cat.replace(" ", "_")
        path     = find_cover(cover_dir, safe_cat)
        result[cat] = f"/static/images/services/bar/covers/{safe_cat}{os.path.splitext(path)[1]}" if path else None
    return result


# =============================================================================
# DINE-IN (RESTAURANT)
# =============================================================================

@router.get("/admin/dine", response_class=HTMLResponse)
def dine_admin(request: Request, occasion: str = "all"):
    db = SessionLocal()
    items = db.query(models.DineItem).all() if occasion == "all" else \
            db.query(models.DineItem).filter(models.DineItem.occasion == occasion).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":           request,
        "page":              "dine",
        "items":             items,
        "selected_occasion": occasion,
        "dine_occasions":    DINE_OCCASIONS,
    })


@router.post("/admin/dine/add")
async def add_dine_item(
    title:       str                  = Form(...),
    occasion:    str                  = Form(...),
    description: str                  = Form(""),
    slot1:       str                  = Form(""),
    slot2:       str                  = Form(""),
    slot3:       str                  = Form(""),
    image:       Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.DineItem).filter(models.DineItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/dine?occasion={occasion}&error=duplicate&conflict={existing.title}", status_code=303)

    dine_dir  = os.path.join(UPLOAD_DIR, "services", "dine")
    os.makedirs(dine_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(dine_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/dine/{filename}"

    db.add(models.DineItem(
        title=title, occasion=occasion,
        description=description or None,
        slot1=slot1 or None, slot2=slot2 or None, slot3=slot3 or None,
        image_url=image_url
    ))
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/dine?occasion={occasion}", status_code=303)


@router.delete("/admin/dine/{item_id}")
def delete_dine_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.DineItem).filter(models.DineItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/dine/edit/{item_id}")
async def edit_dine_item(
    item_id:     int,
    title:       str                  = Form(...),
    occasion:    str                  = Form(...),
    description: str                  = Form(""),
    slot1:       str                  = Form(""),
    slot2:       str                  = Form(""),
    slot3:       str                  = Form(""),
    image:       Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
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
        dine_dir  = os.path.join(UPLOAD_DIR, "services", "dine")
        os.makedirs(dine_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(dine_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/dine/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@router.get("/api/dine-items")
def api_dine_items(occasion: str = "all"):
    db = SessionLocal()
    items = db.query(models.DineItem).all() if occasion == "all" else \
            db.query(models.DineItem).filter(models.DineItem.occasion == occasion).all()
    db.close()
    return [
        {"id": i.id, "title": i.title, "occasion": i.occasion, "description": i.description,
         "slot1": i.slot1, "slot2": i.slot2, "slot3": i.slot3, "image_url": i.image_url}
        for i in items
    ]


@router.post("/admin/dine/category-cover/{occasion}")
async def dine_category_cover(occasion: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "dine", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{occasion}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/dine/covers/{occasion}{ext}"}


@router.get("/api/category-covers/dine")
def dine_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "dine", "covers")
    result    = {}
    for occ in DINE_OCCASIONS:
        path = find_cover(cover_dir, occ)
        result[occ] = f"/static/images/services/dine/covers/{occ}{os.path.splitext(path)[1]}" if path else None
    return result


# =============================================================================
# ENTERTAINMENT
# =============================================================================

@router.get("/admin/entertainment", response_class=HTMLResponse)
def entertainment_admin(request: Request, category: str = "all"):
    db = SessionLocal()
    items = db.query(models.EntertainmentItem).all() if category == "all" else \
            db.query(models.EntertainmentItem).filter(models.EntertainmentItem.category == category).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":                  request,
        "page":                     "entertainment",
        "items":                    items,
        "selected_category":        category,
        "entertainment_categories": ENTERTAINMENT_CATEGORIES,
    })


@router.post("/admin/entertainment/add")
async def add_entertainment_item(
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(0),
    venue:    str                  = Form(""),
    slot1:    str                  = Form(""),
    slot2:    str                  = Form(""),
    slot3:    str                  = Form(""),
    image:    Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.EntertainmentItem).filter(models.EntertainmentItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/entertainment?category={category}&error=duplicate&conflict={existing.title}", status_code=303)

    ent_dir   = os.path.join(UPLOAD_DIR, "services", "entertainment")
    os.makedirs(ent_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(ent_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/entertainment/{filename}"

    db.add(models.EntertainmentItem(
        title=title, category=category, price=price,
        venue=venue or None,
        slot1=slot1 or None, slot2=slot2 or None, slot3=slot3 or None,
        image_url=image_url
    ))
    db.commit()
    db.close()
    return RedirectResponse(f"/admin/entertainment?category={category}", status_code=303)


@router.delete("/admin/entertainment/{item_id}")
def delete_entertainment_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.EntertainmentItem).filter(models.EntertainmentItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/entertainment/edit/{item_id}")
async def edit_entertainment_item(
    item_id:  int,
    title:    str                  = Form(...),
    category: str                  = Form(...),
    price:    int                  = Form(0),
    venue:    str                  = Form(""),
    slot1:    str                  = Form(""),
    slot2:    str                  = Form(""),
    slot3:    str                  = Form(""),
    image:    Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
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
        ent_dir   = os.path.join(UPLOAD_DIR, "services", "entertainment")
        os.makedirs(ent_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(ent_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/entertainment/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@router.get("/api/entertainment-items")
def api_entertainment_items(category: str = "all"):
    db = SessionLocal()
    items = db.query(models.EntertainmentItem).all() if category == "all" else \
            db.query(models.EntertainmentItem).filter(models.EntertainmentItem.category == category).all()
    db.close()
    return [
        {"id": i.id, "title": i.title, "category": i.category, "price": i.price,
         "venue": i.venue, "slot1": i.slot1, "slot2": i.slot2, "slot3": i.slot3, "image_url": i.image_url}
        for i in items
    ]


@router.post("/admin/entertainment/category-cover/{category}")
async def entertainment_category_cover(category: str, image: UploadFile = File(...)):
    cover_dir = os.path.join(UPLOAD_DIR, "services", "entertainment", "covers")
    os.makedirs(cover_dir, exist_ok=True)
    ext       = os.path.splitext(image.filename)[1].lower() or ".jpg"
    file_path = os.path.join(cover_dir, f"{category}{ext}")
    with open(file_path, "wb") as f:
        f.write(await image.read())
    return {"url": f"/static/images/services/entertainment/covers/{category}{ext}"}


@router.get("/api/category-covers/entertainment")
def entertainment_category_covers():
    cover_dir = os.path.join(UPLOAD_DIR, "services", "entertainment", "covers")
    result    = {}
    for cat in ENTERTAINMENT_CATEGORIES:
        path = find_cover(cover_dir, cat)
        result[cat] = f"/static/images/services/entertainment/covers/{cat}{os.path.splitext(path)[1]}" if path else None
    return result


# =============================================================================
# ROOM SERVICES
# =============================================================================

@router.get("/admin/room-services", response_class=HTMLResponse)
def room_services_admin(request: Request):
    db       = SessionLocal()
    items    = db.query(models.RoomServiceItem).all()
    requests = []
    if hasattr(models, "RoomServiceRequest"):
        requests = db.query(models.RoomServiceRequest).order_by(
            models.RoomServiceRequest.created_at.desc()
        ).limit(50).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {
        "request":  request,
        "page":     "room_services",
        "items":    items,
        "requests": requests,
        "rs_icons": ROOM_SERVICE_ICONS,
    })


@router.post("/admin/room-services/add")
async def add_room_service_item(
    title:       str                  = Form(...),
    description: str                  = Form(""),
    icon:        str                  = Form("🧹"),
    image:       Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/room-services?error=duplicate&conflict={existing.title}", status_code=303)

    rs_dir    = os.path.join(UPLOAD_DIR, "services", "room_services")
    os.makedirs(rs_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(rs_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/room_services/{filename}"

    db.add(models.RoomServiceItem(
        title=title, description=description or None,
        icon=icon or "🧹", image_url=image_url, is_active=True
    ))
    db.commit()
    db.close()
    return RedirectResponse("/admin/room-services", status_code=303)


@router.delete("/admin/room-services/{item_id}")
def delete_room_service_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/room-services/edit/{item_id}")
async def edit_room_service_item(
    item_id:     int,
    title:       str                  = Form(...),
    description: str                  = Form(""),
    icon:        str                  = Form("🧹"),
    image:       Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
    item = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.id == item_id).first()
    if not item:
        db.close()
        return {"message": "Item not found"}

    item.title       = title
    item.description = description or None
    item.icon        = icon or "🧹"

    if image and image.filename:
        rs_dir    = os.path.join(UPLOAD_DIR, "services", "room_services")
        os.makedirs(rs_dir, exist_ok=True)
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(rs_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        item.image_url = f"/static/images/services/room_services/{filename}"

    db.commit()
    db.close()
    return {"message": "Updated successfully"}


@router.post("/admin/room-services/toggle/{item_id}")
def toggle_room_service_item(item_id: int):
    db        = SessionLocal()
    item      = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.id == item_id).first()
    is_active = None
    if item:
        item.is_active = not item.is_active
        db.commit()
        is_active = item.is_active
    db.close()
    return {"message": "Toggled", "is_active": is_active}


@router.post("/api/room-service-request")
async def place_room_service_request(request: Request):
    data          = await request.json()
    room_no       = data.get("room_no")
    service_id    = data.get("service_id")
    service_title = data.get("service_title")
    note          = data.get("note", "")

    db = SessionLocal()
    try:
        if hasattr(models, "RoomServiceRequest"):
            db.add(models.RoomServiceRequest(
                room_no=room_no, service_id=service_id, service_title=service_title,
                note=note or None, status="pending", created_at=datetime.now()
            ))
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


@router.post("/admin/room-services/request/{req_id}/status")
async def update_request_status(req_id: int, request: Request):
    data   = await request.json()
    status = data.get("status")
    db     = SessionLocal()
    try:
        if hasattr(models, "RoomServiceRequest"):
            req = db.query(models.RoomServiceRequest).filter(models.RoomServiceRequest.id == req_id).first()
            if req:
                req.status = status
                db.commit()
                return {"message": "Status updated", "status": status}
        return {"message": "Model not found"}
    finally:
        db.close()


@router.get("/api/room-service-items")
def api_room_service_items():
    db    = SessionLocal()
    items = db.query(models.RoomServiceItem).filter(models.RoomServiceItem.is_active == True).all()
    db.close()
    return [
        {"id": i.id, "title": i.title, "description": i.description, "icon": i.icon, "image_url": i.image_url}
        for i in items
    ]


# =============================================================================
# GALLERY
# =============================================================================

@router.get("/admin/gallery", response_class=HTMLResponse)
def gallery_admin(request: Request):
    db    = SessionLocal()
    items = db.query(models.GalleryItem).all()
    db.close()
    return templates.TemplateResponse("dashboard.html", {"request": request, "page": "gallery", "items": items})


@router.post("/admin/gallery/add")
async def add_gallery_item(
    title:       str                  = Form(...),
    description: str                  = Form(""),
    image:       Optional[UploadFile] = File(None)
):
    db = SessionLocal()
    existing = db.query(models.GalleryItem).filter(models.GalleryItem.title.ilike(title.strip())).first()
    if existing:
        db.close()
        return RedirectResponse(f"/admin/gallery?error=duplicate&conflict={existing.title}", status_code=303)

    gallery_dir = os.path.join(UPLOAD_DIR, "services", "gallery")
    os.makedirs(gallery_dir, exist_ok=True)
    image_url = "/static/images/default.jpg"
    if image and image.filename:
        filename  = title_filename(title, image.filename)
        file_path = os.path.join(gallery_dir, filename)
        with open(file_path, "wb") as f:
            f.write(await image.read())
        image_url = f"/static/images/services/gallery/{filename}"

    db.add(models.GalleryItem(title=title, description=description or None, image_url=image_url))
    db.commit()
    db.close()
    return RedirectResponse("/admin/gallery", status_code=303)


@router.delete("/admin/gallery/{item_id}")
def delete_gallery_item(item_id: int):
    db   = SessionLocal()
    item = db.query(models.GalleryItem).filter(models.GalleryItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    db.close()
    return {"message": "Deleted"}


@router.post("/admin/gallery/edit/{item_id}")
async def edit_gallery_item(
    item_id:     int,
    title:       str                  = Form(...),
    description: str                  = Form(""),
    image:       Optional[UploadFile] = File(None)
):
    db   = SessionLocal()
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


@router.get("/api/gallery-items")
def api_gallery_items():
    db    = SessionLocal()
    items = db.query(models.GalleryItem).all()
    db.close()
    return [{"id": i.id, "title": i.title, "description": i.description, "image_url": i.image_url} for i in items]