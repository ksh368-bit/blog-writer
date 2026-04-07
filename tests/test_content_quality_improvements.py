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
            '<h2>마무리</h2>'
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
            '<h2>마무리</h2>'
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
            '<h2>마무리</h2><p>결론이다. 이렇게 하면 달라진다.</p>'
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
            '<h2>마무리</h2><p>결론이다.</p>'
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
            '<h2>마무리</h2><p>이렇게 하면 달라진다. 직접 해보면 확인된다.</p>'
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
            '<h2>마무리</h2><p>이렇게 하면 달라진다. 직접 해보면 확인된다.</p>'
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
            f'<h2>마무리</h2><p>{bad_closing}</p>'
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
            f'<h2>마무리</h2><p>{good_closing}</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        closing_issues = [l for l in msg.split('\n') if '마무리' in l or '마지막' in l or '결말' in l]
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
            '<h2>마무리</h2>'
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
            '<h2>마무리</h2>'
            '<p>한 번 써보면 안 쓰기 어려워진다.</p>'
            '<strong>키워드</strong>'
        ))
        ok, msg = _review(article)
        section_issues = [l for l in msg.split('\n') if ('섹션' in l or 'h2' in l.lower()) and '제목' in l]
        assert not section_issues, f"좋은 h2 제목에 오탐: {section_issues}"
