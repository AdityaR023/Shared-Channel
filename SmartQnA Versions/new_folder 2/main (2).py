"""
SmartQnA — Completions Service
Port: 8002
"""

import os, re, json, sys, time, hashlib
from typing import Optional, List, AsyncGenerator
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from logger import get_logger

load_dotenv()
logger = get_logger("completions_service")

app = FastAPI(title="SmartQnA — Completions Service", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8000"],
                   allow_methods=["*"], allow_headers=["*"])

SEARCH_SERVICE_URL = os.getenv("SEARCH_SERVICE_URL", "http://localhost:5000")
LLM_BASE_URL       = os.getenv("LLM_BASE_URL",       "https://api.mistral.ai/v1")
LLM_API_KEY        = os.getenv("LLM_API_KEY",        "your_api_key_here")
LLM_MODEL          = os.getenv("LLM_MODEL",           "mistral-small-latest")

@app.on_event("startup")
def startup():
    logger.info("Completions service started.")


# ── Cache ─────────────────────────────────────────────────────────────
class Cache:
    def __init__(self, ttl=600):
        self._s = {}; self._ttl = ttl
    def _k(self, q, f):
        return hashlib.md5(json.dumps({"q":q.lower().strip(),**f},sort_keys=True).encode()).hexdigest()
    def get(self, q, f):
        k=self._k(q,f); i=self._s.get(k)
        if not i or time.time()-i["ts"]>self._ttl: return None
        return i["d"]
    def set(self, q, f, d):
        self._s[self._k(q,f)]={"d":d,"ts":time.time()}

cache = Cache()


# ── Guardrails ────────────────────────────────────────────────────────
KW = {"phone","mobile","smartphone","battery","camera","display","screen",
      "processor","ram","storage","5g","4g","3g","2g","android","ios",
      "iphone","samsung","redmi","realme","poco","oneplus","pixel","motorola",
      "nokia","charging","specs","specification","review","price","launch",
      "chipset","megapixel","mp","mah","gb","brand","model","flagship",
      "budget","mid-range","premium","charger","sim","wifi","bluetooth",
      "nfc","amoled","lcd","oled","snapdragon","dimensity","helio","zoom",
      "compare","best","which","recommend","vs","versus","difference"}

def input_guardrail(q):
    return any(k in q.lower() for k in KW)

INJECT = [
    r"ignore (all |previous |your )?(instructions?|prompts?|rules?)",
    r"forget (you are|that you|everything)",
    r"you are now", r"act as (a |an |if you)",
    r"\[system\]", r"jailbreak", r"dan mode", r"developer mode",
    r"override (your )?(instructions?|settings?)",
    r"bypass (your )?(safety|filter)",
]
PII = {
    "email":       r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "phone":       r'\b(\+91|0)?[6-9]\d{9}\b',
    "pan":         r'\b[A-Z]{5}[0-9]{4}[A-Z]\b',
    "aadhar":      r'\b\d{4}\s?\d{4}\s?\d{4}\b',
    "credit_card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
}

def check_injection(q):
    return not any(re.search(p, q.lower()) for p in INJECT)

def redact_pii(text):
    found=[]
    for t,p in PII.items():
        if re.search(p,text):
            found.append(t)
            text=re.sub(p,f"[{t.upper()} REDACTED]",text)
    return text, found


# ── LLM ──────────────────────────────────────────────────────────────
SYS = """You are SmartQnA, an AI assistant answering questions exclusively about smartphones.
Rules:
1. Answer ONLY from the provided context.
2. If context is insufficient say: "I don't have enough information in the uploaded documents."
3. Keep answers factual and concise. Mention the source.
4. Never answer questions unrelated to smartphones.
5. Use conversation history to resolve follow-up questions."""

def build_messages(query, chunks, history):
    msgs = [{"role":"system","content":SYS}]
    for t in (history[-6:] if len(history)>6 else history):
        msgs.append({"role":t["role"],"content":t["content"]})
    if chunks:
        ctx=""
        for i,c in enumerate(chunks,1):
            # Group A uses "answer" field for content
            content = c.get("answer", c.get("content",""))[:600]
            src     = c.get("file", c.get("file_name","Unknown"))
            ctx    += f"\n--- Source {i}: {src} ---\n{content}\n"
        msgs.append({"role":"system","content":f"Context:\n{ctx}"})
    msgs.append({"role":"user","content":query})
    return msgs

async def llm_stream(messages) -> AsyncGenerator[str, None]:
    headers={"Authorization":f"Bearer {LLM_API_KEY}","Content-Type":"application/json"}
    body={"model":LLM_MODEL,"messages":messages,"temperature":0.1,"max_tokens":512,"stream":True}
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST",f"{LLM_BASE_URL}/chat/completions",
                                  headers=headers,json=body) as resp:
            if resp.status_code!=200:
                yield f"data: {json.dumps({'error':f'LLM error {resp.status_code}'})}\n\n"
                return
            async for line in resp.aiter_lines():
                if not line.startswith("data: "): continue
                data=line[6:].strip()
                if data=="[DONE]":
                    yield "data: [DONE]\n\n"; return
                try:
                    token=json.loads(data)["choices"][0].get("delta",{}).get("content","")
                    if token: yield f"data: {json.dumps({'token':token})}\n\n"
                except: continue

async def llm_full(messages) -> str:
    headers={"Authorization":f"Bearer {LLM_API_KEY}","Content-Type":"application/json"}
    body={"model":LLM_MODEL,"messages":messages,"temperature":0.1,"max_tokens":512,"stream":False}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r=await client.post(f"{LLM_BASE_URL}/chat/completions",headers=headers,json=body)
    if r.status_code!=200:
        raise HTTPException(502,f"LLM error: {r.status_code}")
    return r.json()["choices"][0]["message"]["content"].strip()


# ── Models ────────────────────────────────────────────────────────────
class HistMsg(BaseModel):
    role: str; content: str

class ChatRequest(BaseModel):
    query:        str
    history:      List[HistMsg] = []
    domain:       Optional[str] = None
    user_domains: List[str]     = []   # from JWT/session — restricts search
    brand_filter: Optional[str] = None
    stream:       bool          = False


# ── Pipeline ──────────────────────────────────────────────────────────
async def pipeline(body: ChatRequest):
    if not check_injection(body.query):
        logger.warning(f"Prompt injection blocked: '{body.query[:60]}'")
        return {"block":{"answer":"Blocked for security reasons.",
                         "guardrail_triggered":True,"block_reason":"injection",
                         "sources":[],"confidence":0.0}}

    clean, pii = redact_pii(body.query)
    if pii:
        logger.info(f"PII redacted from query: {pii}")

    if not input_guardrail(clean):
        logger.info(f"Guardrail triggered for off-topic query: '{clean[:60]}'")
        return {"block":{"answer":"SmartQnA only answers smartphone-related questions.",
                         "guardrail_triggered":True,"block_reason":"off_topic",
                         "sources":[],"confidence":0.0,"pii_detected":bool(pii)}}

    # Use first user domain if no specific domain passed
    domain = body.domain
    if not domain and body.user_domains:
        domain = body.user_domains[0]

    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(f"{SEARCH_SERVICE_URL}/search",
                             json={"query":clean,"top_k":5,
                                   "domain_filter":domain,
                                   "brand_filter":body.brand_filter})
        chunks = r.json().get("results", [])
        logger.info(f"Search returned {len(chunks)} chunks for: '{clean[:60]}'")
    except Exception as e:
        logger.error(f"Search service unavailable: {e}")
        raise HTTPException(503,f"Search unavailable: {e}")

    seen=set(); sources=[]
    for ch in chunks[:3]:
        fn=ch.get("file",ch.get("file_name",""))
        if fn and fn not in seen:
            sources.append({"document":fn,"url":"",
                            "category":ch.get("category",""),
                            "score":ch.get("score",0)})
            seen.add(fn)

    confidence = chunks[0].get("score",0.0) if chunks else 0.0
    history    = [{"role":m.role,"content":m.content} for m in body.history]
    messages   = build_messages(clean, chunks, history)

    return {"block":None,"messages":messages,"chunks":chunks,
            "sources":sources,"confidence":confidence,
            "pii_detected":bool(pii),"clean_query":clean}


# ── Endpoints ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status":"ok","service":"completions","version":"2.0.0"}

@app.post("/chat")
async def chat(body: ChatRequest):
    logger.info(f"Chat request: '{body.query[:60]}' | stream:{body.stream} | "
                f"domains:{body.user_domains}")

    p = await pipeline(body)
    if p.get("block"):
        return p["block"]

    messages=p["messages"]; sources=p["sources"]
    confidence=p["confidence"]; pii=p["pii_detected"]
    clean=p["clean_query"]
    filters={"domain":body.domain,"brand":body.brand_filter}

    # ── Streaming ─────────────────────────────────────────────────────
    if body.stream:
        async def gen():
            yield f"data: {json.dumps({'type':'meta','sources':sources,'confidence':round(confidence,3),'pii_detected':pii})}\n\n"
            full=""
            async for chunk in llm_stream(messages):
                yield chunk
                if chunk.startswith("data: ") and "[DONE]" not in chunk:
                    try: full+=json.loads(chunk[6:]).get("token","")
                    except: pass
            if full:
                cache.set(clean,filters,{"answer":full,"sources":sources,
                           "confidence":round(confidence,3),"guardrail_triggered":False,
                           "pii_detected":pii})
                logger.info(f"Streamed response cached | confidence:{confidence:.2f}")
        return StreamingResponse(gen(),media_type="text/event-stream",
                                 headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    # ── Non-streaming ─────────────────────────────────────────────────
    hit=cache.get(clean,filters)
    if hit:
        logger.info(f"Cache HIT for: '{clean[:60]}'")
        hit["cache_hit"]=True; return hit

    if not p["chunks"]:
        return {"answer":"I don't have enough information in the uploaded documents.",
                "sources":[],"confidence":0.0,"guardrail_triggered":False,
                "pii_detected":pii,"cache_hit":False}

    answer=await llm_full(messages)
    logger.info(f"LLM response generated | confidence:{confidence:.2f}")

    result={"answer":answer,"sources":sources,"confidence":round(confidence,3),
            "guardrail_triggered":False,"pii_detected":pii,"cache_hit":False}
    cache.set(clean,filters,result)
    return result
