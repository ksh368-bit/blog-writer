"""
tests/test_writing_quality_advanced.py

한국 인기 블로그 분석 기반 고급 글쓰기 품질 검사 (TDD)

분석 근거:
  - 최고 품질 글("반도체 수출이 폭증해도"): 숫자 12개, 연속 긴 문장 0개
  - 문제 글 1 ("Gemma 4 LM Studio"): 숫자 1개 — 추상적 서술만 가득
  - 문제 글 2 ("AI 에이전트 병렬"): 65자 초과 문장 7개 연속 — 모바일에서 읽기 불가

개선 항목:
  Q5. 본문 최소 텍스트 길이 (공백 제거 기준 600자 이상)
  Q6. 구체적 수치 포함 필수 (퍼센트·금액·날짜·횟수 등 최소 2개)
  Q7. 연속 긴 문장 리듬 검사 (65자 초과 문장이 3개 이상 연속되면 금지)

각 테스트는 구현 전 RED, 구현 후 GREEN이 되어야 한다.
"""

import re
import pytest


# ─── 공통 헬퍼 ────────────────────────────────────────────────

def _review(article: dict):
    from bots.prompt_layer.writer_review import presentation_review
    split_sentences = lambda t: re.split(r'(?<=[.!?다])\s+', t)
    return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)


def _make_article(body: str, corner: str = '쉬운세상') -> dict:
    """검수 통과용 기본 메타. body만 바꿔 가며 테스트한다."""
    return {
        'title': '쿠팡이츠 수수료를 낮추면 배달비가 3천 원 줄어든다',
        'meta': '쿠팡이츠 수수료를 낮추면 배달비가 3천 원 줄어든다.',
        'topic': '쿠팡이츠 배달비 수수료',
        'corner': corner,
        'body': body,
    }


# ─── 공유 fixture: 모든 검수를 통과하는 충분한 길이의 기준 본문 ──────────

_GOOD_BODY = (
    '<h2>항공료가 먼저 오른다</h2>'
    '<p>중동 전쟁이 이어지면서 유가가 올라가자 항공사부터 움직였다. '
    '비행기는 한 번 띄울 때마다 수십만 원대의 연료유를 태우는데, '
    '유가가 1달러 오르면 편도 1시간 비행마다 연료비가 수천 원씩 불어난다. '
    '4월은 봄 휴가 시즌이라 항공 수요도 몰린다.</p>'
    '<p>지난주와 이번 주 항공편 표값 차이가 3만 원 이상 벌어지는 이유가 이것이다. '
    '수요가 몰리는 시기에 유가 인상이 겹치면 항공사는 두 가지 이유를 동시에 반영한다. '
    '올봄 항공료는 전년 동기 대비 15% 이상 높다는 통계도 나왔다.</p>'
    '<p>항공사들은 연료 할증료를 별도로 부과하는 방식도 쓴다. '
    '표면 가격은 그대로지만 부대비용이 늘어나는 구조다. '
    '소비자 입장에서는 총 결제액이 오른다는 점에서 사실상 같다.</p>'
    '<h2>배송료는 2주 뒤에 따라온다</h2>'
    '<p>쿠팡이츠는 지난달 기본 배달비를 500원 올렸다. '
    '배달앱은 식당·고객 양쪽과 협상해야 해서 반영이 늦다. '
    '유가 상승이 배달비에 반영되는 데는 보통 2주가 걸린다.</p>'
    '<p>운송사가 계약 단가를 바꾸는 주기가 2주 간격이기 때문이다. '
    '이미 3월 말부터 올리기 시작한 배달비는 4월 중순쯤 정점을 찍을 가능성이 높다. '
    '공공배달앱 수수료는 민간 앱보다 낮아서 여파가 덜한 편이다.</p>'
    '<p>배달의민족도 4월부터 수수료 체계를 일부 조정했다. '
    '플랫폼 간 경쟁이 있어 바로 올리진 못하지만 방향은 인상 쪽이다.</p>'
    '<h2>외식비는 가장 늦게 오른다</h2>'
    '<p>2월 소비자물가 중 외식 항목이 3.4% 올랐다. '
    '재료비·인건비에 에너지 비용까지 겹치면 식당은 가격을 올린다. '
    '한 번 올린 외식 가격은 잘 내려오지 않는다.</p>'
    '<p>손님이 줄어도 고정비가 먼저 나가기 때문이다. '
    '지금 점심 세트 가격이 아직 안 올랐다면, 5월 안에는 바뀔 가능성이 있다. '
    '저녁 정식보다 점심 세트를 먼저 고르는 것이 덜 오른 가격을 쓰는 방법이다.</p>'
    '<p>특히 자영업 식당보다 프랜차이즈 매장이 가격 조정이 더 늦다. '
    '본사 승인이 필요하기 때문이다. 당분간은 프랜차이즈 점심이 선택지다.</p>'
    '<h2>지금 고를 수 있는 것</h2>'
    '<p>항공권은 지금 끊는 게 낫다. '
    '배달은 공공배달앱을 쓰면 수수료가 일반 앱보다 낮아서 가격 인상 여파가 덜하다. '
    '외식은 점심 세트가 저녁보다 오르는 속도가 느리다.</p>'
    '<p>세 가지 모두 유가 인상의 여파지만, 반영 속도가 다르다. '
    '가장 빠르게 움직이는 항공료부터 먼저 체크하면 된다.</p>'
    '<p>유가가 안정되면 역순으로 내려간다. 항공료가 먼저 내리고, 배달비가 따라오고, '
    '외식비는 가장 마지막에 조정된다. 지금은 오르는 순서를 기억해두면 된다.</p>'
    '<strong>유가</strong><strong>항공료</strong>'
)


# ══════════════════════════════════════════════════════════════
# Q5. 본문 최소 텍스트 길이 검사
# ══════════════════════════════════════════════════════════════

class TestBodyMinimumLength:
    """본문 텍스트(HTML 태그 제거·공백 포함 제거)가 900자 미만이면 검수 실패해야 한다."""

    def test_short_body_fails(self):
        """명백히 짧은 본문은 검수 실패해야 한다."""
        short_body = (
            '<h2>첫 섹션</h2>'
            '<p>배달비가 오른다. 유가가 올라서다.</p>'
            '<h2>둘째 섹션</h2>'
            '<p>수수료가 높아지면 가격이 오른다.</p>'
            '<h2>셋째 섹션</h2>'
            '<p>공공배달앱을 쓰면 덜 오른다.</p>'
            '<strong>배달비</strong>'
        )
        article = _make_article(short_body)
        ok, msg = _review(article)
        assert not ok, "너무 짧은 본문인데 검수 통과됨"
        assert '900자' in msg, f"길이 문제 언급 없음: {msg}"

    def test_very_short_body_fails(self):
        """100자 이하 본문도 실패해야 한다."""
        article = _make_article(
            '<h2>a</h2><p>배달비가 오른다.</p>'
            '<h2>b</h2><p>유가 때문이다.</p>'
            '<h2>c</h2><p>지금 써라.</p>'
            '<strong>유가</strong>'
        )
        ok, msg = _review(article)
        assert not ok
        assert '900자' in msg

    def test_good_body_passes_length_check(self):
        """충분히 긴 본문은 길이 검사를 통과해야 한다."""
        article = _make_article(_GOOD_BODY)
        ok, msg = _review(article)
        # 길이 관련 실패가 없어야 한다
        assert '900자' not in msg, f"충분한 길이인데 길이 오류: {msg}"

    def test_border_body_below_threshold_fails(self):
        """약 400자 내외 본문은 실패해야 한다."""
        border_body = (
            '<h2>배달비 인상 원인</h2>'
            '<p>유가가 오르면서 배달비도 따라 오른다. 쿠팡이츠는 지난달 기본 배달비를 '
            '500원 올렸고, 배달의민족도 비슷한 시기에 인상했다. '
            '이 두 플랫폼이 시장의 80%를 차지하니, 배달비 인상은 사실상 전체 시장에 영향을 준다.</p>'
            '<h2>언제 안정될까</h2>'
            '<p>중동 정세가 안정되고 유가가 내려야 배달비도 따라 내린다. '
            '전문가들은 빨라야 3분기는 돼야 가격이 조정될 것으로 본다.</p>'
            '<h2>지금 할 수 있는 것</h2>'
            '<p>공공배달앱을 쓰면 수수료가 낮아서 배달비 인상 여파가 덜하다.</p>'
            '<strong>배달비</strong>'
        )
        article = _make_article(border_body)
        ok, msg = _review(article)
        assert not ok
        assert '900자' in msg

    def test_body_between_old_and_new_threshold_fails(self):
        """750자 본문 (600~899자 중간) — 새 900자 기준 실패해야 한다."""
        # 약 750자 (공백 제거) 본문
        mid_body = (
            '<h2>배달비 인상 원인</h2>'
            '<p>유가가 오르면서 배달비도 따라 오른다. 쿠팡이츠는 지난달 기본 배달비를 500원 올렸고, '
            '배달의민족도 비슷한 시기에 인상했다. 이 두 플랫폼이 시장의 80%를 차지하니, '
            '배달비 인상은 사실상 전체 시장에 영향을 준다. 소비자는 같은 음식을 시켜도 더 많은 돈을 내야 한다.</p>'
            '<h2>언제 안정될까</h2>'
            '<p>중동 정세가 안정되고 유가가 내려야 배달비도 따라 내린다. '
            '전문가들은 빨라야 3분기는 돼야 가격이 조정될 것으로 본다. '
            '그 전까지는 배달 플랫폼이 요금을 낮출 유인이 없다는 분석이 많다. '
            '경쟁사도 같은 상황이기 때문에 가격 경쟁이 발생하지 않는다.</p>'
            '<h2>지금 할 수 있는 것</h2>'
            '<p>공공배달앱을 쓰면 수수료가 낮아서 배달비 인상 여파가 덜하다. '
            '지자체가 운영하는 앱은 민간 플랫폼 대비 배달비가 평균 1,000원 저렴하다. '
            '직접 픽업하면 배달비를 아예 낼 필요가 없다.</p>'
            '<strong>배달비</strong>'
        )
        article = _make_article(mid_body)
        ok, msg = _review(article)
        assert not ok
        assert '짧다' in msg or '900자' in msg


# ══════════════════════════════════════════════════════════════
# QS1. 스캔가능성 — 목록/표 1개 이상 필수
# ══════════════════════════════════════════════════════════════

class TestScannability:
    """본문에 <ul>/<ol>/<table> 없으면 QS1 경고가 발생해야 한다."""

    def test_no_list_triggers_warning(self):
        """순수 <p>/<h2>만 있는 본문은 QS1 경고가 나와야 한다."""
        article = _make_article(_GOOD_BODY)
        ok, msg = _review(article)
        assert '목록' in msg or '<ul>' in msg or 'ul' in msg, f"QS1 경고 없음: {msg}"

    def test_ul_passes_scannability(self):
        """<ul> 포함 본문은 QS1 통과해야 한다."""
        body_with_ul = _GOOD_BODY.replace(
            '<strong>유가</strong>',
            '<ul><li>항공료 먼저 오름</li><li>배달비 2주 후</li></ul><strong>유가</strong>'
        )
        article = _make_article(body_with_ul)
        _, msg = _review(article)
        assert '목록' not in msg and '<ul>' not in msg, f"QS1 오탐: {msg}"

    def test_ol_passes_scannability(self):
        """<ol> 포함 본문은 QS1 통과해야 한다."""
        body_with_ol = _GOOD_BODY.replace(
            '<strong>유가</strong>',
            '<ol><li>1단계</li><li>2단계</li></ol><strong>유가</strong>'
        )
        article = _make_article(body_with_ol)
        _, msg = _review(article)
        assert '목록' not in msg and '<ol>' not in msg, f"QS1 오탐: {msg}"

    def test_table_passes_scannability(self):
        """<table> 포함 본문은 QS1 통과해야 한다."""
        body_with_table = _GOOD_BODY.replace(
            '<strong>유가</strong>',
            '<table><tr><td>항목</td><td>값</td></tr></table><strong>유가</strong>'
        )
        article = _make_article(body_with_table)
        _, msg = _review(article)
        assert '목록' not in msg, f"QS1 오탐: {msg}"


# ══════════════════════════════════════════════════════════════
# Q6. 구체적 수치 포함 필수
# ══════════════════════════════════════════════════════════════

class TestConcreteNumbers:
    """본문에 구체적 수치(퍼센트·금액·날짜·배수·횟수 등)가 2개 미만이면 검수 실패해야 한다."""

    def test_no_numbers_fails(self):
        """수치가 하나도 없는 본문은 검수 실패해야 한다."""
        no_num_body = (
            '<h2>유가가 오르면 항공료가 뛴다</h2>'
            '<p>중동 전쟁이 이어지면서 유가가 올라가자 항공사부터 움직였다. '
            '비행기는 한 번 띄울 때마다 엄청난 연료유를 태우는데, '
            '유가가 오르면 연료비도 함께 불어난다. '
            '항공사는 이 비용을 항공료에 즉시 반영한다.</p>'
            '<p>가격이 오른다는 것은 예약 시점이 중요해진다는 뜻이다. '
            '일찍 예약할수록 인상 전 가격을 잡을 수 있다. '
            '요즘 항공료가 오른 이유는 유가 탓이 가장 크다.</p>'
            '<h2>배송료도 따라 오른다</h2>'
            '<p>배달앱도 유가 인상 여파를 피할 수 없다. '
            '운송사가 계약 단가를 올리면 배달비도 자연히 오른다. '
            '공공배달앱을 쓰면 조금 덜 오른다.</p>'
            '<h2>외식비는 가장 나중에 오른다</h2>'
            '<p>식당은 여러 비용이 한꺼번에 오를 때 가격을 조정한다. '
            '재료비·인건비·에너지 비용이 모두 오르면 외식비도 오른다. '
            '한 번 오른 외식 가격은 잘 내리지 않는다.</p>'
            '<h2>지금 고를 수 있는 것</h2>'
            '<p>항공권은 빨리 끊는 게 낫다. 배달은 공공앱을 쓰면 덜하다. '
            '외식은 점심이 저녁보다 덜 오른다.</p>'
            '<strong>유가</strong><strong>항공료</strong>'
        )
        article = _make_article(no_num_body)
        ok, msg = _review(article)
        assert not ok, "수치 없는 본문인데 검수 통과됨"
        assert '수치' in msg or '숫자' in msg, f"수치 부재 언급 없음: {msg}"

    def test_only_one_number_fails(self):
        """수치가 1개뿐인 본문도 검수 실패해야 한다."""
        one_num_body = (
            '<h2>유가가 오르면 항공료가 뛴다</h2>'
            '<p>중동 전쟁이 이어지면서 유가가 올라가자 항공사부터 움직였다. '
            '비행기는 유가가 1달러 오르면 연료비가 크게 불어난다. '
            '항공사는 이 비용을 항공료에 즉시 반영한다.</p>'
            '<p>가격이 오른다는 것은 예약 시점이 중요해진다는 뜻이다. '
            '일찍 예약할수록 인상 전 가격을 잡을 수 있다. '
            '요즘 항공료가 오른 이유는 유가 탓이 가장 크다.</p>'
            '<h2>배송료도 따라 오른다</h2>'
            '<p>배달앱도 유가 인상 여파를 피할 수 없다. '
            '운송사가 계약 단가를 올리면 배달비도 자연히 오른다. '
            '공공배달앱을 쓰면 조금 덜 오른다.</p>'
            '<h2>외식비는 가장 나중에 오른다</h2>'
            '<p>식당은 재료비·인건비·에너지 비용이 모두 오르면 가격을 조정한다. '
            '한 번 오른 외식 가격은 잘 내리지 않는다. '
            '점심 세트가 저녁보다 오르는 속도가 느리다.</p>'
            '<h2>지금 고를 수 있는 것</h2>'
            '<p>항공권은 빨리 끊는 게 낫다. 배달은 공공앱을 쓰면 덜하다. '
            '외식은 점심이 저녁보다 덜 오른다.</p>'
            '<strong>유가</strong><strong>항공료</strong>'
        )
        article = _make_article(one_num_body)
        ok, msg = _review(article)
        assert not ok, "수치 1개뿐인 본문인데 검수 통과됨"
        assert '수치' in msg or '숫자' in msg

    def test_two_or_more_numbers_passes(self):
        """수치가 2개 이상인 본문은 수치 검사를 통과해야 한다."""
        article = _make_article(_GOOD_BODY)
        ok, msg = _review(article)
        assert '수치' not in msg and '숫자' not in msg, f"충분한 수치인데 수치 오류: {msg}"

    def test_percentages_and_won_count_as_numbers(self):
        """퍼센트(%)와 금액(원)이 각각 1개씩 있으면 통과해야 한다."""
        two_num_body = (
            '<h2>항공료 인상 폭</h2>'
            '<p>4월 항공료는 작년 같은 달 대비 15% 올랐다. '
            '봄 휴가 수요가 몰리면서 항공사가 두 가지 이유를 동시에 반영했다. '
            '예약 시점이 일주일 늦어질수록 표값 차이가 벌어진다.</p>'
            '<p>지난주와 이번 주 항공편 표값 차이가 3만 원 이상 벌어지는 이유가 이것이다. '
            '수요가 몰리는 시기에 유가 인상이 겹치면 두 가지 이유가 동시에 반영된다. '
            '지금 끊는 것이 다음 주보다 저렴할 가능성이 높다.</p>'
            '<h2>배달비 변화 시점</h2>'
            '<p>쿠팡이츠는 지난달 기본 배달비를 500원 올렸다. '
            '운송사와의 계약 단가가 바뀌는 주기가 있어서 바로 반영되지는 않는다. '
            '보통 유가 인상에서 배달비 인상까지 2주가 걸린다.</p>'
            '<p>이미 3월 말부터 올리기 시작한 배달비는 4월 중순에 정점을 찍을 것으로 보인다. '
            '공공배달앱을 쓰면 수수료가 낮아 가격 인상 여파가 일반 앱보다 덜하다. '
            '지금 당장 앱을 바꾸는 것만으로도 배달비를 아낄 수 있다.</p>'
            '<h2>외식비 흐름</h2>'
            '<p>외식 항목이 작년 대비 3.4% 올랐다. '
            '재료비·인건비에 에너지 비용까지 겹치면 식당은 가격을 올린다. '
            '한 번 올린 외식 가격은 잘 내려오지 않는다.</p>'
            '<p>손님이 줄어도 고정비가 먼저 나가기 때문이다. '
            '점심 세트가 저녁보다 오르는 속도가 느리므로 점심을 활용하는 것이 낫다. '
            '5월 안에는 점심 가격도 조정될 가능성이 있다.</p>'
            '<h2>지금 고를 수 있는 것</h2>'
            '<p>항공권은 지금 끊는 게 낫다. '
            '배달은 공공배달앱을 쓰면 수수료가 낮아 가격 인상 여파가 덜하다. '
            '외식은 점심 세트가 저녁보다 오르는 속도가 느리다.</p>'
            '<p>세 가지 모두 유가 인상의 여파지만, 반영 속도가 다르다. '
            '가장 빠르게 움직이는 항공료부터 먼저 체크하면 된다.</p>'
            '<strong>유가</strong><strong>항공료</strong>'
        )
        article = _make_article(two_num_body)
        ok, msg = _review(article)
        assert '수치' not in msg and '숫자' not in msg, f"충분한 수치인데 수치 오류: {msg}"


# ══════════════════════════════════════════════════════════════
# Q7. 연속 긴 문장 리듬 검사 (모바일 가독성)
# ══════════════════════════════════════════════════════════════

class TestMobileRhythm:
    """65자 초과 문장이 3개 이상 연속되면 모바일 가독성이 떨어지므로 검수 실패해야 한다."""

    # 65자 초과 긴 문장 샘플
    # 주의: split_sentences 정규식이 '다 '(다+공백)에서 분리하므로
    # 문장 중간에 '~이었다 ', '~마다 ' 등 '다 ' 패턴이 없어야 연속으로 인식됨
    _LONG_1 = '중동에서 계속 이어지는 전쟁으로 유가가 빠르게 오르기 시작하면서 항공사들이 연료비 인상분을 항공료에 거의 즉시 반영하고 있다.'  # 69자, 중간 '다 ' 없음
    _LONG_2 = '비행기는 한 번 비행할 때 엄청난 양의 연료유를 소비하기 때문에 유가가 조금만 올라도 편도 비행의 연료비가 수천 원씩 크게 오른다.'  # 73자, 중간 '다 ' 없음
    _LONG_3 = '배달앱이 식당과 고객 양쪽과 모두 계약 단가를 따로 협상하는 구조이기 때문에 유가 인상이 배달비에 반영되기까지 보통 2주 정도가 걸린다.'  # 76자, 중간 '다 ' 없음
    _LONG_4 = '운송사와의 계약 단가가 변경되는 주기가 미리 정해져 있으므로, 아무리 유가가 올라도 배달비가 즉시 오르는 것이 아니라 일정 시간이 필요하다.'  # 78자, 중간 '다 ' 없음

    # 공통 본문 보충 — Q5·Q6를 통과할 만큼 충분히 길고 수치도 포함
    _BODY_SUFFIX = (
        '<h2>배달비 변화</h2>'
        '<p>쿠팡이츠는 지난달 기본 배달비를 500원 올렸다. '
        '배달의민족도 같은 달 수수료를 조정해 시장 전체 배달비가 평균 8% 올랐다. '
        '공공배달앱 수수료는 민간보다 낮아서 여파가 덜하다.</p>'
        '<p>운송사 계약 단가가 2주 간격으로 바뀌기 때문에 유가 인상이 배달비에 즉시 반영되지 않는다. '
        '이미 3월 말부터 오르기 시작한 배달비는 4월 중순에 정점을 찍을 것으로 보인다. '
        '지금 공공배달앱으로 바꾸는 것이 가장 빠른 절약 방법이다.</p>'
        '<h2>외식비 흐름</h2>'
        '<p>2월 소비자물가 중 외식 항목이 3.4% 올랐다. '
        '재료비·인건비에 에너지 비용까지 겹치면 식당은 가격을 올린다. '
        '한 번 올린 외식 가격은 잘 내려오지 않는다.</p>'
        '<p>손님이 줄어도 고정비가 먼저 나가기 때문이다. '
        '지금 점심 세트 가격이 아직 안 올랐다면, 5월 안에는 바뀔 가능성이 있다. '
        '저녁 정식보다 점심 세트를 먼저 고르는 것이 덜 오른 가격을 쓰는 방법이다.</p>'
        '<h2>지금 고를 수 있는 것</h2>'
        '<p>항공권은 지금 끊는 게 낫다. '
        '배달은 공공배달앱을 쓰면 수수료가 낮아서 가격 인상 여파가 덜하다. '
        '외식은 점심 세트가 저녁보다 오르는 속도가 느리다.</p>'
        '<p>세 가지 모두 유가 인상의 여파지만, 반영 속도가 다르다. '
        '가장 빠르게 움직이는 항공료부터 먼저 체크하면 된다.</p>'
        '<strong>유가</strong><strong>항공료</strong>'
    )

    def test_three_consecutive_long_sentences_fails(self):
        """65자 초과 문장이 3개 연속되면 검수 실패해야 한다."""
        body = (
            '<h2>항공료 인상 이유</h2>'
            f'<p>{self._LONG_1} {self._LONG_2} {self._LONG_3}</p>'
            '<p>지금 항공권을 끊으면 인상 전 가격을 잡을 수 있다.</p>'
        ) + self._BODY_SUFFIX
        article = _make_article(body)
        ok, msg = _review(article)
        assert not ok, "연속 긴 문장이 3개인데 검수 통과됨"
        assert '연속' in msg or '리듬' in msg or '모바일' in msg, f"연속 긴 문장 언급 없음: {msg}"

    def test_four_consecutive_long_sentences_fails(self):
        """65자 초과 문장이 4개 연속되는 경우도 실패해야 한다."""
        body = (
            '<h2>항공료 인상 이유</h2>'
            f'<p>{self._LONG_1} {self._LONG_2} {self._LONG_3} {self._LONG_4}</p>'
            '<p>지금 항공권을 끊으면 인상 전 가격을 잡을 수 있다.</p>'
        ) + self._BODY_SUFFIX
        article = _make_article(body)
        ok, msg = _review(article)
        assert not ok
        assert '연속' in msg or '리듬' in msg or '모바일' in msg

    def test_alternating_sentences_passes(self):
        """긴 문장과 짧은 문장이 번갈아 오면 리듬 검사를 통과해야 한다."""
        article = _make_article(_GOOD_BODY)
        ok, msg = _review(article)
        assert '연속' not in msg and '리듬' not in msg, f"리듬이 좋은데 리듬 오류: {msg}"

    def test_two_consecutive_long_sentences_passes(self):
        """65자 초과 문장이 2개 연속인 경우는 허용해야 한다 (3개 미만)."""
        body = (
            '<h2>항공료 인상 이유</h2>'
            f'<p>{self._LONG_1} {self._LONG_2} 3만 원이다.</p>'
            '<p>지금 항공권을 끊으면 인상 전 가격을 잡을 수 있다.</p>'
        ) + self._BODY_SUFFIX
        article = _make_article(body)
        ok, msg = _review(article)
        assert '연속' not in msg and '리듬' not in msg, f"2개 연속인데 리듬 오류: {msg}"


# ─── P3: 도입부 훅 타입 (QB1) ───────────────────────────────────

_GOOD_BODY_SUFFIX_QB = (
    '<h2>두 번째 섹션</h2><p>40%의 팀이 3배 빠른 처리 속도를 체감했다.</p><p>두 번째 문단이다.</p>'
    '<h2>세 번째 섹션</h2><p>지금 써보면 바로 느낀다.</p><p>마지막 문단이다.</p>'
)

def _make_qb1_article(first_p_html: str) -> dict:
    body = (
        f'<h2>첫 번째 섹션</h2>{first_p_html}<p>두 번째 문단이다.</p>'
        + _GOOD_BODY_SUFFIX_QB
    )
    return {
        'title': 'AI 5가지 방법',
        'topic': 'AI 자동화',
        'body': body,
        'meta': '요약',
        'corner': '쉬운세상',
    }

def _structure_review(article):
    from bots.prompt_layer.writer_review import structure_review
    from bots.writer_bot import _has_action_result_shape
    return structure_review(article, has_action_result_shape=_has_action_result_shape)


class TestIntroHookType:
    """도입부 훅 타입 강제 — QB1"""

    def test_pure_description_intro_warns(self):
        """순수 설명체 도입 → QB1 경고"""
        article = _make_qb1_article('<p>AI는 현대 사회에서 매우 중요한 기술이다.</p>')
        _, msg = _structure_review(article)
        assert '훅 타입' in msg, f"설명체인데 QB1 경고 없음: {msg}"

    def test_shock_stat_intro_passes(self):
        """충격 수치 도입 → QB1 통과"""
        article = _make_qb1_article('<p>40%의 팀이 3배 빠른 처리 속도를 체감했다.</p>')
        _, msg = _structure_review(article)
        assert '훅 타입' not in msg, f"충격 수치인데 QB1 경고 발생: {msg}"

    def test_paradox_question_intro_passes(self):
        """역설 질문 도입 → QB1 통과"""
        article = _make_qb1_article('<p>잘 팔렸는데 왜 손실이 났을까?</p>')
        _, msg = _structure_review(article)
        assert '훅 타입' not in msg, f"역설 질문인데 QB1 경고 발생: {msg}"

    def test_vivid_scene_intro_passes(self):
        """생생한 장면 도입 → QB1 통과"""
        article = _make_qb1_article('<p>아침에 노트북을 열었더니 AI가 이미 요약을 준비해 두었다.</p>')
        _, msg = _structure_review(article)
        assert '훅 타입' not in msg, f"생생한 장면인데 QB1 경고 발생: {msg}"


# ─── P4: CTA 확장 (QB2) ─────────────────────────────────────────

def _make_qb2_article(last_p_text: str) -> dict:
    body = (
        '<h2>첫 번째 섹션</h2>'
        '<p>40%의 팀이 3배 빨라졌다. 아침에 노트북을 열면 AI가 요약을 준비한다.</p>'
        '<p>두 번째 문단이다.</p>'
        '<h2>두 번째 섹션</h2><p>세 번째 문단이다.</p><p>네 번째 문단이다.</p>'
        '<h2>세 번째 섹션</h2><p>다섯 번째 문단이다.</p>'
        f'<p>{last_p_text}</p>'
    )
    return {
        'title': 'AI 5가지 방법',
        'topic': 'AI 자동화',
        'body': body,
        'meta': '요약',
        'corner': '쉬운세상',
    }


class TestCTATimingBased:
    """마지막 문단 CTA — 시간 기반·손실 기반 확장 (QB2)"""

    def test_timing_cta_지금_passes(self):
        article = _make_qb2_article('지금 써보면 바로 느낀다.')
        _, msg = _structure_review(article)
        assert '독자 행동 기준' not in msg, f"'지금' CTA인데 경고 발생: {msg}"

    def test_timing_cta_당장_passes(self):
        article = _make_qb2_article('당장 확인해보면 된다.')
        _, msg = _structure_review(article)
        assert '독자 행동 기준' not in msg, f"'당장' CTA인데 경고 발생: {msg}"

    def test_loss_cta_모르면_passes(self):
        article = _make_qb2_article('모르면 손해 보는 방법이다.')
        _, msg = _structure_review(article)
        assert '독자 행동 기준' not in msg, f"'모르면' CTA인데 경고 발생: {msg}"

    def test_existing_cta_고르면_still_passes(self):
        """기존 '고르면' 토큰도 계속 통과해야 한다."""
        article = _make_qb2_article('예산에 맞게 고르면 된다.')
        _, msg = _structure_review(article)
        assert '독자 행동 기준' not in msg, f"기존 '고르면' CTA인데 경고 발생: {msg}"

    def test_pure_description_last_para_warns(self):
        """행동 기준 없는 마지막 문단 → 여전히 경고"""
        # '된다' 등 has_result 패턴이 없는 설명체 사용
        article = _make_qb2_article('AI 기술이 업무 방식에 미치는 영향은 상당히 크다.')
        _, msg = _structure_review(article)
        assert '독자 행동 기준' in msg, f"행동 기준 없는데 경고 없음: {msg}"


# ─── 금융/일상 생활 장면 마커 확장 ──────────────────────────────────
# 신한금융 ROE 같은 금융 주제는 노트북·터미널이 아닌 통장·월급·이자 등
# 일상 금융 장면을 사용한다. 이 마커가 '쉬운세상' 생활 장면 검사를 통과해야 한다.

def _make_finance_article(body: str) -> dict:
    return {
        'title': 'ROE 5% 차이를 보면 배당이 달라진다',
        'meta': 'ROE 비율을 보면 어떤 은행 주식이 배당을 더 주는지 바로 알 수 있다.',
        'topic': '신한금융그룹 ROE 경영 전략',
        'corner': '쉬운세상',
        'body': body,
    }


_FINANCE_GOOD_SUFFIX = (
    '<h2>ROE가 배당을 결정하는 방식</h2>'
    '<p>ROE가 10%를 넘으면 자기자본 대비 순이익이 두 자릿수라는 뜻이다. '
    '2024년 신한금융의 ROE는 8.7%였다.</p>'
    '<p>지금 주식 앱을 열어서 ROE 항목을 찾아보면 된다.</p>'
    '<h2>종목 고르는 기준</h2>'
    '<p>배당 성향이 높은 곳을 고르면 매년 이자처럼 배당금을 받을 수 있다.</p>'
    '<p>ROE가 높은 종목부터 확인해보면 선택이 쉬워진다.</p>'
)


class TestFinanceLifeSceneMarkers:
    """금융 주제 생활 장면 마커가 structure_review 생활 장면 검사를 통과해야 한다."""

    def test_통장_relatable_marker_passes_쉬운세상_check(self):
        """'통장' 마커가 포함된 본문 → 쉬운세상 생활 장면 검사 통과"""
        body = (
            '<h2>ROE 뜻부터 알면 선택이 달라진다</h2>'
            '<p>통장에 이자를 받아보면 ROE(자기자본이익률)가 높은 은행이 어딘지 '
            '바로 확인해보게 된다. ROE 8% 이상이면 예금 금리 경쟁력도 높다.</p>'
            '<p>ROE가 높은 은행일수록 예금이자를 더 넉넉히 줄 여력이 있다.</p>'
            + _FINANCE_GOOD_SUFFIX
        )
        article = _make_finance_article(body)
        _, msg = _structure_review(article)
        assert '생활 장면' not in msg, f"통장 마커인데 생활 장면 경고 발생: {msg}"

    def test_월급_relatable_marker_passes_쉬운세상_check(self):
        """'월급' 마커가 포함된 본문 → 쉬운세상 생활 장면 검사 통과"""
        body = (
            '<h2>ROE 뜻부터 알면 선택이 달라진다</h2>'
            '<p>월급날 적금 금리를 비교해보면 ROE가 높은 곳이 금리도 더 주는 경향이 있다. '
            'ROE가 높은 금융사일수록 예금 상품 경쟁력도 높다.</p>'
            '<p>신한금융의 ROE는 2024년 8.7%였다. 1년 전보다 0.3%포인트 올랐다.</p>'
            + _FINANCE_GOOD_SUFFIX
        )
        article = _make_finance_article(body)
        _, msg = _structure_review(article)
        assert '생활 장면' not in msg, f"월급 마커인데 생활 장면 경고 발생: {msg}"

    def test_통장_vivid_scene_passes_QB1(self):
        """금융 생활 장면('통장')이 포함된 도입부 → QB1 훅 타입 통과"""
        body = (
            '<h2>ROE 뜻부터 알면 선택이 달라진다</h2>'
            '<p>통장 이자가 1년 전보다 2만 원 더 들어온 걸 확인해보면 '
            'ROE가 오른 은행이 어딘지 알고 싶어진다.</p>'
            '<p>ROE가 오르면 이런 변화가 생긴다.</p>'
            + _FINANCE_GOOD_SUFFIX
        )
        article = _make_finance_article(body)
        _, msg = _structure_review(article)
        assert '훅 타입' not in msg, f"통장 금액 도입인데 QB1 경고 발생: {msg}"

    def test_주식앱_relatable_marker_passes_쉬운세상_check(self):
        """'주식' 마커가 포함된 본문 → 쉬운세상 생활 장면 검사 통과"""
        body = (
            '<h2>ROE 뜻부터 알면 선택이 달라진다</h2>'
            '<p>주식 앱을 열어 배당 수익률을 찾아볼 때 ROE 항목이 함께 표시된다. '
            'ROE 8% 이상이면 배당 여력이 있다는 신호로 읽으면 된다.</p>'
            '<p>신한금융 ROE는 2024년 기준 8.7%였다.</p>'
            + _FINANCE_GOOD_SUFFIX
        )
        article = _make_finance_article(body)
        _, msg = _structure_review(article)
        assert '생활 장면' not in msg, f"주식 앱 마커인데 생활 장면 경고 발생: {msg}"


# ─── 에너지/교통/일상 생활 마커 확장 ────────────────────────────────
# WTI 유가 같은 에너지·교통 주제는 주유소·가스비·택시 등을 사용한다.

def _make_energy_article(body: str) -> dict:
    return {
        'title': 'WTI 유가 오르면 주유소 기름값이 3% 오른다',
        'meta': 'WTI 선물이 오르면 2주 안에 주유소 기름값도 오른다는 걸 알면 미리 주유할 수 있다.',
        'topic': 'WTI 선물 반등 2.91% 상승',
        'corner': '쉬운세상',
        'body': body,
    }


_ENERGY_GOOD_SUFFIX = (
    '<h2>유가가 생활비에 미치는 경로</h2>'
    '<p>국제 유가가 1% 오르면 국내 휘발유 가격은 2주 뒤에 0.3~0.5% 반영된다. '
    '2024년 4월 기준 WTI는 배럴당 97.16달러였다.</p>'
    '<p>주유비가 오르면 택배·배달 업체 물류비도 따라 오른다.</p>'
    '<h2>지금 할 수 있는 대비</h2>'
    '<p>가스비 고정 요금제를 미리 신청해두면 유가 변동에 덜 흔들린다.</p>'
    '<p>WTI 지표를 보면서 주유 시기를 조정해보면 연간 몇만 원을 아낄 수 있다.</p>'
)


class TestEnergyLifeSceneMarkers:
    """에너지/교통 주제 생활 장면 마커도 쉬운세상 검사를 통과해야 한다."""

    def test_주유소_relatable_marker_passes(self):
        """'주유소' 마커 → 쉬운세상 생활 장면 통과"""
        body = (
            '<h2>WTI가 오르면 주유소에서 먼저 느낀다</h2>'
            '<p>주유소 가격표를 보면 WTI 지수가 오른 날부터 2주 안에 기름값이 오르는 걸 확인해보게 된다. '
            '2024년 4월 WTI는 97.16달러까지 올랐다.</p>'
            '<p>국제 유가 1% 상승은 국내 휘발유 가격 0.3% 인상으로 이어진다.</p>'
            + _ENERGY_GOOD_SUFFIX
        )
        article = _make_energy_article(body)
        _, msg = _structure_review(article)
        assert '생활 장면' not in msg, f"주유소 마커인데 생활 장면 경고 발생: {msg}"

    def test_가스비_relatable_marker_passes(self):
        """'가스비' 마커 → 쉬운세상 생활 장면 통과"""
        body = (
            '<h2>WTI가 오르면 주유소에서 먼저 느낀다</h2>'
            '<p>가스비 청구서를 받아보면 WTI 유가가 반영되는 시차가 2주라는 걸 알 수 있다. '
            '2024년 4월 WTI는 97달러를 돌파했다.</p>'
            '<p>국제 유가 1% 상승은 국내 휘발유 가격 0.3% 인상으로 이어진다.</p>'
            + _ENERGY_GOOD_SUFFIX
        )
        article = _make_energy_article(body)
        _, msg = _structure_review(article)
        assert '생활 장면' not in msg, f"가스비 마커인데 생활 장면 경고 발생: {msg}"

    def test_택시_relatable_marker_passes(self):
        """'택시' 마커 → 쉬운세상 생활 장면 통과"""
        body = (
            '<h2>WTI가 오르면 주유소에서 먼저 느낀다</h2>'
            '<p>택시를 타면 기사가 "기름값이 올라서 힘들다"고 말하는 게 WTI 반등 직후 2주가 지난 시점이다. '
            '2024년 4월 WTI는 97달러였다.</p>'
            '<p>국제 유가 1% 상승은 국내 휘발유 가격 0.3% 인상으로 이어진다.</p>'
            + _ENERGY_GOOD_SUFFIX
        )
        article = _make_energy_article(body)
        _, msg = _structure_review(article)
        assert '생활 장면' not in msg, f"택시 마커인데 생활 장면 경고 발생: {msg}"
