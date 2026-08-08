"""pytest 공통 설정 — backend 루트를 import path에 추가."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
