# dashboard/app.py
import json
import os
import re
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import Cookie, Depends, FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bot.database import AsyncSessionLocal, init_db
from bot.memory import retrieve_relevant_memories
from bot.models import Group, GroupMemory, Message, Persona
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

        # Distinct members with message counts
        members_result = await session.execute(
            select(
                Message.sender_id,
                Message.sender_name,
                func.count(Message.id).label("msg_count"),
            )
            .where(Message.group_id == group.id, Message.is_bot == False)  # noqa: E712
            .group_by(Message.sender_id, Message.sender_name)
            .order_by(func.count(Message.id).desc())
        )
        members = [
            {"sender_id": r.sender_id, "name": r.sender_name, "msg_count": r.msg_count}
            for r in members_result.all()
        ]

    return templates.TemplateResponse(request, "group_edit.html", {
        "group": group,
        "persona": group.persona,
        "total_messages": total_messages,
        "presets": PRESETS,
        "members": members,
    })


@app.get("/groups/{group_id}/analyze")
async def analyze_persona(group_id: int, _=Depends(get_current_user)):
    """Deep bot character analysis: context pairs, temporal, typology, trend, vector facts."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Group)
            .options(selectinload(Group.persona))
            .where(Group.id == group_id)
        )
        group = result.scalar_one_or_none()
        if not group or not group.persona:
            return JSONResponse({"error": "Qrup tapılmadı"}, status_code=404)

        all_msgs_result = await session.execute(
            select(Message.text, Message.is_bot, Message.sent_at)
            .where(Message.group_id == group_id)
            .order_by(Message.sent_at.desc())
            .limit(80)
        )
        all_rows = list(reversed(all_msgs_result.all()))

    bot_rows = [r for r in all_rows if r.is_bot]
    if len(bot_rows) < 5:
        return JSONResponse({"error": "Analiz üçün kifayət qədər mesaj yoxdur (minimum 5)."})

    bot_rows = bot_rows[-30:]

    # #1 Context pairs: user message → bot reply
    context_pairs = []
    for i, row in enumerate(all_rows):
        if row.is_bot:
            for j in range(i - 1, max(i - 4, -1), -1):
                if not all_rows[j].is_bot:
                    context_pairs.append((all_rows[j].text, row.text))
                    break
    pairs_sample = "\n".join(
        f"  İstifadəçi: {u}\n  Bot: {b}" for u, b in context_pairs[-10:]
    )

    # #2 Temporal stats
    hours = [r.sent_at.hour for r in bot_rows if r.sent_at]
    peak_hours = [f"{h:02d}:00" for h in Counter(hours).most_common(3)] if hours else []

    # #4 Message typology
    word_counts = [len(r.text.split()) for r in bot_rows]
    avg_words = round(sum(word_counts) / len(word_counts), 1)
    question_pct = round(sum(1 for r in bot_rows if "?" in r.text) / len(bot_rows) * 100)

    # #5 Trend: first half vs second half
    mid = len(bot_rows) // 2
    first_half = "\n".join(f"- {r.text}" for r in bot_rows[:mid])
    second_half = "\n".join(f"- {r.text}" for r in bot_rows[mid:])

    # Vector facts
    async with AsyncSessionLocal() as session:
        stored_facts = await retrieve_relevant_memories(
            session, group_id, " ".join(r.text for r in bot_rows[-10:]), top_k=8
        )
    facts_block = ""
    if stored_facts:
        facts_block = "Yığılmış qrup bilikləri:\n" + "\n".join(f"- {f}" for f in stored_facts) + "\n"

    prompt = f"""'{group.persona.name}' botunun dərin xarakter analizini JSON formatında ver.

Əvvəlki mesajlar:
{first_half}

Son mesajlar:
{second_half}

Kontekst cütlükləri (istifadəçi → bot cavabı):
{pairs_sample}

{facts_block}
Statistika:
- Orta mesaj uzunluğu: {avg_words} söz
- Sual faizi: {question_pct}%
- Ən aktiv saatlar: {", ".join(peak_hours) if peak_hours else "məlumat yox"}

Yalnız bu JSON strukturunu qaytar, başqa heç nə yazma:
{{
  "danishiq_terzi": "danışıq tərzi və üslubu, 2-3 cümlə",
  "dominant_ehval": "dominant əhval-ruhiyyə, 1-2 cümlə",
  "yumor": "yumor istifadəsi, 1-2 cümlə",
  "aktiv_vaxt": "aktivlik vaxtı nümunəsi, 1-2 cümlə",
  "konfig_ferqi": "konfiqurasiya ilə real davranış fərqi, 1-2 cümlə",
  "trend": "əvvəlki vs son mesajlar arasında dəyişim, 1-2 cümlə"
}}"""

    raw = await _call_ai_for_analysis(prompt)
    return _parse_analysis_response(raw)


def _parse_analysis_response(raw: str | None) -> JSONResponse:
    if not raw:
        return JSONResponse({"error": "Analiz alınmadı."})
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return JSONResponse({"analysis": json.loads(match.group())})
        except json.JSONDecodeError:
            pass
    return JSONResponse({"analysis": raw})


def _analysis_model() -> str:
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    if provider == "anthropic":
        return os.getenv("ANALYSIS_MODEL", os.getenv("AI_MODEL", "claude-haiku-4-5-20251001"))
    if provider == "grok":
        return os.getenv("ANALYSIS_MODEL", os.getenv("AI_MODEL", "grok-3-mini"))
    return os.getenv("ANALYSIS_MODEL", os.getenv("AI_MODEL", "gpt-4o-mini"))


async def _call_ai_for_analysis(prompt: str) -> str | None:
    provider = os.getenv("AI_PROVIDER", "openai").lower()
    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic()
            resp = await client.messages.create(
                model=_analysis_model(),
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        elif provider == "grok":
            import openai
            client = openai.AsyncOpenAI(
                api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1"
            )
            resp = await client.chat.completions.create(
                model=_analysis_model(),
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content
        else:
            import openai
            client = openai.AsyncOpenAI()
            resp = await client.chat.completions.create(
                model=_analysis_model(),
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content
    except Exception as e:
        return f"Xəta: {e}"


@app.get("/groups/{group_id}/members/{sender_id}/analyze")
async def analyze_member(group_id: int, sender_id: int, _=Depends(get_current_user)):
    """Deep member character analysis: typology, temporal, trend, vector facts."""
    async with AsyncSessionLocal() as session:
        msgs_result = await session.execute(
            select(Message.text, Message.sender_name, Message.sent_at)
            .where(Message.group_id == group_id, Message.sender_id == sender_id, Message.is_bot == False)  # noqa: E712
            .order_by(Message.sent_at.desc())
            .limit(40)
        )
        rows = list(reversed(msgs_result.all()))

    if len(rows) < 5:
        return JSONResponse({"error": "Analiz üçün kifayət qədər mesaj yoxdur (minimum 5)."})

    name = rows[-1].sender_name

    # #2 Temporal stats
    hours = [r.sent_at.hour for r in rows if r.sent_at]
    peak_hours = [f"{h:02d}:00" for h in Counter(hours).most_common(3)] if hours else []

    # #4 Message typology
    word_counts = [len(r.text.split()) for r in rows]
    avg_words = round(sum(word_counts) / len(word_counts), 1)
    question_pct = round(sum(1 for r in rows if "?" in r.text) / len(rows) * 100)

    # #5 Trend: first half vs second half
    mid = len(rows) // 2
    first_half = "\n".join(f"- {r.text}" for r in rows[:mid])
    second_half = "\n".join(f"- {r.text}" for r in rows[mid:])

    # Vector facts
    async with AsyncSessionLocal() as session:
        query = f"{name} " + " ".join(r.text for r in rows[-10:])
        stored_facts = await retrieve_relevant_memories(session, group_id, query, top_k=8)
    facts_block = ""
    if stored_facts:
        facts_block = "Yığılmış qrup bilikləri:\n" + "\n".join(f"- {f}" for f in stored_facts) + "\n"

    prompt = f"""'{name}' adlı şəxsin dərin xarakter analizini JSON formatında ver.

Əvvəlki mesajlar:
{first_half}

Son mesajlar:
{second_half}

{facts_block}
Statistika:
- Orta mesaj uzunluğu: {avg_words} söz
- Sual faizi: {question_pct}%
- Ən aktiv saatlar: {", ".join(peak_hours) if peak_hours else "məlumat yox"}

Yalnız bu JSON strukturunu qaytar, başqa heç nə yazma:
{{
  "shexsiyyet": "ümumi şəxsiyyət tipi, 2-3 cümlə",
  "danishiq_terzi": "danışıq tərzi və üslubu, 1-2 cümlə",
  "maraqlar": "maraqları və tez-tez danışdığı mövzular, 1-2 cümlə",
  "qrupdaki_rol": "qrupdakı rolu — lider, zarafatçı, müşahidəçi və s., 1-2 cümlə",
  "ehval": "əhval-ruhiyyəsi — optimist, tənqidçi, neytral, 1-2 cümlə",
  "trend": "əvvəlki vs son mesajlar arasında dəyişim, 1-2 cümlə"
}}"""

    raw = await _call_ai_for_analysis(prompt)
    result = _parse_analysis_response(raw)
    # Inject name for frontend
    result_data = json.loads(result.body)
    result_data["name"] = name
    return JSONResponse(result_data)


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
