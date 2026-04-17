"""
tests/test_automotive_pipeline.py

전장반도체 파이프라인 테스트 (TDD RED 단계)

테스트 대상: bots/automotive_pipeline.py
- filter_automotive_topics(): 수집된 토픽에서 전장/반도체 관련 항목만 필터링
- format_morning_brief(): 텔레그램 아침 브리핑 메시지 포맷
- parse_insight_memo(): 사용자 인사이트 메모 파싱
"""

import pytest


# ─── 샘플 데이터 ───────────────────────────────────────

AUTOMOTIVE_TOPIC = {
    "topic": "NXP S32G3 신규 Zone Controller 레퍼런스 플랫폼 발표",
    "description": "NXP가 AUTOSAR Adaptive 기반의 Zonal Architecture용 S32G3 레퍼런스 플랫폼을 공개했다.",
    "source_name": "EE Times",
    "source_url": "https://www.eetimes.com/nxp-s32g3-zone-controller",
    "published_at": "2026-04-17T07:00:00",
    "quality_score": 75,
    "topic_type": "trending",
}

SEMICONDUCTOR_TOPIC = {
    "topic": "Renesas RH850/U2A 멀티코어 MCU 전장 채택 확대",
    "description": "Renesas의 RH850/U2A가 국내 완성차 OEM의 Zonal ECU 핵심 칩으로 채택되고 있다.",
    "source_name": "Embedded.com",
    "source_url": "https://www.embedded.com/renesas-rh850",
    "published_at": "2026-04-17T06:00:00",
    "quality_score": 80,
    "topic_type": "trending",
}

UNRELATED_TOPIC = {
    "topic": "카카오 신규 AI 서비스 출시",
    "description": "카카오가 GPT 기반 챗봇 서비스를 공개했다.",
    "source_name": "ZDNet Korea",
    "source_url": "https://zdnet.co.kr/kakao-ai",
    "published_at": "2026-04-17T05:00:00",
    "quality_score": 70,
    "topic_type": "trending",
}

FINANCE_TOPIC = {
    "topic": "삼성전자 2분기 반도체 실적 전망",
    "description": "삼성전자 차량용 LPDDR 수출이 2분기에 급증할 것으로 전망된다.",
    "source_name": "Maeil Economy",
    "source_url": "https://mk.co.kr/samsung-semi",
    "published_at": "2026-04-17T04:00:00",
    "quality_score": 65,
    "topic_type": "trending",
}


# ─── filter_automotive_topics 테스트 ──────────────────

class TestFilterAutomotiveTopics:
    def test_returns_automotive_topic(self):
        """전장/AUTOSAR 관련 토픽은 포함된다."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics([AUTOMOTIVE_TOPIC, UNRELATED_TOPIC])
        assert len(result) == 1
        assert result[0]["topic"] == AUTOMOTIVE_TOPIC["topic"]

    def test_returns_semiconductor_topic(self):
        """반도체 MCU 관련 토픽은 포함된다."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics([SEMICONDUCTOR_TOPIC, UNRELATED_TOPIC])
        assert len(result) == 1
        assert result[0]["topic"] == SEMICONDUCTOR_TOPIC["topic"]

    def test_excludes_unrelated_topic(self):
        """전장/반도체와 무관한 토픽은 제외된다."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics([UNRELATED_TOPIC])
        assert len(result) == 0

    def test_includes_automotive_finance_topic(self):
        """차량용 반도체 관련 금융 토픽은 포함된다."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics([FINANCE_TOPIC])
        assert len(result) == 1

    def test_empty_input(self):
        """빈 리스트 입력 시 빈 리스트 반환."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics([])
        assert result == []

    def test_returns_multiple_automotive_topics(self):
        """여러 전장 토픽 모두 반환된다."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics(
            [AUTOMOTIVE_TOPIC, SEMICONDUCTOR_TOPIC, UNRELATED_TOPIC]
        )
        assert len(result) == 2

    def test_sorts_by_quality_score_descending(self):
        """품질 점수 높은 순으로 정렬된다."""
        import bots.automotive_pipeline as ap
        result = ap.filter_automotive_topics(
            [AUTOMOTIVE_TOPIC, SEMICONDUCTOR_TOPIC]
        )
        assert result[0]["quality_score"] >= result[1]["quality_score"]

    def test_automotive_source_with_relevant_keyword_included(self):
        """source_category=automotive + 보조 키워드 1개 → 포함된다."""
        import bots.automotive_pipeline as ap
        topic = {
            "topic": "Radar Reference Platform Improves Identification in Edge AI",
            "description": "A radar-based automotive sensor platform for ADAS.",
            "source_name": "Embedded.com",
            "source_url": "https://embedded.com/radar",
            "source_category": "automotive",
            "quality_score": 68,
        }
        result = ap.filter_automotive_topics([topic, UNRELATED_TOPIC])
        assert len(result) == 1

    def test_automotive_source_without_keyword_excluded(self):
        """source_category=automotive라도 보조 키워드 없으면 제외된다."""
        import bots.automotive_pipeline as ap
        topic = {
            "topic": "Lightrun Report Reveals Reliability Issues in AI-Generated Code",
            "description": "A report on AI-generated code reliability problems.",
            "source_name": "Embedded.com",
            "source_url": "https://embedded.com/lightrun",
            "source_category": "automotive",
            "quality_score": 66,
        }
        result = ap.filter_automotive_topics([topic])
        assert len(result) == 0


# ─── format_morning_brief 테스트 ──────────────────────

class TestFormatMorningBrief:
    def test_contains_topic_title(self):
        """토픽 제목(topic 필드)이 메시지에 포함된다."""
        import bots.automotive_pipeline as ap
        msg = ap.format_morning_brief([AUTOMOTIVE_TOPIC])
        assert "NXP S32G3" in msg

    def test_contains_topic_source(self):
        """출처(source_name 필드)가 메시지에 포함된다."""
        import bots.automotive_pipeline as ap
        msg = ap.format_morning_brief([AUTOMOTIVE_TOPIC])
        assert "EE Times" in msg

    def test_contains_reply_instruction(self):
        """인사이트 메모 입력 안내 문구가 포함된다."""
        import bots.automotive_pipeline as ap
        msg = ap.format_morning_brief([AUTOMOTIVE_TOPIC])
        assert "인사이트" in msg or "메모" in msg or "답장" in msg

    def test_strips_html_tags_from_description(self):
        """HTML 태그가 제거된 plain text로 출력된다."""
        import bots.automotive_pipeline as ap
        topic_with_html = {
            "topic": "NXP S32G3 출시",
            "description": "<p>NXP가 <strong>S32G3</strong>를 공개했다.</p>",
            "source_name": "EE Times",
            "source_url": "https://eetimes.com/nxp",
            "quality_score": 80,
        }
        msg = ap.format_morning_brief([topic_with_html])
        assert "<p>" not in msg
        assert "<strong>" not in msg
        assert "NXP가" in msg
        assert "S32G3" in msg

    def test_unescapes_html_entities(self):
        """HTML 엔티티(&quot; &amp; 등)가 일반 문자로 변환된다."""
        import bots.automotive_pipeline as ap
        topic_with_entities = {
            "topic": "삼성 &quot;반도체 전장 확대&quot; 발표",
            "description": "삼성전자 &amp; SK하이닉스 차량용 메모리 시장 진출.",
            "source_name": "EE Times",
            "source_url": "https://eetimes.com/samsung",
            "quality_score": 75,
        }
        msg = ap.format_morning_brief([topic_with_entities])
        assert "&quot;" not in msg
        assert "&amp;" not in msg
        assert '"반도체' in msg or "반도체" in msg

    def test_empty_topics_returns_no_topics_message(self):
        """토픽이 없으면 없다는 안내 메시지 반환."""
        import bots.automotive_pipeline as ap
        msg = ap.format_morning_brief([])
        assert "없" in msg

    def test_multiple_topics_numbered(self):
        """여러 토픽은 번호가 매겨진다."""
        import bots.automotive_pipeline as ap
        msg = ap.format_morning_brief([AUTOMOTIVE_TOPIC, SEMICONDUCTOR_TOPIC])
        assert "1" in msg
        assert "2" in msg

    def test_contains_source_url(self):
        """원문 링크가 포함된다."""
        import bots.automotive_pipeline as ap
        msg = ap.format_morning_brief([AUTOMOTIVE_TOPIC])
        assert "eetimes.com" in msg


# ─── parse_insight_memo 테스트 ──────────────────────

class TestTranslation:
    def test_english_text_detected_as_english(self):
        """영어 텍스트를 영어로 감지한다."""
        import bots.automotive_pipeline as ap
        assert ap._is_english("NXP announces new Zone Controller platform for automotive") is True

    def test_korean_text_not_detected_as_english(self):
        """한국어 텍스트는 영어로 감지하지 않는다."""
        import bots.automotive_pipeline as ap
        assert ap._is_english("테슬라가 96GB 메모리를 탑재한 차량용 AI 칩을 공개했다") is False

    def test_mixed_text_with_mostly_korean_not_english(self):
        """한국어가 많은 혼합 텍스트는 영어로 감지하지 않는다."""
        import bots.automotive_pipeline as ap
        assert ap._is_english("NXP의 S32G3가 국내 완성차 OEM에 채택됐다") is False

    def test_format_morning_brief_translates_english_title(self):
        """영어 제목은 한국어로 번역되어 출력된다."""
        import unittest.mock as mock
        import bots.automotive_pipeline as ap

        english_topic = {
            "topic": "NXP Announces S32G3 Zone Controller Platform",
            "description": "NXP reveals automotive SoC for Zonal Architecture.",
            "source_name": "EE Times",
            "source_url": "https://eetimes.com/nxp",
            "source_category": "automotive",
            "quality_score": 80,
        }

        with mock.patch.object(ap, '_translate_batch',
                               return_value=[("NXP, S32G3 존 컨트롤러 플랫폼 발표", "NXP가 차량용 SoC를 공개했다.")]):
            msg = ap.format_morning_brief([english_topic])
            assert "NXP, S32G3 존 컨트롤러 플랫폼 발표" in msg

    def test_korean_title_not_translated(self):
        """한국어 제목은 번역하지 않는다 — _translate_batch 호출 없음."""
        import unittest.mock as mock
        import bots.automotive_pipeline as ap

        with mock.patch.object(ap, '_translate_batch') as mock_batch:
            ap.format_morning_brief([AUTOMOTIVE_TOPIC])
            mock_batch.assert_not_called()

    def test_batch_translation_single_call_for_multiple_articles(self):
        """여러 영어 기사가 있어도 AI 호출은 1번만 한다."""
        import unittest.mock as mock
        import bots.automotive_pipeline as ap

        english_topics = [
            {
                "topic": f"English Article {i}",
                "description": f"English description {i} about automotive semiconductor.",
                "source_name": "EE Times",
                "source_url": f"https://eetimes.com/{i}",
                "source_category": "automotive",
                "quality_score": 70,
            }
            for i in range(3)
        ]

        with mock.patch.object(ap, '_translate_batch',
                               return_value=[("번역 제목", "번역 설명")] * 3) as mock_batch:
            ap.format_morning_brief(english_topics)
            # 개별 호출(_translate_to_korean) 대신 _translate_batch 1번만 호출
            mock_batch.assert_called_once()

    def test_translate_batch_returns_same_count(self):
        """_translate_batch는 입력과 같은 수의 (제목, 설명) 쌍을 반환한다."""
        import unittest.mock as mock
        import bots.automotive_pipeline as ap

        items = [
            ("NXP announces Zone Controller", "NXP reveals automotive SoC."),
            ("Renesas RH850 adopted", "Renesas chip for Zonal ECU."),
        ]

        fake_response = "1. NXP, 존 컨트롤러 발표\nNXP가 차량용 SoC를 공개했다.\n2. 르네사스 RH850 채택\n르네사스 칩이 Zonal ECU에 채택됐다."

        with mock.patch.object(ap, '_translate_to_korean', return_value=fake_response):
            result = ap._translate_batch(items)

        assert len(result) == 2
        assert isinstance(result[0], tuple)
        assert len(result[0]) == 2


class TestParseInsightMemo:
    def test_parses_simple_insight(self):
        """단순 인사이트 메모를 파싱한다."""
        import bots.automotive_pipeline as ap
        text = "NXP 기사 흥미롭네. 메모리 이슈랑 연결해봐"
        result = ap.parse_insight_memo(text)
        assert result is not None
        assert "memo" in result

    def test_returns_none_for_bot_command(self):
        """/command 형태는 None 반환 (봇 명령어)."""
        import bots.automotive_pipeline as ap
        result = ap.parse_insight_memo("/status")
        assert result is None

    def test_returns_none_for_empty_string(self):
        """빈 문자열은 None 반환."""
        import bots.automotive_pipeline as ap
        result = ap.parse_insight_memo("")
        assert result is None

    def test_returns_none_for_whitespace(self):
        """공백만 있는 경우 None 반환."""
        import bots.automotive_pipeline as ap
        result = ap.parse_insight_memo("   ")
        assert result is None

    def test_memo_field_contains_original_text(self):
        """result['memo']에 원본 텍스트가 담긴다."""
        import bots.automotive_pipeline as ap
        text = "Zonal 때문에 요즘 Zone Controller 메모리 이슈 진짜 심각함"
        result = ap.parse_insight_memo(text)
        assert result["memo"] == text.strip()

    def test_detects_topic_reference(self):
        """특정 토픽 번호 참조를 감지한다 (예: '1번 기사')."""
        import bots.automotive_pipeline as ap
        text = "1번 기사 흥미롭네. NXP랑 투자 관점으로 연결해줘"
        result = ap.parse_insight_memo(text)
        assert result is not None
        assert result.get("topic_ref") == 1

    def test_no_topic_ref_when_not_specified(self):
        """토픽 번호 없으면 topic_ref는 None."""
        import bots.automotive_pipeline as ap
        text = "Zonal Architecture 메모리 이슈 써봐"
        result = ap.parse_insight_memo(text)
        assert result["topic_ref"] is None
