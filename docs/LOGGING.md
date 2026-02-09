# Logs (API / UI / Nginx / Qdrant)

## 1) Backend FastAPI (rag-api)

Con systemd, lo más fácil es:

```bash
sudo journalctl -u rag-api -f
```

En este bundle, el `main.py` soporta:

- `LOG_LEVEL=INFO`
- `LOG_FILE=/var/log/viva_rag/api.log`

Si defines `LOG_FILE`, se crea un log rotativo (5MB x 5 backups).

## 2) Streamlit (rag-ui)

```bash
sudo journalctl -u rag-ui -f
```

## 3) Nginx

Archivos típicos:
- `/var/log/nginx/access.log`
- `/var/log/nginx/error.log`

Ver en vivo:
```bash
sudo tail -f /var/log/nginx/error.log
```

## 4) Qdrant (Docker)

```bash
docker logs -f qdrant
```

Si ves errores de storage, revisa `docs/QDRANT_FIX.md`.

## 5) Qué buscar cuando sale error 500

- OpenAI:
  - `OPENAI_API_KEY` vacío o incorrecto
  - límites / rate limit
- Qdrant:
  - `failed to open file`
  - `Can't create directory`
  - storage borrado
- ClickUp:
  - token inválido (401/403)
  - list_id incorrecto (404)
  - rate limits

Con este bundle, el API ya devuelve errores más claros (502) y el chat hace *fail-soft* si falla el RAG.
