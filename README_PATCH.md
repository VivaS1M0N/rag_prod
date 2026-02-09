# Viva AI Assistant — Bundle de mejoras (v3)

Este comprimido incluye:

## 1) UI (Streamlit)
- Estética consistente (botones, cards, pills, tabs)
- Logout como botón (no link azul)
- Usuario en un "pill" con estilo
- Chat input flexible (sin hacks de `position: fixed` que chocan con el sidebar)
- Brand kit centralizado en CSS (variables)

Archivo: `streamlit_app.py`

## 2) API (FastAPI)
- Logging configurable por `LOG_LEVEL` y `LOG_FILE`
- Chat *fail-soft*: si Qdrant falla, el chat sigue (sin contexto)
- Errores más claros (502) cuando falla OpenAI o ClickUp
- ClickUp list summary con paginación y payload reducido

Archivo: `main.py`

## 3) AuthZ
- Policy de dominio @vivalandscapedesign.com
- Opción de gating por miembros de una lista de ClickUp (mismo correo)
  - `AUTH_REQUIRE_CLICKUP=true`
  - `CLICKUP_API_TOKEN=...`
  - `CLICKUP_AUTH_LIST_ID=...`

Archivo: `authz.py`

## 4) Login bonito + Embed helper (ClickUp)
Páginas estáticas:
- `web/login/` → login branded (botón "Continuar con Google")
- `web/embed/` → helper para ClickUp embed (abre en pestaña nueva si cookies bloqueadas)
- `web/assets/logo.svg` → logo placeholder reemplazable

## 5) Infra
- Nginx sample: `nginx/aichatbot.conf.sample`
- Qdrant script: `docker/run_qdrant.sh`
- Docs: `docs/`

---

## Variables de entorno clave

- `ALLOWED_EMAIL_DOMAIN=vivalandscapedesign.com`
- `ADMIN_EMAILS=tu@vivalandscapedesign.com,otro@vivalandscapedesign.com`
- `OPENAI_API_KEY=...`
- `QDRANT_URL=http://127.0.0.1:6333`
- `CLICKUP_API_TOKEN=...` (si usas ClickUp)
- `AUTH_REQUIRE_CLICKUP=true` (opcional)
- `CLICKUP_AUTH_LIST_ID=...` (opcional)

---

Lee:
- `docs/QDRANT_FIX.md`
- `docs/GIT_WORKFLOW.md`
- `docs/LOGGING.md`
- `docs/BRAND_KIT.md`
