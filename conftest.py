"""
conftest.py — pytest 루트 설정

프로젝트 루트를 sys.path에 추가해 bots.* 모듈을 테스트에서 임포트할 수 있게 한다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
