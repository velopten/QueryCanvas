#!/usr/bin/env python3
"""
Oracle DDL → 학습 데이터 형식 변환 스크립트.

입력: Oracle CREATE TABLE + comment on column 형식의 DDL
      (단일 테이블 또는 여러 테이블 한꺼번에)
출력: vector_store가 청킹할 수 있는 -- [테이블] 블록 형식

기본 사용 (정규식만):
    python scripts/parse_ddl.py input.sql > output.sql

여러 파일 처리:
    python scripts/parse_ddl.py file1.sql file2.sql -o output.sql

AI 보강 (Claude API 사용 — 핵심 컬럼 분류, 설명, 활용 시나리오):
    python scripts/parse_ddl.py input.sql --enhance > output.sql
    python scripts/parse_ddl.py input.sql --enhance --model haiku > output.sql

stdin 입력:
    cat input.sql | python scripts/parse_ddl.py - > output.sql
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── 데이터 구조 ──


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    comment: str = ""  # 한국어 코멘트


@dataclass
class Table:
    name: str
    comment: str = ""  # 테이블 한국어 코멘트
    columns: list[Column] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)
    raw_create: str = ""  # 원본 CREATE TABLE 문 (참고용)


# ── 1단계: Oracle DDL 파싱 ──

# 매칭 헬퍼: comment on column TABLE.COL is '한글'
COMMENT_COL_RE = re.compile(
    r"comment\s+on\s+column\s+(\w+)\.(\w+)\s+is\s+'([^']*)'",
    re.IGNORECASE,
)
# comment on table TABLE is '한글'
COMMENT_TBL_RE = re.compile(
    r"comment\s+on\s+table\s+(\w+)\s+is\s+'([^']*)'",
    re.IGNORECASE,
)
# CREATE TABLE TABLE_NAME ( ... )
CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+(\w+)\s*\((.*?)\)\s*(?:/|;|\Z)",
    re.IGNORECASE | re.DOTALL,
)
# 컬럼 라인: NAME TYPE [DEFAULT ...] [NOT NULL]
# 예: EMP_ID VARCHAR2(20) not null
#     MARRY_YN VARCHAR2(1) default 'N'
#     BODY_HEIGHT NUMBER default 0
COLUMN_LINE_RE = re.compile(
    r"^\s*(\w+)\s+([A-Z][A-Z0-9_]*(?:\([^)]+\))?(?:\s+WITH\s+TIME\s+ZONE)?)"
    r"(?:\s+default\s+([^,\n]+?))?"
    r"(?:\s+(not\s+null))?"
    r"\s*,?\s*$",
    re.IGNORECASE,
)
# constraint PK_xxx primary key (col1, col2)
PK_RE = re.compile(
    r"constraint\s+\w+\s+primary\s+key\s*\(([^)]+)\)",
    re.IGNORECASE,
)


def parse_ddl(text: str) -> list[Table]:
    """원본 DDL 텍스트를 파싱해서 Table 객체 리스트로 반환."""
    tables: dict[str, Table] = {}

    # 1) CREATE TABLE 본문 추출
    for m in CREATE_TABLE_RE.finditer(text):
        table_name = m.group(1).upper()
        body = m.group(2)
        tbl = Table(name=table_name, raw_create=m.group(0))
        # 컬럼 + PK 분리
        # 본문을 줄 단위로 split (괄호 안 콤마 무시)
        lines = _split_columns(body)
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # PK constraint
            pk_m = PK_RE.search(line)
            if pk_m:
                pks = [c.strip() for c in pk_m.group(1).split(",")]
                tbl.primary_keys = pks
                continue
            # 일반 컬럼
            col_m = COLUMN_LINE_RE.match(line)
            if col_m:
                col = Column(
                    name=col_m.group(1).upper(),
                    data_type=col_m.group(2).strip(),
                    default=col_m.group(3).strip() if col_m.group(3) else None,
                    nullable=col_m.group(4) is None,
                )
                tbl.columns.append(col)
        tables[table_name] = tbl

    # 2) 테이블 코멘트
    for m in COMMENT_TBL_RE.finditer(text):
        name = m.group(1).upper()
        if name in tables:
            tables[name].comment = m.group(2).strip()

    # 3) 컬럼 코멘트
    for m in COMMENT_COL_RE.finditer(text):
        table_name = m.group(1).upper()
        col_name = m.group(2).upper()
        col_comment = m.group(3).strip()
        if table_name not in tables:
            continue
        for col in tables[table_name].columns:
            if col.name == col_name:
                col.comment = col_comment
                break

    return list(tables.values())


def _split_columns(body: str) -> list[str]:
    """CREATE TABLE 본문을 컬럼 단위로 분리. 괄호 안 콤마 무시."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


# ── 2단계: 학습 데이터 형식으로 변환 ──


def format_table(tbl: Table) -> str:
    """Table 객체를 학습 데이터 형식 텍스트로 변환."""
    lines = []
    lines.append(f"-- [테이블] {tbl.name} - {tbl.comment or '(설명 없음)'}")
    lines.append(f"-- [설명] {tbl.comment or '(테이블 코멘트 없음 — 사람이 직접 보강 필요)'}")

    if tbl.primary_keys:
        pk_str = ", ".join(tbl.primary_keys)
        lines.append(f"-- [PK] {pk_str}")

    # 컬럼 분류: 핵심 컬럼 (PK + 자주 쓰일 만한 것) vs 기타
    # 휴리스틱:
    #   - PK는 무조건 핵심
    #   - 한국어 코멘트에 키워드 (이름/명/일자/코드/구분/유형/상태)가 들어가면 핵심
    #   - INS_*, MOD_*, 등록자/수정자는 기타
    core_keywords = ["이름", "명", "일자", "일", "코드", "구분", "유형", "상태", "번호", "id", "여부"]
    skip_keywords = ["입력자", "입력일", "수정자", "수정일", "작업자", "사진path", "보관"]

    core_cols: list[Column] = []
    other_cols: list[Column] = []
    for col in tbl.columns:
        comment_lower = col.comment.lower() if col.comment else ""
        if col.name in tbl.primary_keys:
            core_cols.append(col)
        elif col.name.startswith(("INS_", "MOD_", "REG_")) or any(k in comment_lower for k in skip_keywords):
            other_cols.append(col)
        elif col.comment and any(k in comment_lower for k in core_keywords):
            core_cols.append(col)
        else:
            other_cols.append(col)

    # 핵심 컬럼 너무 많으면 (>25) 잘라냄
    if len(core_cols) > 25:
        moved = core_cols[25:]
        core_cols = core_cols[:25]
        other_cols = moved + other_cols

    lines.append("-- [핵심 컬럼]")
    for col in core_cols:
        type_str = col.data_type
        nullable_str = ", NOT NULL" if not col.nullable else ""
        pk_str = ", PK" if col.name in tbl.primary_keys else ""
        comment = col.comment if col.comment else "(설명 없음)"
        lines.append(f"--   {col.name}({comment}, {type_str}{pk_str}{nullable_str})")

    if other_cols:
        other_names = ", ".join(c.name for c in other_cols[:30])
        if len(other_cols) > 30:
            other_names += f", ... 외 {len(other_cols) - 30}개"
        lines.append(f"-- [기타 컬럼] {other_names}")

    # 데이터 형식 힌트 (날짜)
    date_cols = [c for c in tbl.columns if c.name.endswith("_YMD") and "VARCHAR2" in c.data_type.upper()]
    if date_cols:
        lines.append("-- [참고] *_YMD 컬럼은 VARCHAR2(8) YYYYMMDD 문자열 형식 (DATE 타입 아님)")

    # CREATE TABLE 간소화 (핵심 컬럼만)
    lines.append(f"CREATE TABLE {tbl.name} (")
    col_lines = [
        f"    {col.name:<25} {col.data_type}{' NOT NULL' if not col.nullable else ''}"
        for col in core_cols
    ]
    body = ",\n".join(col_lines)
    if tbl.primary_keys:
        pk_str = ", ".join(tbl.primary_keys)
        body += f",\n    CONSTRAINT PK_{tbl.name} PRIMARY KEY ({pk_str})"
    if other_cols:
        body += f"\n    -- ... 외 {len(other_cols)}개 컬럼 생략"
    lines.append(body)
    lines.append(");")
    lines.append("")

    return "\n".join(lines)


# ── 3단계: AI 보강 (선택) ──


def enhance_with_ai(tbl: Table, model: str = "haiku") -> str:
    """
    AI를 사용해 테이블 설명, 핵심 컬럼 분류, 활용 시나리오를 보강한다.
    환경변수 ANTHROPIC_API_KEY 필요.
    """
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic 패키지가 필요합니다. pip install anthropic", file=sys.stderr)
        return format_table(tbl)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 환경변수가 필요합니다", file=sys.stderr)
        return format_table(tbl)

    client = anthropic.Anthropic(api_key=api_key)
    model_id = "claude-haiku-4-5" if model == "haiku" else "claude-sonnet-5"

    # 컬럼 정보 정리
    columns_info = []
    for col in tbl.columns:
        nullable = "" if col.nullable else " NOT NULL"
        pk = " PK" if col.name in tbl.primary_keys else ""
        comment = f" -- {col.comment}" if col.comment else ""
        columns_info.append(f"  {col.name} {col.data_type}{nullable}{pk}{comment}")

    user_msg = f"""다음 Oracle 테이블의 메타정보를 분석해서 학습 데이터 형식으로 변환해주세요.

[테이블명] {tbl.name}
[테이블 코멘트] {tbl.comment or '(없음)'}
[PK] {', '.join(tbl.primary_keys) if tbl.primary_keys else '(없음)'}
[전체 컬럼 ({len(tbl.columns)}개)]
{chr(10).join(columns_info)}

다음 JSON 형식으로 응답해주세요. 다른 텍스트 없이 JSON만:
{{
  "description": "이 테이블이 무엇을 위한 것인지 한 문장",
  "core_columns": ["가장 자주 사용될 핵심 컬럼명 배열 — 보통 10~20개. PK와 자주 조회되는 키 컬럼 위주"],
  "use_cases": ["이 테이블을 사용하는 대표 활용 시나리오"],
  "join_hints": ["다른 테이블과의 추정 조인 관계 (FK 컬럼명 기반)"],
  "data_notes": ["이 스키마 고유의 데이터 패턴 (예: '_YMD 컬럼은 VARCHAR2(8) YYYYMMDD 문자열', 'STAT_CD 코드값 매핑 필요')"]
}}"""

    try:
        response = client.messages.create(
            model=model_id,
            max_tokens=1500,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        # JSON 추출 (코드 블록 제거)
        if "```" in raw:
            m = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
            if m:
                raw = m.group(1)
        meta = json.loads(raw)
    except Exception as e:
        print(f"ERROR: AI 보강 실패 ({tbl.name}): {e}", file=sys.stderr)
        return format_table(tbl)

    # AI 결과로 다시 포맷
    lines = []
    lines.append(f"-- [테이블] {tbl.name} - {tbl.comment or meta.get('description', '')[:30]}")
    lines.append(f"-- [설명] {meta.get('description', tbl.comment)}")
    if tbl.primary_keys:
        lines.append(f"-- [PK] {', '.join(tbl.primary_keys)}")

    # 핵심 컬럼은 AI가 지정한 것
    core_names_set = set(meta.get("core_columns", []))
    core_cols = [c for c in tbl.columns if c.name in core_names_set]
    other_cols = [c for c in tbl.columns if c.name not in core_names_set]

    lines.append("-- [핵심 컬럼]")
    for col in core_cols:
        type_str = col.data_type
        nullable = ", NOT NULL" if not col.nullable else ""
        pk = ", PK" if col.name in tbl.primary_keys else ""
        comment = col.comment if col.comment else "(설명 없음)"
        lines.append(f"--   {col.name}({comment}, {type_str}{pk}{nullable})")

    if other_cols:
        other_names = ", ".join(c.name for c in other_cols[:30])
        if len(other_cols) > 30:
            other_names += f", ... 외 {len(other_cols) - 30}개"
        lines.append(f"-- [기타 컬럼] {other_names}")

    if meta.get("join_hints"):
        lines.append(f"-- [조인] {' / '.join(meta['join_hints'])}")

    if meta.get("use_cases"):
        lines.append(f"-- [활용] {', '.join(meta['use_cases'])}")

    if meta.get("data_notes"):
        for note in meta["data_notes"]:
            lines.append(f"-- [참고] {note}")

    # 간소화된 CREATE TABLE
    lines.append(f"CREATE TABLE {tbl.name} (")
    col_lines = [
        f"    {col.name:<25} {col.data_type}{' NOT NULL' if not col.nullable else ''}"
        for col in core_cols
    ]
    body = ",\n".join(col_lines)
    if other_cols:
        body += f"\n    -- ... 외 {len(other_cols)}개 컬럼 생략"
    if tbl.primary_keys:
        body += f",\n    CONSTRAINT PK_{tbl.name} PRIMARY KEY ({', '.join(tbl.primary_keys)})"
    lines.append(body)
    lines.append(");")
    lines.append("")

    return "\n".join(lines)


# ── 메인 ──


def main():
    parser = argparse.ArgumentParser(
        description="Oracle DDL → 학습 데이터 형식 변환",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="입력 DDL 파일 (여러 개 가능). '-' 입력 시 stdin 사용",
    )
    parser.add_argument(
        "-o", "--output",
        help="출력 파일 (생략 시 stdout)",
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="AI(Claude) 보강 모드 — 핵심 컬럼 자동 분류 + 활용 시나리오 생성",
    )
    parser.add_argument(
        "--model",
        choices=["haiku", "sonnet"],
        default="haiku",
        help="AI 보강에 사용할 모델 (default: haiku)",
    )
    args = parser.parse_args()

    # 입력 읽기
    raw_text = ""
    for inp in args.inputs:
        if inp == "-":
            raw_text += sys.stdin.read() + "\n"
        else:
            p = Path(inp)
            if not p.exists():
                print(f"ERROR: 파일 없음: {inp}", file=sys.stderr)
                sys.exit(1)
            raw_text += p.read_text(encoding="utf-8") + "\n"

    # 파싱
    tables = parse_ddl(raw_text)
    if not tables:
        print("ERROR: 테이블을 찾을 수 없습니다. CREATE TABLE 구문 확인 필요.", file=sys.stderr)
        sys.exit(1)

    print(f"[parse_ddl] {len(tables)}개 테이블 파싱 완료", file=sys.stderr)

    # 변환
    output_blocks = []
    for tbl in tables:
        print(f"[parse_ddl] {tbl.name} (컬럼 {len(tbl.columns)}개) 변환 중...", file=sys.stderr)
        if args.enhance:
            block = enhance_with_ai(tbl, model=args.model)
        else:
            block = format_table(tbl)
        output_blocks.append(block)

    output = "\n".join(output_blocks)

    # 출력
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"[parse_ddl] {args.output} 저장 완료 ({len(output)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
