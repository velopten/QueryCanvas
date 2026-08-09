"""
공개용 정적 스냅샷 생성기 — 실행 중인 백엔드의 GET 엔드포인트를 순회해
frontend/public/api-snapshot/ 아래 JSON 으로 떠 놓는다.

읽기 전용 공개 배포(Cloudflare Pages 등)에서 백엔드 없이 화면이 동작하게 하는 용도.
프론트는 VITE_STATIC=1 일 때 GET /api/<path> 를 /api-snapshot/<path>.json 으로 바꿔 읽는다.

사용법:
    # 백엔드를 먼저 띄운 상태에서
    cd backend && python scripts/snapshot_static.py

환경변수:
    SNAPSHOT_BASE             대상 백엔드 (기본 http://localhost:8008)
    SNAPSHOT_INCLUDE_PROMPTS  1 이면 시스템 프롬프트/PII 매핑을 마스킹하지 않고 그대로 공개
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.getenv("SNAPSHOT_BASE", "http://localhost:8008").rstrip("/")
REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "frontend" / "public" / "api-snapshot"

# 마스킹 대상은 성격이 다른 두 묶음이라 플래그를 나눈다.
#   프롬프트: 공개해도 되는 자산일 수 있음 (포트폴리오 목적 등)
#   PII 매핑: [PERSON_1] → 실명 대응표. 프롬프트가 아니므로 별도로 판단해야 한다
PROMPT_KEYS = {"system_prompt", "user_message"}
PII_KEYS = {"pii_mapping"}

MASK_PROMPTS = os.getenv("SNAPSHOT_INCLUDE_PROMPTS") != "1"
MASK_PII = os.getenv("SNAPSHOT_INCLUDE_PII") != "1"
MASK_TEXT = "(비공개 — 공개 스냅샷에서 제외됨)"

# 파라미터 없이 그대로 뜨는 엔드포인트
STATIC_PATHS = [
    "/api/health",
    "/api/meta",
    "/api/history",
    "/api/views",
    "/api/tables",
    "/api/admin/prompts",
    "/api/admin/training-data",
    "/api/admin/training-data/overlays",
    "/api/admin/sql-cache",
    "/api/admin/settings",
    "/api/admin/traces",
    "/api/admin/feedback-stats",
    "/api/admin/virtual-views",
    "/api/admin/retrieval-weights",
    "/api/admin/eval/results",
    "/api/admin/logs",
]

# (목록 경로, 항목이 담긴 키, 항목의 id 키, 상세 경로 템플릿)
COLLECTIONS = [
    ("/api/history", "items", "id", "/api/history/{}"),
    ("/api/admin/traces", "traces", "trace_id", "/api/admin/traces/{}"),
    ("/api/admin/virtual-views", "items", "id", "/api/admin/virtual-views/{}"),
    ("/api/admin/eval/results", "items", "filename", "/api/admin/eval/results/{}"),
]

masked_keys: set[str] = set()


def fetch(path: str):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _should_mask(key: str) -> bool:
    return (MASK_PROMPTS and key in PROMPT_KEYS) or (MASK_PII and key in PII_KEYS)


def mask(node):
    """민감 키의 값을 재귀적으로 치환한다 (구조는 유지 — 프론트가 그대로 렌더)."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if _should_mask(k):
                masked_keys.add(k)
                out[k] = MASK_TEXT if isinstance(v, str) else {}
            else:
                out[k] = mask(v)
        return out
    if isinstance(node, list):
        return [mask(v) for v in node]
    return node


def write(path: str, payload) -> int:
    """/api/foo/bar → <OUT>/foo/bar.json"""
    rel = path[len("/api/"):] if path.startswith("/api/") else path.lstrip("/")
    target = OUT_DIR / (rel + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    target.write_text(body, encoding="utf-8")
    return len(body.encode("utf-8"))


def items_of(payload, key: str) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        v = payload.get(key)
        if isinstance(v, list):
            return v
    return []


def main() -> int:
    try:
        fetch("/api/health")
    except (urllib.error.URLError, OSError) as e:
        print(f"백엔드에 연결할 수 없습니다 ({BASE}): {e}")
        print("먼저 `cd backend && uvicorn main:app --port 8008` 로 기동하세요.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_files = 0
    total_bytes = 0
    failures: list[tuple[str, str]] = []

    targets = list(STATIC_PATHS)

    # 목록을 먼저 받아 상세 경로를 유도한다
    for list_path, container, id_key, template in COLLECTIONS:
        try:
            payload = fetch(list_path)
        except Exception as e:  # noqa: BLE001 — 어떤 실패든 요약에 남기고 계속
            failures.append((list_path, str(e)))
            continue
        for item in items_of(payload, container):
            ident = item.get(id_key) if isinstance(item, dict) else item
            if ident:
                targets.append(template.format(ident))

    for path in targets:
        try:
            payload = fetch(path)
        except Exception as e:  # noqa: BLE001
            failures.append((path, str(e)))
            continue
        payload = mask(payload)
        total_bytes += write(path, payload)
        total_files += 1

    print(f"스냅샷 {total_files}개 파일, {total_bytes / 1024:.0f} KB → {OUT_DIR}")
    print(f"마스킹된 필드: {', '.join(sorted(masked_keys)) or '없음'}")
    if not MASK_PROMPTS:
        print("  시스템 프롬프트/유저 메시지가 그대로 공개됩니다 (SNAPSHOT_INCLUDE_PROMPTS=1)")
    if not MASK_PII:
        print("  경고: PII 매핑([PERSON_1] → 실명)이 그대로 공개됩니다 (SNAPSHOT_INCLUDE_PII=1)")
    if failures:
        print(f"\n실패 {len(failures)}건:")
        for path, err in failures:
            print(f"  {path} — {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
