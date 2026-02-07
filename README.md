# Viva RAG – EC2 + (Optional) Lambda Vector Gateway

This update converts your current Inngest-based demo into a simpler production-style API:

- Streamlit: chat UI + 📎 upload (multi-PDF drag & drop)
- FastAPI: /api/ingest, /api/chat, /api/purge
- VectorDB: Qdrant with "permanent" vs "temporary (per-session + TTL)" scope
- Optional: put AWS Lambda between EC2 and Qdrant (VECTOR_BACKEND=lambda)

See assistant instructions for step-by-step AWS setup.