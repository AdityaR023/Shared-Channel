"""
SmartQnA — UI Service
Port: 8000

Changes in this version:
  1. Upload — no manual metadata fields. File goes directly to Group A's
     /generate-metadata endpoint which handles everything automatically.
  2. Profile — assigned domains come from real user data in SQLite.
  3. Logging — all events logged to logs/app.log via shared logger.
"""

import os
import sys
import json
import httpx
from typing import Optional, List
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# ── Add project root to path so logger.py is found ───────────────────
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

load_dotenv()

logger = get_logger("ui_service")

# ── App setup ─────────────────────────────────────────────────────────
app = FastAPI(title="SmartQnA — UI Service", version="3.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Service URLs ──────────────────────────────────────────────────────
# Group A's Flask app runs separately — point to their port
SEARCH_SERVICE_URL      = os.getenv("SEARCH_SERVICE_URL",      "http://localhost:5000")
COMPLETIONS_SERVICE_URL = os.getenv("COMPLETIONS_SERVICE_URL", "http://localhost:8002")

# ── Database ──────────────────────────────────────────────────────────
from database import (
    init_db, create_user, get_user_by_email, verify_password,
    update_last_login, create_conversation, get_conversations,
    get_conversation_with_messages, delete_conversation,
    save_message, get_recent_messages, update_conversation_title,
)

@app.on_event("startup")
def startup():
    init_db()
    logger.info("UI service started. Database initialised.")


# ═════════════════════════════════════════════════════════════════════
# SESSION / AUTH (stub tokens — replace with real JWT later)
# ═════════════════════════════════════════════════════════════════════

import secrets as sec
_sessions = {}   # token → user dict (keeps domains etc in memory)

def create_token(user: dict) -> str:
    token = sec.token_hex(32)
    _sessions[token] = user   # store full user dict, not just ID
    return token

def get_session_user(request: Request) -> Optional[dict]:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return _sessions.get(auth[7:])

def require_user(request: Request) -> dict:
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# ═════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═════════════════════════════════════════════════════════════════════

class SignupRequest(BaseModel):
    username: str
    email:    str
    password: str
    domains:  List[str]

class SearchRequest(BaseModel):
    query:         str
    top_k:         int           = 5
    domain_filter: Optional[str] = None
    brand_filter:  Optional[str] = None

class ChatRequest(BaseModel):
    query:           str
    conversation_id: Optional[str] = None
    domain:          Optional[str] = None
    brand_filter:    Optional[str] = None
    stream:          bool          = False


# ═════════════════════════════════════════════════════════════════════
# PAGE ROUTES
# ═════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return RedirectResponse(url="/login")

@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/signup")
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})

@app.get("/signup/success")
def signup_success_page(request: Request):
    return templates.TemplateResponse("signup_success.html", {"request": request})

@app.get("/upload")
def upload_page(request: Request):
    return templates.TemplateResponse("documents.html", {"request": request})

@app.get("/chat")
def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})

@app.get("/search")
def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})

@app.get("/profile")
def profile_page(request: Request):
    return templates.TemplateResponse("profile.html", {"request": request})


# ═════════════════════════════════════════════════════════════════════
# HEALTH
# ═════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    status = {"ui": "ok", "search": "unknown", "completions": "unknown"}
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            r = await client.get(f"{SEARCH_SERVICE_URL}/health")
            status["search"] = "ok" if r.status_code == 200 else "degraded"
        except Exception:
            status["search"] = "down"
        try:
            r = await client.get(f"{COMPLETIONS_SERVICE_URL}/health")
            status["completions"] = "ok" if r.status_code == 200 else "degraded"
        except Exception:
            status["completions"] = "down"
    logger.info(f"Health check: {status}")
    return status


# ═════════════════════════════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/auth/me")
async def get_me(request: Request):
    user = require_user(request)
    return {
        "id":       user["id"],
        "email":    user["email"],
        "username": user["username"],
        "domains":  user["domains"],   # ← real domains from signup
    }

@app.post("/api/auth/login")
async def login(request: Request):
    try:
        body     = await request.json()
        email    = body.get("username", "")
        password = body.get("password", "")
    except Exception:
        form     = await request.form()
        email    = form.get("username", "")
        password = form.get("password", "")

    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        logger.warning(f"Failed login attempt for email: {email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    update_last_login(user["id"])
    token = create_token(user)   # store full user dict in session
    logger.info(f"User logged in: {email} | domains: {user['domains']}")

    return {
        "access_token": token,
        "token_type":   "bearer",
        "user": {
            "id":       user["id"],
            "email":    user["email"],
            "username": user["username"],
            "domains":  user["domains"],   # ← real domains
        }
    }

@app.post("/api/auth/signup")
async def signup(body: SignupRequest):
    try:
        user = create_user(body.username, body.email, body.password, body.domains)
    except ValueError as e:
        logger.warning(f"Signup failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    token = create_token(user)
    logger.info(f"New user signed up: {body.email} | domains: {body.domains}")

    return {
        "access_token": token,
        "token_type":   "bearer",
        "api_key":      user["api_key"],
        "api_secret":   user["api_secret"],
        "user": {
            "id":       user["id"],
            "email":    user["email"],
            "username": user["username"],
            "domains":  user["domains"],
        }
    }

@app.post("/api/auth/logout")
async def logout(request: Request):
    auth  = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if token and token in _sessions:
        logger.info(f"User logged out: {_sessions[token].get('email')}")
        del _sessions[token]
    return {"success": True}


# ═════════════════════════════════════════════════════════════════════
# PROFILE — return real user data including domains from signup
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/profile")
async def get_profile(request: Request):
    """
    Returns real user profile data from the database.
    Domains come from what the user selected during signup.
    The profile page JS calls this to populate assigned domains.
    """
    user = require_user(request)
    logger.info(f"Profile fetched for: {user['email']}")
    return {
        "id":       user["id"],
        "username": user["username"],
        "email":    user["email"],
        "domains":  user["domains"],       # ← what they picked at signup
        "api_key":  user.get("api_key", ""),
    }


# ═════════════════════════════════════════════════════════════════════
# INGEST — Change 1: no manual metadata fields
# File goes straight to Group A's /generate-metadata endpoint
# which handles saving, metadata extraction, and indexing automatically
# ═════════════════════════════════════════════════════════════════════

@app.post("/api/ingest")
async def ingest_proxy(
    file: UploadFile = File(...),
):
    """
    Upload a file.
    No manual metadata required — Group A's endpoint extracts it automatically.
    Supported: PDF, CSV, HTML, MHTML, JSON
    """
    logger.info(f"File upload started: {file.filename}")

    # Validate file type before forwarding
    allowed = {".pdf", ".csv", ".html", ".mhtml", ".mht", ".json"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        logger.warning(f"Unsupported file type rejected: {file.filename}")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: PDF, CSV, HTML, JSON"
        )

    try:
        content = await file.read()

        # Forward to Group A's Flask endpoint
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{SEARCH_SERVICE_URL}/generate-metadata",
                files={"file": (file.filename, content, file.content_type)},
            )

        data = response.json()

        if response.status_code != 200:
            logger.error(f"Search service rejected upload: {data}")
            raise HTTPException(status_code=response.status_code,
                                detail=data.get("message", "Upload failed"))

        logger.info(
            f"File uploaded and indexed: {file.filename} | "
            f"chunks: {data.get('total_chunks', 0)}"
        )

        # Normalise response so UI gets consistent fields
        return {
            "success":        True,
            "filename":       file.filename,
            "chunks_indexed": data.get("total_chunks", 0),
            "file_path":      data.get("file_path", ""),
            "processed":      data.get("processed", 0),
            "skipped":        data.get("skipped", 0),
        }

    except httpx.ConnectError:
        logger.error("Search service unavailable during upload")
        raise HTTPException(status_code=503, detail="Search service unavailable")


# ═════════════════════════════════════════════════════════════════════
# SEARCH PROXY — adapts Group A's response to what UI expects
# Group A returns: { status, results: [{answer, file, category, score, chunk_id}] }
# UI expects:      { results: [{content, source, score, ...}], total, query }
# ═════════════════════════════════════════════════════════════════════

@app.post("/api/search")
async def search_proxy(body: SearchRequest):
    logger.info(f"Search query: '{body.query}' | domain: {body.domain_filter}")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{SEARCH_SERVICE_URL}/search",
                json={
                    "query":         body.query,
                    "top_k":         body.top_k,
                    "domain_filter": body.domain_filter,
                    "brand_filter":  body.brand_filter,
                },
            )
        data = response.json()

        # Translate Group A's response shape → what our UI expects
        raw_results = data.get("results", [])
        translated  = []
        for r in raw_results:
            translated.append({
                "content":      r.get("answer", ""),     # their "answer" = our "content"
                "source":       r.get("file", ""),
                "file_name":    r.get("file", ""),
                "category":     r.get("category", ""),
                "domain":       r.get("category", "").upper(),
                "score":        r.get("score", 0),
                "chunk_id":     r.get("chunk_id"),
            })

        logger.info(f"Search returned {len(translated)} results for: '{body.query}'")
        return {"query": body.query, "results": translated, "total": len(translated)}

    except httpx.ConnectError:
        logger.error("Search service unavailable")
        raise HTTPException(status_code=503, detail="Search service unavailable")


# ═════════════════════════════════════════════════════════════════════
# CONVERSATION HISTORY
# ═════════════════════════════════════════════════════════════════════

@app.get("/api/conversations")
async def list_conversations(request: Request):
    user    = require_user(request)
    convs   = get_conversations(user["id"], limit=30)
    logger.info(f"Conversations listed for user: {user['email']}")
    return {"conversations": convs}

@app.post("/api/conversations")
async def new_conversation(request: Request):
    user = require_user(request)
    conv = create_conversation(user["id"])
    logger.info(f"New conversation created: {conv['id']} for {user['email']}")
    return conv

@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str, request: Request):
    user = require_user(request)
    conv = get_conversation_with_messages(conv_id, user["id"])
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv

@app.delete("/api/conversations/{conv_id}")
async def remove_conversation(conv_id: str, request: Request):
    user = require_user(request)
    delete_conversation(conv_id, user["id"])
    logger.info(f"Conversation deleted: {conv_id} by {user['email']}")
    return {"success": True}


# ═════════════════════════════════════════════════════════════════════
# CHAT — multi-turn + streaming proxy to Completions Service
# ═════════════════════════════════════════════════════════════════════

@app.post("/api/chat")
async def chat_proxy(body: ChatRequest, request: Request):
    user    = require_user(request)
    user_id = user["id"]

    logger.info(
        f"Chat query from {user['email']}: '{body.query[:80]}' | "
        f"conv: {body.conversation_id} | stream: {body.stream}"
    )

    # Get or create conversation
    if body.conversation_id:
        conv = get_conversation_with_messages(body.conversation_id, user_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        conv_id = body.conversation_id
    else:
        conv    = create_conversation(user_id)
        conv_id = conv["id"]
        title   = body.query[:60] + ("..." if len(body.query) > 60 else "")
        update_conversation_title(conv_id, title)

    # Load recent history
    recent_msgs = get_recent_messages(conv_id, limit=10)
    history     = [{"role": m["role"], "content": m["content"]} for m in recent_msgs]

    # Save user message
    save_message(conv_id, "user", body.query)

    # Build payload for completions service
    # Pass user's domains for automatic filtering
    payload = {
        "query":        body.query,
        "history":      history,
        "domain":       body.domain or (user["domains"][0] if user["domains"] else None),
        "user_domains": user["domains"],   # full list for completions to filter
        "brand_filter": body.brand_filter,
        "stream":       body.stream,
    }

    # ── Streaming ─────────────────────────────────────────────────────
    if body.stream:
        async def stream_and_save():
            full_answer = ""
            sources     = []
            confidence  = 0.0

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST",
                        f"{COMPLETIONS_SERVICE_URL}/chat",
                        json=payload,
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:].strip()
                            yield f"data: {data}\n\n"
                            if data == "[DONE]":
                                break
                            try:
                                parsed = json.loads(data)
                                if parsed.get("type") == "meta":
                                    sources    = parsed.get("sources", [])
                                    confidence = parsed.get("confidence", 0.0)
                                elif parsed.get("token"):
                                    full_answer += parsed["token"]
                            except Exception:
                                pass

            except httpx.ConnectError:
                logger.error("Completions service unavailable during stream")
                yield 'data: {"error": "Completions service unavailable"}\n\n'
                yield "data: [DONE]\n\n"
                return

            if full_answer:
                save_message(conv_id, "assistant", full_answer,
                             sources=sources, confidence=confidence)
                logger.info(f"Streamed response saved | conv: {conv_id} | "
                            f"confidence: {confidence:.2f}")

            yield f"data: {json.dumps({'type': 'conv_id', 'conversation_id': conv_id})}\n\n"

        return StreamingResponse(
            stream_and_save(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Non-streaming ─────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{COMPLETIONS_SERVICE_URL}/chat", json=payload
            )
        data = resp.json()
    except httpx.ConnectError:
        logger.error("Completions service unavailable")
        raise HTTPException(status_code=503, detail="Completions service unavailable")

    if not data.get("guardrail_triggered"):
        save_message(conv_id, "assistant", data.get("answer", ""),
                     sources=data.get("sources", []),
                     confidence=data.get("confidence", 0.0))

    logger.info(f"Response generated | conv: {conv_id} | "
                f"confidence: {data.get('confidence', 0):.2f} | "
                f"guardrail: {data.get('guardrail_triggered', False)}")

    data["conversation_id"] = conv_id
    return data
