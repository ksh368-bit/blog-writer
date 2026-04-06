"""
bots/prompt_layer/writer_memory.py
Persistent memory helpers for writer prompts.
"""

import json
import re
from datetime import datetime
from pathlib import Path

# 이 횟수 이상 누적된 패턴은 영구 규칙으로 승격
PROMOTE_THRESHOLD = 3


# ─── 누적 학습 규칙 ───────────────────────────────────

def _learned_rules_path(memory_path: Path) -> Path:
    return memory_path.parent / 'learned_rules.json'


def load_learned_rules(memory_path: Path) -> dict:
    path = _learned_rules_path(memory_path)
    if not path.exists():
        return {'failure_rules': {}, 'success_rules': {}}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            return {'failure_rules': {}, 'success_rules': {}}
        return {
            'failure_rules': dict(data.get('failure_rules', {})),
            'success_rules': dict(data.get('success_rules', {})),
        }
    except Exception:
        return {'failure_rules': {}, 'success_rules': {}}


def _save_learned_rules(memory_path: Path, rules: dict) -> None:
    path = _learned_rules_path(memory_path)
    path.write_text(
        json.dumps({**rules, 'updated_at': datetime.now().isoformat()},
                   ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _feedback_to_rule(text: str, kind: str) -> str:
    """피드백 문장을 프롬프트 규칙 형식으로 변환."""
    text = text.strip().lstrip('-').strip()
    if kind == 'failure':
        # 실패 피드백 → 금지 규칙
        # "첫 문단에서 독자가 취할 행동이 없다." → "- 첫 문단 첫 문장은 독자가 취할 행동과 얻는 결과를 함께 써."
        return f'- [학습됨] {text}'
    else:
        # 성공 피드백 → 권장 규칙
        return f'- [학습됨] {text}'


_NOISE_PATTERNS = re.compile(
    r'(현재 약 \d+단어|약 \d+단어|단어\)|단어\s*이상|'
    r'"[가-힣a-zA-Z]{2,10}"로 시작하는 문장이|'   # 특정 고유명사 반복 지적 (범용성 없음)
    r'다음 약어/고유명사가 첫 등장 시|'            # 약어 지적은 개별 기사 의존
    r'이번 런에서|이번에도|이번 런|'
    r'자동 발행 최소|품질 점수 \d+점)',
    re.IGNORECASE,
)


def _is_promotable(text: str) -> bool:
    """범용 규칙으로 승격할 수 있는 피드백인지 판단."""
    if _NOISE_PATTERNS.search(text):
        return False
    if len(text.strip()) < 10:
        return False
    return True


def _try_promote(memory_path: Path, counts: dict, kind: str) -> int:
    """threshold 이상 카운트된 항목을 learned_rules에 추가. 새로 승격된 수 반환."""
    rules = load_learned_rules(memory_path)
    bucket = 'failure_rules' if kind == 'failure' else 'success_rules'
    promoted = 0
    for key, count in counts.items():
        if int(count) >= PROMOTE_THRESHOLD and key not in rules[bucket]:
            text = key.split('::', 1)[1] if '::' in key else key
            if not _is_promotable(text):
                continue
            rules[bucket][key] = {
                'rule': _feedback_to_rule(text, kind),
                'count': int(count),
                'promoted_at': datetime.now().isoformat(),
            }
            promoted += 1
    if promoted:
        _save_learned_rules(memory_path, rules)
    return promoted


def build_learned_rules_section(memory_path: Path, corner: str = '전체') -> str:
    """프롬프트에 삽입할 누적 학습 규칙 섹션을 반환."""
    rules = load_learned_rules(memory_path)
    failure_rules = [v['rule'] for v in rules.get('failure_rules', {}).values()]
    success_rules = [v['rule'] for v in rules.get('success_rules', {}).values()]
    parts = []
    if failure_rules:
        parts.append('[누적 학습 규칙 — 반복 실패 패턴 (반드시 피할 것)]')
        parts.extend(failure_rules)
    if success_rules:
        parts.append('[누적 학습 규칙 — 반복 성공 패턴 (적극 활용)]')
        parts.extend(success_rules)
    return '\n'.join(parts).strip()


def empty_writer_memory() -> dict:
    return {
        'recent_failures': [],
        'recent_successes': [],
        'failure_counts': {},
        'success_counts': {},
        'corners': {},
    }


def ensure_memory_shape(data: dict) -> dict:
    memory = empty_writer_memory()
    if not isinstance(data, dict):
        return memory
    memory['recent_failures'] = list(data.get('recent_failures', []))[-8:]
    memory['recent_successes'] = list(data.get('recent_successes', []))[-8:]
    memory['failure_counts'] = dict(data.get('failure_counts', {}))
    memory['success_counts'] = dict(data.get('success_counts', {}))
    corners = data.get('corners', {})
    if isinstance(corners, dict):
        for corner, payload in corners.items():
            if not isinstance(payload, dict):
                continue
            memory['corners'][corner] = {
                'failure_counts': dict(payload.get('failure_counts', {})),
                'success_counts': dict(payload.get('success_counts', {})),
            }
    return memory


def load_writer_memory(memory_path: Path) -> dict:
    if not memory_path.exists():
        return empty_writer_memory()
    try:
        data = json.loads(memory_path.read_text(encoding='utf-8'))
        return ensure_memory_shape(data)
    except Exception:
        return empty_writer_memory()


def save_writer_memory(memory_path: Path, memory: dict) -> None:
    memory_path.write_text(
        json.dumps(
            {
                'recent_failures': list(memory.get('recent_failures', []))[-8:],
                'recent_successes': list(memory.get('recent_successes', []))[-8:],
                'failure_counts': dict(memory.get('failure_counts', {})),
                'success_counts': dict(memory.get('success_counts', {})),
                'corners': dict(memory.get('corners', {})),
                'updated_at': datetime.now().isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding='utf-8',
    )


def classify_memory_point(text: str) -> tuple[str, str]:
    normalized = re.sub(r'\s+', ' ', text).strip()
    lower = normalized.lower()
    if any(token in normalized for token in ('제목', 'meta', 'slug', '행동과 결과', '제목에서')):
        return 'title', normalized
    if any(token in normalized for token in ('첫 문단', '도입', '첫 문장', '메타 문장')):
        return 'intro', normalized
    if any(token in normalized for token in ('마지막 문단', '마지막 문장', '결론', '마무리')):
        return 'conclusion', normalized
    if any(token in normalized for token in ('H2', '섹션 제목', '단락 구조', '섹션')):
        return 'structure', normalized
    if any(token in normalized for token in ('길고', '딱딱하다', '추상', '정리 문장', '메타 문장', '요약')):
        return 'body', normalized
    if any(token in lower for token in ('출처', '보도체', '시간 절감', '퍼센트', '수치')):
        return 'fact', normalized
    return 'body', normalized


def append_writer_memory(memory_path: Path, kind: str, items: list[str], corner: str = '전체') -> None:
    cleaned = []
    for item in items:
        normalized = re.sub(r'\s+', ' ', str(item)).strip()
        if normalized:
            cleaned.append(normalized)
    if not cleaned:
        return

    memory = load_writer_memory(memory_path)
    bucket = 'recent_failures' if kind == 'failure' else 'recent_successes'
    current = list(memory.get(bucket, []))
    count_bucket = 'failure_counts' if kind == 'failure' else 'success_counts'
    memory.setdefault('corners', {})
    memory['corners'].setdefault(corner, {'failure_counts': {}, 'success_counts': {}})
    corner_count_bucket = memory['corners'][corner]['failure_counts' if kind == 'failure' else 'success_counts']
    for item in cleaned:
        if item not in current:
            current.append(item)
        label, normalized = classify_memory_point(item)
        key = f'{label}::{normalized}'
        memory[count_bucket][key] = int(memory[count_bucket].get(key, 0)) + 1
        corner_count_bucket[key] = int(corner_count_bucket.get(key, 0)) + 1
    memory[bucket] = current[-8:]
    save_writer_memory(memory_path, memory)

    # 임계값 이상 누적된 패턴 → 영구 규칙으로 자동 승격
    promoted = _try_promote(memory_path, memory[count_bucket], kind)
    if promoted:
        import logging
        logging.getLogger(__name__).info(
            f"writer_memory: {promoted}개 패턴이 누적 학습 규칙으로 승격됨 "
            f"(임계값 {PROMOTE_THRESHOLD}회)"
        )


def extract_memory_points(feedback: str) -> list[str]:
    return [
        re.sub(r'^\-\s*', '', line).strip()
        for line in str(feedback).splitlines()
        if line.strip().startswith('-')
    ][:5]


def top_memory_items(counts: dict, limit: int = 5) -> list[str]:
    ranked = sorted(counts.items(), key=lambda item: (-int(item[1]), item[0]))
    return [key.split('::', 1)[1] for key, _ in ranked[:limit]]


def build_memory_guidance(memory_path: Path, corner: str = '전체') -> str:
    memory = load_writer_memory(memory_path)
    failures = memory.get('recent_failures', [])
    successes = memory.get('recent_successes', [])
    global_failures = top_memory_items(memory.get('failure_counts', {}), limit=4)
    global_successes = top_memory_items(memory.get('success_counts', {}), limit=4)
    corner_payload = memory.get('corners', {}).get(corner, {})
    corner_failures = top_memory_items(corner_payload.get('failure_counts', {}), limit=4)
    corner_successes = top_memory_items(corner_payload.get('success_counts', {}), limit=4)
    parts = []
    if corner_failures:
        parts.append(f'[최근 {corner}에서 자주 걸린 문제]')
        parts.extend(f'- {item}' for item in corner_failures)
    if corner_successes:
        parts.append(f'[최근 {corner}에서 통과에 도움 된 방향]')
        parts.extend(f'- {item}' for item in corner_successes)
    if global_failures:
        parts.append('[전체 공통 실패 패턴]')
        parts.extend(f'- {item}' for item in global_failures)
    if global_successes:
        parts.append('[전체 공통 성공 패턴]')
        parts.extend(f'- {item}' for item in global_successes)
    if failures:
        parts.append('[최근 자주 걸린 문제]')
        parts.extend(f'- {item}' for item in failures[-5:])
    if successes:
        parts.append('[최근 통과에 도움 된 방향]')
        parts.extend(f'- {item}' for item in successes[-5:])
    return '\n'.join(parts).strip()
