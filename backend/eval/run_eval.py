# -*- coding: utf-8 -*-
"""
Text-to-SQL 평가 하네스.

골든 질문셋(golden_questions.yaml)을 실제 파이프라인(RAG → SQL 생성 → 검증 → 실행)으로
배치 실행하고 정확도/지연/비용을 리포트한다.

사용:
  cd backend
  python eval/run_eval.py                 # 전체 실행
  python eval/run_eval.py --limit 3       # 앞 3개만
  python eval/run_eval.py --case late_by_dept_march

모델/모드 비교 (환경변수):
  MODEL_SQL_GEN=claude-sonnet-5 SQL_GEN_EFFORT=high AGENTIC_SQL=false python eval/run_eval.py

결과는 stdout 테이블 + eval/results/<timestamp>.json 에 저장된다.
프롬프트/모델/검색 가중치를 바꾸기 전후로 실행해 회귀를 확인하는 용도.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent))
from config import domain_dir
GOLDEN_PATH = domain_dir() / "golden_questions.yaml"
RESULTS_DIR = Path(__file__).parent / "results"


def _norm(v) -> str:
    """값 정규화 — 숫자는 3 == 3.0 == '3' 로 취급."""
    if v is None:
        return ""
    s = str(v).strip()
    try:
        f = float(s)
        return f"{f:g}"
    except (ValueError, TypeError):
        return s


def rows_contain(reference_rows: list[dict], generated_rows: list[dict]) -> bool:
    """reference 각 행의 값 집합이 generated 어느 행에든 부분집합으로 존재하는가."""
    gen_sets = [{_norm(v) for v in r.values()} for r in generated_rows]
    for ref in reference_rows:
        ref_vals = {_norm(v) for v in ref.values()}
        if not any(ref_vals <= g for g in gen_sets):
            return False
    return True


def evaluate_case(case: dict, db, agentic: bool) -> dict:
    from logger import QueryTracer
    from text_to_sql.vector_store import vector_store
    from text_to_sql.sql_validator import validate_sql
    from text_to_sql.virtual_view_resolver import resolve as vv_resolve
    from ui_engine.cost_calculator import calculate_cost
    from config import get_llm

    result = {
        "id": case["id"],
        "question": case["question"],
        "sql": None,
        "gen_seconds": None,
        "exec_seconds": None,
        "usage": None,
        "cost_usd": None,
        "generated_rows": None,
        "passed": False,
        "failure": None,
        "tool_calls": None,
    }

    tracer = QueryTracer(f"[eval] {case['question']}")
    context = vector_store.search(case["question"])

    # ── SQL 생성 ──
    t0 = time.time()
    try:
        if agentic:
            from text_to_sql.sql_agent import generate_sql_agentic

            sql = None
            for ev in generate_sql_agentic(case["question"], context, db, tracer):
                if ev["type"] == "done":
                    sql = ev["sql"]
                    result["usage"] = ev.get("usage")
                    result["tool_calls"] = ev.get("tool_calls")
                elif ev["type"] == "error":
                    result["failure"] = f"생성 실패: {ev['message']}"
                    return result
        else:
            from text_to_sql.sql_generator import generate_sql

            sql = generate_sql(case["question"], context, tracer)
            for step in tracer.steps:
                if step["step"] == "sql_generation_response":
                    result["usage"] = step["data"].get("usage")
    except Exception as e:
        result["failure"] = f"생성 예외: {e}"
        return result
    finally:
        result["gen_seconds"] = round(time.time() - t0, 1)

    result["sql"] = sql
    if result["usage"]:
        u = result["usage"]
        result["cost_usd"] = calculate_cost(
            get_llm("MODEL_SQL_GEN"),
            u.get("input_tokens", 0), u.get("output_tokens", 0),
            u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0),
        )["total_cost"]

    # ── 후단 가드레일 (main.py 와 동일 순서) ──
    vres = validate_sql(sql, dialect="sqlite")
    if not vres.ok:
        result["failure"] = f"검증 실패: {'; '.join(vres.errors)}"
        return result
    final_sql = sql
    vres2 = vv_resolve(final_sql, dialect="sqlite")
    if vres2.errors:
        result["failure"] = f"가상 view 해석 실패: {'; '.join(vres2.errors)}"
        return result
    if vres2.resolved:
        final_sql = vres2.sql

    # ── 실행 ──
    t0 = time.time()
    try:
        generated_rows = db.execute(final_sql)
    except Exception as e:
        result["failure"] = f"실행 오류: {e}"
        return result
    finally:
        result["exec_seconds"] = round(time.time() - t0, 2)

    result["generated_rows"] = len(generated_rows)

    # ── 채점 ──
    check = case.get("check") or {}
    mode = check.get("mode", "contain")

    if "min_rows" in check and len(generated_rows) < check["min_rows"]:
        result["failure"] = f"행 수 부족: {len(generated_rows)} < {check['min_rows']}"
        return result
    if "max_rows" in check and len(generated_rows) > check["max_rows"]:
        result["failure"] = f"행 수 초과: {len(generated_rows)} > {check['max_rows']}"
        return result

    if mode == "contain":
        reference_rows = db.execute(case["reference_sql"])
        if not rows_contain(reference_rows, generated_rows):
            result["failure"] = "결과 불일치: reference 행이 생성 결과에 없음"
            return result

    result["passed"] = True
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--case", type=str, default=None, help="특정 case id만 실행")
    args = parser.parse_args()

    from config import get_llm_settings

    llm = get_llm_settings()
    MODEL_SQL_GEN, SQL_GEN_EFFORT, AGENTIC_SQL = (
        llm["MODEL_SQL_GEN"], llm["SQL_GEN_EFFORT"], llm["AGENTIC_SQL"],
    )

    from db.client import get_db
    db = get_db()

    cases = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if args.limit:
        cases = cases[: args.limit]

    config_snapshot = {
        "model": MODEL_SQL_GEN,
        "effort": SQL_GEN_EFFORT,
        "agentic": AGENTIC_SQL,
        "started_at": datetime.now().isoformat(),
    }
    print(f"\n=== Text-to-SQL 평가 ===")
    print(f"model={MODEL_SQL_GEN} effort={SQL_GEN_EFFORT} agentic={AGENTIC_SQL} cases={len(cases)}\n")

    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']} ... ", end="", flush=True)
        r = evaluate_case(case, db, agentic=AGENTIC_SQL)
        results.append(r)
        mark = "PASS" if r["passed"] else f"FAIL ({r['failure']})"
        tools = f", tools={r['tool_calls']}" if r["tool_calls"] else ""
        cost = f", ${r['cost_usd']:.4f}" if r["cost_usd"] else ""
        print(f"{mark}  [{r['gen_seconds']}s{tools}{cost}]")

    # ── 요약 ──
    passed = sum(1 for r in results if r["passed"])
    gen_times = [r["gen_seconds"] for r in results if r["gen_seconds"]]
    costs = [r["cost_usd"] for r in results if r["cost_usd"]]
    summary = {
        "accuracy": round(passed / len(results), 3) if results else 0,
        "passed": passed,
        "total": len(results),
        "avg_gen_seconds": round(sum(gen_times) / len(gen_times), 1) if gen_times else None,
        "total_cost_usd": round(sum(costs), 4) if costs else None,
    }
    print(f"\n정확도: {passed}/{len(results)} ({summary['accuracy']*100:.0f}%)")
    print(f"평균 생성 시간: {summary['avg_gen_seconds']}s")
    print(f"총 비용: ${summary['total_cost_usd']}")

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(
        json.dumps({"config": config_snapshot, "summary": summary, "results": results},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"결과 저장: {out_path}")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
