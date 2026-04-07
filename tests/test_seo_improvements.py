"""
tests/test_seo_improvements.py
P0~P4 SEO 개선 사항 테스트
"""
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
# P0: META 설명 버그 수정
# ──────────────────────────────────────────────────────────────

class TestMetaFallback:
    """META가 플레이스홀더일 때 본문 첫 문장으로 대체"""

    def _sanitize(self, article):
        from bots.publisher_bot import sanitize_article_for_publish
        return sanitize_article_for_publish(article)

    def test_placeholder_replaced_with_body_first_sentence(self):
        article = {
            'title': 'Gemma 4 모델 선택 가이드',
            'meta': '핵심 문구부터 보면 뜻이 바로 잡힌다',
            'body': '<h2>소개</h2><p>Gemma 4는 Google DeepMind가 공개한 오픈소스 LLM이다.</p>',
        }
        result = self._sanitize(article)
        assert '핵심 문구부터 보면' not in result['meta']
        assert 'Gemma 4' in result['meta'] or len(result['meta']) > 10

    def test_empty_meta_replaced_with_body_first_sentence(self):
        article = {
            'title': '테스트 글',
            'meta': '',
            'body': '<h2>소개</h2><p>AI 에이전트를 병렬로 실행하면 작업 속도가 빨라진다.</p>',
        }
        result = self._sanitize(article)
        assert len(result.get('meta', '')) > 10

    def test_good_meta_unchanged(self):
        good_meta = 'Ravenclaw 폴더에 메모를 넣으면 AI 에이전트를 바꿔도 작업 맥락이 유지된다.'
        article = {
            'title': '테스트 글',
            'meta': good_meta,
            'body': '<h2>소개</h2><p>본문 내용.</p>',
        }
        result = self._sanitize(article)
        assert result['meta'] == good_meta

    def test_meta_description_synced_with_meta(self):
        article = {
            'title': '테스트',
            'meta': '핵심 문구부터 보면 뜻이 바로 잡힌다',
            'body': '<h2>소개</h2><p>Claude Code를 사용하면 코드 작업이 자동화된다.</p>',
        }
        result = self._sanitize(article)
        assert result.get('meta') == result.get('meta_description')


class TestBloggerCustomMetaData:
    """Blogger API 호출 시 customMetaData 전송 검증"""

    def test_custom_meta_data_included_in_blogger_body(self):
        from bots.publisher_bot import publish_to_blogger

        mock_service = MagicMock()
        mock_posts = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {'url': 'https://test.blogspot.com/post', 'id': '123'}
        mock_posts.insert.return_value = mock_insert
        mock_service.posts.return_value = mock_posts

        mock_creds = MagicMock()

        article = {
            'title': '테스트 글',
            'meta_description': 'Gemma 4를 선택하면 추론 성능이 달라진다.',
            'corner': '쉬운세상',
            'tags': ['AI'],
        }

        with patch('bots.publisher_bot.build', return_value=mock_service), \
             patch('bots.publisher_bot.BLOG_MAIN_ID', 'fake-blog-id'):
            publish_to_blogger(article, '<p>본문</p>', mock_creds)

        call_kwargs = mock_posts.insert.call_args
        sent_body = call_kwargs.kwargs.get('body') or call_kwargs.args[0] if call_kwargs.args else {}
        if not sent_body:
            sent_body = call_kwargs[1].get('body', {})
        assert 'customMetaData' in sent_body
        assert sent_body['customMetaData'] == 'Gemma 4를 선택하면 추론 성능이 달라진다.'

    def test_empty_meta_does_not_send_custom_meta_data(self):
        from bots.publisher_bot import publish_to_blogger

        mock_service = MagicMock()
        mock_posts = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = {'url': 'https://test.blogspot.com/post', 'id': '123'}
        mock_posts.insert.return_value = mock_insert
        mock_service.posts.return_value = mock_posts

        mock_creds = MagicMock()
        article = {'title': '테스트', 'meta_description': '', 'corner': '쉬운세상', 'tags': []}

        with patch('bots.publisher_bot.build', return_value=mock_service), \
             patch('bots.publisher_bot.BLOG_MAIN_ID', 'fake-blog-id'):
            publish_to_blogger(article, '<p>본문</p>', mock_creds)

        call_kwargs = mock_posts.insert.call_args
        sent_body = call_kwargs.kwargs.get('body') or {}
        if not sent_body and call_kwargs.args:
            sent_body = call_kwargs.args[0] if isinstance(call_kwargs.args[0], dict) else {}
        assert 'customMetaData' not in sent_body


# ──────────────────────────────────────────────────────────────
# P0: writer_review META 플레이스홀더 감지
# ──────────────────────────────────────────────────────────────

class TestWriterReviewMeta:
    """presentation_review에서 META 플레이스홀더 감지"""

    def _review(self, article):
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _make_body(self):
        return '<h2>소개</h2><p>테스트 본문이다.</p><h2>본론</h2><p>내용이다.</p><h2>결론</h2><p>마무리다.</p><strong>핵심</strong>'

    def test_placeholder_meta_fails_review(self):
        article = {
            'title': '완결된 제목입니다',
            'meta': '핵심 문구부터 보면 뜻이 바로 잡힌다',
            'body': self._make_body(),
        }
        ok, msg = self._review(article)
        assert not ok
        assert 'META' in msg

    def test_empty_meta_fails_review(self):
        article = {'title': '완결된 제목', 'meta': '', 'body': self._make_body()}
        ok, msg = self._review(article)
        assert not ok
        assert 'META' in msg

    def test_good_meta_passes_review(self):
        article = {
            'title': '완결된 제목',
            'meta': 'Claude Code를 설치하면 터미널에서 AI 코딩이 바로 시작된다.',
            'body': self._make_body(),
        }
        ok, msg = self._review(article)
        meta_issues = [l for l in msg.split('\n') if 'META' in l]
        assert not meta_issues, f"META 관련 이슈 발생: {meta_issues}"


# ──────────────────────────────────────────────────────────────
# P1: 제목 SEO 검증 (writer_review)
# ──────────────────────────────────────────────────────────────

class TestTitleSEOReview:
    """끊긴 제목 및 고유명사 누락 감지"""

    def _review(self, article):
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _make_body(self):
        return '<h2>소개</h2><p>테스트다.</p><h2>본론</h2><p>내용이다.</p><h2>결론</h2><p>끝이다.</p><strong>강조</strong>'

    def _good_article(self, title, topic=''):
        return {
            'title': title,
            'topic': topic,
            'meta': 'Claude Code를 설치하면 AI 코딩이 시작된다.',
            'body': self._make_body(),
        }

    @pytest.mark.parametrize('dangling_title', [
        'Gemma 4 모델 크기를 보면',
        'Ravenclaw 폴더에 담으면 Claude',
        '프로젝트 메모를 정리하면 AI',
        '설정 파일을 보면',
    ])
    def test_dangling_title_fails(self, dangling_title):
        ok, msg = self._review(self._good_article(dangling_title))
        assert not ok
        title_issues = [l for l in msg.split('\n') if '제목' in l and ('끊겼다' in l or '조건절' in l)]
        assert title_issues, f"'{dangling_title}' → 끊긴 제목 미감지"

    @pytest.mark.parametrize('good_title', [
        'Claude Code를 설치하면 AI 코딩이 바로 시작된다',
        'Gemma 4 모델 크기 비교 가이드',
        'Ravenclaw로 AI 에이전트 작업 맥락 유지하는 법',
    ])
    def test_complete_title_passes(self, good_title):
        ok, msg = self._review(self._good_article(good_title))
        title_issues = [l for l in msg.split('\n') if '제목' in l and ('끊겼다' in l or '조건절' in l)]
        assert not title_issues, f"'{good_title}' → 오탐 발생"

    def test_missing_proper_noun_in_title_flagged(self):
        article = self._good_article(
            title='AI 모델 크기 비교 가이드',
            topic='Gemma 4 최신 모델 공개',
        )
        ok, msg = self._review(article)
        keyword_issues = [l for l in msg.split('\n') if '고유명사' in l or '키워드' in l]
        assert keyword_issues, "글감 고유명사 누락이 감지되지 않았다"

    def test_title_with_proper_noun_passes(self):
        article = self._good_article(
            title='Gemma 4 모델 선택 가이드',
            topic='Gemma 4 최신 모델 공개',
        )
        ok, msg = self._review(article)
        keyword_issues = [l for l in msg.split('\n') if '고유명사' in l or '키워드' in l]
        assert not keyword_issues, f"정상 제목에 오탐: {keyword_issues}"


# ──────────────────────────────────────────────────────────────
# P2: 내부 링크 자동 삽입 (linker_bot)
# ──────────────────────────────────────────────────────────────

class TestInternalLinks:
    """발행 이력 기반 관련 글 내부 링크 삽입"""

    @pytest.fixture
    def published_dir(self, tmp_path):
        pub_dir = tmp_path / 'published'
        pub_dir.mkdir()
        articles = [
            {'title': 'Claude Code 설치 방법 완벽 가이드', 'url': 'https://blog.example.com/claude-code', 'tags': ['AI', 'Claude Code']},
            {'title': 'Gemma 4 모델 크기 비교', 'url': 'https://blog.example.com/gemma-4', 'tags': ['AI', 'LLM', 'Gemma']},
            {'title': '주식 투자 ETF 기초 가이드', 'url': 'https://blog.example.com/etf', 'tags': ['투자', 'ETF']},
        ]
        for i, art in enumerate(articles):
            (pub_dir / f'2026040{i+1}_test.json').write_text(
                json.dumps(art, ensure_ascii=False), encoding='utf-8'
            )
        return pub_dir

    def test_related_section_inserted(self, published_dir):
        from bots.linker_bot import insert_internal_links

        html = '<article class="t4p-post"><h2>소개</h2><p>Claude Code와 AI 에이전트를 활용한다.</p></article>'
        article = {'title': 'AI 에이전트 새 글', 'tags': ['AI']}

        with patch('bots.linker_bot.DATA_DIR', published_dir.parent):
            result = insert_internal_links(html, article)

        assert 't4p-related' in result

    def test_current_article_not_self_linked(self, published_dir):
        from bots.linker_bot import insert_internal_links

        html = '<article class="t4p-post"><h2>소개</h2><p>Claude Code 설치 방법.</p></article>'
        article = {'title': 'Claude Code 설치 방법 완벽 가이드', 'tags': ['AI']}

        with patch('bots.linker_bot.DATA_DIR', published_dir.parent):
            result = insert_internal_links(html, article)

        # 현재 글 URL이 관련 글에 포함되면 안 됨
        assert result.count('claude-code') <= 1  # 자기 자신 제외

    def test_irrelevant_articles_not_linked(self, published_dir):
        from bots.linker_bot import insert_internal_links

        html = '<article class="t4p-post"><h2>소개</h2><p>파이썬 문법 기초를 알아본다.</p></article>'
        article = {'title': '파이썬 기초 문법', 'tags': ['Python']}

        with patch('bots.linker_bot.DATA_DIR', published_dir.parent):
            result = insert_internal_links(html, article)

        # 관련 없는 글이라면 ETF 링크가 삽입되면 안 됨
        assert 'etf' not in result

    def test_max_links_respected(self, published_dir):
        from bots.linker_bot import insert_internal_links

        html = '<article class="t4p-post"><h2>소개</h2><p>Claude Code와 Gemma 4와 AI 에이전트와 LLM을 사용한다.</p></article>'
        article = {'title': '새 AI 글', 'tags': ['AI', 'LLM', 'Claude']}

        with patch('bots.linker_bot.DATA_DIR', published_dir.parent):
            result = insert_internal_links(html, article, max_links=2)

        links = re.findall(r'<li><a href=', result)
        assert len(links) <= 2

    def test_no_published_articles_no_section(self, tmp_path):
        from bots.linker_bot import insert_internal_links

        empty_dir = tmp_path / 'published'
        empty_dir.mkdir()

        html = '<article class="t4p-post"><h2>소개</h2><p>내용이다.</p></article>'
        article = {'title': '새 글', 'tags': []}

        with patch('bots.linker_bot.DATA_DIR', tmp_path):
            result = insert_internal_links(html, article)

        assert 't4p-related' not in result


# ──────────────────────────────────────────────────────────────
# P3: Search Console Indexing API 실제 호출
# ──────────────────────────────────────────────────────────────

class TestSearchConsoleIndexing:
    """Google Indexing API URL_UPDATED 실제 호출 검증"""

    def test_indexing_api_called_with_url_updated(self):
        from bots.publisher_bot import submit_to_search_console

        mock_service = MagicMock()
        mock_url_notif = MagicMock()
        mock_publish = MagicMock()
        mock_publish.execute.return_value = {
            'urlNotificationMetadata': {'url': 'https://test.blogspot.com/post'}
        }
        mock_url_notif.publish.return_value = mock_publish
        mock_service.urlNotifications.return_value = mock_url_notif

        mock_creds = MagicMock()

        with patch('bots.publisher_bot.build', return_value=mock_service):
            submit_to_search_console('https://test.blogspot.com/post', mock_creds)

        mock_service.urlNotifications.assert_called_once()
        call_kwargs = mock_url_notif.publish.call_args
        body = call_kwargs.kwargs.get('body') or (call_kwargs.args[0] if call_kwargs.args else {})
        if not body:
            body = call_kwargs[1].get('body', {})
        assert body.get('type') == 'URL_UPDATED'
        assert body.get('url') == 'https://test.blogspot.com/post'

    def test_indexing_api_build_called_with_indexing_v3(self):
        from bots.publisher_bot import submit_to_search_console

        mock_service = MagicMock()
        mock_service.urlNotifications.return_value.publish.return_value.execute.return_value = {}
        mock_creds = MagicMock()

        with patch('bots.publisher_bot.build', return_value=mock_service) as mock_build:
            submit_to_search_console('https://test.blogspot.com/post', mock_creds)
            mock_build.assert_called_once_with('indexing', 'v3', credentials=mock_creds)

    def test_indexing_api_failure_does_not_raise(self):
        """API 실패해도 예외 전파 없이 경고 로그만 남김"""
        from bots.publisher_bot import submit_to_search_console

        mock_creds = MagicMock()
        with patch('bots.publisher_bot.build', side_effect=Exception('API 오류')):
            # 예외가 밖으로 나오면 안 됨
            submit_to_search_console('https://test.blogspot.com/post', mock_creds)


# ──────────────────────────────────────────────────────────────
# P4: Open Graph + Twitter Card 메타 태그
# ──────────────────────────────────────────────────────────────

class TestOpenGraphTags:
    """build_og_tags 및 build_full_html OG 태그 검증"""

    def test_og_title_present(self):
        from bots.publisher_bot import build_og_tags
        result = build_og_tags({'title': 'AI 에이전트 병렬 실행', 'meta_description': '설명'})
        assert 'og:title' in result
        assert 'AI 에이전트 병렬 실행' in result

    def test_og_description_present(self):
        from bots.publisher_bot import build_og_tags
        result = build_og_tags({'title': '제목', 'meta_description': 'AI 에이전트를 쓰면 빨라진다.'})
        assert 'og:description' in result
        assert 'AI 에이전트를 쓰면 빨라진다.' in result

    def test_og_type_article(self):
        from bots.publisher_bot import build_og_tags
        result = build_og_tags({'title': '제목', 'meta_description': '설명'})
        assert 'og:type' in result
        assert 'article' in result

    def test_og_url_included_when_present(self):
        from bots.publisher_bot import build_og_tags
        result = build_og_tags({
            'title': '제목',
            'meta_description': '설명',
            'url': 'https://thedayz9.blogspot.com/test',
        })
        assert 'og:url' in result
        assert 'thedayz9.blogspot.com' in result

    def test_twitter_card_tags_present(self):
        from bots.publisher_bot import build_og_tags
        result = build_og_tags({'title': 'AI 글', 'meta_description': '설명'})
        assert 'twitter:card' in result
        assert 'twitter:title' in result
        assert 'twitter:description' in result

    def test_og_tags_in_build_full_html(self):
        from bots.publisher_bot import build_full_html
        article = {
            'title': 'AI 에이전트',
            'meta_description': '설명입니다.',
            'disclaimer': '',
        }
        html = build_full_html(article, '<h2>소개</h2><p>본문.</p>', '')
        assert 'og:title' in html
        assert 'twitter:card' in html

    def test_og_tags_appear_before_article_body(self):
        from bots.publisher_bot import build_full_html
        article = {'title': '제목', 'meta_description': '설명', 'disclaimer': ''}
        html = build_full_html(article, '<h2>소개</h2><p>본문.</p>', '')
        og_pos = html.find('og:title')
        body_pos = html.find('<article')
        assert og_pos < body_pos, "OG 태그가 article 본문보다 앞에 있어야 한다"
