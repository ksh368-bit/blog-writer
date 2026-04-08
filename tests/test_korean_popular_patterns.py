"""
tests/test_korean_popular_patterns.py

한국 인기 블로그(네이버·브런치·티스토리) 분석 기반 글 품질 개선 테스트 (TDD)

개선 항목:
  Q10. 추측 표현 남용 금지 — "것 같다/듯하다/것으로 보인다" 3개+ 반복
  Q11. 과도하게 긴 단락 금지 — 200자 초과 단락 2개 이상이면 모바일 가독성 파괴
  Q12. 동일 종결어미 과반복 금지 — "할 수 있다" 4개+ 반복 시 단조로운 리듬 경고

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
    """검수 통과 가능한 기본 아티클."""
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
            '<h2>마무리</h2>'
            '<p>코딩 도구를 바꾸면 작업 흐름이 달라진다. 한 번 써보면 안 쓰기 어려워진다.</p>'
            '<strong>Claude Code</strong>'
        ),
        'topic': 'Claude Code 설치 및 활용',
        'corner': '쉬운세상',
    }
    base.update(overrides)
    return base


# ─── Q11/Q12 테스트에서 본문이 600자 이상이 되도록 공통 패딩 ──────────────
_BODY_SUFFIX = (
    '<h2>마무리</h2>'
    '<p>코딩 도구를 바꾸면 작업 흐름이 달라진다. 한 번 써보면 안 쓰기 어려워진다.'
    ' 직접 해보면 확인된다. 이 차이를 아는 것만으로도 작업 속도가 달라진다.'
    ' 지금 바로 시도해볼 가치가 있다. 결과는 생각보다 빠르게 나온다.</p>'
    '<strong>Claude Code</strong>'
    '<strong>AI 코딩</strong>'
    '<strong>터미널</strong>'
)


# ══════════════════════════════════════════════════════════════
# Q10. 추측 표현 남용 금지
# ══════════════════════════════════════════════════════════════

class TestHedgingOveruse:
    """"것 같다/듯하다/것으로 보인다" 등 추측 표현이 3개 이상 반복되면 경고해야 한다."""

    _Q10_KEY = '추측 표현'

    @pytest.mark.parametrize('body', [
        # 케이스 1: "것 같다" 3회
        (
            '<h2>소개</h2>'
            '<p>터미널에 명령어를 입력했더니 AI가 응답했다. 3초 만에 결과가 나왔다.</p>'
            '<h2>분석</h2>'
            '<p>이 기능은 속도가 빠른 것 같다. 기존 도구보다 효율적인 것 같다. '
            '많은 개발자에게 도움이 되는 것 같다.</p>'
            '<h2>마무리</h2>'
            '<p>한 번 써보면 안 쓰기 어려워진다. 직접 해보면 차이가 확인된다.</p>'
            '<strong>키워드</strong>'
        ),
        # 케이스 2: 혼합 추측 표현 3회
        (
            '<h2>소개</h2>'
            '<p>유가가 4월에 10% 올랐다. 항공권 가격도 달라졌다.</p>'
            '<h2>분석</h2>'
            '<p>배달비도 오를 것으로 보인다. 수수료 구조가 바뀐 듯하다. '
            '소비자 부담이 커질 것 같다.</p>'
            '<h2>마무리</h2>'
            '<p>4월 안에 예약을 마치면 인상 전 가격을 잡을 수 있다.</p>'
            '<strong>유가</strong>'
        ),
        # 케이스 3: "인 듯하다" + "것 같다" + "것으로 보인다"
        (
            '<h2>소개</h2>'
            '<p>같은 배달 주문인데 앱에 따라 가게 수익이 2천 원 차이 났다.</p>'
            '<h2>이유</h2>'
            '<p>수수료 구조가 다른 듯하다. 공공앱이 더 저렴한 것 같다. '
            '민간앱은 마진이 높은 것으로 보인다.</p>'
            '<h2>마무리</h2>'
            '<p>지금 이 차이를 아는 것만으로도 지출이 달라진다.</p>'
            '<strong>배달앱</strong>'
        ),
    ])
    def test_hedging_overuse_flagged(self, body):
        """추측 표현이 3개 이상이면 검수 실패해야 한다."""
        article = _base_article(body=body)
        ok, msg = _review(article)
        assert not ok, "추측 표현 남용이 통과됨"
        assert self._Q10_KEY in msg, f"'{self._Q10_KEY}' 언급 없음: {msg}"

    @pytest.mark.parametrize('body', [
        # 좋은 케이스: 추측 표현 2회 미만 (팩트 기반)
        (
            '<h2>소개</h2>'
            '<p>터미널에 명령어를 입력했더니 3초 만에 AI가 응답했다.</p>'
            '<h2>결과</h2>'
            '<p>반복 작업이 30% 줄었다. 코드 리뷰 시간이 절반으로 단축됐다.</p>'
            '<h2>마무리</h2>'
            '<p>한 번 써보면 안 쓰기 어려워진다. 직접 해보면 차이가 확인된다.</p>'
            '<strong>Claude Code</strong>'
        ),
        # 좋은 케이스: 추측 표현 1개 (허용)
        (
            '<h2>소개</h2>'
            '<p>4월에 유가가 배럴당 5달러 올랐다.</p>'
            '<h2>영향</h2>'
            '<p>항공료가 가장 빠르게 반영됐다. 2주 뒤 배달비도 오를 것으로 보인다.</p>'
            '<h2>마무리</h2>'
            '<p>4월 안에 예약하면 인상 전 가격을 잡을 수 있다.</p>'
            '<strong>유가</strong>'
        ),
    ])
    def test_factual_writing_passes(self, body):
        """팩트 기반 글은 Q10 지적이 없어야 한다."""
        article = _base_article(body=body)
        ok, msg = _review(article)
        q10_issues = [l for l in msg.split('\n') if self._Q10_KEY in l]
        assert not q10_issues, f"팩트 기반 글에 오탐: {q10_issues}"


# ══════════════════════════════════════════════════════════════
# Q11. 과도하게 긴 단락 금지 (모바일 가독성)
# ══════════════════════════════════════════════════════════════

class TestLongParagraphs:
    """200자 초과 단락이 2개 이상이면 모바일 가독성 경고를 해야 한다."""

    _Q11_KEY = '긴 단락'

    # 200자가 넘는 단락용 텍스트 (현재 ~230자)
    _LONG_P = (
        '이 기능은 터미널에서 직접 실행할 수 있으며 설정 파일 없이도 동작한다.'
        '코드 리뷰를 자동화하고 PR 단계에서 바로 피드백을 받을 수 있어 작업 흐름이 크게 달라진다.'
        '특히 낯선 코드베이스를 처음 볼 때 전체 구조를 빠르게 파악하는 데 효과적이다.'
        '기존 도구와 달리 별도 플러그인 없이도 어느 환경에서든 동일하게 실행된다.'
        '복잡한 설정 과정 없이 바로 쓸 수 있다는 것이 가장 큰 장점이다.'
    )  # ~230자

    def test_two_long_paragraphs_flagged(self):
        """200자 초과 단락이 2개 이상이면 검수 실패해야 한다."""
        body = (
            '<h2>소개</h2>'
            f'<p>터미널에 명령어를 입력했더니 AI가 응답했다. 3초 만에 결과가 나왔다.</p>'
            '<h2>기능 설명</h2>'
            f'<p>{self._LONG_P}</p>'
            '<h2>활용</h2>'
            f'<p>{self._LONG_P}</p>'
            + _BODY_SUFFIX
        )
        article = _base_article(body=body)
        ok, msg = _review(article)
        assert not ok, "긴 단락 2개가 통과됨"
        assert self._Q11_KEY in msg, f"'{self._Q11_KEY}' 언급 없음: {msg}"

    def test_one_long_paragraph_passes(self):
        """200자 초과 단락이 1개면 Q11 지적이 없어야 한다."""
        body = (
            '<h2>소개</h2>'
            '<p>터미널에 명령어를 입력했더니 AI가 응답했다. 3초 만에 결과가 나왔다.</p>'
            '<h2>기능 설명</h2>'
            f'<p>{self._LONG_P}</p>'
            '<h2>활용</h2>'
            '<p>PR 리뷰 직전에 꺼내면 된다. 낯선 코드를 볼 때 효과적이다.</p>'
            + _BODY_SUFFIX
        )
        article = _base_article(body=body)
        ok, msg = _review(article)
        q11_issues = [l for l in msg.split('\n') if self._Q11_KEY in l]
        assert not q11_issues, f"단락 1개에 오탐: {q11_issues}"

    def test_short_paragraphs_pass(self):
        """모든 단락이 짧으면 Q11 지적이 없어야 한다."""
        article = _base_article()  # 기본 아티클은 단락 짧음
        ok, msg = _review(article)
        q11_issues = [l for l in msg.split('\n') if self._Q11_KEY in l]
        assert not q11_issues, f"짧은 단락에 오탐: {q11_issues}"

    def test_three_long_paragraphs_flagged(self):
        """200자 초과 단락이 3개면 반드시 검수 실패해야 한다."""
        body = (
            '<h2>소개</h2>'
            f'<p>{self._LONG_P}</p>'
            '<h2>기능 설명</h2>'
            f'<p>{self._LONG_P}</p>'
            '<h2>활용</h2>'
            f'<p>{self._LONG_P}</p>'
            + _BODY_SUFFIX
        )
        article = _base_article(body=body)
        ok, msg = _review(article)
        assert not ok
        assert self._Q11_KEY in msg


# ══════════════════════════════════════════════════════════════
# Q12. 동일 종결어미 과반복 금지
# ══════════════════════════════════════════════════════════════

class TestEndingRepetition:
    """"할 수 있다"가 4회 이상 반복되면 단조로운 리듬 경고를 해야 한다."""

    _Q12_KEY = '종결 표현'

    # 기본 패딩 (600자 달성용)
    _BODY_SUFFIX = _BODY_SUFFIX

    @pytest.mark.parametrize('repeated_ending,count', [
        ('할 수 있다', 4),
        ('할 수 있다', 5),
        ('수 있습니다', 4),
    ])
    def test_ending_repetition_flagged(self, repeated_ending, count):
        """같은 종결 표현이 4회 이상이면 검수 실패해야 한다."""
        sentences = [f'이 기능을 사용하면 작업을 자동화{repeated_ending}.' for _ in range(count)]
        repeated_block = ' '.join(sentences)
        body = (
            '<h2>소개</h2>'
            '<p>터미널에 명령어를 입력했더니 3초 만에 AI가 응답했다.</p>'
            '<h2>기능</h2>'
            f'<p>{repeated_block}</p>'
            + self._BODY_SUFFIX
        )
        article = _base_article(body=body)
        ok, msg = _review(article)
        assert not ok, f"'{repeated_ending}' {count}회 반복이 통과됨"
        assert self._Q12_KEY in msg, f"'{self._Q12_KEY}' 언급 없음: {msg}"

    @pytest.mark.parametrize('ending', [
        '할 수 있다',
        '수 있습니다',
    ])
    def test_ending_three_times_passes(self, ending):
        """같은 종결 표현이 3회 이하면 Q12 지적이 없어야 한다."""
        sentences = [f'이 기능을 쓰면 작업을 자동화{ending}.' for _ in range(3)]
        repeated_block = ' '.join(sentences)
        body = (
            '<h2>소개</h2>'
            '<p>터미널에 명령어를 입력했더니 3초 만에 AI가 응답했다.</p>'
            '<h2>기능</h2>'
            f'<p>{repeated_block}</p>'
            + self._BODY_SUFFIX
        )
        article = _base_article(body=body)
        ok, msg = _review(article)
        q12_issues = [l for l in msg.split('\n') if self._Q12_KEY in l]
        assert not q12_issues, f"3회 이하에 오탐: {q12_issues}"

    def test_varied_endings_pass(self):
        """다양한 종결어미를 쓰면 Q12 지적이 없어야 한다."""
        body = (
            '<h2>소개</h2>'
            '<p>터미널에 명령어를 입력했더니 3초 만에 AI가 응답했다.</p>'
            '<h2>기능</h2>'
            '<p>이 기능을 쓰면 작업이 자동화된다. 속도가 30% 빨라진다. '
            '코드 리뷰를 자동화할 수 있다. 낯선 코드도 빠르게 파악된다. '
            '결과가 즉시 나온다. 설정 없이 바로 시작된다.</p>'
            + self._BODY_SUFFIX
        )
        article = _base_article(body=body)
        ok, msg = _review(article)
        q12_issues = [l for l in msg.split('\n') if self._Q12_KEY in l]
        assert not q12_issues, f"다양한 어미에 오탐: {q12_issues}"
