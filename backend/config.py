import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# Claude API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── 역할별 모델 맵 ──
# 파이프라인 각 단계의 지능 요구 수준에 맞춰 모델 티어를 분리한다.
# 환경변수 MODEL_* 로 개별 오버라이드 가능.
# (구 CLAUDE_MODEL 환경변수는 더 이상 사용하지 않음 — MODEL_SQL_GEN 등으로 대체)
if os.getenv("CLAUDE_MODEL"):
    import warnings
    warnings.warn(
        "CLAUDE_MODEL 환경변수는 deprecated — MODEL_SQL_GEN/MODEL_UI_DECISION 등을 사용하세요",
        stacklevel=1,
    )

# SQL 생성 — 파이프라인 정확도를 좌우하는 핵심 단계.
# 기본: Sonnet 5 (코딩/에이전틱에서 near-Opus 품질 + 인터랙티브에 맞는 지연/비용).
# 최고 정확도가 필요하면 MODEL_SQL_GEN=claude-opus-5 로 오버라이드 —
# 교체 전후 eval/run_eval.py 로 정확도/지연/비용을 측정해서 판단할 것.
MODEL_SQL_GEN = os.getenv("MODEL_SQL_GEN", "claude-sonnet-5")
# SQL 생성 effort (Opus 5/Sonnet 5 계열: low|medium|high|xhigh|max)
SQL_GEN_EFFORT = os.getenv("SQL_GEN_EFFORT", "high")
# UI 스펙 결정 — 구조화 출력 품질 중요. 중상위 티어.
MODEL_UI_DECISION = os.getenv("MODEL_UI_DECISION", "claude-sonnet-5")
# 질문 분류/사전필터 — 단순 분류. 경량 모델.
MODEL_CLASSIFY = os.getenv("MODEL_CLASSIFY", "claude-haiku-4-5")
# SQL 오류 수정 — 문법 교정. 경량 모델.
MODEL_FIX = os.getenv("MODEL_FIX", "claude-haiku-4-5")
# 학습 데이터 큐레이션 — 신중한 판단 필요. 중상위 티어.
MODEL_CURATOR = os.getenv("MODEL_CURATOR", "claude-sonnet-5")

# 하위 호환 (admin settings 등에서 참조)
CLAUDE_MODEL = MODEL_SQL_GEN

# 에이전틱 SQL 생성 — 모델이 도구(스키마 검색/식별자 확정/시험 실행)를 스스로 사용.
# false 면 기존 1-pass 생성으로 폴백.
AGENTIC_SQL = os.getenv("AGENTIC_SQL", "true").lower() == "true"

# ── LLM 설정 런타임 오버라이드 ──
# 관리자 화면에서 저장한 설정이 .env/기본값을 덮어쓴다 (재시작 불필요).
# 저장 위치: db/llm_settings.json (gitignore — 런타임 상태)
import json as _json

_LLM_RUNTIME_PATH = BASE_DIR / "db" / "llm_settings.json"

LLM_SETTING_KEYS = {
    "MODEL_SQL_GEN": str,
    "MODEL_UI_DECISION": str,
    "MODEL_CLASSIFY": str,
    "MODEL_FIX": str,
    "MODEL_CURATOR": str,
    "SQL_GEN_EFFORT": str,
    "AGENTIC_SQL": bool,
}
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

_ENV_LLM_DEFAULTS = {
    "MODEL_SQL_GEN": MODEL_SQL_GEN,
    "MODEL_UI_DECISION": MODEL_UI_DECISION,
    "MODEL_CLASSIFY": MODEL_CLASSIFY,
    "MODEL_FIX": MODEL_FIX,
    "MODEL_CURATOR": MODEL_CURATOR,
    "SQL_GEN_EFFORT": SQL_GEN_EFFORT,
    "AGENTIC_SQL": AGENTIC_SQL,
}


def _load_llm_overrides() -> dict:
    try:
        data = _json.loads(_LLM_RUNTIME_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in LLM_SETTING_KEYS}
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}


def get_llm_settings() -> dict:
    """env/기본값 + 런타임 오버라이드 병합 결과."""
    return {**_ENV_LLM_DEFAULTS, **_load_llm_overrides()}


def get_llm(key: str):
    """호출 시점 기준 LLM 설정 조회 — 모델/effort는 반드시 이걸로 읽는다."""
    return get_llm_settings()[key]


def update_llm_settings(updates: dict) -> dict:
    """유효성 검증 후 오버라이드 저장. 반환: 병합된 전체 설정."""
    current = _load_llm_overrides()
    for k, v in updates.items():
        if k not in LLM_SETTING_KEYS:
            raise ValueError(f"알 수 없는 설정 키: {k}")
        expected = LLM_SETTING_KEYS[k]
        if not isinstance(v, expected):
            raise ValueError(f"{k}: {expected.__name__} 타입이어야 합니다")
        if expected is str and not v.strip():
            raise ValueError(f"{k}: 빈 값 불가")
        if k == "SQL_GEN_EFFORT" and v not in EFFORT_LEVELS:
            raise ValueError(f"SQL_GEN_EFFORT: {'/'.join(EFFORT_LEVELS)} 중 하나여야 합니다")
        current[k] = v
    _LLM_RUNTIME_PATH.write_text(
        _json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return get_llm_settings()


def reset_llm_settings() -> dict:
    """오버라이드 삭제 — .env/기본값으로 복귀."""
    _LLM_RUNTIME_PATH.unlink(missing_ok=True)
    return get_llm_settings()

# ── DB ──
# 조회 대상은 도메인 팩이 생성하는 SQLite mock DB 하나다.
# SQL 문법(생성 프롬프트/검증/가상 view 치환)은 모두 이 값 하나를 따른다 —
# 다른 백엔드를 붙일 때 바꿀 지점은 db/client.py 의 어댑터와 이 상수뿐이다.
SQL_DIALECT = "sqlite"

# ── 도메인 팩 ──
# 도메인 결합 자산(프롬프트/mock 생성기/학습 데이터/가상 view/골든셋)은
# backend/domains/<DOMAIN>/ 아래에 팩으로 묶여 있다. 전환은 이 값 하나로.
DOMAIN = os.getenv("DOMAIN", "commerce")


def domain_dir():
    """현재 도메인 팩 디렉토리 (pathlib.Path)."""
    from pathlib import Path
    return Path(__file__).parent / "domains" / DOMAIN

# ChromaDB
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", str(BASE_DIR / "chroma_data"))

# Server
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8008"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG")
LOG_DIR = os.getenv("LOG_DIR", str(BASE_DIR / "logs"))
