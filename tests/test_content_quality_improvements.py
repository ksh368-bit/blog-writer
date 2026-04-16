"""
tests/test_content_quality_improvements.py

인기 콘텐츠 비교 분석 기반 글 품질 개선 테스트 (TDD)

개선 항목:
  Q1. 목차(TOC) 자동 생성 금지
  Q2. 도입부 설명체 금지 (훅 강제)
  Q3. 마무리 스펙/설치 문장 금지 (인사이트로 종료)
  Q4. 섹션 제목이 결론을 미리 말하는 패턴 감지

각 테스트는 현재 코드에서 RED → 개선 후 GREEN이 되어야 한다.
"""
import re

import pytest


# ─── 공통 헬퍼 ────────────────────────────────────────────────

def _review(article: dict):
    from bots.prompt_layer.writer_review import presentation_review
    split_sentences = lambda t: re.split(r'(?<=[.!?다])\s', t)
    return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)


def _base_article(**overrides) -> dict:
    """검수 통과 가능한 기본 아티클. 개별 테스트에서 body만 바꿔 씀."""
    base = {
        'title': 'Claude Code를 설치하면 AI 코딩이 바로 시작된다',
        'meta': 'Claude Code를 설치하면 터미널에서 AI 코딩 작업이 자동화된다.',
        'body': (
            '<h2>처음 연결하는 순간</h2>'
            '<p>터미널에 명령어 하나를 입력했더니 AI가 코드 리뷰를 시작했다.</p>'
            '<h2>실제로 달라지는 것</h2>'
            '<p>반복 작업이 줄어들고 코드 흐름을 더 빨리 파악할 수 있다.</p>'
            '<h2>언제 쓰면 가장 효과적일까</h2>'
            '<p>PR 리뷰 직전이나 낯선 코드베이스를 처음 볼 때 꺼내면 된다.</p>'
            '<h2>직접 써본 경험의 차이</h2>'
            '<p>코딩 도구를 바꾸면 작업 흐름이 달라진다. 한 번 써보면 안 쓰기 어려워진다.</p>'
            '<strong>Claude Code</strong>'
        ),
        'topic': 'Claude Code 설치 및 활용',
        'corner': '쉬운세상',
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════
# Q1. 목차(TOC) 자동 생성 금지
# ══════════════════════════════════════════════════════════════

class TestNoTableOfContents:
    """본문에 목차 섹션이 있으면 presentation_review가 이를 지적해야 한다."""

    def test_toc_h2_section_flagged(self):
        """<h2>목차</h2> 블록이 있으면 검수 실패해야 한다."""
        article = _base_article(body=(
            '<h2>목차</h2>'
            '<ul><li>항공료</li><li>배송료</li><li>외식비</li></ul>'
            '<h2>항공료가 먼저 오른다</h2>'
            '<p>비행기 한 번 띄울 때 연료유 비용이 수천 원씩 오른다.</p>'
            '<h2>배송료는 2주 뒤에 따라온다</h2>'
            '<p>배달앱은 식당·고객 양쪽과 협상해야 해서 늦다.</p>'
            '<h2>직접 써본 경험의 차이</h2>'
            '<p>4월 안에 숙박 예약을 마치면 인상 전 가격을 잡을 수 있다.</p>'
            '<strong>유가</strong>'
        ))
        ok, msg = _review(article)
        assert not ok, "목차 섹션이 있는데 검수 통과됨"
        assert '목차' in msg, f"'목차' 언급 없음: {msg}"

    def test_toc_h3_section_flagged(self):
        """<h3>목차</h3> 형태도 감지해야 한다."""
        article = _base_article(body=(
            '<h3>목차</h3>'
            '<ol><li>도입</li><li>본론</li></ol>'
            '<h2>도입</h2><p>내용이다.</p>'
            '<h2>본론</h2><p>내용이다.</p>'
            '<h2>직접 써본 경험의 차이</h2><p>결론이다. 이렇게 하면 달라진다.</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        assert not ok, "h3 목차도 감지해야 한다"
        assert '목차' in msg

    def test_no_toc_passes(self):
        """목차 없이 바로 본론으로 시작하면 Q1 관련 지적이 없어야 한다."""
        article = _base_article()  # 기본 아티클에는 목차 없음
        ok, msg = _review(article)
        toc_issues = [l for l in msg.split('\n') if '목차' in l]
        assert not toc_issues, f"목차 없는데 오탐: {toc_issues}"

    def test_toc_mid_body_flagged(self):
        """목차가 본문 중간에 있어도 감지해야 한다."""
        article = _base_article(body=(
            '<h2>시작</h2><p>유가가 올랐다.</p>'
            '<h2>목차</h2><ul><li>항공료</li></ul>'
            '<h2>항공료</h2><p>내용.</p>'
            '<h2>직접 써본 경험의 차이</h2><p>결론이다.</p>'
            '<strong>유가</strong>'
        ))
        ok, msg = _review(article)
        assert not ok
        assert '목차' in msg


# ══════════════════════════════════════════════════════════════
# Q2. 도입부 설명체 금지 (훅 강제)
# ══════════════════════════════════════════════════════════════

class TestOpeningHook:
    """첫 번째 <p> 문단이 '~은/는 ~이다' 형태의 순수 설명체면 경고해야 한다."""

    # 나쁜 도입부: 정의/설명으로 시작
    @pytest.mark.parametrize('bad_opening', [
        '유가 상승은 항공료와 배달비에 영향을 줍니다.',
        'Claude Code는 Anthropic이 만든 AI 코딩 도구입니다.',
        '공공배달앱은 민간 배달앱보다 수수료가 낮은 플랫폼입니다.',
        'ETF는 여러 주식을 묶어 거래소에서 사고파는 상품입니다.',
    ])
    def test_declarative_first_paragraph_flagged(self, bad_opening):
        """정의·설명체로 시작하는 도입부는 훅이 없으므로 지적해야 한다."""
        article = _base_article(body=(
            f'<h2>소개</h2>'
            f'<p>{bad_opening}</p>'
            '<p>이 글에서는 이 주제를 알아본다.</p>'
            '<h2>본론</h2><p>내용이다.</p>'
            '<h2>직접 써본 경험의 차이</h2><p>이렇게 하면 달라진다. 직접 해보면 확인된다.</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        assert not ok, f"설명체 도입부가 통과됨: '{bad_opening}'"
        assert '도입부' in msg or '첫 문단' in msg, f"도입부 관련 언급 없음: {msg}"

    # 좋은 도입부: 장면·질문·사건으로 시작
    @pytest.mark.parametrize('good_opening', [
        '터미널에 명령어 하나를 입력했더니 AI가 코드 리뷰를 시작했다.',
        '4월에 항공권을 예매하려다 가격을 보고 멈췄다.',
        '같은 배달 주문인데 앱에 따라 가게 사장이 받는 돈이 다르다.',
        '환율이 1,400원을 넘은 날, 달러 배당금을 받은 투자자는 손해를 봤다.',
    ])
    def test_hook_opening_passes(self, good_opening):
        """장면·사건·질문으로 시작하는 도입부는 Q2 지적이 없어야 한다."""
        article = _base_article(body=(
            f'<h2>소개</h2>'
            f'<p>{good_opening}</p>'
            '<p>이런 상황이 생기는 이유가 있다.</p>'
            '<h2>본론</h2><p>내용이다.</p>'
            '<h2>직접 써본 경험의 차이</h2><p>이렇게 하면 달라진다. 직접 해보면 확인된다.</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        intro_issues = [l for l in msg.split('\n') if '도입부' in l or '첫 문단' in l]
        assert not intro_issues, f"좋은 도입부에 오탐: {intro_issues}"


# ══════════════════════════════════════════════════════════════
# Q3. 마무리 스펙/설치 문장 금지 (인사이트로 종료)
# ══════════════════════════════════════════════════════════════

class TestClosingInsight:
    """마지막 <p> 문단이 스펙 안내·설치 방법·다운로드 안내로 끝나면 경고해야 한다."""

    @pytest.mark.parametrize('bad_closing', [
        'Ravenclaw는 오픈소스 프로젝트이며, 지원 에이전트는 클라이언트 라이브러리 설치 여부에 따라 달라집니다.',
        '현재 버전은 0.3.2이며 GitHub에서 다운로드할 수 있습니다.',
        '설치는 pip install ravenclaw 명령어로 진행하면 됩니다.',
        '자세한 사용법은 공식 문서에서 확인할 수 있습니다.',
        '이 기능은 Pro 플랜 이상에서만 사용 가능합니다.',
    ])
    def test_spec_closing_flagged(self, bad_closing):
        """스펙/설치 안내로 끝나는 마무리는 인사이트가 없으므로 지적해야 한다."""
        article = _base_article(body=(
            '<h2>소개</h2><p>터미널에서 명령어를 입력하니 AI가 응답했다.</p>'
            '<h2>본론</h2><p>반복 작업이 줄어들었다.</p>'
            f'<h2>직접 써본 경험의 차이</h2><p>{bad_closing}</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        assert not ok, f"스펙 마무리가 통과됨: '{bad_closing}'"
        assert '마무리' in msg or '마지막' in msg or '결말' in msg, f"마무리 관련 언급 없음: {msg}"

    @pytest.mark.parametrize('good_closing', [
        '코딩 도구를 바꾸면 작업 흐름이 달라진다. 한 번 써보면 안 쓰기 어려워진다.',
        '유가가 오르는 속도보다 예약 버튼을 누르는 속도가 빠른 사람이 덜 낸다.',
        '같은 배달 주문이 가게 사장에게 더 남게 만드는 선택이 있다.',
        '지금 이 차이를 아는 것만으로도 4월 지출이 달라진다.',
    ])
    def test_insight_closing_passes(self, good_closing):
        """인사이트·관점·행동 촉구로 끝나는 마무리는 Q3 지적이 없어야 한다."""
        article = _base_article(body=(
            '<h2>소개</h2><p>터미널에서 명령어를 입력하니 AI가 응답했다.</p>'
            '<h2>본론</h2><p>반복 작업이 줄어들었다.</p>'
            f'<h2>직접 써본 경험의 차이</h2><p>{good_closing}</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        closing_issues = [l for l in msg.split('\n') if '마무리 문단' in l or ('마지막' in l and '스펙' in l)]
        assert not closing_issues, f"좋은 마무리에 오탐: {closing_issues}"


# ══════════════════════════════════════════════════════════════
# Q4. 섹션 제목이 결론을 미리 공개하는 패턴 감지
# ══════════════════════════════════════════════════════════════

class TestSectionTitleCuriosity:
    """h2 제목이 '~한다', '~이다' 서술형으로 결론을 미리 말하면 경고해야 한다."""

    @pytest.mark.parametrize('boring_h2', [
        '항공사가 가장 빠르게 반영한다',
        '택시는 2주 뒤에 오른다',
        '배달앱 수수료가 민간보다 낮다',
        'Claude Code가 가장 좋은 선택이다',
    ])
    def test_conclusion_first_h2_flagged(self, boring_h2):
        """결론을 미리 드러내는 h2 제목은 독자 호기심을 죽이므로 지적해야 한다."""
        article = _base_article(body=(
            f'<h2>{boring_h2}</h2>'
            '<p>터미널에서 명령어를 입력했더니 AI가 응답했다. 결과가 빠르게 나왔다.</p>'
            '<h2>실제로 달라지는 점</h2>'
            '<p>반복 작업이 줄었다.</p>'
            '<h2>직접 써본 경험의 차이</h2>'
            '<p>한 번 써보면 안 쓰기 어려워진다.</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        assert not ok, f"결론 선공개 h2 제목이 통과됨: '{boring_h2}'"
        assert '섹션' in msg or 'h2' in msg.lower() or '제목' in msg, f"섹션 제목 관련 언급 없음: {msg}"

    @pytest.mark.parametrize('curious_h2', [
        '항공료는 왜 제일 먼저 오를까',
        '배달앱 수수료, 어디가 얼마나 다를까',
        '내 배당금이 줄어드는 진짜 이유',
        '같은 주문인데 가게 수익이 달라지는 구조',
    ])
    def test_curious_h2_passes(self, curious_h2):
        """호기심을 유발하는 h2 제목은 Q4 지적이 없어야 한다."""
        article = _base_article(body=(
            f'<h2>{curious_h2}</h2>'
            '<p>터미널에서 명령어를 입력했더니 AI가 응답했다. 결과가 빠르게 나왔다.</p>'
            '<h2>실제로 달라지는 점</h2>'
            '<p>반복 작업이 줄었다.</p>'
            '<h2>직접 써본 경험의 차이</h2>'
            '<p>한 번 써보면 안 쓰기 어려워진다.</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        section_issues = [l for l in msg.split('\n') if ('섹션' in l or 'h2' in l.lower()) and '제목' in l]
        assert not section_issues, f"좋은 h2 제목에 오탐: {section_issues}"


# ─── H2 제목이 문장 검사에서 제외되어야 한다 ──────────────────────────
# 근본 원인: _heuristic_review()에서 H2 태그를 제거하면 H2 내용이
# 본문 <p> 텍스트와 이어져 "왜 WTI를 봐야 할까?"처럼 짧은 H2 제목이
# "너무 짧아 정보나 감각의 밀도가 부족하다" 오탐을 발생시킨다.

class TestH2ExcludedFromHeuristicReview:
    """H2 제목 텍스트는 _heuristic_review 문장 길이/밀도 검사에서 제외돼야 한다."""

    def test_short_h2_question_not_flagged_as_low_density(self):
        """H2 수사 질문('왜 WTI를 봐야 할까?')이 문장 밀도 오탐으로 걸리면 안 된다."""
        from bots.writer_bot import _heuristic_review
        body = (
            '<h2>왜 WTI를 봐야 할까?</h2>'
            '<p>주유소 기름값은 국제 유가 변동 2주 후에 반영된다. '
            '2024년 4월 WTI는 배럴당 97달러였다. '
            '유가가 1% 오르면 국내 휘발유 가격은 0.3% 오른다.</p>'
            '<p>가스비 청구서에서 이 변화를 주유소 방문 2주 뒤에 느낄 수 있다.</p>'
            '<h2>생활비에 미치는 경로</h2>'
            '<p>택시비와 배달비도 유가 상승 2~4주 뒤에 오른다.</p>'
            '<p>월급 들어오는 날 장바구니 물가도 달라져 있을 수 있다.</p>'
            '<h2>지금 할 수 있는 준비</h2>'
            '<p>가스비 고정 요금제를 미리 신청해두면 유가 변동에 덜 흔들린다.</p>'
            '<p>주유비가 오르기 전에 주유해두면 연간 몇만 원을 아낄 수 있다.</p>'
        )
        ok, msg = _heuristic_review(body, require_relatable=False)
        short_h2_issue = '왜 WTI를 봐야 할까?' in msg and '밀도' in msg
        assert not short_h2_issue, f"H2 질문이 문장 밀도 오탐으로 걸림: {msg}"

    def test_short_h2_단어_not_flagged(self):
        """단어 하나짜리 H2('이상하다', '왜일까')가 문장 밀도 오탐으로 걸리면 안 된다."""
        from bots.writer_bot import _heuristic_review
        body = (
            '<h2>이상한 패턴</h2>'
            '<p>CEO가 주식을 팔았는데 주가는 오히려 올랐다. '
            '2024년 4월, 화이트호크 CEO가 89만 달러 상당을 매도했다.</p>'
            '<p>통장에 배당이 들어오는 날 이런 뉴스를 보면 판단이 헷갈릴 수 있다.</p>'
            '<h2>매도 신호 해석 방법</h2>'
            '<p>매도액이 보유 주식의 5% 미만이면 단순 자금 조달일 가능성이 높다.</p>'
            '<p>CEO 매도 이력을 SEC 공시에서 확인해보면 패턴을 파악할 수 있다.</p>'
            '<h2>투자자가 볼 체크리스트</h2>'
            '<p>매도액, 매도 빈도, 최근 회사 뉴스를 함께 보면 판단이 쉬워진다.</p>'
            '<p>주식 앱에서 내부자 거래 내역을 확인해보면 패턴이 보인다.</p>'
        )
        ok, msg = _heuristic_review(body, require_relatable=False)
        short_h2_issues = [l for l in msg.split('\n') if '이상한' in l and '밀도' in l]
        assert not short_h2_issues, f"H2 단어가 문장 밀도 오탐으로 걸림: {short_h2_issues}"


# ─── AI 응답 텍스트 disclaimer 오염 방지 ─────────────────────────────

class TestDisclaimerAIResponseLeak:
    """disclaimer 필드에 AI의 완성 메시지가 포함되면 안 된다.
    ---DISCLAIMER--- 이후 AI가 '완성했습니다.' 같은 코멘트를 추가한 경우
    _sanitize_article()이 이를 제거해야 한다."""

    def _make_article(self, disclaimer: str) -> dict:
        return {
            'title': 'ROE 목표 10%',
            'meta': '신한금융 ROE 설명',
            'slug': 'roe-test',
            'tags': ['금융'],
            'corner': '쉬운세상',
            'body': '<h2>제목</h2><p>테스트 본문입니다.</p>',
            'disclaimer': disclaimer,
        }

    def test_ai_completion_message_stripped_from_disclaimer(self):
        """'완성했습니다.' 뒤에 오는 AI 코멘트가 disclaimer에서 제거돼야 한다."""
        from bots.writer_bot import _sanitize_article
        disclaimer = (
            '본 글은 신한금융 공식 발표에 기반하며, 금융 의사결정은 전문가 상담이 필요합니다.\n'
            '```\n\n완성했습니다. **이전 검수 실패 3가지를 모두 반영했습니다:**\n\n'
            '1. 문제 → 해결\n2. 문제 → 해결\n'
        )
        article = self._make_article(disclaimer)
        result = _sanitize_article(article)
        assert '완성했습니다' not in result['disclaimer'], (
            f"AI 완성 메시지가 disclaimer에 남아있음: {result['disclaimer'][:200]}"
        )
        assert '본 글은' in result['disclaimer'], "실제 disclaimer 내용이 지워지면 안 됨"

    def test_backtick_fence_stripped_from_disclaimer(self):
        """``` 코드 펜스로 시작하는 AI 응답이 disclaimer에 포함되면 안 된다."""
        from bots.writer_bot import _sanitize_article
        disclaimer = '투자 정보는 참고용이며 개인 판단이 필요합니다.\n```\n\n다음과 같이 작성했습니다.'
        article = self._make_article(disclaimer)
        result = _sanitize_article(article)
        assert '```' not in result['disclaimer']
        assert '투자 정보는 참고용' in result['disclaimer']

    def test_clean_disclaimer_unchanged(self):
        """정상적인 disclaimer는 그대로 유지돼야 한다."""
        from bots.writer_bot import _sanitize_article
        disclaimer = '본 글은 공식 발표에 기반하며, 투자 결정은 개인의 판단과 전문가 상담이 필요합니다.'
        article = self._make_article(disclaimer)
        result = _sanitize_article(article)
        assert result['disclaimer'] == disclaimer


# ══════════════════════════════════════════════════════════════
# F1. _feedback_bucket 룰 유형 정규화 — 같은 룰이 반복되면 같은 버킷
# ══════════════════════════════════════════════════════════════

class TestFeedbackBucketNormalization:
    """같은 룰 유형의 피드백은 다른 문장에 붙어 나와도 같은 버킷이어야 한다."""

    def _bucket(self, feedback: str) -> str:
        from bots.writer_bot import _feedback_bucket
        return _feedback_bucket(feedback)

    def test_same_rule_different_sentences_same_bucket(self):
        """'너무 짧다' 룰이 다른 문장에 붙어도 같은 버킷을 반환해야 한다."""
        fb1 = '[룰 기반 검수 실패]\n- "인터넷도 필요 없다." → 너무 짧아 정보나 감각의 밀도가 부족하다.'
        fb2 = '[룰 기반 검수 실패]\n- "그럼 풀이가 쉽다." → 너무 짧아 정보나 감각의 밀도가 부족하다.'
        assert self._bucket(fb1) == self._bucket(fb2), (
            f"같은 룰인데 버킷 다름: {self._bucket(fb1)!r} vs {self._bucket(fb2)!r}"
        )

    def test_different_rules_different_buckets(self):
        """룰 유형이 다르면 버킷도 달라야 한다."""
        fb_short = '[룰 기반 검수 실패]\n- "짧다." → 너무 짧아 정보나 감각의 밀도가 부족하다.'
        fb_long  = '[룰 기반 검수 실패]\n- "매우 긴 문장이다." → 문장이 너무 길고 딱딱하다.'
        assert self._bucket(fb_short) != self._bucket(fb_long), "다른 룰인데 같은 버킷"

    def test_no_quoted_sentence_in_bucket(self):
        """버킷 키에 따옴표로 묶인 특정 문장이 포함되지 않아야 한다."""
        fb = '[룰 기반 검수 실패]\n- "이게 바로 Blank." → 너무 짧아 정보나 감각의 밀도가 부족하다.'
        bucket = self._bucket(fb)
        assert '"이게 바로 Blank."' not in bucket, f"버킷에 특정 문장 포함: {bucket!r}"

    def test_empty_feedback_returns_empty(self):
        """빈 피드백은 빈 버킷을 반환해야 한다."""
        assert self._bucket('') == ''

    def test_single_line_feedback_unchanged(self):
        """이슈 라인 없이 헤더만 있는 피드백도 처리돼야 한다."""
        fb = '[표현/가독성 검수 실패]'
        assert self._bucket(fb) == '[표현/가독성 검수 실패]'


# ══════════════════════════════════════════════════════════════
# F2. 짧은 문장 피드백 메시지 — 구체적 수정 방향 포함
# ══════════════════════════════════════════════════════════════

class TestShortSentenceFeedbackMessage:
    """짧은 문장 룰 피드백이 수정 방향을 구체적으로 제시해야 한다."""

    def _rule_check(self, sentence: str) -> str:
        """writer_bot의 _heuristic_review를 통해 짧은 문장 피드백 메시지를 추출."""
        from bots.writer_bot import _heuristic_review
        body = f'<h2>테스트</h2><p>{sentence}</p>'
        ok, msg = _heuristic_review(body, require_relatable=False)
        return msg

    def test_short_sentence_feedback_contains_fix_direction(self):
        """짧은 문장 피드백에 '연결' 또는 '추가' 등 수정 방향이 포함돼야 한다."""
        msg = self._rule_check('인터넷도 필요 없다.')
        assert '연결' in msg or '추가' in msg or '이어' in msg, (
            f"수정 방향 없는 피드백: {msg}"
        )

    def test_short_sentence_feedback_still_mentions_density(self):
        """밀도/짧다 표현은 여전히 포함돼야 한다."""
        msg = self._rule_check('그럼 풀이가 쉽다.')
        assert '짧' in msg or '밀도' in msg, f"밀도 언급 없음: {msg}"


# ──────────────────────────────────────────────────────────────
# 재발방지: 기술 고유명사 과밀 경고 임계값
# ──────────────────────────────────────────────────────────────

class TestProperNounDensityThreshold:
    """기술 글에서 3개 고유명사 포함 문장도 허용 (임계값 4 이상)"""

    def _heuristic(self, sentence):
        from bots.writer_bot import _heuristic_review
        # _heuristic_review는 단락 전체에 대해 동작 — 단일 문장을 <p>로 감쌈
        body = f'<p>{sentence}</p>'
        ok, msg = _heuristic_review(body, require_relatable=False)
        return [l for l in msg.split('\n') if '고유명사' in l and '몰아' in l]

    def test_three_tech_terms_no_warning(self):
        """Claude Code, Cursor, AI 3개 포함 — 기술 글에선 정상 (임계값 4)"""
        sentence = 'Claude Code나 Cursor 같은 AI 에디터의 덕분에 코드 작성 속도는 빨라졌다.'
        noun_issues = self._heuristic(sentence)
        assert not noun_issues, f"3개 기술 고유명사 오탐: {noun_issues}"

    def test_four_proper_nouns_still_warned(self):
        """4개 이상 고유명사 → 경고 유지"""
        sentence = 'Claude Code와 Cursor와 ChatGPT와 Gemini를 동시에 열어서 비교했다.'
        noun_issues = self._heuristic(sentence)
        assert noun_issues, f"4개 고유명사 경고 없음"


class TestListSentenceLengthExemption:
    """HTML 목록이 인라인으로 합쳐진 '→ 열거' 문장은 80자 길이 경고에서 제외해야 한다.

    근본 원인: <ul><li> 태그 제거 후 목록 항목들이 하나의 긴 문장으로 합쳐짐
    → '문장이 너무 길고 딱딱하다' 경고가 9회 반복 발생 → 토큰 예산 소진
    """

    def _length_issues(self, sentence: str) -> list[str]:
        from bots.writer_bot import _heuristic_review
        body = f'<p>{sentence}</p>'
        _, msg = _heuristic_review(body, require_relatable=False)
        return [l for l in msg.split('\n') if '너무 길고 딱딱' in l]

    def test_arrow_list_sentence_no_length_warning(self):
        """→ 포함 목록형 문장 (80자 초과) → 길이 경고 없음"""
        sentence = (
            '원유를 정제하면 다양한 제품이 나온다: 플라스틱 → 용기, 포장재, 일회용품 '
            '의약품 원료 → 감기약, 주사제, 항생제 합성섬유 → 옷, 침구류, 신발 화학비료 → 농산물 생산.'
        )
        assert len(sentence) > 80, f"테스트 전제: 80자 초과 문장 (현재 {len(sentence)}자)"
        issues = self._length_issues(sentence)
        assert issues == [], f"→ 목록 문장에 불필요한 길이 경고: {issues}"

    def test_colon_paren_list_sentence_no_length_warning(self):
        """콜론+괄호 열거 문장 (80자 초과) → 길이 경고 없음"""
        sentence = (
            '정부가 지시한 대체원유 확보 대상: 러시아 (카스피해 유전) 아프리카 (나이지리아, 앙골라) '
            '남미 (베네수엘라, 브라질) 동남아 (말레이시아, 인도네시아).'
        )
        assert len(sentence) > 80, f"테스트 전제: 80자 초과 문장 (현재 {len(sentence)}자)"
        issues = self._length_issues(sentence)
        assert issues == [], f"콜론+괄호 목록 문장에 불필요한 길이 경고: {issues}"

    def test_normal_long_sentence_still_warned(self):
        """→ / 콜론 없는 일반 긴 문장은 여전히 경고"""
        sentence = (
            '이 구체적인 숫자가 나온 이유는 국제유가가 불안정해지면 새 공급처를 찾아 '
            '계약을 체결하고 배에 실어 한국까지 도착하는 데 걸리는 기간이 대략 6주에서 8주이기 때문이다.'
        )
        assert len(sentence) > 80, "테스트 전제: 80자 초과 문장"
        issues = self._length_issues(sentence)
        assert issues != [], f"일반 긴 문장에 경고가 없음 (회귀)"


# ─── 룰 기반 검수 / 재작성 피드백 정합성 ────────────────────────────────────────────


class TestWritingPromptHeuristicAlignment:
    """writer_prompt 작성 규칙이 _heuristic_review 차단 기준과 일치하는지 확인"""

    def _prompt(self):
        """compose_writer_prompt의 두 번째 반환값(user prompt, 작성 지침 포함)을 반환"""
        from bots.prompt_layer.writer_prompt import compose_writer_prompt
        _, prompt = compose_writer_prompt(
            topic='test', corner='쉬운세상', description='test',
            source='', published_at=''
        )
        return prompt

    def test_system_prompt_contains_min_sentence_length(self):
        """writing 지침 prompt에 18자 최소 문장 길이 규칙이 포함돼야 한다"""
        prompt = self._prompt()
        assert '18자' in prompt, (
            "writer_prompt에 최소 18자 문장 길이 규칙이 없다. "
            "_heuristic_review는 18자 미만 문장을 차단하므로 writing 지침에도 동일 기준이 있어야 한다."
        )

    def test_system_prompt_proper_noun_limit_matches_heuristic(self):
        """writing 지침 prompt의 고유명사 규칙이 heuristic(4개 이상 차단)과 일치해야 한다"""
        prompt = self._prompt()
        assert '4개' in prompt, (
            "writer_prompt에 고유명사 4개 이상 차단 기준이 없다. "
            "_heuristic_review는 unique_caps >= 4일 때 차단하므로 writing 지침에 동일 임계값이 있어야 한다."
        )


class TestRevisionFeedbackHeuristicRules:
    """compose_revision_feedback이 heuristic 실패 시 특화 규칙을 추가하는지 확인"""

    def _build(self, feedback: str, attempt: int = 2) -> str:
        from bots.prompt_layer.writer_revision import compose_revision_feedback
        return compose_revision_feedback(feedback, attempt=attempt, min_revision_rounds=1)

    def test_short_sentence_feedback_adds_min_length_rule(self):
        """짧은 문장 heuristic 실패 피드백이 있으면 18자 최소 규칙을 추가해야 한다"""
        feedback = '[룰 기반 검수 실패]\n- "봉제도 마찬가지다." → 너무 짧아 밀도가 부족하다.'
        result = self._build(feedback)
        assert '18자' in result, (
            "짧은 문장 실패 피드백에 18자 최소 규칙이 포함되지 않았다. "
            "재작성 프롬프트에 구체 기준이 없으면 writer가 같은 짧은 문장을 반복 생성한다."
        )

    def test_proper_noun_feedback_adds_split_rule(self):
        """고유명사 heuristic 실패 피드백이 있으면 문장 분리 규칙을 추가해야 한다"""
        feedback = (
            '[룰 기반 검수 실패]\n'
            '- "The North Face, Vans, Timberland, Jansport" → '
            '고유명사나 서비스 이름을 한 문장에 너무 많이 몰아 넣었다.'
        )
        result = self._build(feedback)
        assert '두 문장' in result or '분리' in result, (
            "고유명사 과다 실패 피드백에 문장 분리 규칙이 포함되지 않았다."
        )

    def test_unrelated_feedback_no_short_sentence_rule(self):
        """짧은 문장 피드백이 없으면 18자 규칙이 추가되지 않아야 한다"""
        feedback = '[룰 기반 검수 실패]\n- "결국 이것이 핵심이다." → 전환 문장에 가깝고 구체 정보가 약하다.'
        result = self._build(feedback)
        # 18자가 없거나 있어도 짧은문장 규칙 없는 경우 통과
        # (이 테스트는 불필요한 노이즈 방지 목적)
        assert '18자' not in result, (
            "짧은 문장 피드백이 없는데 18자 규칙이 추가됐다. 관련 없는 규칙을 추가하면 프롬프트가 길어진다."
        )


# ─── 제목 정규화 버그 / 리스트 오탐 ────────────────────────────────────────────


class TestNormalizeTitleNumberComma:
    """_normalize_title_text가 숫자 속 쉼표를 잘못 잘라내는 버그 방지"""

    def _normalize(self, text: str) -> str:
        from bots.writer_bot import _normalize_title_text
        return _normalize_title_text(text)

    def test_number_comma_not_stripped(self):
        """'1,425원' 같은 숫자 속 쉼표에서 뒷부분을 잘라내면 안 된다"""
        title = '달러-원 1,425원이 연말 목표라면 지금 환전 전략을 바꿔야 한다'
        result = self._normalize(title)
        assert '425' in result, (
            f"숫자 속 쉼표에서 제목이 잘렸다: {result!r}\n"
            "r',\\s*.+$' 패턴이 '1,425원' 중간을 절삭하는 버그. "
            "한글 부제 제거 패턴은 콤마 뒤 공백+한글에만 적용해야 한다."
        )

    def test_korean_subtitle_after_comma_stripped(self):
        """콤마 뒤 한글 부제목은 여전히 제거되어야 한다"""
        title = '달러-원 전망, 지금 환전해야 할까'
        result = self._normalize(title)
        assert result == '달러-원 전망', (
            f"한글 부제 제거가 작동하지 않는다: {result!r}"
        )

    def test_number_with_comma_and_korean_subtitle(self):
        """'1,425원, 지금 바꿔야 할까' — 한글 부제만 제거, 숫자 보존"""
        title = '달러-원 1,425원, 지금 환전해야 하나'
        result = self._normalize(title)
        assert '1,425' in result, (
            f"숫자 '1,425'가 사라졌다: {result!r}"
        )
        assert '지금 환전해야 하나' not in result, (
            f"한글 부제가 제거되지 않았다: {result!r}"
        )


class TestHeuristicListSentenceFalsePositive:
    """<ul><li> 목록이 초장문 단일 문장으로 오탐되는 버그 방지"""

    def _heuristic(self, body: str):
        from bots.writer_bot import _heuristic_review
        return _heuristic_review(body, require_relatable=False)

    def test_li_items_not_flagged_as_long_sentence(self):
        """<ul><li> 목록 항목들이 합쳐져 초장문으로 오탐돼서는 안 된다"""
        body = (
            '<p>이 기능을 활용하면 다음이 가능하다.</p>'
            '<ul>'
            '<li>코드 리뷰: 에디터 창을 열어두고 구체적인 함수나 로직에 대해 물어보기</li>'
            '<li>문서 편집: 작성 중인 글의 문법·논리·톤 검토를 한 번의 클릭으로 받기</li>'
            '<li>데이터 분석: 스프레드시트나 대시보드를 보면서 추세 해석과 인사이트 얻기</li>'
            '<li>프레젠테이션 준비: 슬라이드 내용 검증과 발표 포인트 구성 조언 받기</li>'
            '</ul>'
            '<p>이 조합으로 여러 창을 오가는 시간이 줄어든다.</p>'
        )
        ok, msg = self._heuristic(body)
        long_sentence_flags = [
            line for line in msg.splitlines()
            if '문장이 너무 길고 딱딱하다' in line and '코드 리뷰' in line
        ]
        assert long_sentence_flags == [], (
            f"<li> 항목이 합쳐진 초장문을 오탐하고 있다:\n"
            + '\n'.join(long_sentence_flags)
        )

    def test_normal_long_sentence_still_flagged(self):
        """일반 긴 문장은 여전히 flagged 돼야 한다 (회귀 방지)"""
        body = (
            '<p>이 구체적인 숫자가 나온 이유는 국제유가가 불안정해지면 새 공급처를 찾아 '
            '계약을 체결하고 배에 실어 한국까지 도착하는 데 걸리는 기간이 대략 6주에서 8주이기 때문이다.</p>'
        )
        ok, msg = self._heuristic(body)
        assert '문장이 너무 길고 딱딱하다' in msg, "일반 초장문 문장에 경고가 없음 (회귀)"
