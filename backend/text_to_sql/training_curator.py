"""
학습 데이터 AI 큐레이터.

사용자의 자유 텍스트 입력을 받아:
1) 새 정보(add) vs 기존 보강(patch) 판단
2) 표준 마크다운 청크로 구조화
3) preview → commit 2단계로 overlay/ 디렉토리에 저장

원본 큐레이션 파일은 절대 수정하지 않고, overlay만 추가/수정한다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, get_llm
from logger import pipeline_logger
from text_to_sql.vector_store import OVERLAY_DIR, vector_store


def _model() -> str:
    """큐레이션은 신중해야 하므로 더 큰 모델 사용 (관리자 설정에서 변경 가능)."""
    return get_llm("MODEL_CURATOR")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# structured output 스키마 — CURATOR_SYSTEM_PROMPT의 출력 JSON 스키마와 동일
CURATOR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["add", "patch", "reject"]},
        "destination": {"type": "string", "enum": ["vector", "prompt", "both"]},
        "category": {
            "type": "string",
            "enum": ["table", "sql_pattern", "code_mapping", "rule", "policy", "note"],
        },
        "title": {"type": "string"},
        "target_chunk_id": {"type": "string"},
        "rationale": {"type": "string"},
        "structured_md": {"type": "string"},
        "prompt_directive": {"type": "string"},
    },
    "required": [
        "action", "destination", "category", "title",
        "target_chunk_id", "rationale", "structured_md", "prompt_directive",
    ],
    "additionalProperties": False,
}


def _build_existing_summary(max_chars: int = 6000) -> str:
    """
    벡터 스토어에서 기존 청크 요약본 생성.
    AI가 add/patch 판단 시 참고할 컨텍스트.
    """
    docs = vector_store.get_all_documents()
    lines = []
    for d in docs:
        # 첫 줄(제목)만 추출
        first_line = d["content"].splitlines()[0] if d["content"] else ""
        head = first_line[:120]
        lines.append(f"- [{d['id']}] ({d.get('source','?')}) {head}")
    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 30] + "\n...(잘림)"
    return summary


CURATOR_SYSTEM_PROMPT = """당신은 Text-to-SQL 학습 데이터 큐레이터입니다.

사용자가 자유 텍스트로 학습 데이터를 추가하면, 당신은 두 가지를 판단합니다:

## 판단 1: action (어떻게 저장할지)
- `add`: 완전히 새로운 테이블/패턴/규약 → 새 청크
- `patch`: 이미 기존 청크에 있고 보완 정보면 → 기존 청크 보강
- 애매하면 add

## 판단 2: destination (어디에 반영할지)

**`vector`** (기본값) — 벡터 DB에만 저장
- 특정 테이블/컬럼/SQL 패턴 정보처럼 **사용자 질문이 해당 토픽일 때만 검색되어야 하는 지식**
- 예: "TB_XXXX 테이블은 반품 접수 마스터" → 반품 관련 질문일 때만 회수되면 됨

**`prompt`** — SQL 생성 시스템 프롬프트에 항상 append (모든 SQL 생성에 영향)
- **모든 SQL에 항상 적용되어야 하는 규칙/제약/관례**
- 예: "주민번호 컬럼은 절대 SELECT에 포함하지 말 것", "조회 결과는 항상 100건 제한"
- 너무 많이 쌓이면 프롬프트가 비대해지므로 신중하게 판단

**`both`** — 둘 다
- 핵심 운영 규칙이면서 동시에 특정 테이블 컨텍스트로도 검색되어야 하는 경우
- 예: "TAM0520은 마감 후에만 채워지므로 마감 안 된 월 조회 시 빈 결과 가능 — 항상 CLOSE_YN 체크"

## destination 판단 가이드
- 입력이 "항상", "절대", "모든 쿼리에서", "기본적으로" 같은 어구를 쓰면 → prompt 후보
- 특정 테이블/컬럼만 다루면 → vector
- 운영 정책/보안 규칙/사용자 환경 설정이면 → prompt 또는 both
- 단순 사실/메타데이터면 → vector

## 출력 JSON 스키마
```json
{
  "action": "add" | "patch",
  "destination": "vector" | "prompt" | "both",
  "category": "table" | "sql_pattern" | "code_mapping" | "rule" | "policy" | "note",
  "title": "한 줄 제목 (예: PA9999 — 출장 신청 테이블)",
  "target_chunk_id": "patch일 때만, 어느 청크 보강하는지 ID. add면 빈 문자열",
  "rationale": "action과 destination 판단 근거 1-2줄",
  "structured_md": "## 제목\\n표준 마크다운 본문 (300~1500자)",
  "prompt_directive": "destination이 prompt/both일 때만, system prompt에 들어갈 1-3줄짜리 명령형 지침. 예: '- PER_NO 컬럼은 절대 SELECT 절에 포함하지 마세요.'"
}
```

## structured_md 작성 규칙
- 반드시 `## ` 헤더로 시작
- patch의 경우: 제목에 "보강", "추가", "수정" 등 명시 (예: `## TB_LEAVE 보강 — 반차 DAYS=0.5 규칙`)
- 표 형식 적극 활용 (컬럼 정의, 코드 매핑 등)
- SQL 예시는 코드 블록(```sql)으로
- 사용자가 입력한 내용 외에 새 사실을 만들지 말 것
- 한국어로 작성

## prompt_directive 작성 규칙 (destination이 prompt/both일 때 필수)
- 매우 짧게 (1-3줄)
- 명령형: "~하지 마세요", "항상 ~하세요", "~인 경우 ~"
- system prompt에 직접 append되므로 토큰을 아껴야 함
- 좋은 예: `- 조회 결과는 항상 FETCH FIRST 100 ROWS ONLY로 제한하세요.`
- 나쁜 예 (장문 설명, 배경 포함): `- 사용자가 100건 넘는 결과를 보면 화면이 느려지므로 ...`

## 안전 규칙
- DROP/INSERT/UPDATE/DELETE/ALTER 등 DML/DDL 위험 키워드가 입력에 포함되면 거부:
  `{"action": "reject", "rationale": "위험 키워드 포함"}`
- 20자 미만 또는 무의미한 입력은 reject

오직 JSON만 출력하세요. 코드블록(```) 없이 raw JSON으로."""


def curate(user_input: str) -> dict:
    """
    AI에 입력 → 분류 + 구조화된 청크 생성. 저장은 안 함.
    """
    if len(user_input.strip()) < 20:
        return {"action": "reject", "rationale": "입력이 너무 짧음"}

    summary = _build_existing_summary()

    user_msg = f"""## 기존 청크 목록
{summary}

## 사용자 입력
{user_input}

위 입력을 분석하여 JSON으로 응답하세요."""

    pipeline_logger.info(f"[curator] 호출 (입력 길이: {len(user_input)})")

    response = client.messages.create(
        model=_model(),
        max_tokens=8000,
        system=CURATOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        output_config={"format": {"type": "json_schema", "schema": CURATOR_OUTPUT_SCHEMA}},
    )
    raw = next((b.text for b in response.content if b.type == "text"), "").strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        pipeline_logger.error(f"[curator] JSON 파싱 실패: {e}\n원본: {raw[:500]}")
        return {"action": "reject", "rationale": f"AI 응답 파싱 실패: {e}"}

    # 검증
    if result.get("action") not in {"add", "patch", "reject"}:
        return {"action": "reject", "rationale": "잘못된 action"}

    if result.get("action") == "patch":
        tgt = result.get("target_chunk_id", "")
        if not tgt:
            return {"action": "reject", "rationale": "patch인데 target_chunk_id 없음"}
        # target 존재 확인
        existing = vector_store.collection.get(ids=[tgt])
        if not existing["ids"]:
            return {
                "action": "reject",
                "rationale": f"target_chunk_id '{tgt}' 가 존재하지 않음",
            }
        result["target_content"] = existing["documents"][0]

    return result


def commit(curated: dict, source_input: str) -> dict:
    """
    curate() 결과를 overlay 파일로 저장.
    destination에 따라 벡터 스토어 + system prompt addendum 양쪽에 반영.
    """
    if curated.get("action") not in {"add", "patch"}:
        return {"status": "rejected", "reason": curated.get("rationale", "")}

    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)

    action = curated["action"]
    destination = curated.get("destination", "vector")
    if destination not in {"vector", "prompt", "both"}:
        destination = "vector"
    category = curated.get("category", "note")
    title = curated.get("title", "untitled")
    structured_md = curated["structured_md"]
    target_chunk_id = curated.get("target_chunk_id", "")
    prompt_directive = curated.get("prompt_directive", "").strip()

    if destination in {"prompt", "both"} and not prompt_directive:
        return {
            "status": "rejected",
            "reason": "destination이 prompt/both인데 prompt_directive가 비어있음",
        }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9가-힣_-]", "_", title)[:40]
    fname = f"{action}_{destination}_{ts}_{slug}.md"
    fpath = OVERLAY_DIR / fname

    # frontmatter
    fm_lines = [
        "---",
        f"action: {action}",
        f"destination: {destination}",
        f"category: {category}",
        f"title: {title}",
        f"created_at: {datetime.now().isoformat()}",
        f"ai_model: {_model()}",
    ]
    if target_chunk_id:
        fm_lines.append(f"target_chunk_id: {target_chunk_id}")
    if prompt_directive:
        # 단일 라인으로 frontmatter에 저장 (개행은 \n 으로 이스케이프)
        fm_lines.append(f"prompt_directive: {prompt_directive!r}")
    fm_lines.append("source_input: |")
    for line in source_input.splitlines():
        fm_lines.append(f"  {line}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(structured_md)

    fpath.write_text("\n".join(fm_lines), encoding="utf-8")
    pipeline_logger.info(f"[curator] overlay 저장: {fname} (destination={destination})")

    # 벡터 스토어 추가 (vector 또는 both일 때만)
    new_chunk_id = ""
    if destination in {"vector", "both"}:
        new_chunk_id = f"overlay_{int(datetime.now().timestamp())}"
        doc_type = "doc_patch" if action == "patch" else "doc_overlay"
        vector_store.collection.add(
            documents=[structured_md],
            metadatas=[
                {
                    "type": doc_type,
                    "source": f"overlay/{fname}",
                    "target_chunk_id": target_chunk_id,
                }
            ],
            ids=[new_chunk_id],
        )

    # 학습 데이터가 바뀌었으므로 SQL 캐시 무효화
    try:
        from text_to_sql.sql_cache import sql_cache
        sql_cache.clear()
        pipeline_logger.info("[curator] SQL 캐시 무효화 완료")
    except Exception as e:
        pipeline_logger.warning(f"[curator] SQL 캐시 무효화 실패: {e}")

    return {
        "status": "committed",
        "file": fname,
        "chunk_id": new_chunk_id,
        "action": action,
        "destination": destination,
        "target_chunk_id": target_chunk_id,
    }


def get_prompt_addenda() -> list[dict]:
    """
    destination이 prompt/both 인 overlay의 prompt_directive 모음.
    sql_generator가 매 요청마다 호출해서 system prompt에 append.
    """
    if not OVERLAY_DIR.exists():
        return []

    items = []
    for path in sorted(OVERLAY_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        if not content.startswith("---\n"):
            continue
        end = content.find("\n---\n", 4)
        if end == -1:
            continue
        fm = content[4:end]
        meta: dict[str, str] = {}
        for line in fm.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        if meta.get("destination") not in {"prompt", "both"}:
            continue
        directive = meta.get("prompt_directive", "")
        # repr 형태로 저장됐으므로 eval 대신 따옴표 제거 처리
        if directive.startswith(("'", '"')) and directive.endswith(("'", '"')):
            try:
                directive = ast_literal_unquote(directive)
            except Exception:
                directive = directive.strip("'\"")
        if directive:
            items.append(
                {
                    "file": path.name,
                    "title": meta.get("title", ""),
                    "directive": directive,
                }
            )
    return items


def ast_literal_unquote(s: str) -> str:
    """frontmatter에 repr()로 저장된 문자열을 안전하게 복원."""
    import ast

    return ast.literal_eval(s)


def list_overlays() -> list[dict]:
    """저장된 overlay 파일 목록."""
    if not OVERLAY_DIR.exists():
        return []
    items = []
    for p in sorted(OVERLAY_DIR.glob("*.md")):
        content = p.read_text(encoding="utf-8")
        items.append(
            {
                "file": p.name,
                "size": len(content),
                "preview": content[:300],
            }
        )
    return items


def delete_overlay(filename: str) -> dict:
    """overlay 파일 삭제 + 벡터 스토어에서도 제거."""
    fpath = OVERLAY_DIR / filename
    if not fpath.exists() or ".." in filename or "/" in filename:
        return {"status": "not_found"}

    # 벡터 스토어에서 source가 일치하는 청크 삭제
    all_docs = vector_store.collection.get(
        where={"source": f"overlay/{filename}"}
    )
    if all_docs["ids"]:
        vector_store.collection.delete(ids=all_docs["ids"])

    fpath.unlink()

    try:
        from text_to_sql.sql_cache import sql_cache
        sql_cache.clear()
    except Exception:
        pass

    return {"status": "deleted", "file": filename}
