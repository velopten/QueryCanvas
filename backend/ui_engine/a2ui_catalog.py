# -*- coding: utf-8 -*-
"""
A2UI 카탈로그 — 커스텀 컴포넌트 4종(Chart/DataTable/BriefingCard/Filter)을
번들 basic 카탈로그에 확장 등록하고, UI 결정 LLM용 시스템 프롬프트와
스트리밍 파서를 제공한다.

프론트(frontend/src/lib/a2ui/catalog.tsx)와 계약 공유:
- catalogId: query-canvas/v1
- surfaceId: "result" (클라이언트가 createSurface — LLM은 updateComponents만 출력)
- 데이터 모델: /rows (SQL 결과), /filters (Filter two-way), /meta/loading
"""

import copy
import json
import os
from functools import lru_cache
from typing import Any

import a2ui
from a2ui.inference_formats.direct_json import DirectJsonFormat
from a2ui.schema.catalog import A2uiCatalogProvider, CatalogConfig

CATALOG_ID = "query-canvas/v1"
SURFACE_ID = "result"
SPEC_VERSION = "0.9.1"

# LLM이 사용해도 되는 컴포넌트 (프롬프트 제한 + 서버 sanitize 이중 적용)
# Tabs/List/Icon 제외 — Tabs는 위젯 원칙상 비권장, List/Icon은 실사용 없음 (프롬프트 다이어트)
ALLOWED_COMPONENTS = [
    "BriefingCard", "Chart", "DataTable", "Filter", "StatCard", "Notice",
    "Column", "Row", "Text", "Card", "Divider",
]

# 커스텀 컴포넌트 이름 (description 보존 대상)
CUSTOM_COMPONENT_NAMES = {"Chart", "DataTable", "BriefingCard", "Filter", "StatCard", "Notice"}


def _strip_basic_descriptions(schema: dict) -> dict:
    """프롬프트 다이어트 — basic 컴포넌트/공통 타입의 description 제거 (커스텀 6종은 유지).

    실측: 스키마 프롬프트 32.6k → 23.7k chars (-27%). 캐시 write/미스 비용 비례 절감.
    """
    schema = copy.deepcopy(schema)

    def walk(node, keep: bool):
        if isinstance(node, dict):
            if not keep:
                node.pop("description", None)
            for v in node.values():
                walk(v, keep)
        elif isinstance(node, list):
            for v in node:
                walk(v, keep)

    for name, comp in schema.get("components", {}).items():
        walk(comp, keep=(name in CUSTOM_COMPONENT_NAMES))
    if "$defs" in schema:
        walk(schema["$defs"], keep=False)
    return schema

_CT = "https://a2ui.org/specification/v0_9/common_types.json#/$defs"


def _component(name: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """번들 카탈로그와 동일한 골격으로 커스텀 컴포넌트 스키마를 만든다."""
    return {
        "type": "object",
        "allOf": [
            {"$ref": f"{_CT}/ComponentCommon"},
            {"$ref": "#/$defs/CatalogComponentCommon"},
            {
                "type": "object",
                "properties": {"component": {"const": name}, **props},
                "required": ["component", *required],
            },
        ],
        "unevaluatedProperties": False,
    }


# 스키마 description은 영문 (한글은 \uXXXX 이스케이프로 토큰 낭비 — docs/a2ui-notes.md)
_CUSTOM_COMPONENTS: dict[str, dict[str, Any]] = {
    "Chart": _component("Chart", {
        "chartType": {"type": "string", "enum": ["bar", "line", "pie", "gauge", "heatmap"],
                      "description": "bar=category comparison, line=time series, pie=composition, gauge=single ratio, heatmap=2D matrix"},
        "title": {"$ref": f"{_CT}/DynamicString"},
        "xField": {"type": "string", "description": "column name for x axis (category/time)"},
        "yField": {"type": "string", "description": "column name for y axis (numeric)"},
        "xLabel": {"type": "string"},
        "yLabel": {"type": "string"},
        "seriesField": {"type": "string", "description": "optional column to split into multiple series"},
        "highlightField": {"type": "string"},
        "highlightThreshold": {"type": "number"},
        "height": {"type": "number"},
        "rows": {"$ref": f"{_CT}/DynamicValue", "description": "data binding — always {\"path\": \"/rows\"}"},
        "filters": {"$ref": f"{_CT}/DynamicValue", "description": "optional filter binding — {\"path\": \"/filters\"}"},
        "loading": {"$ref": f"{_CT}/DynamicBoolean", "description": "client-managed loading state — do not set"},
    }, required=["chartType", "rows"]),
    "DataTable": _component("DataTable", {
        "title": {"$ref": f"{_CT}/DynamicString"},
        "pageSize": {"type": "number"},
        "columnFormats": {
            "type": "object",
            "description": "per-column number display, keyed by exact column name. omit columns that need no formatting",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["number", "percent", "text"],
                             "description": "number=thousands separator, percent=append % (value is already 0-100), text=leave as-is"},
                    "decimals": {"type": "number", "description": "fixed fraction digits"},
                    "unit": {"type": "string", "description": "suffix after the number"},
                    "currency": {"type": "string", "description": "symbol before the number"},
                },
                "additionalProperties": False,
            },
        },
        "rows": {"$ref": f"{_CT}/DynamicValue", "description": "data binding — always {\"path\": \"/rows\"}"},
        "filters": {"$ref": f"{_CT}/DynamicValue", "description": "optional filter binding — {\"path\": \"/filters\"}"},
        "loading": {"$ref": f"{_CT}/DynamicBoolean", "description": "client-managed loading state — do not set"},
    }, required=["rows"]),
    "BriefingCard": _component("BriefingCard", {
        "headline": {"$ref": f"{_CT}/DynamicString", "description": "one-line key insight (~15 chars, Korean)"},
        "bullets": {"type": "array", "items": {"type": "string"},
                    "description": "objective numeric points, each <=30 chars, max 5"},
        "note": {"$ref": f"{_CT}/DynamicString"},
    }, required=["headline"]),
    "StatCard": _component("StatCard", {
        "label": {"$ref": f"{_CT}/DynamicString", "description": "metric name, e.g. '이번 달 매출'"},
        "value": {"$ref": f"{_CT}/DynamicString", "description": "the headline figure with unit, e.g. '26.0시간'"},
        "delta": {"$ref": f"{_CT}/DynamicString", "description": "optional comparison, e.g. '+12% vs 지난달'"},
        "tone": {"type": "string", "enum": ["neutral", "positive", "negative"],
                 "description": "visual tone of the delta"},
    }, required=["label", "value"]),
    "Notice": _component("Notice", {
        "noticeType": {"type": "string", "enum": ["info", "warning", "success", "error"]},
        "title": {"$ref": f"{_CT}/DynamicString"},
        "message": {"$ref": f"{_CT}/DynamicString"},
    }, required=["noticeType", "message"]),
    "Filter": _component("Filter", {
        "title": {"$ref": f"{_CT}/DynamicString"},
        "columns": {"type": "array", "items": {"type": "string"},
                    "description": "categorical column names to offer as dropdown filters"},
        "rows": {"$ref": f"{_CT}/DynamicValue", "description": "data binding — always {\"path\": \"/rows\"}"},
        "filters": {"$ref": f"{_CT}/DynamicValue", "description": "two-way filter state binding — always {\"path\": \"/filters\"}"},
        "defaultValue": {"type": "object", "additionalProperties": {"type": "string"},
                         "description": "initial filter selection, e.g. {\"DEPT_NAME\": \"영업1팀\"} — set from promoted filters"},
    }, required=["columns", "rows", "filters"]),
}


class _DictCatalogProvider(A2uiCatalogProvider):
    def __init__(self, data: dict[str, Any]):
        self._data = data

    def load(self) -> dict[str, Any]:
        return self._data


@lru_cache(maxsize=1)
def build_catalog_dict() -> dict[str, Any]:
    """번들 basic 카탈로그를 복제하고 커스텀 4종을 등록한 카탈로그 dict."""
    root = list(a2ui.__path__)[0]
    path = os.path.join(root, "assets", SPEC_VERSION, "catalog.json")
    cat = json.loads(open(path, encoding="utf-8").read())
    cat = copy.deepcopy(cat)
    cat["catalogId"] = CATALOG_ID
    for name, schema in _CUSTOM_COMPONENTS.items():
        cat["components"][name] = schema
        # 주의: components 등록만으로는 부족 — anyComponent oneOf에도 넣어야 검증 통과
        cat["$defs"]["anyComponent"]["oneOf"].append({"$ref": f"#/components/{name}"})
    return cat


def _catalog_config() -> CatalogConfig:
    return CatalogConfig(name="query-canvas", provider=_DictCatalogProvider(build_catalog_dict()))


def new_format() -> DirectJsonFormat:
    """요청별 fresh format (parser가 인스턴스에 캐시되므로 스트림마다 새로 생성)."""
    return DirectJsonFormat(
        SPEC_VERSION,
        catalogs=[_catalog_config()],
        schema_modifiers=[_strip_basic_descriptions],
    )


@lru_cache(maxsize=1)
def get_stable_schema_prompt() -> str:
    """SDK가 카탈로그에서 생성하는 시스템 프롬프트 (안정 블록 — 캐시 대상).

    출력 계약(<a2ui-json> 태그, 메시지 스키마)과 컴포넌트 스키마를 포함한다.
    도메인 UI 규칙은 prompts.loader.UI_SYSTEM_PROMPT(별도 블록, 관리자 편집 가능)에 둔다.
    """
    fmt = new_format()
    return fmt.prompt_generator.generate(
        role_description=(
            "You are a data-visualization UI agent for a natural-language data query system. "
            "You compose A2UI component trees from SQL query results."
        ),
        workflow_description=(
            "The SQL result rows are injected into the data model at path /rows by the client. "
            f"Your FIRST message must be createSurface with surfaceId '{SURFACE_ID}' and catalogId "
            f"'{CATALOG_ID}'. After that, output ONLY updateComponents messages for surfaceId "
            f"'{SURFACE_ID}'. The root component id MUST be 'root'. "
            "Never emit updateDataModel or deleteSurface. "
            "Never inline row data into components — always bind with {\"path\": \"/rows\"}."
        ),
        include_schema=True,
        allowed_components=ALLOWED_COMPONENTS,
        # 주의: $defs 키 기준 이름 — camelCase("updateComponents")를 주면 oneOf가 비어버림
        allowed_messages=["CreateSurfaceMessage", "UpdateComponentsMessage"],
    )
