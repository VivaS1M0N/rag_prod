import os
import time
from typing import List

from dotenv import load_dotenv
from llama_index.core.node_parser import SentenceSplitter
from openai import OpenAI

load_dotenv()

client = OpenAI()

# Embeddings
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-large").strip()
EMBED_DIMENSION = int(os.getenv("EMBED_DIMENSION", "3072"))

# Tuning (avoid 400 payload too large / rate limits)
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", "4"))
EMBED_RETRY_BASE_S = float(os.getenv("EMBED_RETRY_BASE_S", "1.5"))

# Chunking
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def _extract_text_pypdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            parts.append(txt)
    return "\n\n".join(parts)


def _extract_text_pymupdf(path: str) -> str:
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    parts = []
    for page in doc:
        txt = page.get_text("text") or ""
        if txt.strip():
            parts.append(txt)
    return "\n\n".join(parts)


def extract_text_from_pdf(path: str) -> str:
    """Robust PDF text extraction.

    We prefer pypdf (pure python). If it fails or returns empty, try PyMuPDF.
    """
    # 1) pypdf
    try:
        txt = _extract_text_pypdf(path)
        if txt and txt.strip():
            return txt
        print("[RAG] pypdf returned empty text, trying PyMuPDF...")
    except Exception as e:
        print(f"[RAG] pypdf failed: {e}. Trying PyMuPDF...")

    # 2) pymupdf
    try:
        txt = _extract_text_pymupdf(path)
        if txt and txt.strip():
            return txt
    except Exception as e:
        print(f"[RAG] PyMuPDF failed: {e}.")

    raise RuntimeError(
        "No pude extraer texto del PDF. Instala dependencias: pip install pypdf pymupdf"
    )


def load_and_chunk_pdf(path: str) -> List[str]:
    text = extract_text_from_pdf(path)
    if not text.strip():
        return []
    # SentenceSplitter returns list[str]
    chunks = splitter.split_text(text)
    # Remove extremely small chunks
    return [c.strip() for c in chunks if c and c.strip() and len(c.strip()) > 20]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Create embeddings in safe batches + retry.

    Returns: list of vectors aligned with input order.
    """
    if not texts:
        return []

    vectors: List[List[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start:start + EMBED_BATCH_SIZE]

        last_err = None
        for attempt in range(EMBED_MAX_RETRIES + 1):
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=batch)
                vectors.extend([item.embedding for item in resp.data])
                last_err = None
                break
            except Exception as e:
                last_err = e
                # Backoff
                sleep_s = EMBED_RETRY_BASE_S * (2 ** attempt)
                print(f"[RAG] embed batch failed (attempt {attempt+1}): {e} | sleeping {sleep_s:.1f}s")
                time.sleep(sleep_s)

        if last_err is not None:
            raise RuntimeError(f"Fallo creando embeddings (batch {start}-{start+len(batch)}): {last_err}")

    return vectors
