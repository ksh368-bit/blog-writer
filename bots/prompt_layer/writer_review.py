"""
bots/prompt_layer/writer_review.py
Fact review prompt and heuristic rule constants for writer reviews.
"""

import json
import re
from pathlib import Path

_HEURISTIC_PATTERNS_PATH = Path(__file__).parent.parent.parent / 'data' / 'heuristic_patterns.json'


def _load_learned_heuristic_patterns() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """data/heuristic_patterns.json에서 자가학습된 패턴을 로드."""
    if not _HEURISTIC_PATTERNS_PATH.exists():
        return (), ()
    try:
        data = json.loads(_HEURISTIC_PATTERNS_PATH.read_text(encoding='utf-8'))
        return (
            tuple(data.get('transition_patterns', [])),
            tuple(data.get('recap_patterns', [])),
        )
    except Exception:
        return (), ()

FACT_REVIEW_TEMPLATE = """아래 블로그 본문이 제공된 출처 범위를 벗어나 단정하거나, 출처에 없는 사실을 추가했는지 검토해줘.

검토 기준:
1. 본문의 핵심 주장과 수치, 기능 설명이 아래 출처 발췌 안에서 직접 확인되거나 자연스럽게 추론 가능한가?
2. 출처에 없는 내용을 마치 사실처럼 단정하거나, 보도체 표현으로 과장하지 않았는가?
3. "직접 써봤다", "알려졌다", "보도된 예시처럼" 같은 표현이 출처 근거 없이 들어가 있지 않은가?

PASS 조건:
- 본문이 출처 범위 안에서 조심스럽게 설명되어 있고, 과장이나 근거 없는 단정이 없다.
- 출처 사실을 바탕으로 독자가 이해하기 쉽게 풀어쓴 약한 해석은 모두 허용한다.
- "헷갈림이 줄 수 있다", "판단이 쉬워진다", "이쪽에 더 가깝다", "이 기준으로 보면 된다" 같은 설명형 문장은 PASS다.
- 생활 장면 비유도 PASS다. 단, 새로운 수치나 구체 사례를 사실처럼 덧붙이지 않았을 때만 PASS다.

FAIL 조건:
- 출처에 없는 수치, 시간, 퍼센트, 횟수를 본문이 사실처럼 단정한다.
- 출처에 없는 기능, 정책, 사례, 사용 경험을 새로 만들어 넣는다.
- 출처에는 없는데 업계 반응, 보도 사례, 직접 사용 후기를 꾸며 넣는다.
- 출처에 없는 시간 절감, 분 단위 계산, 주간/월간 합산 효과를 사실처럼 쓴다.

허용:
- 설명을 쉽게 하려고 넣은 약한 생활 장면은 허용한다.
- 다만 그 장면이 새로운 수치, 구체 사례, 공식 선택 규칙, 강한 효과 단정으로 이어지면 FAIL이다.
- "부담이 덜하다", "판단이 쉬워진다", "헷갈림이 줄 수 있다" 정도의 약한 해석은 허용한다.

중요:
- 단순한 설명형 재구성, 요약, 비교, 독자 이해를 돕는 해석만으로는 FAIL 주지 마라.
- 아래 중 하나가 있을 때만 FAIL 줘:
  1) 출처에 없는 숫자/시간/퍼센트/횟수
  2) 출처에 없는 기능/정책/사례/사용 경험
  3) 출처에 없는 업계 반응/보도 사례/직접 체험
  4) 출처에 없는 강한 효과를 사실처럼 단정
  5) 보도체 꾸며쓰기

[출처 발췌]
{source_context}

[본문]
{plain}

출력 형식 (반드시 아래 형식만 사용):
REVIEW_RESULT: PASS 또는 FAIL
FAILED_SENTENCES:
- "실패한 문장" → 이유
"""


WEAK_START_PATTERNS = (
    '하지만 ', '그리고 ', '그런데 ', '결국 ', '즉 ', '다만 ',
    '이것은 ', '이 장면은 ', '이 변화는 ', '이 흐름은 ', '이 사실은 ',
)

DANGLING_PATTERNS = (
    '세 가지', '두 가지', 'A는', 'Cloud는', 'Desktop은', 'Slack과', 'Linear와',
    'Google Drive와', 'PR 검토와', 'CI 분석은', '아침 30분은',
)

ABSTRACT_MARKERS = (
    '의미', '본질', '질문', '시사', '함의', '관점', '태도', '감각', '느낌',
)

REPORT_MARKERS = (
    '보도된', '알려졌다', '업계에서는', '관계자는', '전했다', '전망된다',
)

GENERIC_ENDINGS = (
    '중요하다', '인상적이다', '흥미롭다', '시사한다', '보여준다', '드러낸다',
    '생각해볼 문제다', '눈여겨볼 만하다', '주목할 만하다',
)

RECAP_MARKERS = (
    '읽고 나면', '남는다', '같이 남는다', '함께 남는다', '복잡하지 않다',
    '마지막에 남는', '끝에 남는', '정리하면', '결국 남는',
    '라는 뜻입니다', '라는 의미입니다', '라는 뜻이다', '라는 의미다',
)

TRANSITION_ONLY_PATTERNS = (
    '을 이해하려면, 먼저', '하려면 먼저', '하려면, 먼저',
    '더 중요한 변화는', '더 중요한 것은', '더 큰 문제는', '더 큰 차이는',
    '기능 설명만 놓고 보면',
)

META_OPENERS = (
    '이 글은', '이 구분이', '이 차이는', '끝까지 읽고', '그래서 이 예시 묶음은',
    '이 섹션은', '이 문장은', '이 설명은',
)

ABSTRACT_INTRO_MARKERS = (
    '쉽게 말하면', '첫 구분은', '마지막 기준은', '그래서 기준은', '그래서 마지막',
    '즉 이제', '결국 기준은', '핵심 기준은', '가장 큰 구분은',
)

RELATABLE_MARKERS = (
    '아침', '출근', '회의', '노트북', '맥북', '화면', '탭', '로그', '폴더',
    '요약', '알림', '메신저', '슬랙', '브라우저', '퇴근', '새벽',
)

UNSUPPORTED_EFFECT_MARKERS = (
    '줄어든다', '바뀐다', '아낀다', '절약된다', '돌아온다', '비게 된다',
    '짧아진다', '빨라진다', '덜 든다', '줄일 수 있다',
)

COMMON_ACRONYMS = {
    'AI', 'IT', 'TV', 'PC', 'API', 'HTML', 'CSS', 'JS', 'UI', 'UX', 'DB', 'URL',
    'CEO', 'CFO', 'CTO', 'COO', 'GDP', 'CPU', 'GPU', 'TPU', 'RAM', 'ROM', 'USB',
    'PDF', 'GPS', 'ATM', 'VPN', 'SDK', 'CMS', 'SNS', 'NFT', 'AR', 'VR', 'XR',
    'SSD', 'HDD', 'LTE', 'KPI', 'ROI', 'HR', 'PR', 'QR', 'IP',
}


_META_PLACEHOLDERS = (
    '핵심 문구부터 보면 뜻이 바로 잡힌다',
    '핵심 문구부터 보면',
    '뜻이 바로 잡힌다',
    'META_DESCRIPTION',
    '메타 설명',
    'meta description',
)


def presentation_review(
    article: dict,
    *,
    raw_term_replacements: dict[str, str],
    split_sentences,
) -> tuple[bool, str]:
    issues = []
    title = article.get('title', '')
    meta = article.get('meta', article.get('meta_description', ''))
    body = article.get('body', '')

    # META 플레이스홀더 감지
    if not meta or any(ph in meta for ph in _META_PLACEHOLDERS):
        issues.append('- META 설명이 플레이스홀더이거나 비어 있다. "[무엇을 하면/보면] [무엇이 달라진다]" 구조로 이 글만의 핵심 결과를 담아 다시 써라. 예: "Ravenclaw 폴더에 메모를 넣으면 AI 에이전트를 바꿔도 작업 맥락이 유지된다."')

    for raw in raw_term_replacements:
        if raw in title:
            issues.append(f'- 제목에 "{raw}" 같은 코드식 표기가 남아 있다.')
        if raw in body:
            issues.append(f'- 본문에 "{raw}" 같은 코드식 표기가 남아 있다.')

    # 제목 완결성 검사: 끊긴 제목 감지
    _DANGLING_TITLE_ENDINGS = ('을 보면', '를 보면', '이 보면', '으로 보면', '면 Claude', '면 AI', '면 LLM')
    if title and any(title.endswith(e) for e in _DANGLING_TITLE_ENDINGS):
        issues.append(f'- "{title}" → 제목이 중간에 끊겼다. 결과나 변화가 보이는 완결된 문장으로 마무리해라.')

    # 제목에 글감 핵심 키워드(고유명사) 포함 여부 검사
    topic = article.get('topic', '')
    if topic and title:
        # topic에서 대문자로 시작하거나 영문·숫자 포함된 고유명사 추출
        proper_nouns = re.findall(r'[A-Za-z0-9][A-Za-z0-9\s\.\-]{1,30}', topic)
        proper_nouns = [t.strip() for t in proper_nouns if len(t.strip()) >= 3]
        missing = [n for n in proper_nouns[:3] if n.lower() not in title.lower()]
        if missing and len(missing) == len(proper_nouns[:3]):
            issues.append(
                f'- 제목에 글감 핵심 고유명사({", ".join(missing[:2])})가 없다. '
                '검색에서 찾히려면 도구명·서비스명·브랜드명이 제목에 들어가야 한다.'
            )

    if title and len(title) > 42:
        issues.append(f'- "{title}" → 제목이 너무 길어 목록/공유 화면 가독성이 떨어진다.')

    h2_texts = re.findall(r'<h2>(.*?)</h2>', body, flags=re.IGNORECASE | re.DOTALL)
    for h2 in h2_texts:
        plain = re.sub(r'<[^>]+>', '', h2).strip()
        if not plain:
            issues.append('- 비어 있는 H2가 있다.')
            continue
        if len(plain) > 26:
            issues.append(f'- "{plain}" → H2가 너무 길어 훑어읽기 가독성이 떨어진다.')
        if '<code' in h2.lower():
            issues.append(f'- "{plain}" → H2 안에 code 표기가 들어가 있다.')

    if body.count('<strong>') < max(2, len(h2_texts)):
        issues.append('- 본문 강조가 부족하다. 각 섹션 핵심어를 더 분명하게 드러내야 한다.')

    long_sentences = [s for s in split_sentences(re.sub(r'<[^>]+>', ' ', body)) if len(s) > 80]
    if len(long_sentences) >= 3:
        issues.append('- 긴 문장이 많다. 쉬운세상 톤에 맞게 더 짧게 끊어야 한다.')

    plain_body = re.sub(r'<[^>]+>', ' ', body)
    learned_transition, learned_recap = _load_learned_heuristic_patterns()
    all_transition = TRANSITION_ONLY_PATTERNS + learned_transition
    all_recap_check = tuple(p for p in learned_recap if p not in RECAP_MARKERS)
    for pattern in all_transition:
        if pattern in plain_body:
            issues.append(f'- "{pattern}" 패턴이 감지됨. 전환만 하는 문장이다. 바로 핵심 내용으로 대체해.')
    for pattern in all_recap_check:
        if pattern in plain_body:
            issues.append(f'- "{pattern}" 로 끝나는 환언 문장이 감지됨. 앞 내용을 다시 말하지 말고 새 정보로 교체해.')

    plain_for_acronym = re.sub(r'<[^>]+>', ' ', body)
    seen_acronyms: set[str] = set()
    unexplained_acronyms: list[str] = []
    for m in re.finditer(r'(?<![A-Za-z])[A-Z]{2,6}(?![A-Za-z])', plain_for_acronym):
        acr = m.group()
        if acr in seen_acronyms or acr in COMMON_ACRONYMS:
            continue
        seen_acronyms.add(acr)
        after = plain_for_acronym[m.end():m.end() + 80]
        has_parens = bool(re.match(r'\s*[\(（]', after))
        same_sentence = re.split(r'[.\n]', after)[0]
        has_definition = bool(
            re.match(r'\s*[는은]\s', after)
            and re.search(r'이다\b|이란\b|말한다|가리키|줄임말|뜻한다|의미한다|불린다', same_sentence)
        )
        if not (has_parens or has_definition):
            unexplained_acronyms.append(acr)
    if unexplained_acronyms:
        issues.append(
            f'- 다음 약어/고유명사가 첫 등장 시 설명 없이 사용됨: {", ".join(unexplained_acronyms)}. '
            '첫 등장 때 괄호 안에 한국어 풀이를 추가하라. 예: "LHC(대형 강입자 충돌기)".'
        )

    if issues:
        return False, '\n'.join(dict.fromkeys(issues))
    return True, ''


def structure_review(
    article: dict,
    *,
    has_action_result_shape,
) -> tuple[bool, str]:
    issues = []
    body = article.get('body', '')
    corner = article.get('corner', '')
    paragraphs = [p.strip() for p in re.findall(r'<p>(.*?)</p>', body, flags=re.IGNORECASE | re.DOTALL)]
    h2_texts = [re.sub(r'<[^>]+>', '', h).strip() for h in re.findall(r'<h2>(.*?)</h2>', body, flags=re.IGNORECASE | re.DOTALL)]

    if len(h2_texts) < 3:
        issues.append('- 글의 단락 구조가 너무 짧다. 최소 3개 이상의 의미 있는 섹션이 필요하다.')

    if paragraphs:
        first_paragraph = re.sub(r'<[^>]+>', '', paragraphs[0])
        first_action, first_result = has_action_result_shape(first_paragraph)
        if not (
            first_action
            or first_result
            or any(token in first_paragraph for token in ('헷갈리는 지점', '오해', '뜻', '핵심 문구', '먼저 볼 것'))
        ):
            issues.append('- 첫 문단이 글의 핵심을 너무 늦게 말한다. 독자가 바로 주제를 잡을 수 있어야 한다.')

    if corner == '쉬운세상':
        relatable_markers = ('아침', '출근', '회의', '노트북', '맥북', '화면', '탭', '로그', '폴더', '퇴근', '브라우저')
        relatable_paragraphs = [
            p for p in paragraphs
            if any(marker in re.sub(r'<[^>]+>', '', p) for marker in relatable_markers)
        ]
        min_relatable_paragraphs = 2 if len(paragraphs) >= 4 else 1
        if len(relatable_paragraphs) < min_relatable_paragraphs:
            issues.append('- 쉬운세상 글치고 생활 장면이 부족하다. 독자가 자기 경험을 떠올릴 문단이 더 필요하다.')

        last_paragraph = re.sub(r'<[^>]+>', '', paragraphs[-1]) if paragraphs else ''
        last_action, last_result = has_action_result_shape(last_paragraph)
        if not (
            last_action
            or any(token in last_paragraph for token in ('고르면', '선택', '정하면', '먼저 보면', '기준'))
            or last_result
        ):
            issues.append('- 마지막 문단이 독자 행동 기준으로 닫히지 않는다. "그래서 뭘 고르면 되는지"가 남아야 한다.')

    normalized_h2 = [' '.join(text.split()) for text in h2_texts]
    if len(normalized_h2) != len(set(normalized_h2)):
        issues.append('- 섹션 제목이 반복된다. 각 단락의 역할이 더 분명해야 한다.')

    if issues:
        return False, '\n'.join(dict.fromkeys(issues))
    return True, ''
