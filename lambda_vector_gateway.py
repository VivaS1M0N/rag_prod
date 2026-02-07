"""AWS Lambda "Vector Gateway" for Qdrant.

Place this Lambda between EC2 (agent) and VectorDB.
Only requires qdrant-client (pure python), so it's lightweight.

Env:
- QDRANT_URL         e.g. http://10.0.1.25:6333  (private IP recommended)
- QDRANT_COLLECTION  docs
- QDRANT_DIM         3072
"""

import os
import time
from typing import Any, Dict

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue, Range

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")
QDRANT_DIM = int(os.getenv("QDRANT_DIM", "3072"))

client = QdrantClient(url=QDRANT_URL, timeout=30)

def _ensure_collection(name: str):
    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=QDRANT_DIM, distance=Distance.COSINE),
        )

def handler(event: Dict[str, Any], context=None):
    action = (event.get("action") or "").lower()
    collection = event.get("collection") or QDRANT_COLLECTION
    _ensure_collection(collection)

    if action == "upsert":
        ids = event["ids"]
        vectors = event["vectors"]
        payloads = event["payloads"]
        points = [PointStruct(id=ids[i], vector=vectors[i], payload=payloads[i]) for i in range(len(ids))]
        client.upsert(collection, points=points)
        return {"ok": True, "upserted": len(points)}

    if action == "search":
        query_vector = event["query_vector"]
        top_k = int(event.get("top_k", 5))
        tenant_id = event["tenant_id"]
        session_id = event["session_id"]
        scope = event.get("scope")
        now = int(event.get("now") or time.time())

        must = [FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id))]

        if scope in ("permanent", "temporary"):
            must.append(FieldCondition(key="scope", match=MatchValue(value=scope)))
            if scope == "temporary":
                must.append(FieldCondition(key="session_id", match=MatchValue(value=session_id)))
                must.append(FieldCondition(key="expires_at", range=Range(gte=now)))
            flt = Filter(must=must)
        else:
            permanent = Filter(must=[FieldCondition(key="scope", match=MatchValue(value="permanent"))])
            temporary = Filter(must=[
                FieldCondition(key="scope", match=MatchValue(value="temporary")),
                FieldCondition(key="session_id", match=MatchValue(value=session_id)),
                FieldCondition(key="expires_at", range=Range(gte=now)),
            ])
            flt = Filter(must=must, should=[permanent, temporary])

        results = client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=flt,
        ).points

        contexts = []
        sources = set()
        for r in results:
            payload = getattr(r, "payload", None) or {}
            text = payload.get("text", "")
            source = payload.get("source", "")
            if text:
                contexts.append(text)
                if source:
                    sources.add(source)

        return {"contexts": contexts, "sources": list(sources)}

    if action == "purge_expired":
        tenant_id = event["tenant_id"]
        now = int(event.get("now") or time.time())
        flt = Filter(must=[
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            FieldCondition(key="scope", match=MatchValue(value="temporary")),
            FieldCondition(key="expires_at", range=Range(lt=now)),
        ])
        client.delete(collection_name=collection, points_selector=flt)
        return {"ok": True, "deleted": 0}

    return {"ok": False, "error": f"Unknown action: {action}"}