"""
ChromaDB용 커스텀 임베딩 함수.

EMBEDDING_MODEL 환경변수로 교체할 수 있지만, 차원이 달라지면 기존 컬렉션과
호환되지 않는다 — 교체 시 chroma_data/ 를 지우고 재기동하면 자동 재학습된다.
"""

import os
from chromadb import Documents, EmbeddingFunction, Embeddings
from logger import pipeline_logger

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

_model_instance = None


def _get_model():
    """모델을 lazy load (첫 호출 시에만 다운로드/로드)."""
    global _model_instance
    if _model_instance is None:
        from sentence_transformers import SentenceTransformer
        pipeline_logger.info(f"임베딩 모델 로드 시작: {EMBEDDING_MODEL}")
        _model_instance = SentenceTransformer(EMBEDDING_MODEL)
        pipeline_logger.info(f"임베딩 모델 로드 완료 (dim={_model_instance.get_sentence_embedding_dimension()})")
    return _model_instance


class KoreanEmbeddingFunction(EmbeddingFunction):
    """ChromaDB용 커스텀 임베딩 함수 (한국어 최적화)."""

    def __call__(self, input: Documents) -> Embeddings:
        model = _get_model()
        embeddings = model.encode(
            list(input),
            normalize_embeddings=True,  # cosine 거리 사용 시 권장
            convert_to_numpy=True,
        )
        return embeddings.tolist()


# 싱글톤 인스턴스
korean_embedding = KoreanEmbeddingFunction()
