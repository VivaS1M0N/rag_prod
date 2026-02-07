import os
import time
from typing import List, Dict, Any, Optional

VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "direct").lower()  # direct | lambda
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "docs")
QDRANT_DIM = int(os.getenv("QDRANT_DIM", "3072"))

class VectorStore:
    def __init__(self):
        if VECTOR_BACKEND == "lambda":
            import boto3
            self.lambda_client = boto3.client("lambda", region_name=os.getenv("AWS_REGION"))
            self.lambda_fn = os.getenv("LAMBDA_VECTOR_FN", "rag-vector-gateway")
            self.mode = "lambda"
        else:
            from qdrant_client import QdrantClient
            from qdrant_client.models import VectorParams, Distance

            self.client = QdrantClient(url=QDRANT_URL, timeout=30)
            self.collection = QDRANT_COLLECTION
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=VectorParams(size=QDRANT_DIM, distance=Distance.COSINE),
                )
            self.mode = "direct"

    def upsert(self, ids: List[str], vectors: List[List[float]], payloads: List[Dict[str, Any]]):
        if self.mode == "lambda":
            return self._lambda_invoke({
                "action": "upsert",
                "collection": QDRANT_COLLECTION,
                "ids": ids,
                "vectors": vectors,
                "payloads": payloads,
            })
        from qdrant_client.models import PointStruct
        points = [PointStruct(id=ids[i], vector=vectors[i], payload=payloads[i]) for i in range(len(ids))]
        self.client.upsert(QDRANT_COLLECTION, points=points)
        return {"ok": True, "upserted": len(points)}

    def search(
        self,
        query_vector: List[float],
        top_k: int,
        tenant_id: str,
        session_id: str,
        scope: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = int(time.time())
        if self.mode == "lambda":
            return self._lambda_invoke({
                "action": "search",
                "collection": QDRANT_COLLECTION,
                "query_vector": query_vector,
                "top_k": top_k,
                "tenant_id": tenant_id,
                "session_id": session_id,
                "scope": scope,
                "now": now,
            })

        from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

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

        results = self.client.query_points(
            collection_name=QDRANT_COLLECTION,
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

    def purge_expired(self, tenant_id: str) -> int:
        now = int(time.time())
        if self.mode == "lambda":
            out = self._lambda_invoke({
                "action": "purge_expired",
                "collection": QDRANT_COLLECTION,
                "tenant_id": tenant_id,
                "now": now,
            })
            return int(out.get("deleted", 0) or 0)

        from qdrant_client.models import Filter, FieldCondition, MatchValue, Range
        flt = Filter(must=[
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
            FieldCondition(key="scope", match=MatchValue(value="temporary")),
            FieldCondition(key="expires_at", range=Range(lt=now)),
        ])
        self.client.delete(collection_name=QDRANT_COLLECTION, points_selector=flt)
        return 0

    def _lambda_invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import json
        resp = self.lambda_client.invoke(
            FunctionName=self.lambda_fn,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        raw = resp["Payload"].read().decode("utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}