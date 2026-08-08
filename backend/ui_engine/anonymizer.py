"""
가역적 개인정보 난독화.
매핑 키로 대체 → AI 분석 → 매핑 키를 원본으로 복원.

흐름:
1. anonymize_with_mapping(data) → (anonymized_data, mapping)
2. AI가 anonymized_data로 분석, summary에 [PERSON_1] 같은 키 사용
3. restore_from_mapping(text, mapping) → 원본 이름이 복원된 텍스트
"""

import re

# 개인정보로 판단할 컬럼명 패턴 (대소문자 무시)
PII_COLUMN_PATTERNS = [
    (r".*(?:이름|NAME|성명|직원명|사원명|고객명|회원명).*", "PERSON"),
    (r".*(?:사번|EMP_ID|직원ID|사원번호|EMPLOYEE.?ID|고객번호|회원번호|CUST_ID|CUSTOMER.?ID|MEMBER.?ID).*", "PID"),
    (r".*(?:메일|EMAIL|MAIL).*", "EMAIL"),
    (r".*(?:전화|연락처|PHONE|TEL|MOBILE|핸드폰|휴대폰).*", "PHONE"),
    (r".*(?:주민|SSN|RESIDENT).*", "SSN"),
    (r".*(?:주소|ADDRESS|ADDR).*", "ADDR"),
    (r".*(?:계좌|ACCOUNT|BANK).*", "ACCOUNT"),
]

# PII로 잘못 매칭되는 것을 방지하는 제외 패턴 (조직/직급/회사 등은 NAME이 들어가도 PII 아님)
# 예: DEPT_NAME, COMPANY_NAME, POSITION_NAME, TEAM_NAME, JOB_NAME 등
PII_EXCLUDE_PATTERNS = [
    r".*(?:DEPT|부서|부서명|TEAM|팀|팀명|GROUP|그룹).*",
    r".*(?:COMPANY|회사|법인|CORP|ORG).*",
    r".*(?:POSITION|직급|직위|직책|JOB|RANK).*",
    r".*(?:CODE|코드|CD).*",  # 코드명은 PII 아님
    r".*(?:STATUS|상태|TYPE|유형|구분|KIND).*",
    r".*(?:PROD|PRODUCT|ITEM|GOODS|BRAND|CATEGORY|상품|품목|카테고리|지역|REGION).*",  # 커머스: 상품/카테고리명은 PII 아님
]

_pii_patterns = [(re.compile(pat, re.IGNORECASE), prefix) for pat, prefix in PII_COLUMN_PATTERNS]
_pii_exclude_patterns = [re.compile(pat, re.IGNORECASE) for pat in PII_EXCLUDE_PATTERNS]


def _detect_pii_columns(columns: list[str]) -> dict[str, str]:
    """컬럼명 → PII 유형 prefix 매핑 반환. 조직/직급 등은 제외."""
    result = {}
    for col in columns:
        # 제외 패턴에 먼저 매칭되면 PII 아님 (예: DEPT_NAME)
        if any(ex.match(col) for ex in _pii_exclude_patterns):
            continue
        for regex, prefix in _pii_patterns:
            if regex.match(col):
                result[col] = prefix
                break
    return result


def anonymize_with_mapping(data: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """
    데이터에서 PII를 매핑 키로 대체한다.

    Returns:
        (anonymized_data, mapping)
        - anonymized_data: PII가 [PERSON_1] 등으로 대체된 데이터
        - mapping: {"[PERSON_1]": "류건우", "[EMP_1]": "E014", ...}
    """
    if not data:
        return data, {}

    columns = list(data[0].keys())
    pii_cols = _detect_pii_columns(columns)

    if not pii_cols:
        return data, {}

    # 값 → 매핑 키 생성
    value_to_key: dict[str, str] = {}  # "류건우" → "[PERSON_1]"
    counters: dict[str, int] = {}      # "PERSON" → 1

    for row in data:
        for col, prefix in pii_cols.items():
            val = row.get(col)
            if val is None:
                continue
            val_str = str(val)
            if val_str not in value_to_key:
                counters[prefix] = counters.get(prefix, 0) + 1
                key = f"[{prefix}_{counters[prefix]}]"
                value_to_key[val_str] = key

    # 역매핑: "[PERSON_1]" → "류건우"
    mapping = {v: k for k, v in value_to_key.items()}

    # 데이터 대체
    anonymized = []
    for row in data:
        new_row = dict(row)
        for col in pii_cols:
            val = new_row.get(col)
            if val is not None:
                new_row[col] = value_to_key.get(str(val), str(val))
        anonymized.append(new_row)

    return anonymized, mapping


def restore_from_mapping(text: str | dict, mapping: dict[str, str]) -> str | dict:
    """
    AI 응답에서 매핑 키를 원본 값으로 복원한다.
    문자열 또는 딕셔너리(summary 객체) 모두 처리.
    """
    if not mapping:
        return text

    if isinstance(text, dict):
        # summary 객체 전체를 재귀적으로 복원
        return {k: restore_from_mapping(v, mapping) for k, v in text.items()}

    if isinstance(text, list):
        return [restore_from_mapping(item, mapping) for item in text]

    if not isinstance(text, str):
        return text

    result = text
    for key, original in mapping.items():
        result = result.replace(key, original)
    return result


def get_pii_columns(data: list[dict]) -> list[str]:
    """데이터에서 개인정보로 감지된 컬럼 목록을 반환한다."""
    if not data:
        return []
    return list(_detect_pii_columns(list(data[0].keys())).keys())
