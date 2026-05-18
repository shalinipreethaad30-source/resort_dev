"""
app/auth_routes.py
Admin authentication endpoints: login, logout, session check, change password.
"""

import os
import bcrypt
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def get_admin_password_hash() -> bytes:
    """Load hash from file (if password was reset) or fall back to default."""
    if os.path.exists("admin_pass.hash"):
        with open("admin_pass.hash", "rb") as f:
            return f.read().strip()
    # Default hash — generated from 'admin123'
    return b"$2b$12$/x2e9vG1J06O51UFLameD.wGsdi7CuQ0gZkgbO/NtfKsLO5dAjjb."


def require_admin(request: Request):
    """Dependency — raises 401 if admin is not logged in."""
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    new_password: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/api/admin/login")
async def admin_login(data: LoginRequest, request: Request):
    password = data.password.encode("utf-8")
    if data.username == "admin" and bcrypt.checkpw(password, get_admin_password_hash()):
        request.session["admin_logged_in"] = True
        return {"success": True}
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/api/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return {"success": True}


@router.get("/api/admin/check-session")
async def check_admin_session(request: Request):
    return {"logged_in": request.session.get("admin_logged_in", False)}


@router.post("/api/admin/change-password")
async def change_admin_password(data: ChangePasswordRequest, request: Request):
    if not request.session.get("admin_logged_in"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password too short")
    new_hash = bcrypt.hashpw(data.new_password.encode("utf-8"), bcrypt.gensalt())
    with open("admin_pass.hash", "wb") as f:
        f.write(new_hash)
    return {"success": True}