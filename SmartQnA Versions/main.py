"""
SmartQnA — Completions Service
Port: 8002
Owns: RAG pipeline, LLM calls, guardrails, security, response caching
"""

import os
import re
import json
import time
import hashlib
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv()

# ── App setup ─────────────────────────────────────────────────────────
app = FastAPI(title="SmartQnA — Completions Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Service URLs ──────────────────────────────────────────────────────
SEARCH_SERVICE_URL = os.getenv("SEARCH_SERVICE_URL", "http://localhost:8001")

# ── LLM Configuration ─────────────────────────────────────────────────
# Swap these when you get access to your company's engine:
#   LLM_BASE_URL = "https://your-company-endpoint"
#   LLM_API_KEY  = "your-key"
#   LLM_MODEL    = "your-model-name"
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.mistral.ai/v1")
LLM_API_KEY  = os.getenv("LLM_API_KEY",  "your_mistral_api_key_here")
LLM_MODEL    = os.getenv("LLM_MODEL",    "mistral-small-latest")


# ═════════════════════════════════════════════════════════════════════
# RESPONSE CACHE
# ═════════════════════════════════════════════════════════════════════

class ResponseCache:
    def __init__(self, ttl_seconds=600):  # 10 min TTL for LLM responses
        self._store = {}
        self._ttl   = ttl_seconds

    def _key(self, query: str, filters: dict) -> str:
        raw = json.dumps({"q": query.lower().strip(), **filters}, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    def get(self, query: str, filters: dict):
        key  = self._key(query, filters)
        item = self._store.get(key)
        if not item:
            return None
        if time.time() - item["ts"] > self._ttl:
            del self._store[key]
            return None
        return item["data"]

    def set(self, query: str, filters: dict, data):
        key = self._key(query, filters)
        self._store[key] = {"data": data, "ts": time.time()}

response_cache = ResponseCache(ttl_seconds=600)


# ═════════════════════════════════════════════════════════════════════
# GUARDRAILS
# ═════════════════════════════════════════════════════════════════════

# Smartphone-related keywords — query must contain at least one
SMARTPHONE_KEYWORDS = {
    "phone", "mobile", "smartphone", "battery", "camera", "display",
    "screen", "processor", "ram", "storage", "5g", "4g", "3g", "2g",
    "android", "ios", "iphone", "samsung", "redmi", "realme", "poco",
    "oneplus", "pixel", "motorola", "nokia", "charging", "specs",
    "specification", "review", "price", "launch", "chipset", "sensor",
    "megapixel", "mp", "mah", "gb", "brand", "model", "flagship",
    "budget", "mid-range", "premium", "charger", "cable", "accessory",
    "sim", "network", "lte", "wifi", "bluetooth", "nfc", "fingerprint",
    "face unlock", "amoled", "lcd", "oled", "refresh rate", "hz",
    "snapdragon", "dimensity", "helio", "exynos", "bionic", "gpu",
    "benchmark", "antutu", "geekbench", "zoom", "aperture", "ois",
    "ultra wide", "telephoto", "selfie", "video", "4k", "slow motion",
    "water resistant", "ip rating", "gorilla glass", "ceramic",
    "titanium", "aluminium", "plastic", "glass back"
}

def check_input_guardrail(query: str) -> dict:
    """
    Check if query is smartphone-related.
    Returns: { "allowed": bool, "reason": str }
    """
    query_lower = query.lower()
    words       = set(re.findall(r'\b\w+\b', query_lower))

    # Check direct keyword match
    if words & SMARTPHONE_KEYWORDS:
        return {"allowed": True, "reason": "smartphone_related"}

    # Check multi-word phrases
    for kw in SMARTPHONE_KEYWORDS:
        if kw in query_lower:
            return {"allowed": True, "reason": "smartphone_related"}

    return {
        "allowed": False,
        "reason":  "Query is not related to smartphones. "
                   "SmartQnA only answers questions about smartphones, "
                   "their specs, features, pricing and comparisons."
    }


def check_output_guardrail(answer: str) -> dict:
    """
    Check LLM output doesn't contain anything off-topic or harmful.
    Returns: { "safe": bool, "reason": str }
    """
    # Block clearly off-topic responses
    off_topic_signals = [
        "as an ai language model",
        "i cannot help with",
        "i'm not able to provide",
        "please consult a professional",
    ]
    answer_lower = answer.lower()
    for signal in off_topic_signals:
        if signal in answer_lower:
            return {"safe": False, "reason": "off_topic_response"}

    return {"safe": True, "reason": "ok"}


# ═════════════════════════════════════════════════════════════════════
# SECURITY
# ═════════════════════════════════════════════════════════════════════

# Prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore (all |previous |your )?(instructions?|prompts?|rules?|guidelines?)",
    r"forget (you are|that you('re)?|everything)",
    r"you are now",
    r"act as (a |an |if you('re)?)",
    r"\[system\]",
    r"new (instructions?|prompt|persona|role)",
    r"override (your )?(instructions?|settings?|programming)",
    r"disregard (all |previous |your )?",
    r"jailbreak",
    r"dan mode",
    r"developer mode",
    r"bypass (your )?(safety|filter|restriction)",
]

# PII patterns
PII_PATTERNS = {
    "email":        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "phone_number": r'\b(\+91|0)?[6-9]\d{9}\b',
    "pan_card":     r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',
    "aadhar":       r'\b\d{4}\s?\d{4}\s?\d{4}\b',
    "credit_card":  r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
}

def check_prompt_injection(query: str) -> dict:
    """
    Detect prompt injection attempts.
    Returns: { "safe": bool, "threat_type": str }
    """
    query_lower = query.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query_lower):
            return {
                "safe":        False,
                "threat_type": "prompt_injection",
                "detail":      f"Matched pattern: {pattern}"
            }
    return {"safe": True, "threat_type": None}


def detect_and_redact_pii(text: str) -> dict:
    """
    Detect and redact PII from text.
    Returns: { "has_pii": bool, "redacted_text": str, "pii_types": list }
    """
    found_types  = []
    redacted     = text

    for pii_type, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, redacted)
        if matches:
            found_types.append(pii_type)
            redacted = re.sub(pattern, f"[{pii_type.upper()} REDACTED]", redacted)

    return {
        "has_pii":      len(found_types) > 0,
        "redacted_text": redacted,
        "pii_types":    found_types,
    }


# ═════════════════════════════════════════════════════════════════════
# LLM CALL
# Abstracted so swapping provider = changing 3 env vars
# ═════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are SmartQnA, an AI assistant that answers questions exclusively about smartphones.

Rules you must follow:
1. Answer ONLY from the provided context. Do not use outside knowledge.
2. If the context does not contain enough information, say: "I don't have enough information in the uploaded documents to answer this question."
3. Keep answers factual, concise and grounded in the context.
4. Always mention which document or source your answer comes from.
5. Never answer questions unrelated to smartphones.
6. Format key specs in a readable way when listing them.
"""

def build_prompt(query: str, context_chunks: list) -> str:
    """Build the RAG prompt from query + retrieved chunks."""
    context_text = ""
    for i, chunk in enumerate(context_chunks, 1):
        source  = chunk.get("file_name", chunk.get("source", "Unknown"))
        content = chunk.get("content", "")[:800]  # limit each chunk
        context_text += f"\n--- Source {i}: {source} ---\n{content}\n"

    return f"""Context from uploaded documents:
{context_text}

User question: {query}

Answer based strictly on the context above:"""


async def call_llm(prompt: str) -> str:
    """
    Call the LLM API.
    Uses OpenAI-compatible format — works with Mistral, Groq, Azure OpenAI,
    and most other providers. Just update the env vars.
    """
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type":  "application/json",
    }
    body = {
        "model":       LLM_MODEL,
        "messages": [
            {"role": "system",  "content": SYSTEM_PROMPT},
            {"role": "user",    "content": prompt},
        ],
        "temperature": 0.1,    # low temp = more factual, less creative
        "max_tokens":  512,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"LLM API error: {response.status_code} — {response.text}"
        )

    data   = response.json()
    answer = data["choices"][0]["message"]["content"].strip()
    return answer


# ═════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    query:         str
    domain:        Optional[str] = None
    brand_filter:  Optional[str] = None
    source_filter: Optional[str] = None


# ═════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "service": "completions"}


@app.post("/chat")
async def chat_endpoint(
    request: Request,
    query:         Optional[str]        = Form(None),
    image:         Optional[UploadFile] = File(None),
    domain:        Optional[str]        = Form(None),
    brand_filter:  Optional[str]        = Form(None),
    source_filter: Optional[str]        = Form(None),
):
    """
    Main chat endpoint — full RAG pipeline:
    1. Security checks (injection + PII)
    2. Input guardrail (smartphone-related?)
    3. Cache check
    4. Search service → retrieve context chunks
    5. LLM call with context
    6. Output guardrail
    7. Cache result and return
    """

    # Handle JSON body (text-only)
    if query is None:
        try:
            body         = await request.json()
            query        = body.get("query", "")
            domain       = body.get("domain")
            brand_filter = body.get("brand_filter")
            source_filter= body.get("source_filter")
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid request body")

    if not query or not query.strip():
        raise HTTPException(status_code=422, detail="query cannot be empty")

    # ── Step 1: Prompt injection check ───────────────────────────────
    injection_check = check_prompt_injection(query)
    if not injection_check["safe"]:
        return {
            "answer":              "This query was blocked due to security concerns.",
            "sources":             [],
            "confidence":          0.0,
            "guardrail_triggered": True,
            "block_reason":        "prompt_injection",
        }

    # ── Step 2: PII detection + redaction ────────────────────────────
    pii_check    = detect_and_redact_pii(query)
    clean_query  = pii_check["redacted_text"]  # use redacted version
    pii_detected = pii_check["has_pii"]

    # ── Step 3: Input guardrail ───────────────────────────────────────
    guardrail = check_input_guardrail(clean_query)
    if not guardrail["allowed"]:
        return {
            "answer":              guardrail["reason"],
            "sources":             [],
            "confidence":          0.0,
            "guardrail_triggered": True,
            "block_reason":        "off_topic",
        }

    # ── Step 4: Cache check ───────────────────────────────────────────
    filters = {"domain": domain, "brand": brand_filter}
    cached  = response_cache.get(clean_query, filters)
    if cached:
        cached["cache_hit"]   = True
        cached["pii_detected"]= pii_detected
        return cached

    # ── Step 5: Retrieve context from Search Service ──────────────────
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            search_response = await client.post(
                f"{SEARCH_SERVICE_URL}/search",
                json={
                    "query":         clean_query,
                    "top_k":         5,
                    "domain_filter": domain,
                },
            )
        search_data = search_response.json()
        chunks      = search_data.get("results", [])
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Search service unavailable: {str(e)}"
        )

    # ── Step 6: Handle no results ─────────────────────────────────────
    if not chunks:
        result = {
            "answer":              "I don't have enough information in the uploaded documents to answer this question. Please upload relevant smartphone documents first.",
            "sources":             [],
            "confidence":          0.0,
            "guardrail_triggered": False,
            "cache_hit":           False,
            "pii_detected":        pii_detected,
        }
        return result

    # ── Step 7: Build prompt and call LLM ────────────────────────────
    prompt = build_prompt(clean_query, chunks)

    try:
        answer = await call_llm(prompt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {str(e)}")

    # ── Step 8: Output guardrail ──────────────────────────────────────
    output_check = check_output_guardrail(answer)
    if not output_check["safe"]:
        answer = "I wasn't able to generate a relevant answer. Please rephrase your question."

    # ── Step 9: Build sources list ────────────────────────────────────
    sources = []
    seen_sources = set()
    for chunk in chunks[:3]:
        fname = chunk.get("file_name", chunk.get("source", ""))
        if fname and fname not in seen_sources:
            sources.append({
                "document": fname,
                "url":      "",
                "category": chunk.get("category", ""),
                "score":    chunk.get("score", 0),
            })
            seen_sources.add(fname)

    # Use top chunk score as confidence
    confidence = chunks[0].get("score", 0.0) if chunks else 0.0

    result = {
        "answer":              answer,
        "sources":             sources,
        "confidence":          round(confidence, 3),
        "guardrail_triggered": False,
        "cache_hit":           False,
        "pii_detected":        pii_detected,
    }

    # ── Step 10: Cache the result ─────────────────────────────────────
    response_cache.set(clean_query, filters, result)

    return result
