"""
파이프라인 전체 로깅 모듈.
벡터 검색, SQL 생성, SQL 실행, UI 결정 등 모든 중간 결과를 추적한다.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from config import LOG_DIR, LOG_LEVEL

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# 파이프라인 로거 (파일 + 콘솔)
pipeline_logger = logging.getLogger("pipeline")
pipeline_logger.setLevel(getattr(logging, LOG_LEVEL))

file_handler = logging.FileHandler(
    os.path.join(LOG_DIR, "pipeline.log"), encoding="utf-8"
)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
pipeline_logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
)
pipeline_logger.addHandler(console_handler)


class QueryTracer:
    """한 번의 질의 파이프라인 전체를 추적하는 트레이서."""

    def __init__(self, question: str):
        self.trace_id = uuid.uuid4().hex[:12]
        self.question = question
        self.started_at = datetime.now().isoformat()
        self.steps: list[dict] = []

    def log_step(self, step: str, data: dict):
        entry = {
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        self.steps.append(entry)
        pipeline_logger.info(
            f"[{self.trace_id}] {step}: {json.dumps(data, ensure_ascii=False, default=str)[:5000]}"
        )

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "started_at": self.started_at,
            "steps": self.steps,
        }
