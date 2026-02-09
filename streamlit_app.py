import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Viva AI Assistant", page_icon="💬", layout="wide")

# -----------------------
# UI polish (CSS)
# -----------------------
st.markdown(
    """
<style>
/* -------------------------
   Viva Brand Kit (UI)
   ------------------------- */
:root {
  --viva-bg: #0b0e14;
  --viva-bg-2: #121826;
  --viva-surface: rgba(255, 255, 255, 0.06);
  --viva-surface-2: rgba(255, 255, 255, 0.10);
  --viva-border: rgba(255, 255, 255, 0.10);
  --viva-text: rgba(255, 255, 255, 0.92);
  --viva-muted: rgba(255, 255, 255, 0.66);
  --viva-accent: #ff2d55;
  --viva-accent-2: #6ee7ff;
  --viva-radius: 18px;
  --viva-radius-sm: 12px;
  --viva-shadow: 0 14px 40px rgba(0, 0, 0, 0.35);
}

/* App background */
div[data-testid="stAppViewContainer"] {
  background: radial-gradient(900px 500px at 8% 10%, rgba(255, 45, 85, 0.18), transparent 55%),
              radial-gradient(800px 520px at 85% 0%, rgba(110, 231, 255, 0.14), transparent 55%),
              linear-gradient(180deg, var(--viva-bg) 0%, var(--viva-bg-2) 100%) !important;
  color: var(--viva-text);
}

/* Main block container spacing so the chat input never covers content */
section.main > div.block-container {
  padding-bottom: 9.5rem !important;
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: rgba(0, 0, 0, 0.22) !important;
  border-right: 1px solid var(--viva-border);
  backdrop-filter: blur(10px);
}
section[data-testid="stSidebar"] * {
  color: var(--viva-text);
}

/* Generic cards */
.viva-card {
  background: var(--viva-surface);
  border: 1px solid var(--viva-border);
  border-radius: var(--viva-radius);
  padding: 14px 14px;
  box-shadow: var(--viva-shadow);
}
.viva-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 999px;
  background: rgba(255,255,255,0.08);
  border: 1px solid var(--viva-border);
  color: var(--viva-text);
  font-size: 0.92rem;
}
.viva-muted {
  color: var(--viva-muted);
}

/* Buttons - Streamlit */
div[data-testid="stButton"] button {
  border-radius: 999px !important;
  border: 1px solid rgba(255,255,255,0.18) !important;
  background: rgba(255,255,255,0.08) !important;
  color: var(--viva-text) !important;
  padding: 0.55rem 0.9rem !important;
  transition: transform 0.05s ease, background 0.15s ease, border-color 0.15s ease;
}
div[data-testid="stButton"] button:hover {
  background: rgba(255,255,255,0.12) !important;
  border-color: rgba(255,255,255,0.28) !important;
}
div[data-testid="stButton"] button:active {
  transform: translateY(1px);
}

/* Link-buttons (HTML anchors) */
a.viva-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(255,255,255,0.08);
  color: var(--viva-text) !important;
  padding: 0.55rem 0.9rem;
  text-decoration: none !important;
}
a.viva-btn:hover {
  background: rgba(255,255,255,0.12);
  border-color: rgba(255,255,255,0.28);
}
a.viva-btn-primary {
  background: linear-gradient(135deg, rgba(255,45,85,1) 0%, rgba(255,122,24,1) 100%);
  border: none;
}

/* Tabs */
button[data-baseweb="tab"] {
  color: var(--viva-muted) !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
  color: var(--viva-text) !important;
}

/* Selectbox & inputs */
div[data-baseweb="select"] > div {
  border-radius: var(--viva-radius-sm) !important;
  background: rgba(255,255,255,0.06) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
}
input, textarea {
  caret-color: var(--viva-accent);
}

/* Chat input: keep Streamlit layout, only style */
div[data-testid="stChatInput"] {
  border-top: 1px solid var(--viva-border);
  background: rgba(11, 14, 20, 0.72);
  backdrop-filter: blur(12px);
}
div[data-testid="stChatInput"] textarea {
  border-radius: 18px !important;
  min-height: 48px !important;
  max-height: 180px !important; /* allows growth */
  background: rgba(255,255,255,0.06) !important;
  border: 1px solid rgba(255,255,255,0.12) !important;
  color: var(--viva-text) !important;
}

/* File uploader */
div[data-testid="stFileUploaderDropzone"] {
  border-radius: var(--viva-radius) !important;
  border: 1px dashed rgba(255,255,255,0.20) !important;
  background: rgba(255,255,255,0.04) !important;
}

/* Make default markdown links less "blue" */
a {
  color: var(--viva-accent-2) !important;
}
a:hover {
  opacity: 0.9;
}
</style>
    """,
    unsafe_allow_html=True
)

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_TENANT_ID = os.getenv("TENANT_ID", "viva")

AUTH_MODE = os.getenv("AUTH_MODE", "prod").strip().lower()  # prod | dev
AVAILABLE_MODELS = [m.strip() for m in os.getenv("AVAILABLE_CHAT_MODELS", os.getenv("LLM_MODEL", "gpt-4o-mini")).split(",") if m.strip()]
DEFAULT_MODEL = os.getenv("LLM_MODEL", AVAILABLE_MODELS[0] if AVAILABLE_MODELS else "gpt-4o-mini")

# -----------------------
# Helpers
# -----------------------
def _headers_lower() -> Dict[str, str]:
    try:
        hdrs = getattr(st, "context").headers  # Streamlit >= 1.35
        return {str(k).lower(): str(v) for k, v in (hdrs or {}).items()}
    except Exception:
        return {}

def get_user_email() -> Optional[str]:
    h = _headers_lower()
    email = h.get("x-forwarded-email") or h.get("x-auth-request-email") or h.get("x-user-email")
    if email:
        return email.strip().lower()
    return None


def get_public_base_url() -> str:
    """Best-effort public base URL (behind Nginx)."""
    h = _headers_lower()
    # Streamlit sometimes provides Host without proto; we try forwarded proto
    host = h.get("host")
    proto = h.get("x-forwarded-proto") or "https"
    if host:
        return f"{proto}://{host}"
    return os.getenv("PUBLIC_BASE_URL", "").rstrip("/")


def is_embedded() -> bool:
    try:
        return bool(getattr(st, "context").is_embedded)
    except Exception:
        return False

def api_get(path: str, user_email: str, params: Optional[dict] = None) -> requests.Response:
    return requests.get(
        f"{BACKEND_BASE_URL}{path}",
        params=params or {},
        headers={"X-User-Email": user_email},
        timeout=60,
    )

def api_post(path: str, user_email: str, json_body: Optional[dict] = None, files=None, data=None) -> requests.Response:
    return requests.post(
        f"{BACKEND_BASE_URL}{path}",
        json=json_body,
        files=files,
        data=data,
        headers={"X-User-Email": user_email},
        timeout=300,
    )

def fmt_ts(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)

# -----------------------
# Identity / Auth
# -----------------------
user_email = get_user_email()

if not user_email:
    # Dev fallback so you puedas probar local sin Nginx/oauth2-proxy
    if AUTH_MODE == "dev":
        st.warning("AUTH_MODE=dev: no se detectó email desde headers. Escribe tu correo para simular login.")
        user_email = st.text_input("Correo (solo para desarrollo)", value=os.getenv("DEV_EMAIL", "dev@vivalandscapedesign.com")).strip().lower()
    else:
        st.error(
            "No se detectó usuario autenticado.\n\n"
            "Si estás en producción, esto normalmente significa que falta el proxy de autenticación (Nginx + oauth2-proxy) "
            "o que estás entrando directo al puerto de Streamlit.\n\n"
            "✅ Entra por el dominio/URL principal (Nginx), no por :8501."
        )
        st.stop()

# Backend 'me' check (valida dominio + (opcional) ClickUp membership)
me = None
is_admin = False
try:
    r = api_get("/api/auth/me", user_email=user_email, params={"tenant_id": DEFAULT_TENANT_ID})
    if r.status_code != 200:
        st.error(f"Acceso denegado: {r.status_code} {r.text}")
        st.stop()
    me = r.json()
    is_admin = bool(me.get("is_admin", False))
except Exception as e:
    st.error(f"No pude validar tu acceso con el backend: {e}")
    st.stop()

# -----------------------
# Session state init
# -----------------------
if "tenant_id" not in st.session_state:
    st.session_state.tenant_id = DEFAULT_TENANT_ID

if "model" not in st.session_state:
    st.session_state.model = DEFAULT_MODEL

if "top_k" not in st.session_state:
    st.session_state.top_k = 5

if "show_sources" not in st.session_state:
    st.session_state.show_sources = True

# session_id is the "conversation id" (stored in DB)
if "session_id" not in st.session_state:
    # Create a new session in backend (so it can be listed later)
    try:
        resp = api_post("/api/session/new", user_email=user_email, json_body={"tenant_id": st.session_state.tenant_id})
        st.session_state.session_id = resp.json().get("session_id") or str(uuid.uuid4())
    except Exception:
        st.session_state.session_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Hola 👋 Soy el asistente interno de Viva Landscape & Design.\n\n"
                       "• Puedes chatear conmigo en cualquier momento.\n"
                       "• Si necesitas contexto, sube PDFs con el ícono 📎.\n"
                       "• Los PDFs **temporales** solo viven unas horas y no quedan para siempre.",
        }
    ]

# -----------------------
# Sidebar: profile + conversations + settings
# -----------------------
with st.sidebar:
    st.markdown("## Viva AI")
    st.caption("Asistente interno con RAG (PDFs + conocimiento).")

        # Logout URL: if nginx has /logout mapped, use that; else oauth2-proxy sign_out
    logout_url = "/logout"  # nginx should route /logout to /oauth2/sign_out

    role_label = "🛡️ Admin" if is_admin_user else "👥 Equipo"

    st.markdown(
        f"""
<div class="viva-card">
  <div class="viva-muted" style="font-size:0.9rem; margin-bottom:10px;">Sesión</div>
  <div class="viva-pill">👤 {user_email}</div>
  <div style="height:10px;"></div>
  <div class="viva-pill" style="opacity:0.9;">{role_label}</div>
  <div style="height:12px;"></div>
  <a class="viva-btn" href="{logout_url}" target="_self">🚪 Cerrar sesión</a>
</div>
""",
        unsafe_allow_html=True,
    )

    if is_embedded():
        st.info("Estás viendo el app embebido. Si algo no carga (login), abre en una pestaña nueva.")

    st.divider()

    # Conversations
    st.markdown("### Conversaciones")
    sessions = []
    try:
        rs = api_get("/api/sessions", user_email=user_email, params={"tenant_id": st.session_state.tenant_id, "limit": 30})
        if rs.status_code == 200:
            sessions = rs.json().get("sessions", [])
    except Exception:
        sessions = []

    # Build selectbox options
    session_ids = [s.get("session_id") for s in sessions if s.get("session_id")]
    labels = {s.get("session_id"): f"{s.get('title','Conversación')} · {fmt_ts(int(s.get('updated_at',0)))}" for s in sessions}

    # Ensure current session is included
    if st.session_state.session_id not in session_ids:
        session_ids = [st.session_state.session_id] + session_ids
        labels[st.session_state.session_id] = labels.get(st.session_state.session_id, "Conversación actual")

    selected_sid = st.selectbox(
        "Historial",
        options=session_ids,
        index=session_ids.index(st.session_state.session_id) if st.session_state.session_id in session_ids else 0,
        format_func=lambda sid: labels.get(sid, sid),
        label_visibility="collapsed",
    )

    if selected_sid and selected_sid != st.session_state.session_id:
        # Load messages for that session
        try:
            rm = api_get(f"/api/session/{selected_sid}", user_email=user_email, params={"tenant_id": st.session_state.tenant_id})
            if rm.status_code == 200:
                st.session_state.session_id = selected_sid
                st.session_state.messages = rm.json().get("messages", st.session_state.messages)
            else:
                st.warning("No pude cargar esa conversación.")
        except Exception:
            st.warning("No pude cargar esa conversación (error de red).")

    if st.button("➕ Nueva conversación", use_container_width=True):
        try:
            resp = api_post("/api/session/new", user_email=user_email, json_body={"tenant_id": st.session_state.tenant_id})
            st.session_state.session_id = resp.json().get("session_id") or str(uuid.uuid4())
        except Exception:
            st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = [
            {"role": "assistant", "content": "Listo. Empecemos una conversación nueva 🙂"}
        ]
        st.rerun()

    st.divider()

    st.markdown("### Configuración")
    st.session_state.model = st.selectbox("Modelo", options=AVAILABLE_MODELS, index=AVAILABLE_MODELS.index(st.session_state.model) if st.session_state.model in AVAILABLE_MODELS else 0)
    st.session_state.top_k = st.slider("Contextos (top_k)", min_value=1, max_value=15, value=int(st.session_state.top_k))
    st.session_state.show_sources = st.checkbox("Mostrar fuentes", value=bool(st.session_state.show_sources))

    st.divider()

    # Admin-only utilities
    if is_admin:
        with st.expander("🛠️ Admin"):
            if st.button("Purgar temporales vencidos", use_container_width=True):
                try:
                    pr = api_post("/api/purge", user_email=user_email, json_body={"tenant_id": st.session_state.tenant_id})
                    st.success(f"Deleted: {pr.json().get('deleted', 0)}")
                except Exception as e:
                    st.error(str(e))

# -----------------------
# Main layout
# -----------------------
colA, colB = st.columns([0.7, 0.3], vertical_alignment="top")

with colA:
    st.markdown("# 💬 Viva AI Assistant")
    st.caption("Chat interno — PDFs temporales / permanentes (solo admin) + historial de conversaciones.")

with colB:
    # Upload popover (icon-like)
    with st.popover("📎 PDFs", use_container_width=True):
        st.markdown("### Añadir PDFs")
        st.caption("Sube uno o varios PDFs. Puedes arrastrar y soltar dentro del selector.")

        uploaded_files = st.file_uploader(
            "Selecciona PDFs",
            type=["pdf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )

        # Scope selection
        if is_admin:
            scope = st.radio("Tipo de indexado", options=["Temporal", "Permanente"], horizontal=True)
        else:
            scope = "Temporal"
            st.info("Tu cuenta es **usuario**: los PDFs se indexan como **temporales** (no quedan para siempre).")

        ttl_hours = 24
        if scope == "Temporal":
            ttl_hours = st.slider("Duración (horas)", min_value=1, max_value=168, value=24, step=1)
            st.caption("Después de esta duración, los vectores pueden ser purgados automáticamente.")

        if st.button("Indexar PDFs", type="primary", use_container_width=True, disabled=(not uploaded_files)):
            try:
                multipart_files = [("files", (f.name, f.getbuffer(), "application/pdf")) for f in uploaded_files]  # type: ignore
                form_data = {
                    "tenant_id": st.session_state.tenant_id,
                    "session_id": st.session_state.session_id,
                    "scope": "permanent" if scope == "Permanente" else "temporary",
                    "ttl_hours": int(ttl_hours),
                }
                with st.spinner("Indexando..."):
                    r = requests.post(
                        f"{BACKEND_BASE_URL}/api/ingest",
                        files=multipart_files,
                        data=form_data,
                        headers={"X-User-Email": user_email},
                        timeout=600,
                    )
                if r.status_code != 200:
                    st.error(f"Error: {r.status_code} {r.text}")
                else:
                    j = r.json()
                    st.success(f"✅ Listo. Archivos: {', '.join(j.get('files', []))}")
                    if j.get('failed'):
                        st.warning('Algunos archivos fallaron al indexar:')
                        for f in j.get('failed', []):
                            st.write(f"- {f.get('file')}: {f.get('error')}")
                    st.caption(f"Chunks ingeridos: {j.get('ingested', 0)} | scope: {j.get('scope')}")
            except Exception as e:
                st.error(f"Error al indexar PDFs: {e}")

tabs = st.tabs(["💬 Chat", "❓ Ayuda", "🔗 ClickUp (beta)"])

# -----------------------
# Tab: Chat
# -----------------------
with tabs[0]:
    # Render chat history
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    prompt = st.chat_input("Escribe tu mensaje…")

    if prompt:
        prompt = prompt.strip()
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Call backend
        payload = {
            "question": prompt,
            "top_k": int(st.session_state.top_k),
            "tenant_id": st.session_state.tenant_id,
            "session_id": st.session_state.session_id,
            "scope": None,
            "model": st.session_state.model,
        }

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    r = api_post("/api/chat", user_email=user_email, json_body=payload)
                    if r.status_code != 200:
                        st.error(f"Error: {r.status_code} {r.text}")
                        st.stop()
                    data = r.json()
                    answer = data.get("answer", "")
                    sources = data.get("sources", [])
                    st.markdown(answer if answer else "(Sin respuesta)")
                    if st.session_state.show_sources and sources:
                        with st.expander("Fuentes"):
                            for s in sources:
                                st.write(f"- {s}")
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                except Exception as e:
                    st.error(f"Error backend: {e}")

# -----------------------
# Tab: Help / Onboarding
# -----------------------
with tabs[1]:
    st.markdown("## Cómo usar Viva AI")
    st.markdown(
        """
        **1) Ingreso**  
        - En producción, el acceso recomendado es con **Google Workspace** del dominio `@vivalandscapedesign.com`.  
        - Si te abren este app desde ClickUp en un *embed*, puede que el login de Google no cargue dentro del iframe. En ese caso, usa el botón **Abrir en nueva pestaña** (lo agregaremos en `/embed`).

        **2) Chat**  
        - Escribe tu pregunta en la caja de chat.  
        - El asistente buscará contexto en tus PDFs indexados y luego responderá.

        **3) PDFs (📎)**  
        - Sube uno o varios PDFs desde el ícono **📎 PDFs**.  
        - Usuarios normales: los PDFs se indexan como **Temporales**.  
        - Admins: pueden elegir **Permanente**.

        **4) Temporal vs Permanente**  
        - **Temporal**: los vectores se guardan con un `expires_at` (vencimiento).  
        - **Permanente**: no expira (ideal para políticas internas, manuales, etc.).  
        - Recomendación: para pruebas o docs de un cliente puntual, usa Temporal.

        **5) Privacidad**  
        - Evita subir información extremadamente sensible si no es necesario.  
        - Para producción, recomendamos HTTPS y restringir acceso por autenticación.
        """
    )

    st.markdown("## Cómo acceder desde ClickUp")
    st.markdown(
        """
        ✅ Lo más práctico es crear un **Website Embed** en ClickUp apuntando a:

        - `https://TU_DOMINIO/embed/`

        Ese `/embed` muestra un botón para abrir el app principal en una nueva pestaña (donde sí se puede hacer login con Google).
        """
    )

# -----------------------
# Tab: ClickUp (beta)
# -----------------------
with tabs[2]:
    st.markdown("## ClickUp (beta)")
    st.caption("Esto es opcional. Solo funciona si el backend tiene `CLICKUP_API_TOKEN` configurado.")

    list_url_or_id = st.text_input("Pega un List ID o URL de ClickUp (para traer tareas)", placeholder="Ej: https://app.clickup.com/123456/v/li/987654321 ... o 987654321")
    if st.button("Generar resumen de la lista", type="primary"):
        if not list_url_or_id.strip():
            st.warning("Pega un List ID/URL primero.")
        else:
            try:
                resp = api_post(
                    "/api/clickup/list_summary",
                    user_email=user_email,
                    json_body={"tenant_id": st.session_state.tenant_id, "list_id_or_url": list_url_or_id.strip(), "model": st.session_state.model},
                )
                if resp.status_code != 200:
                    st.error(f"Error: {resp.status_code} {resp.text}")
                else:
                    j = resp.json()
                    st.success("Resumen generado")
                    st.markdown(j.get("summary", ""))
                    with st.expander("Detalle"):
                        st.json(j.get("stats", {}))
            except Exception as e:
                st.error(str(e))
