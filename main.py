import os
import time
import uuid
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
def chat(
    req: ChatRequest,
    user_email: str = Depends(get_user_email),
):
    question = (req.question or "").strip()
    if not question:
        return {"answer": "Escribe una pregunta.", "sources": [], "num_contexts": 0, "model": validate_model(req.model)}

    model = validate_model(req.model)

    # Optional: keep vector DB clean
    try:
        vector_store.purge_expired(tenant_id=req.tenant_id)
    except Exception:
        pass

    query_vec = embed_texts([question])[0]

    found = vector_store.search(
        query_vector=query_vec,
        top_k=req.top_k,
        tenant_id=req.tenant_id,
        session_id=req.session_id,
        scope=req.scope,
    )

    contexts = found.get("contexts", [])
    sources = found.get("sources", [])

    user_content = build_user_content(question, contexts)

    res = llm_client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=900,
        messages=[
            {"role": "system", "content": "Eres un asistente útil y preciso. Responde con base en los contextos."},
            {"role": "user", "content": user_content},
        ],
    )
    answer = (res.choices[0].message.content or "").strip()

    # Persist chat if enabled
    try:
        chat_store.add_message(req.tenant_id, user_email, req.session_id, role="user", content=question, model=model, sources=[])
        chat_store.add_message(req.tenant_id, user_email, req.session_id, role="assistant", content=answer, model=model, sources=sources)
    except Exception:
        pass

    return {"answer": answer, "sources": sources, "num_contexts": len(contexts), "model": model}

# -----------------------
# ClickUp (beta)
# -----------------------
@app.post("/api/clickup/list_summary", response_model=ClickUpListSummaryResponse)
def clickup_list_summary(
    req: ClickUpListSummaryRequest,
    user_email: str = Depends(get_user_email),
):
    if not CLICKUP_ENABLED:
        raise HTTPException(status_code=400, detail="CLICKUP is not enabled on this backend.")
    list_id = extract_list_id(req.list_id_or_url)
    if not list_id:
        raise HTTPException(status_code=400, detail="Could not extract list_id. Provide a numeric list_id or a valid list URL.")

    model = validate_model(req.model)

    data = get_tasks_from_list(api_token=CLICKUP_API_TOKEN, list_id=list_id, include_closed=True)

    tasks = data.get("tasks", []) or []
    stats: Dict[str, Any] = {
        "total": len(tasks),
        "by_status": {},
        "by_priority": {},
    }

    for t in tasks:
        status = ((t.get("status") or {}).get("status") if isinstance(t.get("status"), dict) else t.get("status")) or "unknown"
        stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

        pr = t.get("priority")
        pr_label = (pr.get("priority") if isinstance(pr, dict) else pr) or "none"
        stats["by_priority"][pr_label] = stats["by_priority"].get(pr_label, 0) + 1

    # Build a concise prompt with only essential fields
    sample = []
    for t in tasks[:60]:
        sample.append(
            {
                "name": t.get("name"),
                "status": (t.get("status") or {}).get("status") if isinstance(t.get("status"), dict) else t.get("status"),
                "due_date": t.get("due_date"),
                "assignees": [a.get("username") for a in (t.get("assignees") or []) if isinstance(a, dict)],
            }
        )

    prompt = (
        "Eres un asistente interno. Genera un resumen ejecutivo en español de la lista de tareas de ClickUp.\n"
        "Incluye:\n"
        "- Estado general (cuántas tareas y distribución por estado)\n"
        "- Riesgos o alertas (si hay muchas overdue o sin due date, menciónalo)\n"
        "- Próximos pasos sugeridos\n\n"
        f"Estadísticas: {stats}\n\n"
        f"Muestra (primeras tareas): {sample}\n"
    )

    res = llm_client.chat.completions.create(
        model=model,
        temperature=0.2,
        max_tokens=700,
        messages=[
            {"role": "system", "content": "Eres un asistente de operaciones. Responde en español, con bullets claros."},
            {"role": "user", "content": prompt},
        ],
    )
    summary = (res.choices[0].message.content or "").strip()

    return {"list_id": list_id, "stats": stats, "summary": summary, "model": model}
