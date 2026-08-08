# -*- coding: utf-8 -*-
"""가역적 PII 마스킹 테스트."""

from ui_engine.anonymizer import (
    anonymize_with_mapping,
    get_pii_columns,
    restore_from_mapping,
)


class TestPiiDetection:
    def test_detects_name_columns(self):
        data = [{"EMP_NAME": "김철수", "HOURS": 8}]
        assert get_pii_columns(data) == ["EMP_NAME"]

    def test_detects_korean_column_names(self):
        data = [{"사원명": "김철수", "부서명": "인사팀"}]
        # 사원명은 PII, 부서명은 제외 패턴
        assert get_pii_columns(data) == ["사원명"]

    def test_excludes_dept_and_position(self):
        data = [{"DEPT_NAME": "인사팀", "POSITION_NAME": "과장", "COMPANY_NAME": "휴넬"}]
        assert get_pii_columns(data) == []

    def test_detects_emp_id_email_phone(self):
        data = [{"EMP_ID": "E001", "EMAIL": "a@b.com", "PHONE": "010-1234"}]
        assert set(get_pii_columns(data)) == {"EMP_ID", "EMAIL", "PHONE"}

    def test_code_columns_excluded(self):
        data = [{"ATT_TYPE_CODE": "01", "STATUS": "Y"}]
        assert get_pii_columns(data) == []

    def test_empty_data(self):
        assert get_pii_columns([]) == []


class TestAnonymizeRestore:
    def test_roundtrip(self):
        data = [
            {"EMP_NAME": "김철수", "HOURS": 8},
            {"EMP_NAME": "이영희", "HOURS": 9},
        ]
        masked, mapping = anonymize_with_mapping(data)
        # 마스킹됨
        assert masked[0]["EMP_NAME"].startswith("[PERSON_")
        assert masked[1]["EMP_NAME"].startswith("[PERSON_")
        assert masked[0]["EMP_NAME"] != masked[1]["EMP_NAME"]
        # 비 PII 컬럼 유지
        assert masked[0]["HOURS"] == 8
        # 복원
        text = f"{masked[0]['EMP_NAME']}의 근무시간은 8시간"
        assert restore_from_mapping(text, mapping) == "김철수의 근무시간은 8시간"

    def test_same_value_same_key(self):
        data = [{"EMP_NAME": "김철수"}, {"EMP_NAME": "김철수"}]
        masked, _ = anonymize_with_mapping(data)
        assert masked[0]["EMP_NAME"] == masked[1]["EMP_NAME"]

    def test_restore_nested_dict_and_list(self):
        data = [{"EMP_NAME": "김철수"}]
        masked, mapping = anonymize_with_mapping(data)
        key = masked[0]["EMP_NAME"]
        obj = {"headline": f"{key} 최다 근무", "bullets": [f"{key}: 10h"]}
        restored = restore_from_mapping(obj, mapping)
        assert restored["headline"] == "김철수 최다 근무"
        assert restored["bullets"][0] == "김철수: 10h"

    def test_no_pii_returns_original(self):
        data = [{"DEPT_NAME": "인사팀", "CNT": 3}]
        masked, mapping = anonymize_with_mapping(data)
        assert masked == data
        assert mapping == {}

    def test_none_values_skipped(self):
        data = [{"EMP_NAME": None, "HOURS": 8}]
        masked, mapping = anonymize_with_mapping(data)
        assert masked[0]["EMP_NAME"] is None
        assert mapping == {}
