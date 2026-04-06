"""
자가 개선 봇 (bots/self_improve.py)
역할: 파이프라인 완료 후 Claude 검수 실패 문장을 분석해
      data/heuristic_patterns.json을 자동 업데이트.
      writer_review.py의 presentation_review()가 이 JSON을 읽어
      다음 파이프라인부터 동일 패턴을 Claude 검수 전에 차단한다.
"""

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'

HEURISTIC_PATTERNS_PATH = DATA_DIR / 'heuristic_patterns.json'
PIPELINE_LOG_PATH = LOG_DIR / 'pipeline.log'

# 동일 패턴이 몇 회 이상 등장해야 등록하는가 (단일 파이프라인 런 내 기준)
PATTERN_THRESHOLD = 2

logger = logging.getLogger(__name__)

# 탐지 후보 패턴 목록 (새 패턴은 여기에 추가)
# 이미 writer_review.py 하드코드에 있는 것도 포함 — JSON 중복 검사로 방지
_ENDING_CANDIDATES = [
    '라는 뜻입니다', '라는 의미입니다', '라는 뜻이다', '라는 의미다',
    '봐야 합니다', '봐야 한다', '는 것입니다', '는 셈입니다',
]
_START_CANDIDATES = [
    '더 중요한', '더 큰 문제', '더 큰 차이', '더 큰 변화',
    '문제는 이', '문제는 그', '문제는 바로',
    '이 과정은', '이 변화는', '이 차이는', '이 기능은', '이 흐름은',
]
_MID_CANDIDATES = [
    '기능 설명만 놓고 보면',
    '을 이해하려면', '를 이해하려면',
    '하려면 먼저', '하려면, 먼저',
    '보면 이미 예상', '에서 이미 예상',
]


def load_heuristic_patterns() -> dict:
    if not HEURISTIC_PATTERNS_PATH.exists():
        return {'transition_patterns': [], 'recap_patterns': []}
    try:
        data = json.loads(HEURISTIC_PATTERNS_PATH.read_text(encoding='utf-8'))
        data.setdefault('transition_patterns', [])
        data.setdefault('recap_patterns', [])
        return data
    except Exception:
        return {'transition_patterns': [], 'recap_patterns': []}


def save_heuristic_patterns(patterns: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    patterns['updated_at'] = datetime.now().isoformat()
    HEURISTIC_PATTERNS_PATH.write_text(
        json.dumps(patterns, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def extract_review_failures_from_log(log_path: Path, last_n_lines: int = 8000) -> list[str]:
    """pipeline.log 후반부에서 Claude 검수 실패 문장만 추출."""
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding='utf-8').splitlines()[-last_n_lines:]
    failures = []
    in_block = False
    for line in lines:
        if 'Claude 검수 실패' in line:
            in_block = True
            continue
        if in_block:
            m = re.match(r'[-\s]*"(.+?)"\s*→', line)
            if m:
                failures.append(m.group(1).strip())
            elif line.strip() and not line.strip().startswith('-'):
                in_block = False
    return failures


def detect_new_patterns(sentences: list[str]) -> tuple[list[str], list[str]]:
    """실패 문장 목록에서 임계값 이상 반복되는 패턴 반환."""
    counter: Counter = Counter()
    new_transition: set[str] = set()
    new_recap: set[str] = set()

    for sent in sentences:
        for p in _ENDING_CANDIDATES:
            if sent.endswith(p) or sent.endswith(p + '.'):
                counter[p] += 1
                if counter[p] >= PATTERN_THRESHOLD:
                    new_recap.add(p)
        for p in _START_CANDIDATES:
            if sent.startswith(p):
                counter[p] += 1
                if counter[p] >= PATTERN_THRESHOLD:
                    new_transition.add(p)
        for p in _MID_CANDIDATES:
            if p in sent:
                counter[p] += 1
                if counter[p] >= PATTERN_THRESHOLD:
                    new_transition.add(p)

    return sorted(new_transition), sorted(new_recap)


def update_heuristic_patterns(new_transition: list[str], new_recap: list[str]) -> int:
    """새 패턴을 JSON에 병합. 추가된 개수 반환."""
    existing = load_heuristic_patterns()
    existing_t = set(existing['transition_patterns'])
    existing_r = set(existing['recap_patterns'])

    added = 0
    for p in new_transition:
        if p not in existing_t:
            existing_t.add(p)
            added += 1
            logger.info(f"[자가개선] 새 전환 패턴 등록: '{p}'")
    for p in new_recap:
        if p not in existing_r:
            existing_r.add(p)
            added += 1
            logger.info(f"[자가개선] 새 환언 패턴 등록: '{p}'")

    if added:
        existing['transition_patterns'] = sorted(existing_t)
        existing['recap_patterns'] = sorted(existing_r)
        save_heuristic_patterns(existing)

    return added


def run() -> None:
    """파이프라인 완료 후 호출. 실패 패턴 분석 → heuristic_patterns.json 업데이트."""
    failures = extract_review_failures_from_log(PIPELINE_LOG_PATH)
    if not failures:
        logger.info("[자가개선] 분석할 검수 실패 문장 없음")
        return

    logger.info(f"[자가개선] 검수 실패 문장 {len(failures)}개 분석 시작")
    new_t, new_r = detect_new_patterns(failures)
    added = update_heuristic_patterns(new_t, new_r)

    if added:
        logger.info(f"[자가개선] 완료 — {added}개 패턴 신규 등록 (다음 파이프라인부터 적용)")
    else:
        logger.info("[자가개선] 완료 — 신규 패턴 없음 (이미 등록됐거나 임계값 미달)")
