"""
tests/test_automotive_collector.py

전장 소스 수집 예외 처리 테스트 (TDD RED)

테스트 대상:
- collect_rss_feeds(): automotive 카테고리 소스에 source_category 필드 저장
- apply_discard_rules(): automotive 소스는 한국 관련성 필터 예외 처리
"""

import pytest


class TestCollectRssFeeds:
    def test_automotive_source_has_category_field(self):
        """automotive 카테고리 RSS 피드 수집 시 source_category 필드가 저장된다."""
        import bots.collector_bot as cb

        fake_sources = {
            'rss_feeds': [
                {
                    'name': 'EE Times',
                    'url': 'https://httpbin.org/get',  # 실제 RSS 아님, 오류 시 빈 리스트
                    'category': 'automotive',
                    'trust_level': 'high',
                }
            ]
        }

        # feedparser가 빈 결과를 반환해도 source_category 필드가 붙는지 확인
        # 실제 URL 대신 mock 사용
        import unittest.mock as mock
        import feedparser

        fake_entry = mock.MagicMock()
        fake_entry.get.side_effect = lambda key, default='': {
            'title': 'NXP S32G3 Zone Controller Platform',
            'summary': 'NXP announces new automotive SoC',
            'link': 'https://eetimes.com/nxp-s32g3',
        }.get(key, default)
        fake_entry.published_parsed = None

        fake_feed = mock.MagicMock()
        fake_feed.entries = [fake_entry]

        with mock.patch.object(feedparser, 'parse', return_value=fake_feed):
            items = cb.collect_rss_feeds(fake_sources)

        assert len(items) == 1
        assert items[0]['source_category'] == 'automotive'

    def test_non_automotive_source_has_empty_category(self):
        """non-automotive RSS 피드는 source_category가 비어 있거나 tech/finance다."""
        import bots.collector_bot as cb
        import unittest.mock as mock
        import feedparser

        fake_sources = {
            'rss_feeds': [
                {
                    'name': 'GeekNews',
                    'url': 'https://feeds.feedburner.com/geeknews-feed',
                    'category': 'tech',
                    'trust_level': 'high',
                }
            ]
        }

        fake_entry = mock.MagicMock()
        fake_entry.get.side_effect = lambda key, default='': {
            'title': '카카오 신규 AI 출시',
            'summary': '카카오가 AI를 공개했다',
            'link': 'https://news.hada.io/topic?id=123',
        }.get(key, default)
        fake_entry.published_parsed = None

        fake_feed = mock.MagicMock()
        fake_feed.entries = [fake_entry]

        with mock.patch.object(feedparser, 'parse', return_value=fake_feed):
            items = cb.collect_rss_feeds(fake_sources)

        assert len(items) == 1
        assert items[0].get('source_category', '') != 'automotive'


class TestApplyDiscardRules:
    """automotive 카테고리 아이템은 한국 관련성 필터를 통과해야 한다."""

    BASE_RULES = {
        'discard_rules': [
            {'id': 'no_korean_relevance', 'description': '한국 독자와 무관'}
        ]
    }

    def test_automotive_source_passes_korean_relevance_filter(self):
        """source_category=automotive 아이템은 korean_relevance_score=0이어도 통과."""
        import bots.collector_bot as cb

        item = {
            'topic': 'NXP S32G3 Zone Controller Platform Released',
            'description': 'NXP announces automotive SoC for Zonal Architecture.',
            'source_name': 'EE Times',
            'source_url': 'https://eetimes.com/nxp-s32g3',
            'source_category': 'automotive',
            'korean_relevance_score': 0,  # 영어 기사라 0점
            'source_trust_level': 'high',
        }

        result = cb.apply_discard_rules(item, self.BASE_RULES, set())
        assert result is None, f"automotive 소스가 폐기됨: {result}"

    def test_non_automotive_source_fails_korean_relevance_filter(self):
        """source_category가 automotive가 아니면 korean_relevance_score=0 시 폐기."""
        import bots.collector_bot as cb

        item = {
            'topic': 'Some English Tech News',
            'description': 'An English article about something.',
            'source_name': 'TechCrunch',
            'source_url': 'https://techcrunch.com/article',
            'source_category': 'tech',
            'korean_relevance_score': 0,
            'source_trust_level': 'high',
        }

        result = cb.apply_discard_rules(item, self.BASE_RULES, set())
        assert result == '한국 독자 관련성 없음'
