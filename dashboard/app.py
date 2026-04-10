# dashboard/app.py
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import json

from fastapi import Cookie, Depends, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bot.database import AsyncSessionLocal, init_db
from bot.models import Group, Message, Persona
from dashboard.auth import (
    SESSION_COOKIE,
    make_session_token,
    require_auth,
    verify_credentials,
    verify_session,
)
from dashboard.presets import PRESETS

app = FastAPI(docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)


@app.on_event("startup")
async def startup():
    await init_db()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if not verify_credentials(username, password):
        return RedirectResponse("/login?error=1", status_code=status.HTTP_302_FOUND)
    response = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(SESSION_COOKIE, make_session_token(), httponly=True, samesite="lax")
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Auth dependency for protected routes
# ---------------------------------------------------------------------------

def get_current_user(dsession: str | None = Cookie(default=None)):
    if not dsession or not verify_session(dsession):
        raise _redirect_to_login()
    return True


def _redirect_to_login():
    from fastapi import HTTPException
    return HTTPException(
        status_code=status.HTTP_302_FOUND,
        headers={"Location": "/login"},
    )


# ---------------------------------------------------------------------------
# Groups list
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, _=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .order_by(Group.created_at.desc())
        )
        groups = result.scalars().all()

        # Message counts per group
        counts = {}
        for group in groups:
            cnt = await session.execute(
                select(func.count()).where(Message.group_id == group.id)
            )
            counts[group.id] = cnt.scalar() or 0

    return templates.TemplateResponse(request, "groups.html", {
        "groups": groups,
        "counts": counts,
    })


# ---------------------------------------------------------------------------
# Toggle auto-message
# ---------------------------------------------------------------------------

@app.post("/groups/{group_id}/toggle")
async def toggle_auto_message(group_id: int, _=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Persona).where(Persona.group_id == group_id)
        )
        persona = result.scalar_one_or_none()
        if persona:
            persona.auto_message_enabled = not persona.auto_message_enabled
            await session.commit()
    return RedirectResponse("/", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Group detail / persona edit
# ---------------------------------------------------------------------------

@app.get("/groups/{group_id}", response_class=HTMLResponse)
async def group_detail(group_id: int, request: Request, _=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()
        if not group:
            return RedirectResponse("/", status_code=status.HTTP_302_FOUND)

        cnt = await session.execute(
            select(func.count()).where(Message.group_id == group.id)
        )
        total_messages = cnt.scalar() or 0

    return templates.TemplateResponse(request, "group_edit.html", {
        "group": group,
        "persona": group.persona,
        "total_messages": total_messages,
        "presets": PRESETS,
    })


@app.post("/groups/{group_id}/persona")
async def update_persona(
    group_id: int,
    name: str = Form(...),
    gender: str = Form(...),
    bio: str = Form(...),
    personality: str = Form(...),
    language_style: str = Form(...),
    auto_message_interval_min: int = Form(...),
    auto_message_interval_max: int = Form(...),
    context_window: int = Form(...),
    _=Depends(get_current_user),
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Persona).where(Persona.group_id == group_id)
        )
        persona = result.scalar_one_or_none()
        if persona:
            persona.name = name
            persona.bio = bio
            persona.personality = personality
            persona.language_style = language_style
            persona.auto_message_interval_min = auto_message_interval_min
            persona.auto_message_interval_max = auto_message_interval_max
            persona.context_window = context_window
            # Store gender in bio prefix if provided
            if gender and not persona.bio.startswith(f"[{gender}]"):
                persona.bio = f"[{gender}] {bio}"
            await session.commit()
    return RedirectResponse(f"/groups/{group_id}?saved=1", status_code=status.HTTP_302_FOUND)
