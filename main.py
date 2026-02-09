import os
import time
import uuid
import logging
from logging.handlers import RotatingFileHandler
import tempfile
from typing import Any, Dict, List, Optional

import requests
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

from data_loader import load_and_chunk_pdf, embed_texts
from vector_db import VectorStore
from authz import is_admin as is_admin_email, is_user_allowed, normalize_email
from chat_store import ChatStore
from clickup_client import extract_list_id, get_tasks_from_list

load_dotenv()

# -----------------------
# Logging
# -----------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", "").strip()  # e.g. /var/log/viva_rag/api.log

_root = logging.getLogger()
_root.setLevel(LOG_LEVEL)

if not _root.handlers:
    _fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _root.addHandler(_sh)

if LOG_FILE:
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        _fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=5)
        _fh.setFormatter(_fmt)
        _root.addHandler(_fh)
    except Exception:
        _root.exception("Failed to configure LOG_FILE handler")

log = logging.getLogger("viva_rag.api")


app = FastAPI(title="Viva RAG API", version="2.0.0")

# IMPORTANT:
# - In production behind Nginx, you can tighten CORS to your domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_TENANT_ID = os.getenv("TENANT_ID", "viva")

LLM_DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
AVAILABLE_CHAT_MODELS = [
    m.strip() for m in os.getenv("AVAILABLE_CHAT_MODELS", LLM_DEFAULT_MODEL).split(",") if m.strip()
]

CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "").strip()
CLICKUP_ENABLED = bool(os.getenv("CLICKUP_ENABLED", "true").strip().lower() == "true" and CLICKUP_API_TOKEN)

llm_client = OpenAI()
vector_store = VectorStore()
chat_store = ChatStore()

# -----------------------
# Auth helpers
# -----------------------
def get_user_email(
    x_user_email: Optional[str] = Header(default=None),
    x_forwarded_email: Optional[str] = Header(default=None),
) -> str:
    email = x_user_email or x_forwarded_email
    if not email:
        # If you're testing locally without auth, you can send X-User-Email manually.
        raise HTTPException(status_code=401, detail="Missing user email (X-User-Email / X-Forwarded-Email).")

    email = normalize_email(email)
    if not is_user_allowed(email):
        raise HTTPException(status_code=403, detail="User is not allowed for this application.")

    return email

def require_admin(user_email: str) -> None:
    if not is_admin_email(user_email):
        raise HTTPException(status_code=403, detail="Admin privileges required.")

def validate_model(model: Optional[str]) -> str:
    m = (model or "").strip()
    if not m:
        return LLM_DEFAULT_MODEL
    if AVAILABLE_CHAT_MODELS and m not in AVAILABLE_CHAT_MODELS:
        # Hard fail to avoid unexpected costs or model misuse
        raise HTTPException(status_code=400, detail=f"Model not allowed: {m}")
    return m

# -----------------------
# Schemas
# -----------------------
class AuthMeResponse(BaseModel):
    email: str
    is_admin: bool
    tenant_id: str

class NewSessionRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID

class NewSessionResponse(BaseModel):
    session_id: str

class ListSessionsResponse(BaseModel):
    sessions: List[Dict[str, Any]]

class GetSessionResponse(BaseModel):
    session_id: str
    messages: List[Dict[str, Any]]

class ChatRequest(BaseModel):
    question: str
    top_k: int = 5
    tenant_id: str = DEFAULT_TENANT_ID
    session_id: str
    scope: Optional[str] = None  # "permanent" | "temporary" | None
    model: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str
    sources: List[str]
    num_contexts: int
    model: str

class PurgeRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID

class PurgeResponse(BaseModel):
    deleted: int

class ClickUpListSummaryRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID
    list_id_or_url: str
    include_closed: bool = True
    max_pages: int = 2  # ClickUp pages (100 tasks per page). 2 pages ≈ 200 tasks
    model: Optional[str] = None

class ClickUpListSummaryResponse(BaseModel):
    list_id: str
    stats: Dict[str, Any]
    summary: str
    model: str

# -----------------------
# Health + Auth
# -----------------------
@app.get("/api/health")
def health():
    return {"ok": True, "time": int(time.time())}

@app.get("/api/auth/me", response_model=AuthMeResponse)
def auth_me(
    tenant_id: str = DEFAULT_TENANT_ID,
    user_email: str = Depends(get_user_email),
):
    return {
        "email": user_email,
        "is_admin": bool(is_admin_email(user_email)),
        "tenant_id": tenant_id,
    }

# -----------------------
# Chat sessions (optional but recommended)
# -----------------------
@app.post("/api/session/new", response_model=NewSessionResponse)
def new_session(
    req: NewSessionRequest,
    user_email: str = Depends(get_user_email),
):
    sid = chat_store.create_session(tenant_id=req.tenant_id, user_email=user_email)
    return {"session_id": sid}

@app.get("/api/sessions", response_model=ListSessionsResponse)
def list_sessions(
    tenant_id: str = DEFAULT_TENANT_ID,
    limit: int = 30,
    user_email: str = Depends(get_user_email),
):
    sessions = chat_store.list_sessions(tenant_id=tenant_id, user_email=user_email, limit=int(limit))
    return {
        "sessions": [
            {
                "tenant_id": s.tenant_id,
                "user_email": s.user_email,
                "session_id": s.session_id,
                "title": s.title,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in sessions
        ]
    }

@app.get("/api/session/{session_id}", response_model=GetSessionResponse)
def get_session(
    session_id: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    user_email: str = Depends(get_user_email),
):
    messages = chat_store.get_messages(tenant_id=tenant_id, user_email=user_email, session_id=session_id)
    # Convert to Streamlit-friendly shape
    st_messages = []
    for m in messages:
        st_messages.append({"role": m.get("role"), "content": m.get("content")})
    return {"session_id": session_id, "messages": st_messages}

# -----------------------
# Vector DB maintenance
# -----------------------
@app.post("/api/purge", response_model=PurgeResponse)
def purge(
    req: PurgeRequest,
    user_email: str = Depends(get_user_email),
):
    # Safe: purge only deletes expired temporals
    deleted = vector_store.purge_expired(tenant_id=req.tenant_id)
    return {"deleted": deleted}

# -----------------------
# Ingest PDFs
# -----------------------
@app.post("/api/ingest")
async def ingest_pdfs(
    files: List[UploadFile] = File(...),
    tenant_id: str = Form(DEFAULT_TENANT_ID),
    session_id: str = Form(...),
    scope: str = Form("temporary"),
    ttl_hours: int = Form(24),
    user_email: str = Depends(get_user_email),
):
    """Index one or many PDFs.

    Common 500 causes are missing PDF dependencies (pypdf/pymupdf) or a too-large embedding request.
    Here we:
      - validate size
      - batch embeddings (done inside embed_texts)
      - capture per-file errors and return them cleanly
    """
    scope = scope if scope in ("temporary", "permanent") else "temporary"
    if scope == "permanent":
        require_admin(user_email)

    max_pdf_mb = int(os.getenv("MAX_PDF_MB", "25"))
    expires_at = int(time.time() + int(ttl_hours) * 3600) if scope == "temporary" else None

    total_ingested = 0
    processed_files: List[str] = []
    failed: List[Dict[str, Any]] = []

    for f in files:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                content = await f.read()
                if content is None:
                    content = b""
                size_mb = len(content) / (1024 * 1024)
                if size_mb > max_pdf_mb:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Archivo demasiado grande ({size_mb:.1f}MB). Máximo permitido: {max_pdf_mb}MB.",
                    )

                tmp.write(content)
                tmp_path = tmp.name

            # 1) Extract + chunk
            chunks = load_and_chunk_pdf(tmp_path)
            if not chunks:
                failed.append({"file": f.filename, "error": "No pude extraer texto (PDF vacío o escaneado sin OCR)."})
                continue

            # 2) Embeddings (batched in data_loader.embed_texts)
            vectors = embed_texts(chunks)
            if len(vectors) != len(chunks):
                raise RuntimeError(f"Embeddings desalineados: chunks={len(chunks)} vectors={len(vectors)}")

            # 3) Prepare Qdrant payloads
            ids: List[str] = []
            payloads: List[Dict[str, Any]] = []
            source_id = f.filename or "uploaded.pdf"
            now_ts = int(time.time())

            for i, text in enumerate(chunks):
                ids.append(str(uuid.uuid4()))
                payloads.append(
                    {
                        "tenant_id": tenant_id,
                        "scope": scope,
                        "session_id": session_id if scope == "temporary" else None,
                        "expires_at": expires_at,
                        "source": source_id,
                        "chunk_index": i,
                        "created_at": now_ts,
                        "uploaded_by": user_email,
                        "text": text,
                    }
                )

            # 4) Upsert
            vector_store.upsert(ids=ids, vectors=vectors, payloads=payloads)

            total_ingested += len(chunks)
            processed_files.append(source_id)

        except HTTPException as he:
            failed.append({"file": f.filename, "error": str(he.detail), "status": he.status_code})
        except Exception as e:
            failed.append({"file": f.filename, "error": str(e)})
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    # Important: do NOT 500 the whole request if one PDF fails.
    return {
        "ingested": total_ingested,
        "files": processed_files,
        "failed": failed,
        "scope": scope,
        "expires_at": expires_at,
    }

# -----------------------
# Chat
# -----------------------
def build_user_content(question: str, contexts: List[str]) -> str:
    context_block = "\n\n".join(f"- {c}" for c in contexts)
    return (
        "Usa los siguientes contextos para responder la pregunta. "
        "Si no hay información suficiente en los contextos, dilo claramente.\n\n"
        f"Contextos:\n{context_block}\n\n"
        f"Pregunta: {question}\n\n"
        "Responde en español, claro, y si aplica agrega bullets."
    )

@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, user_email: str = Depends(get_user_email)):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    model = validate_model(req.model or LLM_DEFAULT_MODEL)

    # Best-effort purge expired temporary points.
    try:
        vector_store.purge_expired(tenant_id=req.tenant_id, scope=req.scope)
    except Exception:
        log.exception("purge_expired failed (non-blocking) tenant=%s scope=%s", req.tenant_id, req.scope)

    # --- RAG retrieval (fail-soft)
    contexts: List[str] = []
    sources: List[str] = []

    try:
        query_vec = embed_texts([question])[0]
        found = vector_store.search(
            tenant_id=req.tenant_id,
            scope=req.scope,
            query_embedding=query_vec,
            top_k=req.top_k,
        )
        contexts = found.get("contexts", []) or []
        sources = found.get("sources", []) or []
    except Exception as e:
        # If Qdrant storage is corrupted or unavailable, don't break chat.
        log.exception("vector search failed (continuing without RAG) tenant=%s scope=%s", req.tenant_id, req.scope)
        contexts = []
        sources = []

    user_content = build_user_content(question, contexts)

    # --- LLM
    try:
        res = llm_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )
        answer = (res.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("LLM call failed model=%s", model)
        raise HTTPException(status_code=502, detail=f"LLM/OpenAI error: {str(e)}") from e

    # Persist conversation (best-effort)
    try:
        session_id = req.session_id or str(uuid.uuid4())
        chat_store.add_message(req.tenant_id, user_email, session_id, role="user", content=question)
        chat_store.add_message(req.tenant_id, user_email, session_id, role="assistant", content=answer)
    except Exception:
        log.exception("chat_store append failed (non-blocking)")

    return ChatResponse(
        answer=answer,
        sources=sources,
        num_contexts=len(contexts),
        model=model,
    )

# -----------------------
# ClickUp (beta)
# -----------------------
@app.post("/api/clickup/list_summary", response_model=ClickUpListSummaryResponse)
def clickup_list_summary(req: ClickUpListSummaryRequest, user_email: str = Depends(get_user_email)) -> ClickUpListSummaryResponse:
    if not CLICKUP_API_TOKEN:
        raise HTTPException(status_code=400, detail="CLICKUP_API_TOKEN not configured")

    list_id = extract_list_id(req.list_id_or_url)
    if not list_id:
        raise HTTPException(status_code=400, detail="Invalid ClickUp list URL/ID")

    include_closed = bool(req.include_closed)
    max_pages = max(1, min(int(req.max_pages or 1), 10))  # safety cap

    tasks: List[Dict[str, Any]] = []
    try:
        for page in range(max_pages):
            data = get_tasks_from_list(
                api_token=CLICKUP_API_TOKEN,
                list_id=list_id,
                include_closed=include_closed,
                include_markdown_description=False,
                page=page,
            )
            page_tasks = data.get("tasks", []) or []
            tasks.extend(page_tasks)
            # Stop early if we reached the end
            if len(page_tasks) == 0:
                break
    except ClickUpAPIError as e:
        log.exception("ClickUp API error list_id=%s", list_id)
        raise HTTPException(status_code=502, detail=str(e)) from e
    except Exception as e:
        log.exception("ClickUp fetch failed list_id=%s", list_id)
        raise HTTPException(status_code=502, detail=f"ClickUp fetch failed: {str(e)}") from e

    sample = [
        {
            "name": t.get("name"),
            "status": (t.get("status") or {}).get("status"),
            "assignees": [a.get("email") for a in (t.get("assignees") or []) if isinstance(a, dict)],
            "due_date": t.get("due_date"),
            "url": t.get("url"),
        }
        for t in tasks[:120]
    ]

    prompt = f"""Eres un PM/operaciones interno de Viva Landscape & Design.
Genera un resumen ejecutivo claro de una lista de ClickUp.

- Resumen de alto nivel (3-6 bullets)
- Riesgos / bloqueos (si detectas por status o vencidos)
- Próximos pasos (3-6 bullets)
- Si hay pocos datos, dilo y sugiere qué información falta.

Datos (muestra):
{sample}
"""

    model = validate_model(req.model or LLM_DEFAULT_MODEL)

    try:
        res = llm_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        summary = (res.choices[0].message.content or "").strip()
    except Exception as e:
        log.exception("LLM call failed for ClickUp summary model=%s", model)
        raise HTTPException(status_code=502, detail=f"LLM/OpenAI error: {str(e)}") from e

    return ClickUpListSummaryResponse(list_id=list_id, summary=summary, tasks_count=len(tasks))

