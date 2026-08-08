# -*- coding: utf-8 -*-
"""
도메인 팩 프롬프트 로더.

config.DOMAIN에 해당하는 domains/<DOMAIN>/prompts.py를 로드해
SQL_SYSTEM_PROMPT / UI_SYSTEM_PROMPT / SUGGESTED_QUESTIONS를 조립한다.
관리자 프롬프트 편집(main.py PUT /api/admin/prompts)은 이 모듈의 속성을
런타임에 덮어쓴다 — 기존 계약 유지.

도메인 팩 prompts.py가 제공해야 하는 것:
  SQL_SYSTEM_PROMPT   — 도메인 SQL 프롬프트 (base.LIVE_SQL_RULES 포함 권장)
  UI_DOMAIN_CONTEXT   — UI 결정 프롬프트의 도메인 컨텍스트 문단
  SUGGESTED_QUESTIONS — 첫 화면 추천 질문 목록
"""

import importlib

from config import DOMAIN
from ui_engine.prompts.base import UI_BASE_RULES

_pack = importlib.import_module(f"domains.{DOMAIN}.prompts")

SQL_SYSTEM_PROMPT: str = _pack.SQL_SYSTEM_PROMPT
UI_SYSTEM_PROMPT: str = _pack.UI_DOMAIN_CONTEXT + UI_BASE_RULES
SUGGESTED_QUESTIONS: list[str] = list(_pack.SUGGESTED_QUESTIONS)
DISPLAY_NAME: str = getattr(_pack, "DISPLAY_NAME", DOMAIN)
