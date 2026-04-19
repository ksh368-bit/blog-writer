"""
conftest.py — pytest 루트 설정

프로젝트 루트를 sys.path에 추가해 bots.* 모듈을 테스트에서 임포트할 수 있게 한다.
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# runtime_guard: 테스트 환경에서 패키지 설치 검사를 건너뜀
_mock_runtime_guard = types.ModuleType("runtime_guard")
_mock_runtime_guard.ensure_project_runtime = lambda *a, **kw: None  # no-op
sys.modules.setdefault("runtime_guard", _mock_runtime_guard)
