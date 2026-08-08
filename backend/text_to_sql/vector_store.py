"""
ChromaDB 벡터 저장소.
DDL, SQL, 문서를 임베딩하여 저장하고, 자연어 질문으로 관련 컨텍스트를 검색한다.
"""

import re
from pathlib import Path

import chromadb
import yaml

from config import CHROMA_PERSIST_DIR
from logger import pipeline_logger
from text_to_sql.embedding import korean_embedding

from config import domain_dir, DOMAIN
TRAINING_DATA_DIR = domain_dir() / "training_data"
OVERLAY_DIR = TRAINING_DATA_DIR / "overlay"
WEIGHTS_PATH = Path(__file__).parent / "retrieval_weights.yaml"

_weights_cache: dict = {}
_weights_mtime: float = 0.0


def load_retrieval_weights() -> dict:
    """retrieval_weights.yaml 핫리로드. {type: {per_type_n, weight, inject_limit}}"""
    global _weights_cache, _weights_mtime
    try:
        m = WEIGHTS_PATH.stat().st_mtime
        if m != _weights_mtime or not _weights_cache:
            _weights_cache = yaml.safe_load(WEIGHTS_PATH.read_text(encoding="utf-8")) or {}
            _weights_mtime = m
    except FileNotFoundError:
        _weights_cache = {}
    return _weights_cache


def reload_retrieval_weights() -> dict:
    global _weights_mtime
    _weights_mtime = 0.0
    return load_retrieval_weights()


class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        self.collection = self.client.get_or_create_collection(
            name=DOMAIN,
            metadata={"hnsw:space": "cosine"},
            embedding_function=korean_embedding,
        )
        pipeline_logger.info(
            f"ChromaDB 초기화 완료 (문서 수: {self.collection.count()})"
        )

    def count(self) -> int:
        return self.collection.count()

    def train(self):
        """동기 wrapper — train_stream() 을 끝까지 소비 후 최종 결과만 반환."""
        last = None
        for ev in self.train_stream():
            if ev.get("phase") == "done":
                last = ev
        return {"total": (last or {}).get("total", 0)}

    def train_stream(self):
        """진행 상황을 yield 하는 generator. SSE 로 스트리밍 가능."""
        # 기존 데이터 삭제
        existing = self.collection.get()
        if existing["ids"]:
            self.collection.delete(ids=existing["ids"])
            yield {"phase": "delete", "message": f"기존 벡터 데이터 {len(existing['ids'])}건 삭제"}
        else:
            yield {"phase": "delete", "message": "기존 벡터 데이터 없음"}

        documents = []
        metadatas = []
        ids = []
        idx = 0

        # training_data 디렉토리의 모든 .sql / .md 파일 자동 로드
        # - *.sql 중 "-- [테이블]" 블록을 포함하면 DDL로 분류, 아니면 SQL 패턴으로 분류
        # - *.md 는 문서로 분류, "## " 섹션 단위 청킹
        # - GUIDE.md 는 사람용 가이드라 제외
        EXCLUDE = {"GUIDE.md"}

        # 1) 베이스 파일
        files = sorted(
            [p for p in TRAINING_DATA_DIR.glob("*") if p.suffix in {".sql", ".md"} and p.name not in EXCLUDE]
        )
        yield {"phase": "load_files", "message": f"학습 파일 {len(files)}개 로드 시작"}
        for fi, path in enumerate(files, 1):
            content = path.read_text(encoding="utf-8")
            source = path.name

            if path.suffix == ".sql":
                if "-- [테이블]" in content:
                    blocks = re.split(r"\n(?=-- \[테이블\])", content)
                    doc_type = "ddl"
                else:
                    blocks = re.split(r"\n(?=-- Q:|## )", content)
                    doc_type = "sql"
            else:  # .md
                blocks = re.split(r"\n(?=## )", content)
                # 파일명에 sql_pattern 또는 _queries 가 들어가면 SQL 타입으로 분류
                if "sql_pattern" in path.stem.lower() or "queries" in path.stem.lower():
                    doc_type = "sql"
                else:
                    doc_type = "doc"

            count = 0
            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                documents.append(block)
                metadatas.append({"type": doc_type, "source": source})
                ids.append(f"{doc_type}_{idx}")
                idx += 1
                count += 1
            pipeline_logger.info(f"{source} → {count}개 청크 ({doc_type})")
            yield {"phase": "load_files", "message": f"{source} → {count}개 청크 ({doc_type})", "current": fi, "total": len(files)}

        # 2) overlay 파일 (사용자 추가/보강)
        if OVERLAY_DIR.exists():
            overlay_files = sorted(OVERLAY_DIR.glob("*.md"))
            for path in overlay_files:
                content = path.read_text(encoding="utf-8").strip()
                if not content:
                    continue
                # frontmatter 파싱 (간단)
                meta_extra: dict[str, str] = {}
                body = content
                if content.startswith("---\n"):
                    end = content.find("\n---\n", 4)
                    if end != -1:
                        fm = content[4:end]
                        body = content[end + 5 :].strip()
                        for line in fm.splitlines():
                            if ":" in line:
                                k, v = line.split(":", 1)
                                meta_extra[k.strip()] = v.strip()
                action = meta_extra.get("action", "add")  # add | patch
                target_chunk_id = meta_extra.get("target_chunk_id", "")
                doc_type = "doc_patch" if action == "patch" else "doc_overlay"

                documents.append(body)
                metadatas.append(
                    {
                        "type": doc_type,
                        "source": f"overlay/{path.name}",
                        "target_chunk_id": target_chunk_id,
                    }
                )
                ids.append(f"overlay_{idx}")
                idx += 1
            pipeline_logger.info(f"overlay {len(overlay_files)}개 파일 로드")
            yield {"phase": "load_overlay", "message": f"overlay {len(overlay_files)}개 파일 로드"}

        # 3) 가상 view 카탈로그 (메타만 임베딩, SQL 본문 제외)
        try:
            from text_to_sql.virtual_view_store import list_views
            views = list_views()
            for v in views:
                documents.append(v.embedding_text())
                metadatas.append({"type": "virtual_view", "source": v.meta_path.name, "view_id": v.id})
                ids.append(f"vview_{v.id}")
                idx += 1
            pipeline_logger.info(f"가상 view {len(views)}건 임베딩")
            yield {"phase": "load_views", "message": f"가상 view {len(views)}건 메타 로드"}
        except Exception as e:
            pipeline_logger.warning(f"가상 view 임베딩 스킵: {e}")
            yield {"phase": "load_views", "message": f"가상 view 스킵: {e}"}

        if documents:
            yield {"phase": "embed", "message": f"임베딩 인코딩 중... ({len(documents)}건, 모델 호출)"}
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
            )
            pipeline_logger.info(f"벡터 저장소에 총 {len(documents)}건 저장 완료")
            yield {"phase": "save", "message": f"벡터 저장소에 {len(documents)}건 저장 완료"}

        yield {"phase": "done", "total": len(documents), "message": f"재임베딩 완료 — 총 {len(documents)}건"}

    # 하위 호환용 (admin/test에서 참조 가능) — 실제 동작은 retrieval_weights.yaml 기준
    @property
    def INJECT_LIMITS(self) -> dict[str, int]:
        return {k: v.get("inject_limit", 3) for k, v in load_retrieval_weights().items()}

    def search(self, question: str, n_results: int | None = None) -> dict:
        """
        타입별 분리 검색 + 가중치 + inject_limit.

        - 각 타입을 chroma 에 별도 query 로 던져 per_type_n 후보를 받는다.
        - effective_distance = cosine_distance * weight (낮을수록 우선)
        - 같은 타입 안에서 effective_distance 정렬 → inject_limit 으로 자른다.
        - patch 부스팅은 회수된 청크 ID 기준으로 별도 강제 포함.
        """
        weights = load_retrieval_weights()
        if not weights:
            pipeline_logger.warning("retrieval_weights.yaml 비어있음 — 기본 검색 fallback")
            weights = {
                "ddl": {"per_type_n": 8, "weight": 1.0, "inject_limit": 3},
                "sql": {"per_type_n": 6, "weight": 1.0, "inject_limit": 3},
                "doc": {"per_type_n": 8, "weight": 1.0, "inject_limit": 4},
            }

        classified: dict[str, list] = {t: [] for t in weights.keys()}
        retrieved_ids: set[str] = set()

        for doc_type, cfg in weights.items():
            per_n = int(cfg.get("per_type_n", 5))
            weight = float(cfg.get("weight", 1.0))
            inject_limit = int(cfg.get("inject_limit", 3))
            try:
                results = self.collection.query(
                    query_texts=[question],
                    n_results=per_n,
                    where={"type": doc_type},
                )
            except Exception as e:
                pipeline_logger.debug(f"타입 {doc_type} 검색 실패: {e}")
                continue
            if not results["documents"] or not results["documents"][0]:
                continue
            items: list[dict] = []
            for doc_id, doc, meta, distance in zip(
                results["ids"][0],
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                eff = distance * weight
                items.append({
                    "content": doc,
                    "distance": distance,
                    "effective_distance": eff,
                    "weight": weight,
                    "source": meta.get("source", ""),
                })
                retrieved_ids.add(doc_id)
            items.sort(key=lambda x: x["effective_distance"])
            classified[doc_type] = items[:inject_limit]

        # patch 부스팅
        try:
            patch_results = self.collection.get(
                where={"type": "doc_patch"},
                include=["documents", "metadatas"],
            )
            for pid, pdoc, pmeta in zip(
                patch_results["ids"], patch_results["documents"], patch_results["metadatas"]
            ):
                tgt = pmeta.get("target_chunk_id", "")
                if tgt and tgt in retrieved_ids and pid not in retrieved_ids:
                    classified.setdefault("doc_patch", []).append(
                        {"content": pdoc, "distance": 0.0, "effective_distance": 0.0,
                         "weight": 0.0, "source": pmeta.get("source", ""), "boosted": True}
                    )
        except Exception as e:
            pipeline_logger.debug(f"patch 부스팅 스킵: {e}")

        pipeline_logger.debug(
            "벡터 검색 결과: " + ", ".join(f"{k}={len(v)}" for k, v in classified.items() if v)
        )
        return classified

    def search_raw(self, question: str, n_results: int = 10) -> dict:
        """
        타입별 분리 검색 결과 (관리자 테스트용 — inject_limit 적용 안 함).
        가중치는 effective_distance 로 함께 표시 — 어떤 것이 결국 우선되는지 비교용.
        """
        weights = load_retrieval_weights()
        if not weights:
            return {}

        classified: dict[str, list] = {t: [] for t in weights.keys()}
        for doc_type, cfg in weights.items():
            per_n = max(int(cfg.get("per_type_n", 5)), n_results)  # 관리자 화면은 더 많이 보여줌
            weight = float(cfg.get("weight", 1.0))
            try:
                results = self.collection.query(
                    query_texts=[question],
                    n_results=per_n,
                    where={"type": doc_type},
                )
            except Exception as e:
                pipeline_logger.debug(f"타입 {doc_type} 검색 실패: {e}")
                continue
            if not results["documents"] or not results["documents"][0]:
                continue
            items = []
            for doc, meta, distance in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                items.append({
                    "content": doc,
                    "distance": distance,
                    "effective_distance": distance * weight,
                    "weight": weight,
                    "source": meta.get("source", ""),
                })
            items.sort(key=lambda x: x["effective_distance"])
            classified[doc_type] = items
        return classified

    def get_all_documents(self) -> list[dict]:
        """저장된 모든 문서를 반환한다 (관리자 화면용)."""
        result = self.collection.get(include=["documents", "metadatas"])
        docs = []
        for doc_id, doc, meta in zip(result["ids"], result["documents"], result["metadatas"]):
            docs.append({"id": doc_id, "content": doc, "type": meta.get("type"), "source": meta.get("source")})
        return docs


vector_store = VectorStore()
