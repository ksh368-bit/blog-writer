"""
bots/prompt_layer/writer_review.py
Fact review prompt and heuristic rule constants for writer reviews.
"""

import datetime
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
    # 결과 표현이 없는데 조건절(~하면/보면/쓰면 등)로만 끝나는 제목 감지
    _RESULT_PATTERNS = re.compile(
        r'(된다|안 된다|보인다|줄어|쉬워|달라진다|잡힌다|낮아|높아|바뀐다|없어진다|'
        r'생긴다|만들어진다|줄어든다|덜하다|적어진다|커진다|나온다|나타난다|알 수 있다|'
        r'파악된다|해결된다|사라진다|빨라진다|늘어난다|올라간다|내려간다|알게 된다|'
        r'든다|이다|였다|됐다|있다|없다)'
    )
    _VERB_MYEON = re.compile(
        r'(하면|보면|쓰면|되면|읽으면|고르면|넣으면|바꾸면|걸면|열면|올리면|내리면|'
        r'줄이면|늘리면|확인하면|사용하면|설치하면|실행하면|적용하면|입력하면|주문하면|'
        r'클릭하면|선택하면|연결하면|등록하면|구독하면|설정하면|붙이면|꺼내면|찾으면|'
        r'켜면|끄면|나누면|모으면|올리면|담으면|묶으면|돌리면)$'
    )
    if title and (
        any(title.endswith(e) for e in _DANGLING_TITLE_ENDINGS)
        or (_VERB_MYEON.search(title) and not _RESULT_PATTERNS.search(title))
    ):
        issues.append(f'- "{title}" → 제목이 조건절로만 끝났다. "[무엇을 하면] [이렇게 된다]" 구조로 결과까지 완결해라.')

    # 제목에 글감 핵심 키워드(고유명사) 포함 여부 검사
    # 영문+숫자 고유명사 AND 한국어 브랜드/서비스명 모두 체크
    topic = article.get('topic', '')
    if topic and title:
        topic_clean = re.sub(r'[\[\]()（）【】「」『』《》<>]', ' ', topic)

        # 영문/숫자 고유명사 (기존)
        en_nouns = re.findall(r'[A-Za-z0-9][A-Za-z0-9\s\.\-]{1,30}', topic_clean)
        en_nouns = [t.strip() for t in en_nouns if len(t.strip()) >= 3]

        # 한국어 고유명사 후보 — 2~6 한글 + 끝 조사 1글자 제거 시도
        _KR_PARTICLES_END = set('을를이가은는와과의에도만서랑')
        _KR_COMMON = {
            # 일반 명사/동사 파생어
            '관련', '이유', '방법', '결과', '현황', '분석', '정리', '소식', '내용',
            '최신', '최초', '세계', '한국', '국내', '해외', '공식', '발표', '업데이트',
            '완전', '정도', '수준', '이후', '이전', '중심', '기반', '활용', '구현',
            '지원', '협약', '제공', '출시', '공개', '추진', '확대', '개선', '강화',
            # 뉴스 헤드라인 노이즈
            '게시판', '속보', '단독', '긴급', '종합', '업계', '전문가', '관계자',
            '서비스', '플랫폼', '시스템', '솔루션', '프로그램',
            # 행정/경제 일반어
            '소상공인', '중소기업', '스타트업', '대기업', '투자자', '사용자',
            '시장', '산업', '분야', '영역', '부문',
        }
        kr_raw = re.findall(r'[가-힣]{2,7}', topic_clean)
        kr_nouns = []
        seen_kr: set = set()
        for w in kr_raw:
            # 끝 1글자가 조사이면 제거
            candidate = w[:-1] if (w[-1] in _KR_PARTICLES_END and len(w) > 2) else w
            if candidate not in seen_kr and candidate not in _KR_COMMON and len(candidate) >= 2:
                seen_kr.add(candidate)
                kr_nouns.append(candidate)

        # 영문 고유명사: 하나도 제목에 없으면 경고
        if en_nouns:
            missing_en = [n for n in en_nouns[:3] if n.lower() not in title.lower()]
            if missing_en and len(missing_en) == len(en_nouns[:3]):
                issues.append(
                    f'- 제목에 글감 핵심 고유명사({", ".join(missing_en[:2])})가 없다. '
                    '검색에서 찾히려면 도구명·서비스명·브랜드명이 제목에 들어가야 한다.'
                )
        # 영문 고유명사 없을 때: 한국어 키워드 중 짧은 것(브랜드명 우선)이 제목에 없으면 경고
        elif kr_nouns:
            # 짧은 단어 우선 — 2-3음절이 브랜드명일 가능성 높음
            kr_nouns_sorted = sorted(kr_nouns[:6], key=lambda w: (len(w), kr_nouns.index(w)))
            top_kr = kr_nouns_sorted[:3]
            missing_kr = [n for n in top_kr if n not in title]
            # 주요 키워드가 하나도 없으면 경고 (짧은 단어 우선 메시지 — 브랜드명 강조)
            if missing_kr and len(missing_kr) == len(top_kr):
                issues.append(
                    f'- 제목에 글감 핵심 키워드({", ".join(top_kr[:2])})가 없다. '
                    '검색에서 찾히려면 브랜드명·서비스명 등 이 글만의 핵심 키워드가 제목에 들어가야 한다.'
                )

    # QP1: 플레이스홀더 앱명 감지 — 'Word. 한국어' 패턴 (영어 단어 + 마침표 + 공백 + 한국어)
    _PLACEHOLDER_APP = re.compile(r'\b[A-Z][A-Za-z]{1,}\.[ \u00a0][가-힣]')
    _body_plain_for_qp1 = re.sub(r'<[^>]+>', ' ', body)
    if (title and _PLACEHOLDER_APP.search(title)) or _PLACEHOLDER_APP.search(_body_plain_for_qp1):
        issues.append(
            '- 제목 또는 본문에 "Word. 한국어" 형태의 앱명 패턴이 있다 (예: "Blank. 정답이..."). '
            '실제 앱명이라면 "영단어 앱 Blank"처럼 설명과 함께 표기해라. '
            '아직 결정되지 않은 앱명이라면 지금 구체적인 이름으로 교체해라.'
        )

    if title and len(title) > 38:
        issues.append(
            f'- "{title}" → 제목이 {len(title)}자로 너무 길다. '
            '모바일 Google 검색 결과 38자 이후는 잘린다. '
            '38자 이하로 줄이되 손실·숫자·방법 패턴은 유지해라.'
        )
    if title and len(title) < 15:
        issues.append(f'- "{title}" → 제목이 너무 짧다 ({len(title)}자). 글감의 핵심 키워드와 행동/결과를 담아 15자 이상으로 써라.')

    # QT6: Freshness 신호 — 금융·정책 시의성 주제면 제목에 현재 연도 포함 권장
    _TIMELY_TOPICS = re.compile(
        r'(금리|물가|환율|수출|주가|코스피|부동산|대출|청약|세금|정책|지원금|보조금|개정|개편)'
    )
    if title and _TIMELY_TOPICS.search(article.get('topic', '') or title):
        _CURRENT_YEAR = datetime.datetime.now().year
        _YEAR_IN_TITLE = re.compile(r'20[2-9][0-9]년?')
        if not _YEAR_IN_TITLE.search(title):
            issues.append(
                f'- "{title}" → 시의성 주제인데 제목에 연도가 없다. '
                f'"{_CURRENT_YEAR}년 금리 변화 대비법"처럼 현재 연도를 포함하면 Google CTR이 높아진다.'
            )

    # QT1: 제목 클릭 유발 패턴 검사 (조회수 1만+ 분석 기반)
    if title:
        _LOSS_FRAME     = re.compile(r'(안 하면|모르면|못하면|안 받으면|이거 모르면|하지 않으면)')
        _NUMBER_TITLE   = re.compile(r'[0-9]+\s*(가지|개|초|원|배|번|단계|분|주|달|년|위|명|억|만원)')
        _REVERSE_TITLE  = re.compile(r'(하지 마세요|신청하지 마|사지 마세요|쓰지 마세요)')
        _QUESTION_TITLE = re.compile(r'[?？]|왜\s|어떻게\s|얼마나\s')
        _HOW_TO_TITLE   = re.compile(r'(방법|하는 법|가이드|전략|비결|공식|원리|이유)')
        _ACTION_RESULT  = re.compile(
            r'[가-힣]{2,}면.{0,20}(된다|줄어든다|달라진다|빨라진다|쉬워진다|낸다|바뀐다|오른다|내린다|늘어난다)'
        )
        if not any(p.search(title) for p in [
            _LOSS_FRAME, _NUMBER_TITLE, _REVERSE_TITLE, _QUESTION_TITLE, _HOW_TO_TITLE, _ACTION_RESULT
        ]):
            _topic_snippet = (article.get('topic', '') or '')[:40]
            issues.append(
                f'- "{title}" → 제목에 클릭 유발 패턴 없음. '
                '①손실 프레임("이거 안 하면 손해"), ②숫자("5가지","3초"), '
                '③역발상("하지 마세요"), ④질문("왜~?"), ⑤방법("이유·해결법") 중 하나 필수. '
                f'현재 글감: "{_topic_snippet}..." — 이 글감의 핵심 수치·문제·변화를 제목에 직접 드러내라.'
            )

    # QT2: 제목 내 핵심 키워드 위치 검사 (Google 스니펫 최적화)
    if title and len(title) > 20:
        _topic_words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', article.get('topic', ''))
        _STOP_TITLE_WORDS = {'이', '가', '을', '를', '의', '은', '는', '와', '과', '도', '에', '서'}
        _kw_candidates = [w for w in _topic_words if w not in _STOP_TITLE_WORDS]
        if _kw_candidates:
            title_start = title[:min(15, len(title))]
            if not any(kw in title_start for kw in _kw_candidates):
                issues.append(
                    f'- "{title}" → 핵심 키워드가 제목 뒷부분에 있다. '
                    'Google 검색 스니펫은 제목 앞 30자를 강조 표시하므로 핵심 키워드를 앞으로 이동해라.'
                )

    # Q1: 목차 섹션 감지 — Wikipedia처럼 보이고 도입부 흡입력을 죽임
    if re.search(r'<h[23][^>]*>\s*목차\s*</h[23]>', body, re.IGNORECASE):
        issues.append(
            '- 본문에 목차 섹션이 있다. 개인 블로그가 아닌 위키처럼 보이고 도입부 흡입력을 죽인다. '
            '목차를 제거하고 바로 본론으로 시작해라.'
        )

    # Q2: 도입부 설명체 감지 — "X는 Y이다/입니다" 형태의 정의·사전 설명으로 시작하면 훅이 없음
    _DECLARATIVE_END = re.compile(r'(이다|입니다|됩니다|합니다|줍니다|습니다)[.\s]*$')
    _SUBJECT_PARTICLE = re.compile(r'^.{0,20}[은는이가]\s')
    _HOOK_SIGNALS = re.compile(r'[0-9]|었|았|했|는데|인데|지만|면서도|[?？]|보니|했더니')
    _first_p = re.search(r'<p>(.*?)</p>', body, re.IGNORECASE | re.DOTALL)
    if _first_p:
        _first_text = re.sub(r'<[^>]+>', '', _first_p.group(1)).strip()
        # 전체 첫 문단을 대상으로 검사 ('보다', '되다' 등 중간 '다'에서 오분리 방지)
        if (len(_first_text) > 15
                and _DECLARATIVE_END.search(_first_text)
                and _SUBJECT_PARTICLE.match(_first_text)
                and not _HOOK_SIGNALS.search(_first_text)):
            issues.append(
                f'- 도입부 첫 문단이 "X는 Y이다/입니다" 형태의 설명체로 시작한다. '
                '독자를 잡아끄는 장면·사건·질문으로 바꿔라. '
                '예: "터미널에 명령어 하나를 입력했더니 AI가 코드 리뷰를 시작했다."'
            )

    # Q3: 마무리 스펙/설치 문장 감지 — 독자에게 인상 없이 기술 안내로 끝나는 패턴
    _SPEC_CLOSING = re.compile(
        r'(다운로드할 수 있|설치할 수 있|확인할 수 있|'
        r'공식 문서에서|GitHub에서|공식 사이트에서|홈페이지에서|'
        r'플랜 이상|버전 이상|이상에서만 사용|'
        r'명령어로 진행|명령어로 설치|'
        r'오픈소스 프로젝트이며|라이브러리 설치 여부|'
        r'pip install|npm install|brew install)'
    )
    _all_p = re.findall(r'<p>(.*?)</p>', body, re.IGNORECASE | re.DOTALL)
    if _all_p:
        _last_p_text = re.sub(r'<[^>]+>', '', _all_p[-1]).strip()
        if _SPEC_CLOSING.search(_last_p_text):
            issues.append(
                '- 마무리 문단이 스펙 안내·설치 방법·다운로드 안내로 끝난다. '
                '독자에게 남는 인상이 없다. 인사이트·관점·행동 촉구 문장으로 바꿔라. '
                '예: "한 번 써보면 안 쓰기 어려워진다."'
            )

    h2_texts = re.findall(r'<h2>(.*?)</h2>', body, flags=re.IGNORECASE | re.DOTALL)
    # Q4: 섹션 제목 결론 선공개 패턴 감지 — 독자 호기심을 죽이는 서술형 h2
    _CONCLUSION_H2 = re.compile(
        r'(한다|이다|된다|있다|없다|낮다|높다|좋다|나쁘다|크다|작다|많다|적다|'
        r'빠르다|느리다|오른다|내린다|달라진다|줄어든다|늘어난다|올라간다|내려간다|'
        r'강하다|약하다|쉽다|어렵다|중요하다|필요하다)$'
    )
    for h2 in h2_texts:
        plain = re.sub(r'<[^>]+>', '', h2).strip()
        if not plain:
            issues.append('- 비어 있는 H2가 있다.')
            continue
        if len(plain) > 26:
            issues.append(f'- "{plain}" → H2가 너무 길어 훑어읽기 가독성이 떨어진다.')
        if '<code' in h2.lower():
            issues.append(f'- "{plain}" → H2 안에 code 표기가 들어가 있다.')
        if _CONCLUSION_H2.search(plain):
            issues.append(
                f'- "{plain}" → 섹션 제목이 결론을 미리 말해버린다. '
                '독자 호기심을 죽이는 패턴이다. '
                '"왜 ~할까", "~이 다른 이유", "~하는 구조"처럼 궁금증을 유발하는 형태로 바꿔라.'
            )
        # QC2: 추상 H2 경고 — Google 섹션 색인에 무기여
        _ABSTRACT_H2_TERMS = re.compile(
            r'^(소개|개요|배경|현황|정리|마무리|결론|요약|들어가며|시작하며|왜 중요한가|무엇인가)$'
        )
        if _ABSTRACT_H2_TERMS.match(plain):
            issues.append(
                f'- "{plain}" → 추상적인 H2 제목이다. '
                'Google 섹션 색인에 무기여. '
                '"왜 ~할까", "~이 다른 이유", "~하는 구조"처럼 검색 키워드가 담긴 형태로 바꿔라.'
            )

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

    # Q8: 섹션별 두괄식 확장 — 2번째 이후 H2 섹션 첫 문단도 선언체("X는 Y이다") 시작 감지
    # Q2는 글 전체의 첫 문단만 검사하지만, 인기 블로그는 각 섹션도 두괄식으로 시작해야 함
    _DECLARATIVE_END = re.compile(r'(이다|입니다|됩니다|합니다|줍니다|습니다)[.\s]*$')
    _SUBJECT_PARTICLE = re.compile(r'^.{0,20}[은는이가]\s')
    _HOOK_SIGNALS = re.compile(r'[0-9]|었|았|했|는데|인데|지만|면서도|[?？]|보니|했더니')
    _section_re = re.compile(r'<h2[^>]*>.*?</h2>\s*((?:<p>.*?</p>\s*)*)', re.IGNORECASE | re.DOTALL)
    _section_matches = list(_section_re.finditer(body))
    _declarative_sections: list[str] = []
    for _sm in _section_matches[1:]:  # 첫 섹션은 Q2가 처리, 두 번째부터 검사
        _sec_content = _sm.group(1)
        _sec_first_p = re.search(r'<p>(.*?)</p>', _sec_content, re.IGNORECASE | re.DOTALL)
        if not _sec_first_p:
            continue
        _sec_text = re.sub(r'<[^>]+>', '', _sec_first_p.group(1)).strip()
        if (len(_sec_text) > 15
                and _DECLARATIVE_END.search(_sec_text)
                and _SUBJECT_PARTICLE.match(_sec_text)
                and not _HOOK_SIGNALS.search(_sec_text)):
            _declarative_sections.append(_sec_text[:30])
    if _declarative_sections:
        issues.append(
            f'- 섹션 첫 문단 설명체: {len(_declarative_sections)}개 H2 섹션의 첫 문단이 '
            '"X는 Y이다/입니다" 형태로 시작한다. '
            '각 섹션도 숫자·사건·과거형으로 바로 시작하는 두괄식으로 써라. '
            f'예: "{_declarative_sections[0]}..."'
        )

    # Q9: 문단 추상어 오프너 반복 감지 — "이것은", "일반적으로", "많은 사람들이" 등이 2개+ 반복 시 경고
    # 인기 블로그 연구: 추상어로 시작하는 문단이 2개 이상이면 글 정보 밀도가 낮아 독자 이탈
    _ABSTRACT_OPENER_RE = re.compile(
        r'^(이것은\s|이것이\s|이것을\s|'
        r'일반적으로\s|일반적인\s|'
        r'많은 사람들이\s|많은 사람들은\s|많은 분들이\s|많은 분들은\s|'
        r'현대 사회에서\s|현대인들은\s|현대인들이\s|'
        r'오늘날\s|요즘 시대에\s|'
        r'사람들은 보통\s|우리는 보통\s)'
    )
    _all_p_texts = [re.sub(r'<[^>]+>', '', p).strip()
                    for p in re.findall(r'<p>(.*?)</p>', body, re.IGNORECASE | re.DOTALL)]
    _abstract_opener_count = sum(
        1 for p in _all_p_texts[1:]  # 첫 문단 제외 (Q2가 처리)
        if _ABSTRACT_OPENER_RE.match(p) and len(p) > 10
    )
    if _abstract_opener_count >= 2:
        issues.append(
            f'- 추상어 오프너가 {_abstract_opener_count}개 문단에서 반복된다. '
            '"이것은", "일반적으로", "많은 사람들이", "오늘날" 등으로 시작하면 '
            '독자가 글에서 구체 정보를 얻지 못하고 이탈한다. '
            '숫자·고유명사·사례로 바로 시작해라.'
        )

    # Q5: 본문 최소 텍스트 길이 검사 — 공백 제거 기준 900자 미만이면 독자가 읽기에 너무 짧음
    _plain_no_space = re.sub(r'\s', '', re.sub(r'<[^>]+>', '', body))
    if len(_plain_no_space) < 900:
        issues.append(
            f'- 본문 텍스트가 너무 짧다 ({len(_plain_no_space)}자). '
            '조회수 1만+ 블로그 기준 최소 900자 (목표 1,500자 이상)이어야 한다.'
        )

    # QS1: 스캔가능성 — 목록 요소 없음 경고
    if not re.search(r'<(ul|ol|table)\b', body, re.IGNORECASE):
        issues.append(
            '- 본문에 목록(<ul>/<ol>) 또는 표(<table>)가 없다. '
            '모바일 독자는 목록 구조가 있는 글에서 체류시간이 길다. '
            '비교 항목·단계·기준·체크리스트 중 하나를 목록으로 표현해라.'
        )

    # QK1: 키워드 밀도 — topic 핵심어의 과반이 본문에 2회 미만이면 Google 주제 신호 부족
    _topic = article.get('topic', '')
    if _topic:
        _STOP_KW = {
            '현황', '전망', '이유', '방법', '결과', '분석', '정리', '소식', '내용',
            '상황', '문제', '효과', '기준', '종류', '특징', '차이', '비교', '활용',
        }
        _topic_kws = [w for w in re.findall(r'[가-힣]{2,}|[A-Za-z0-9]{3,}', _topic)
                      if w not in _STOP_KW]
        _topic_kws = list(dict.fromkeys(_topic_kws))[:4]
        if _topic_kws:
            _body_plain = re.sub(r'<[^>]+>', '', body)
            _under = [kw for kw in _topic_kws if _body_plain.count(kw) < 2]
            if len(_under) > len(_topic_kws) // 2:
                issues.append(
                    f'- 핵심 키워드 {_under[:3]}이(가) 본문에 1회 이하 등장한다. '
                    'Google 주제 신호를 위해 핵심 키워드를 본문에 자연스럽게 2~3회 배치해라.'
                )

    # Q6: 구체적 수치 포함 필수 — 퍼센트·금액·날짜·배수·횟수 등 최소 2개
    # '몇 초', '몇 분' 같은 한글 수량 표현도 수치로 인정 (기술 글 오탐 방지)
    _NUMBER_RE = re.compile(
        r'[0-9]+[%％]|'
        r'[0-9]+\.?[0-9]*[원달러억만천백]|'
        r'[0-9]{4}년|'
        r'[0-9]+배|'
        r'[0-9]+개|[0-9]+명|'
        r'[0-9]+초|[0-9]+분|[0-9]+시간|[0-9]+주|[0-9]+달|[0-9]+월|'
        r'몇\s*(초|분|시간|일|주|달|개월|배|개|명|번)'  # 한글 수량 표현
    )
    _concrete_numbers = _NUMBER_RE.findall(plain_body)
    if len(_concrete_numbers) < 2:
        issues.append(
            f'- 본문에 구체적인 수치가 부족하다 ({len(_concrete_numbers)}개). '
            '퍼센트, 금액, 날짜, 횟수 등 숫자를 최소 2개 이상 포함해 독자가 실감할 수 있게 해라. '
            '예: "3.4%", "500원", "2주", "4월"'
        )

    # Q7: 연속 긴 문장 리듬 검사 — 65자 초과 문장이 3개 이상 연속되면 모바일 가독성 파괴
    _rhythm_sentences = split_sentences(re.sub(r'<[^>]+>', ' ', body))
    _consec_long = 0
    _max_consec_long = 0
    for _rs in _rhythm_sentences:
        if len(_rs.strip()) > 65:
            _consec_long += 1
            _max_consec_long = max(_max_consec_long, _consec_long)
        else:
            _consec_long = 0
    if _max_consec_long >= 3:
        issues.append(
            f'- 65자 초과 긴 문장이 {_max_consec_long}개 연속된다. '
            '모바일 독자를 위해 짧은 문장(30자 내외)을 사이사이에 넣어 읽기 리듬을 살려라.'
        )

    # Q10: 추측 표현 남용 감지 — "것 같다/듯하다/것으로 보인다" 3개+ 반복 시 신뢰도 하락
    # 한국 인기 블로그 연구: 추측 어미 남발은 글의 신뢰도를 크게 떨어뜨림
    _HEDGING_RE = re.compile(
        r'것 같다|것 같습니다|인 것 같다|인 것 같습니다|'
        r'인 듯하다|인 듯합니다|[가-힣] 듯하다|[가-힣] 듯합니다|'
        r'것으로 보인다|것으로 보입니다|'
        r'할 것 같다|할 것 같습니다|'
        r'[가-힣] 것 같다|[가-힣] 것 같습니다'
    )
    _plain_body_q10 = re.sub(r'<[^>]+>', '', body)
    _hedging_matches = _HEDGING_RE.findall(_plain_body_q10)
    if len(_hedging_matches) >= 3:
        issues.append(
            f'- 추측 표현이 {len(_hedging_matches)}회 반복된다 ({_hedging_matches[0]!r} 등). '
            '"것 같다", "듯하다", "것으로 보인다" 등 추측 어미를 남발하면 독자 신뢰도가 떨어진다. '
            '확인 가능한 사실·수치·경험으로 교체하고, 추측이 필요하면 1~2개로 제한해라.'
        )

    # Q11: 과도하게 긴 단락 금지 — 200자 초과 단락 2개 이상이면 모바일 가독성 파괴
    # 브런치·네이버 인기 글 연구: 단락 길이가 너무 길면 독자 이탈
    _long_paragraph_count = sum(
        1 for p in _all_p
        if len(re.sub(r'<[^>]+>', '', p).strip()) > 200
    )
    if _long_paragraph_count >= 2:
        issues.append(
            f'- 긴 단락이 {_long_paragraph_count}개다. '
            '200자 초과 단락은 모바일 독자가 읽기 힘들다. '
            '각 단락을 3~5문장(100~150자) 안으로 쪼개라.'
        )

    # Q12: 동일 종결어미 과반복 금지 — "할 수 있다/수 있습니다" 4회+ 반복 시 단조로운 리듬 경고
    # 한국어 글쓰기 연구: 같은 어미가 반복되면 리듬이 단조로워져 독자 이탈
    _ENDING_PATTERNS = [
        (re.compile(r'할 수 있다'), '할 수 있다'),
        (re.compile(r'수 있습니다'), '수 있습니다'),
    ]
    _plain_body_q12 = re.sub(r'<[^>]+>', '', body)
    for _ending_re, _ending_label in _ENDING_PATTERNS:
        _ending_count = len(_ending_re.findall(_plain_body_q12))
        if _ending_count >= 4:
            issues.append(
                f'- 종결 표현 "{_ending_label}"이 {_ending_count}회 반복된다. '
                '같은 어미가 반복되면 글 리듬이 단조로워진다. '
                '"된다", "이다", "있다", "달라진다" 등 다양한 어미로 교체해라.'
            )
            break  # 하나만 감지해도 충분

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

    # QB1: 도입부 훅 타입 검사 (충격 수치 / 역설 질문 / 생생한 장면)
    if paragraphs:
        _first_p_text = re.sub(r'<[^>]+>', '', paragraphs[0])
        _SHOCK_STAT  = re.compile(r'[0-9]+\s*[%％배원억만초분주달년개명]')
        _PARADOX_Q   = re.compile(r'(인데|인데도|지만|해도).{1,20}(왜|이상|역설|모순)|[?？]')
        _VIVID_SCENE = re.compile(
            r'(아침|출근|퇴근|점심|저녁|새벽|회의|터미널|노트북|화면|클릭|입력|열었|켰|봤더니|했더니|'
            r'통장|월급|이자|주식|배당|대출|적금|예금|청구서|연금|보험|가계)'
        )
        if not (_SHOCK_STAT.search(_first_p_text) or _PARADOX_Q.search(_first_p_text) or _VIVID_SCENE.search(_first_p_text)):
            issues.append(
                '- 도입부에 독자를 잡아끄는 훅 타입이 없다. '
                '①충격 수치("한 달 만에 3배"), ②역설 질문("잘 팔렸는데 왜 손실?"), '
                '③생생한 장면("아침에 노트북을 열었더니") 중 하나로 시작해라.'
            )

    if corner == '쉬운세상':
        relatable_markers = (
            # 기술/업무 장면
            '아침', '출근', '회의', '노트북', '맥북', '화면', '탭', '로그', '폴더', '퇴근', '브라우저',
            # 금융/일상 생활 장면
            '통장', '월급', '이자', '주식', '배당', '대출', '적금', '예금', '청구서', '연금', '보험',
            '주식 앱', '월급날', '가계',
            # 에너지/교통/소비 생활 장면
            '주유소', '기름값', '가스비', '택시', '배달', '전기요금', '난방비', '물가',
            '장바구니', '마트', '편의점', '카페', '식비', '공과금',
        )
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
            or any(token in last_paragraph for token in (
                '고르면', '선택', '정하면', '먼저 보면', '기준',          # 선택 기반 (기존)
                '지금', '바로', '오늘', '이번 달', '당장',                 # 시간 기반
                '안 하면', '모르면', '못하면',                              # 손실 기반
                '먼저 해보', '확인해보', '써보면', '해보면',               # 행동 즉시성
            ))
            or last_result
        ):
            issues.append('- 마지막 문단이 독자 행동 기준으로 닫히지 않는다. "그래서 뭘 고르면 되는지"가 남아야 한다.')

    normalized_h2 = [' '.join(text.split()) for text in h2_texts]
    if len(normalized_h2) != len(set(normalized_h2)):
        issues.append('- 섹션 제목이 반복된다. 각 단락의 역할이 더 분명해야 한다.')

    if issues:
        return False, '\n'.join(dict.fromkeys(issues))
    return True, ''
