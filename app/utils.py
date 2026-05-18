"""
app/utils.py
Shared helpers used across all route modules.
"""

import os
import re
import subprocess
from datetime import datetime
from fastapi import WebSocket


# ---------------------------------------------------------------------------
# Path constants (mirrors what was in main.py)
# ---------------------------------------------------------------------------
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR     = os.path.join(BASE_DIR, "static")
UPLOAD_DIR     = os.path.join(BASE_DIR, "static", "images")
MENU_CARD_DIR  = os.path.join(BASE_DIR, "static", "uploads", "menu_card")


# ---------------------------------------------------------------------------
# Filename helper
# ---------------------------------------------------------------------------

def title_filename(title: str, original_filename: str) -> str:
    """Return a clean filename based on the item title, e.g. 'masala_dosa.jpg'"""
    ext  = os.path.splitext(original_filename)[1].lower() or ".jpg"
    safe = re.sub(r"[^\w\s-]", "", title.strip().lower())
    safe = re.sub(r"[\s_]+", "_", safe)
    safe = safe.strip("_") or "item"
    return safe + ext


# ---------------------------------------------------------------------------
# TV status ping
# ---------------------------------------------------------------------------

def check_tv_status(ip_address: str) -> str:
    try:
        param  = "-n" if os.name == "nt" else "-c"
        result = subprocess.run(
            ["ping", param, "1", ip_address],
            capture_output=True, text=True
        )
        return "ONLINE" if ("TTL=" in result.stdout or "ttl=" in result.stdout) else "OFFLINE"
    except Exception:
        return "OFFLINE"


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, data):
        for connection in self.active_connections:
            await connection.send_json(data)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Room message store (in-memory, shared across routers via import)
# ---------------------------------------------------------------------------

room_messages: dict[int, str] = {}


# ---------------------------------------------------------------------------
# Menu card helper
# ---------------------------------------------------------------------------

def get_menu_card_url():
    """Scans MENU_CARD_DIR and returns (url, updated_at) if a file exists."""
    os.makedirs(MENU_CARD_DIR, exist_ok=True)
    for ext in [".pdf", ".jpg", ".jpeg", ".png", ".webp"]:
        path = os.path.join(MENU_CARD_DIR, f"menu_card{ext}")
        if os.path.exists(path):
            ts         = os.path.getmtime(path)
            updated_at = datetime.fromtimestamp(ts).strftime("%d %b %Y, %I:%M %p")
            return f"/static/uploads/menu_card/menu_card{ext}", updated_at
    return None, None


# ---------------------------------------------------------------------------
# Category cover image helper
# ---------------------------------------------------------------------------

def find_cover(cover_dir: str, category: str):
    """Return the file-system path of an existing cover, or None."""
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        p = os.path.join(cover_dir, category + ext)
        if os.path.exists(p):
            return p
    return None