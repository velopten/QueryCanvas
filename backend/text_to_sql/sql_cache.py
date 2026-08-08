"""
SQL 캐시.
이전에 생성된 SQL을 질문과 함께 저장하고,
유사한 질문이 들어오면 AI 호출 없이 기존 SQL을 재활용한다.
"""

import json
import uuid
from datetime import datetime

import chromadb

from config import CHROMA_PERSIST_DIR, DOMAIN
from logger import pipeline_logger
from text_to_sql.embedding import korean_embedding

# 유사도 임계값 (cosine distance) — 이 값 이하면 캐시 히트
# cosine distance: 0 = 완전 동일, 2 = 정반대
# 0.05 = 극도로 엄격 — 거의 동일한 질문만 캐시 히트
CACHE_HIT_THRESHOLD = 0.05


class SqlCache:
    def __init__(self):
        client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.collection = client.get_or_create_collection(
            name=f"sql_cache_{DOMAIN}",
            metadata={"hnsw:space": "cosine"},
            embedding_function=korean_embedding,
        )
        pipeline_logger.info(f"SQL 캐시 초기화 완료 (캐시 수: {self.collection.count()})")

    def count(self) -> int:
        return self.collection.count()

    def lookup(self, question: str) -> dict | None:
        """
        유사한 질문이 캐시에 있으면 해당 SQL을 반환한다.
        Returns: {"sql": str, "original_question": str, "distance": float, "cached_at": str} or None
        """
        if self.collection.count() == 0:
            return None

        results = self.collection.query(
            query_texts=[question],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"] or not results["documents"][0]:
            return None

        distance = results["distances"][0][0]
        metadata = results["metadatas"][0][0]

        if distance <= CACHE_HIT_THRESHOLD:
            pipeline_logger.info(
                f"SQL 캐시 히트! distance={distance:.4f}, "
                f"원본질문=\"{metadata.get('question', '')[:50]}\""
            )
            return {
                "sql": metadata.get("sql", ""),
                "original_question": metadata.get("question", ""),
                "distance": distance,
                "cached_at": metadata.get("cached_at", ""),
                "hit_count": metadata.get("hit_count", 0),
            }

        pipeline_logger.debug(
            f"SQL 캐시 미스 — 최근접 distance={distance:.4f} (임계값: {CACHE_HIT_THRESHOLD})"
        )
        return None

    def store(self, question: str, sql: str):
        """질문-SQL 쌍을 캐시에 저장한다. 동일 질문이면 업데이트."""
        # 기존에 매우 유사한 질문이 있으면 교체
        if self.collection.count() > 0:
            results = self.collection.query(
                query_texts=[question],
                n_results=1,
                include=["distances"],
            )
            if results["distances"] and results["distances"][0]:
                if results["distances"][0][0] <= CACHE_HIT_THRESHOLD:
                    # 기존 캐시 업데이트 (삭제 후 재추가)
                    self.collection.delete(ids=[results["ids"][0][0]])

        cache_id = f"cache_{uuid.uuid4().hex[:8]}"
        self.collection.add(
            documents=[question],
            metadatas=[{
                "question": question,
                "sql": sql,
                "cached_at": datetime.now().isoformat(),
                "hit_count": 0,
            }],
            ids=[cache_id],
        )
        pipeline_logger.info(f"SQL 캐시 저장: \"{question[:50]}\" → {sql[:80]}")

    def get_all(self) -> list[dict]:
        """모든 캐시 항목 반환 (관리자 화면용)."""
        if self.collection.count() == 0:
            return []
        result = self.collection.get(include=["documents", "metadatas"])
        items = []
        for doc_id, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
            items.append({
                "id": doc_id,
                "question": doc,
                "sql": meta.get("sql", ""),
                "cached_at": meta.get("cached_at", ""),
            })
        return items

    def search_raw(self, question: str, n_results: int = 10) -> list[dict]:
        """캐시에서 유사 질문을 검색한다 (관리자 테스트용)."""
        if self.collection.count() == 0:
            return []
        results = self.collection.query(
            query_texts=[question],
            n_results=min(n_results, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        items = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
                items.append({
                    "question": doc,
                    "sql": meta.get("sql", ""),
                    "cached_at": meta.get("cached_at", ""),
                    "distance": dist,
                    "would_hit": dist <= CACHE_HIT_THRESHOLD,
                })
        return items

    def delete(self, cache_id: str):
        self.collection.delete(ids=[cache_id])

    def clear(self):
        """캐시 전체 삭제."""
        existing = self.collection.get()
        if existing["ids"]:
            self.collection.delete(ids=existing["ids"])
        pipeline_logger.info("SQL 캐시 전체 삭제")


sql_cache = SqlCache()
