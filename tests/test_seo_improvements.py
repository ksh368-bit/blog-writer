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
        return '<h2>AI가 업무를 바꾸는 방식</h2><p>테스트다.</p><h2>사람이 적응하는 구조</h2><p>내용이다.</p><h2>직접 써본 경험의 차이</h2><p>끝이다.</p><strong>강조</strong>'

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
        # 제목 관련 고유명사·키워드 오류만 확인 (본문 키워드 밀도 QK1은 별개)
        keyword_issues = [l for l in msg.split('\n') if '제목' in l and ('고유명사' in l or '키워드' in l)]
        assert not keyword_issues, f"정상 제목에 오탐: {keyword_issues}"

    def test_title_39chars_triggers_length_warning(self):
        """39자 제목은 38자 초과 경고가 나와야 한다."""
        title_39 = 'ROE가 낮으면 내 통장 이자도 낮아진다 신한금융 10퍼센트 목표의 의'
        assert len(title_39) == 39, f"제목 길이 확인: {len(title_39)}"
        ok, msg = self._review(self._good_article(title_39))
        length_issues = [l for l in msg.split('\n') if '제목' in l and '길다' in l]
        assert length_issues, f"39자 제목인데 길이 경고 없음: {msg}"

    def test_title_38chars_passes_length(self):
        """38자 제목은 길이 경고가 없어야 한다."""
        title_38 = 'ROE가 낮으면 내 통장 이자도 낮아진다 신한금융 10퍼센트 목표의 '
        assert len(title_38) == 38, f"제목 길이 확인: {len(title_38)}"
        ok, msg = self._review(self._good_article(title_38))
        length_issues = [l for l in msg.split('\n') if '제목' in l and '길다' in l]
        assert not length_issues, f"38자 제목인데 길이 경고 발생: {msg}"

    def test_qt1_feedback_includes_topic_context(self):
        """QT1 실패 피드백에 글감 컨텍스트가 포함되어 LLM이 어떤 키워드로 제목을 고쳐야 할지 알 수 있어야 한다."""
        article = self._good_article(
            title='Blank. 정답이 자꾸 같다면',
            topic="Show GN: 'Blank.' 업데이트 - Gemma 4 전환, 중복 정답 버그 수정",
        )
        ok, msg = self._review(article)
        qt1_issues = [l for l in msg.split('\n') if '클릭 유발 패턴' in l]
        assert qt1_issues, f"QT1 경고가 없음: {msg}"
        issue_line = qt1_issues[0]
        # 인용된 제목 뒤 조언 부분에 글감 관련 정보('글감:')가 있어야 LLM이 구체적으로 수정 가능
        advice_part = issue_line.split('→', 1)[-1] if '→' in issue_line else issue_line
        assert '글감' in advice_part, (
            f"QT1 피드백 조언 부분에 '글감' 컨텍스트 없음: {advice_part!r}"
        )


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


# ─── P1: 내부 링크 폴백 ─────────────────────────────────────────

class TestInternalLinkFallback:
    """key_points 없는 구버전 JSON — 임계값 0.40에서 링크 생성.

    테마 매칭(+0.20 보너스)을 피하기 위해 어떤 테마 클러스터에도 없는
    '소비·패턴·교육·복지' 같은 중립 단어를 사용한다.
    """

    def test_no_key_points_title_only_match_scores_above_040(self):
        """key_points·tags·theme 모두 없을 때 title 단어 2개 겹침 → 0.40 이상.
        현재(title weight 0.15, cap 0.30): 2단어×0.15 = 0.30 → 실패 (RED)
        수정(no-kp 시 weight 0.30, cap 0.45): 0.45 → 성공 (GREEN)
        """
        from bots.linker_bot import _score_relevance
        # '소비', '패턴' — 어떤 테마 클러스터에도 없는 중립 단어
        candidate = {
            'title': '소비 패턴 변화 연구',  # "소비", "패턴" 2개 매칭 예상
            # tags 없음, key_points 없음 (구버전 포맷)
        }
        score = _score_relevance(candidate, '소비 패턴 분석 결과', '소비 패턴 변화')
        assert score >= 0.40, f"key_points·tags·theme 없는 글 점수 {score:.2f} — 0.40 이상이어야 한다"

    def test_insert_internal_links_generates_link_for_no_key_points_article(self):
        """threshold 0.40으로 변경 후, key_points 없는 구버전 JSON도 관련 글 링크 생성.
        '소비·패턴'은 테마 클러스터에 없어서 테마 보너스(+0.20)가 붙지 않는다.
        현재 score = 0.30 < 0.50 threshold → 링크 미생성 (RED)
        수정 후 score = 0.45 >= 0.40 threshold → 링크 생성 (GREEN)
        """
        from bots.linker_bot import insert_internal_links
        published_record = {
            'title': '소비 패턴 변화 연구',
            'url': 'https://thedayz9.blogspot.com/consume',
            # tags, key_points 없음 (구버전)
        }
        article = {
            'title': '소비 패턴 분석 결과',
            'tags': [],
        }
        html_in = '<article><h2>분석</h2><p>소비 패턴 변화 추적</p></article>'
        with patch('bots.linker_bot._load_published_index', return_value=[published_record]):
            result = insert_internal_links(html_in, article)
        assert '관련 글' in result or 'thedayz9.blogspot.com/consume' in result, \
            "key_points 없는 글인데 관련 글 링크 미생성 — threshold가 아직 0.50"

    def test_unrelated_article_stays_below_threshold(self):
        """관련 없는 글은 여전히 0.40 미만이어야 한다 (false positive 방지)."""
        from bots.linker_bot import _score_relevance
        candidate = {
            'title': '강남 아파트 시세 전망',
            'tags': ['부동산', '아파트'],
        }
        score = _score_relevance(candidate, 'Claude Code AI 코딩 자동화', 'AI 코드 자동화')
        assert score < 0.40, f"관련 없는 글 점수 {score:.2f} — 0.40 미만이어야 한다"


# ─── P2: 제목 클릭 패턴 (QT1 + QT2) ─────────────────────────────

class TestTitleClickPattern:
    """제목에 클릭 유발 패턴 및 키워드 위치 검사"""

    @staticmethod
    def _review(article):
        import re
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s+', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    @staticmethod
    def _make_article(title, topic='AI 업무 자동화'):
        return {
            'title': title,
            'topic': topic,
            'body': (
                '<h2>첫 번째 섹션</h2><p>본문 내용이다.</p><p>두 번째 문단이다.</p>'
                '<h2>두 번째 섹션</h2><p>세 번째 문단이다.</p><p>네 번째 문단이다.</p>'
                '<h2>세 번째 섹션</h2><p>다섯 번째 문단이다.</p><p>여섯 번째 문단이다.</p>'
            ),
            'meta': '요약 설명',
            'corner': '쉬운세상',
        }

    def test_no_click_pattern_title_warns(self):
        """클릭 유발 패턴 없는 제목 → QT1 경고 발생"""
        article = self._make_article('AI의 미래와 인간 사회의 변화')
        _, msg = self._review(article)
        assert '클릭 유발 패턴 없음' in msg, f"QT1 경고 없음: {msg}"

    def test_loss_frame_title_passes(self):
        """손실 프레임 제목 → QT1 통과"""
        article = self._make_article('이거 안 하면 AI 경쟁에서 뒤처진다')
        _, msg = self._review(article)
        assert '클릭 유발 패턴 없음' not in msg, f"손실 프레임인데 경고 발생: {msg}"

    def test_number_title_passes(self):
        """숫자 있는 제목 → QT1 통과"""
        article = self._make_article('AI 업무 자동화 5가지 핵심 방법')
        _, msg = self._review(article)
        assert '클릭 유발 패턴 없음' not in msg, f"숫자 제목인데 경고 발생: {msg}"

    def test_how_to_title_passes(self):
        """방법 있는 제목 → QT1 통과"""
        article = self._make_article('AI로 업무 자동화하는 방법')
        _, msg = self._review(article)
        assert '클릭 유발 패턴 없음' not in msg, f"방법 제목인데 경고 발생: {msg}"

    def test_keyword_at_end_warns(self):
        """핵심 키워드가 제목 15자 이후에만 있을 때 → QT2 경고"""
        # 'AI 업무 자동화'가 title 15번째 자 이후에 나옴
        article = self._make_article('이걸 정말로 모르면 엄청 손해 보는 AI 업무 자동화', topic='AI 업무 자동화')
        _, msg = self._review(article)
        assert '앞으로 이동' in msg or '스니펫' in msg, f"QT2 키워드 위치 경고 없음: {msg}"

    def test_keyword_at_start_passes_qt2(self):
        """핵심 키워드가 제목 앞에 있을 때 → QT2 통과"""
        article = self._make_article('AI 업무 자동화 안 하면 3배 손해', topic='AI 업무 자동화')
        _, msg = self._review(article)
        assert '앞으로 이동' not in msg and '스니펫' not in msg, f"앞에 있는데 QT2 경고 발생: {msg}"


# ─── P5: H2 추상어 경고 (QC2) ───────────────────────────────────

class TestH2AbstractWarning:
    """H2에 추상적 단어 사용 시 경고"""

    @staticmethod
    def _review(article):
        import re
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s+', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _make_article(self, h2_titles):
        sections = ''
        for h2 in h2_titles:
            sections += f'<h2>{h2}</h2><p>본문 내용이다.</p><p>두 번째 문단이다.</p>'
        return {
            'title': 'AI 업무 자동화 5가지 방법',
            'topic': 'AI',
            'body': sections,
            'meta': '요약',
            'corner': '쉬운세상',
        }

    def test_abstract_h2_소개_warns(self):
        article = self._make_article(['소개', 'AI 활용 구체적 방법', '정리'])
        _, msg = self._review(article)
        assert '추상적인 H2' in msg, f"'소개' H2인데 경고 없음: {msg}"

    def test_abstract_h2_마무리_warns(self):
        article = self._make_article(['AI란 무엇인가', '활용 전략', '마무리'])
        _, msg = self._review(article)
        assert '추상적인 H2' in msg, f"'마무리' H2인데 경고 없음: {msg}"

    def test_concrete_h2_passes(self):
        article = self._make_article([
            'AI가 업무를 바꾸는 방식',
            'Claude Code 설치하는 3단계',
            '사람이 적응하는 구조',
        ])
        _, msg = self._review(article)
        assert '추상적인 H2' not in msg, f"구체적 H2인데 경고 발생: {msg}"

    def test_abstract_h2_배경_warns(self):
        article = self._make_article(['배경', '핵심 분석', '결론'])
        _, msg = self._review(article)
        assert '추상적인 H2' in msg, f"'배경' H2인데 경고 없음: {msg}"


# ─── P6: 본문 어절 수 상향 (QW1) ───────────────────────────────

class TestWordCountMinimum:
    """본문 최소 500어절 기준 검사"""

    @staticmethod
    def _check_quality(article):
        from bots.writer.article_reviewer import ArticleReviewer
        reviewer = ArticleReviewer()
        return reviewer.check_quality(article)

    def _make_article_with_words(self, word_count: int) -> dict:
        word = '단어'
        body_words = ' '.join([word] * word_count)
        body = f'<h2>섹션</h2><p>{body_words}</p>'
        return {
            'title': 'AI 업무 자동화 5가지 핵심 방법',
            'meta': '요약',
            'body': body,
            'key_points': ['핵심 포인트 1', '핵심 포인트 2'],
            'sources': [{'url': 'https://example.com', 'title': '출처', 'published_at': '2026-04-01'}],
        }

    def test_400_words_fails(self):
        """400어절 → 500 미만이므로 품질 검사 실패"""
        article = self._make_article_with_words(400)
        ok, msg = self._check_quality(article)
        assert not ok, "400어절인데 통과됨"
        assert '어절' in msg or '단어' in msg or '길이' in msg, f"어절 수 언급 없음: {msg}"

    def test_500_words_passes(self):
        """500어절 → 통과"""
        article = self._make_article_with_words(500)
        ok, _ = self._check_quality(article)
        assert ok, "500어절인데 실패함"


class TestExtractMetaFromBody:
    """publisher_bot._extract_meta_from_body — H2 텍스트 혼입 방지"""

    @staticmethod
    def _extract(body, title=''):
        from bots.publisher_bot import _extract_meta_from_body
        return _extract_meta_from_body(body, title)

    def test_h2_text_not_included_in_meta(self):
        # H2 텍스트가 meta에 포함되면 안 됨 — 첫 <p>만 추출해야 한다
        body = (
            '<h2>보안 검사 도구도 놓치는 것들</h2>\n'
            '<p>코드를 분석해서 보안 허점을 찾는 일은 프로그래머들이 해온 작업이다.</p>'
        )
        result = self._extract(body)
        assert '보안 검사 도구도 놓치는 것들' not in result, \
            f"H2 텍스트가 meta에 포함됨: '{result}'"
        assert '코드를 분석해서' in result

    def test_first_paragraph_extracted(self):
        body = (
            '<h2>섹션 제목</h2>'
            '<p>첫 번째 단락 내용이 여기 있고 독자가 읽으면 바로 이해된다.</p>'
            '<p>두 번째 단락은 포함되면 안 된다.</p>'
        )
        result = self._extract(body)
        assert '첫 번째 단락 내용이 여기 있고' in result
        assert '두 번째 단락은 포함되면 안 된다' not in result

    def test_placeholder_meta_replaced_with_first_p(self):
        # sanitize_article_for_publish: placeholder 감지 → 첫 <p>로 대체
        from bots.publisher_bot import sanitize_article_for_publish
        article = {
            'title': 'Claude로 코드를 분석하면 취약점을 찾아낸다',
            'meta': '핵심 문구부터 보면 뜻이 바로 잡힌다.',
            'body': (
                '<h2>보안 검사 도구도 놓치는 것들</h2>\n'
                '<p>수십 년간 발견되지 않은 취약점을 AI가 찾아낸다.</p>'
            ),
            'tags': [],
        }
        result = sanitize_article_for_publish(article)
        assert '보안 검사 도구도 놓치는 것들' not in result['meta'], \
            f"H2 텍스트가 meta에 포함됨: '{result['meta']}'"
        assert '수십 년간 발견되지 않은 취약점' in result['meta']


# ──────────────────────────────────────────────────────────────
# quality_score 필터 제거: 73점 글감도 작성 시도해야 한다
# ──────────────────────────────────────────────────────────────

class TestRankPendingTopicsNoQualityFilter:
    """_rank_pending_topics()는 quality_score 기반으로 글감을 건너뛰면 안 된다.
    글 품질은 작성 프롬프트와 검수 루프로 높여야지, 글감을 아예 제외해서는 안 된다."""

    def _make_topic_file(self, tmp_path: Path, name: str, quality_score: float) -> Path:
        f = tmp_path / name
        f.write_text(
            json.dumps({
                'topic': f'테스트 주제 {name}',
                'description': '테스트 설명',
                'quality_score': quality_score,
                'tags': [],
            }, ensure_ascii=False),
            encoding='utf-8',
        )
        return f

    def test_73_point_topic_is_not_skipped(self, tmp_path):
        """quality_score 73인 글감은 스킵되지 않고 ranked 목록에 포함돼야 한다."""
        from bots.writer_bot import _rank_pending_topics
        originals_dir = tmp_path / 'originals'
        originals_dir.mkdir()
        topics_dir = tmp_path / 'topics'
        topics_dir.mkdir()

        topic_file = self._make_topic_file(topics_dir, '20260409_test73.json', 73)
        ranked = _rank_pending_topics([topic_file], originals_dir)
        assert len(ranked) == 1, f"73점 글감이 스킵됨 — ranked={ranked}"

    def test_60_point_topic_is_not_skipped(self, tmp_path):
        """quality_score 60인 글감도 스킵되지 않아야 한다."""
        from bots.writer_bot import _rank_pending_topics
        originals_dir = tmp_path / 'originals'
        originals_dir.mkdir()
        topics_dir = tmp_path / 'topics'
        topics_dir.mkdir()

        topic_file = self._make_topic_file(topics_dir, '20260409_test60.json', 60)
        ranked = _rank_pending_topics([topic_file], originals_dir)
        assert len(ranked) == 1, f"60점 글감이 스킵됨 — ranked={ranked}"

    def test_zero_quality_score_topic_is_included(self, tmp_path):
        """quality_score가 0(없음)인 글감도 포함돼야 한다."""
        from bots.writer_bot import _rank_pending_topics
        originals_dir = tmp_path / 'originals'
        originals_dir.mkdir()
        topics_dir = tmp_path / 'topics'
        topics_dir.mkdir()

        topic_file = self._make_topic_file(topics_dir, '20260409_test0.json', 0)
        ranked = _rank_pending_topics([topic_file], originals_dir)
        assert len(ranked) == 1, f"quality_score=0 글감이 스킵됨 — ranked={ranked}"


# ──────────────────────────────────────────────────────────────
# 품질 검수 통과 시 article quality_score >= 75 보장
# ──────────────────────────────────────────────────────────────

class TestArticleQualityScoreAfterWriting:
    """write_article()이 완료된 뒤 article의 quality_score는 최소 75 이상이어야 한다.
    topic의 research score가 73이어도, 글 품질 검수를 통과했으면 발행 가능해야 한다."""

    def test_write_article_sets_quality_score_at_least_75(self, tmp_path):
        """topic quality_score=73 → write_article 완료 후 article.quality_score >= 75"""
        import json
        from unittest.mock import patch, MagicMock
        from pathlib import Path

        topic_data = {
            'topic': '신한금융 ROE 경영 전략',
            'description': 'ROE 목표 10%',
            'quality_score': 73,
            'corner': '쉬운세상',
            'sources': [
                {'url': 'https://example.com/shinhan', 'title': '신한금융 보고서', 'date': '2026-04-09'}
            ],
        }
        output_path = tmp_path / '20260409_test.json'

        dummy_article_output = """---TITLE---
ROE를 보면 신한금융 배당이 달라지는 이유

---META---
ROE를 보면 어떤 금융주가 배당을 더 줄지 바로 알 수 있다.

---SLUG---
shinhan-roe-dividend

---TAGS---
금융, ROE, 신한

---CORNER---
쉬운세상

---BODY---
<h2>ROE 뜻과 배당의 연결 고리</h2>
<p>통장 이자가 작년보다 2만 원 더 들어온 날, ROE(자기자본이익률)가 오른 은행이 어딘지 찾아보게 됐다. 신한금융의 ROE는 2024년 8.7%였다.</p>
<p>ROE가 높은 금융사일수록 배당 여력이 커진다. 2024년 신한금융 배당 성향은 35%였다.</p>
<h2>10% 목표가 의미하는 것</h2>
<p>ROE 10% 달성이면 자기자본 100원으로 10원을 버는 구조가 된다. 주식 앱에서 ROE 항목을 찾아보면 경쟁사 대비 위치가 보인다.</p>
<p>월급날 적금 금리를 비교할 때 ROE가 높은 곳이 금리 경쟁력도 높은 경향이 있다.</p>
<h2>투자자가 볼 체크리스트</h2>
<p>ROE 8% 이상이면 배당 여력이 있다는 신호다. 지금 주식 앱을 열어서 ROE 항목부터 확인해보면 된다.</p>
<p>ROE가 높은 종목부터 보면 배당 선택이 쉬워진다.</p>

---KEY_POINTS---
- ROE 8% 이상이면 배당 여력이 있다
- 신한금융 2024년 ROE는 8.7%였다
- 주식 앱에서 ROE를 찾아보면 된다

---COUPANG_KEYWORDS---
금융

---SOURCES---
https://example.com/shinhan | 신한금융 보고서 | 2026-04-09

---DISCLAIMER---
"""

        # generate_article 전체를 mock — 품질 검수 통과 후 반환되는 완성 원고 시뮬레이션
        good_article = {
            'title': 'ROE를 보면 신한금융 배당이 달라지는 이유',
            'meta': 'ROE를 보면 어떤 금융주가 배당을 더 줄지 바로 알 수 있다.',
            'slug': 'shinhan-roe-dividend',
            'tags': ['금융', 'ROE', '신한'],
            'corner': '쉬운세상',
            'body': dummy_article_output,
            'key_points': ['ROE 8% 이상이면 배당 여력이 있다'],
            'sources': [{'url': 'https://example.com/shinhan', 'title': '신한금융 보고서', 'date': '2026-04-09'}],
            'disclaimer': '',
        }

        from bots.writer_bot import write_article
        with patch('bots.writer_bot.generate_article', return_value=good_article):
            article = write_article(topic_data, output_path)

        assert article.get('quality_score', 0) >= 75, (
            f"품질 검수 통과했는데 quality_score={article.get('quality_score')} — "
            f"73점 topic이어도 발행 가능하도록 75 이상이어야 한다."
        )


# ──────────────────────────────────────────────────────────────
# 재발행 경로 제목 검수 (재발방지)
# ──────────────────────────────────────────────────────────────

class TestRepublishTitleReview:
    """_title_has_click_pattern() — 재발행 필터에서 사용하는 제목 패턴 검사."""

    def test_no_pattern_title_fails(self):
        """클릭 패턴 없는 제목 → False"""
        from bots.pipeline import _title_has_click_pattern
        assert not _title_has_click_pattern('신한금융의 ROE 10% 목표')

    def test_loss_frame_passes(self):
        """손실 프레임 → True"""
        from bots.pipeline import _title_has_click_pattern
        assert _title_has_click_pattern('ROE가 낮으면 내 통장 이자도 낮아진다 — 신한금융 10% 목표의 의미')

    def test_method_title_passes(self):
        """방법 가이드 → True"""
        from bots.pipeline import _title_has_click_pattern
        assert _title_has_click_pattern('병원에서 언어 장벽 없애는 방법 — 외국인 의료 가이드')


# ──────────────────────────────────────────────────────────────
# _write_quality_passed 플래그 (재발방지 핵심)
# ──────────────────────────────────────────────────────────────

class TestWriteQualityPassedFlag:
    """generate_article()이 반환하는 article dict에 _write_quality_passed 플래그가 있어야 한다.
    - 모든 검수를 통과한 경우: True
    - force-publish(타임아웃/예산초과/최대재시도)인 경우: False 또는 부재
    write_article()이 이 플래그를 originals JSON에 보존해야 한다."""

    def _make_good_article(self):
        return {
            'title': 'ROE가 낮으면 내 통장 이자도 낮아진다',
            'meta': '신한금융 ROE 10% 목표 설명',
            'slug': 'roe-test',
            'tags': ['금융'],
            'corner': '쉬운세상',
            'body': '<h2>ROE 연결 고리</h2><p>통장 이자가 오른다.</p>',
            'key_points': ['ROE 8% 이상'],
            'sources': [],
            'disclaimer': '투자 판단은 개인 책임입니다.',
        }

    def test_genuine_pass_sets_flag_true(self, tmp_path):
        """모든 검수 통과 → write_article 결과에 _write_quality_passed=True"""
        from unittest.mock import patch
        from bots.writer_bot import write_article

        good = self._make_good_article()
        # _write_quality_passed=True인 article을 generate_article이 반환하는 경우 시뮬레이션
        good['_write_quality_passed'] = True

        with patch('bots.writer_bot.generate_article', return_value=good):
            result = write_article({'topic': 'test', 'quality_score': 80}, tmp_path / 't.json')

        assert result.get('_write_quality_passed') is True, (
            f"generate_article이 True를 반환했는데 write_article이 플래그를 지움: {result.get('_write_quality_passed')}"
        )

    def test_force_publish_sets_flag_false(self, tmp_path):
        """force-publish 경로 → write_article 결과에 _write_quality_passed=False (또는 부재)"""
        from unittest.mock import patch
        from bots.writer_bot import write_article

        forced = self._make_good_article()
        # force-publish된 article에는 플래그가 없거나 False
        forced['_write_quality_passed'] = False

        with patch('bots.writer_bot.generate_article', return_value=forced):
            result = write_article({'topic': 'test', 'quality_score': 73}, tmp_path / 't.json')

        assert result.get('_write_quality_passed') is not True, (
            f"force-publish인데 _write_quality_passed=True로 설정됨"
        )

    def test_flag_persisted_in_json(self, tmp_path):
        """_write_quality_passed 플래그가 originals JSON 파일에 저장돼야 한다."""
        import json
        from unittest.mock import patch
        from bots.writer_bot import write_article

        good = self._make_good_article()
        good['_write_quality_passed'] = True

        out = tmp_path / 'test.json'
        with patch('bots.writer_bot.generate_article', return_value=good):
            write_article({'topic': 'test', 'quality_score': 80}, out)

        saved = json.loads(out.read_text())
        assert '_write_quality_passed' in saved, "JSON에 플래그가 저장되지 않음"
        assert saved['_write_quality_passed'] is True


# ──────────────────────────────────────────────────────────────
# 재발행 경로 발행 차단 (근본 수정)
# ──────────────────────────────────────────────────────────────

class TestRepublishBlocksFailedArticles:
    """_write_quality_passed=False 인 원고는 재발행 경로에서 발행되면 안 된다.
    presentation_review + title_actionability_review 재실행 후:
    - 통과 시 발행 허용
    - 실패 시 pending_review로 이동, 발행 목록에서 제외"""

    def _force_published_article(self, title='신한금융의 ROE 10% 목표') -> dict:
        return {
            'title': title,
            'slug': 'roe-test',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'meta': '설명',
            'corner': '쉬운세상',
            'sources': [{'url': 'https://a.com', 'title': '출처', 'date': '2026-04-09'}],
            'quality_score': 75.0,
            '_write_quality_passed': False,  # force-publish
        }

    def _genuine_article(self, title='ROE가 낮으면 내 통장 이자도 낮아진다') -> dict:
        return {
            'title': title,
            'slug': 'roe-good',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'meta': '설명',
            'corner': '쉬운세상',
            'sources': [{'url': 'https://a.com', 'title': '출처', 'date': '2026-04-09'}],
            'quality_score': 80.0,
            '_write_quality_passed': True,
        }

    def test_force_published_article_filtered_out(self):
        """_write_quality_passed=False이고 제목 검수 실패 → 재발행 목록에서 제외"""
        from bots.pipeline import _filter_republishable
        articles = [self._force_published_article()]
        publishable, blocked = _filter_republishable(articles)
        assert len(publishable) == 0, f"제목 검수 실패 글이 발행 목록에 포함됨: {publishable}"
        assert len(blocked) == 1, f"차단 목록에 있어야 함: {blocked}"

    def test_genuine_article_passes_through(self):
        """_write_quality_passed=True → 재발행 목록에 포함"""
        from bots.pipeline import _filter_republishable
        articles = [self._genuine_article()]
        publishable, blocked = _filter_republishable(articles)
        assert len(publishable) == 1
        assert len(blocked) == 0

    def test_force_published_but_good_title_passes(self):
        """_write_quality_passed=False이지만 제목 검수 통과 → 재발행 허용"""
        from bots.pipeline import _filter_republishable
        # force-publish됐지만 제목이 좋은 경우
        art = self._force_published_article(
            title='CEO가 주식 팔 때 따라 팔면 손해 — 5% 기준으로 판단하는 법'
        )
        publishable, blocked = _filter_republishable([art])
        assert len(publishable) == 1, f"제목 검수 통과인데 차단됨: {blocked}"

    def test_missing_flag_triggers_review(self):
        """_write_quality_passed 플래그 없는 구버전 원고도 제목 검수 실행"""
        from bots.pipeline import _filter_republishable
        art = {
            'title': 'CEO가 주식을 팔 때',  # 구버전, 플래그 없음, 제목 나쁨
            'slug': 'ceo-old',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'meta': '설명',
            'corner': '쉬운세상',
            'sources': [{'url': 'https://a.com', 'title': '출처', 'date': '2026-04-09'}],
            'quality_score': 75.0,
            # _write_quality_passed 키 없음
        }
        publishable, blocked = _filter_republishable([art])
        assert len(publishable) == 0, "구버전 글도 제목 검수 실패 시 차단해야 함"


# ──────────────────────────────────────────────────────────────
# Publisher check_safety: 제목 클릭 패턴 게이트
# ──────────────────────────────────────────────────────────────

class TestPublisherTitleGate:
    """check_safety()가 클릭 유발 패턴 없는 제목을 수동 검토로 보낸다."""

    def _safety_cfg(self):
        return {
            'always_manual_review': ['팩트체크'],
            'crypto_keywords': [],
            'criticism_keywords': [],
            'investment_keywords': [],
            'legal_keywords': [],
            'criticism_phrases': [],
            'min_sources_required': 2,
            'min_quality_score_for_auto': 75,
        }

    def _good_article(self, title: str) -> dict:
        return {
            'title': title,
            'corner': '쉬운세상',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'sources': [
                {'url': 'https://a.com', 'title': '출처1', 'date': '2026-04-09'},
                {'url': 'https://b.com', 'title': '출처2', 'date': '2026-04-09'},
            ],
            'quality_score': 80,
        }

    def test_bad_title_triggers_manual_review(self):
        """클릭 유발 패턴 없는 제목 → needs_review=True"""
        from bots.publisher_bot import check_safety
        article = self._good_article('신한금융의 ROE 목표와 배당 현황')  # 패턴 없는 순수 설명체 제목
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is True, f"나쁜 제목이 자동 발행됨: reason={reason}"
        assert '제목' in reason, f"이유에 '제목' 없음: {reason}"

    def test_loss_frame_title_passes(self):
        """손실 프레임 제목 → 자동 발행 허용"""
        from bots.publisher_bot import check_safety
        article = self._good_article('ROE 모르면 배당주 투자에서 손해 보는 이유')
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is False, f"좋은 제목이 차단됨: reason={reason}"

    def test_number_title_passes(self):
        """숫자 포함 제목 → 자동 발행 허용"""
        from bots.publisher_bot import check_safety
        article = self._good_article('배당주 고르는 3가지 기준 — ROE·배당성향·이자보상배율')
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is False, f"좋은 제목이 차단됨: reason={reason}"

    def test_howto_title_passes(self):
        """방법 제목 → 자동 발행 허용"""
        from bots.publisher_bot import check_safety
        article = self._good_article('병원에서 언어 장벽 없애는 방법 — 외국인 의료 가이드')
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is False, f"좋은 제목이 차단됨: reason={reason}"

    def test_existing_safety_checks_still_work(self):
        """기존 quality_score 게이트는 유지됨"""
        from bots.publisher_bot import check_safety
        article = self._good_article('배당주 고르는 3가지 기준')
        article['quality_score'] = 70  # 기준 미달
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is True
        assert '품질 점수' in reason


# ──────────────────────────────────────────────────────────────
# QK1: 키워드 밀도 — topic 핵심어 과반이 본문에 2회+ 등장해야 함
# ──────────────────────────────────────────────────────────────

class TestKeywordDensity:
    """topic 핵심 키워드 과반이 본문에 2회 미만이면 QK1 경고가 나와야 한다."""

    def _review(self, article):
        from bots.prompt_layer.writer_review import presentation_review
        import re
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s+', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _base_article(self, topic, body):
        return {
            'title': '신한금융 ROE 10% 목표 달성하면 배당이 3배 된다',
            'meta': '신한금융 ROE 목표.',
            'topic': topic,
            'corner': '쉬운세상',
            'body': body,
        }

    def _good_body(self, extra=''):
        """QS1·Q5·Q6 등 다른 검사를 통과할 만큼 충분한 기본 본문."""
        return (
            '<h2>ROE란 무엇인가</h2>'
            '<p>ROE는 자기자본이익률이다. 신한금융은 2024년 ROE 10% 목표를 발표했다. '
            '신한금융이 이 목표를 달성하면 배당도 늘어난다.</p>'
            '<p>ROE가 높아지면 주주 환원이 강화된다. '
            '신한금융의 현재 ROE는 8.5% 수준으로 목표까지 1.5%p 격차가 있다.</p>'
            '<p>이 격차를 줄이는 방법은 이익을 늘리거나 자본을 줄이는 것이다.</p>'
            '<h2>배당 확대 전망</h2>'
            '<p>신한금융은 올해 배당성향을 30%에서 35%로 올릴 계획이다. '
            'ROE 목표 달성 시 배당금은 주당 3,000원을 넘길 수 있다.</p>'
            '<p>배당 확대는 주가에도 긍정적 신호다. '
            '2023년 대비 배당 수익률이 2배 이상 높아질 가능성이 있다.</p>'
            '<p>신한금융 주주라면 ROE 개선 속도를 분기별로 확인해야 한다.</p>'
            '<h2>투자 판단 기준</h2>'
            '<p>ROE 10% 달성 여부가 배당 투자자에게 핵심 지표다. '
            '금리가 내려가는 환경에서 ROE 개선은 더욱 중요해진다.</p>'
            '<p>신한금융 2분기 실적 발표 시점이 중요한 분기점이 될 것이다.</p>'
            '<p>투자 전에 ROE 추이와 배당 정책을 반드시 확인해라.</p>'
            f'<ul><li>ROE 목표: 10%</li><li>현재: 8.5%</li></ul>{extra}'
            '<strong>신한금융</strong><strong>ROE</strong>'
        )

    def test_both_keywords_missing_triggers_warning(self):
        """topic="신한금융 ROE", 본문에 두 키워드 모두 0회 → QK1 경고 (과반 미달)"""
        body = (
            '<h2>은행주 배당 분석</h2>'
            '<p>금융주 배당이 늘고 있다. 은행 업종 전체가 주주 환원을 강화하는 추세다. '
            '투자자들은 배당 수익률을 기준으로 종목을 선별한다.</p>'
            '<p>올해 배당성향은 평균 30%에서 35%로 높아질 전망이다. '
            '주당 배당금도 작년 대비 15% 이상 증가할 것으로 예상된다.</p>'
            '<p>배당 투자는 장기 관점에서 접근해야 한다.</p>'
            '<h2>배당주 선별 기준</h2>'
            '<p>배당 수익률이 3% 이상인 종목을 우선 고려해야 한다. '
            '배당 성장률도 함께 확인하는 것이 중요하다. '
            '최근 5년 배당 이력을 검토하는 것이 기본이다.</p>'
            '<p>배당 컷 이력이 있는 종목은 주의가 필요하다. '
            '금리 환경 변화에 민감한 업종은 배당 안정성이 낮다.</p>'
            '<p>배당 재투자 전략이 장기 복리 수익을 극대화한다.</p>'
            '<h2>결론</h2>'
            '<p>배당주 투자는 장기 관점으로 접근해야 한다. '
            '안정적 배당 기업을 선별하는 기준을 갖추어야 한다.</p>'
            '<p>배당 수익률 3% 이상, 배당 성장 5년 이상이 기본 기준이다.</p>'
            '<p>포트폴리오 다각화도 잊지 마라.</p>'
            '<ul><li>배당 수익률 3%+</li><li>5년 이상 배당 이력</li></ul>'
            '<strong>배당</strong>'
        )
        article = self._base_article('신한금융 ROE', body)
        ok, msg = self._review(article)
        assert '1회 이하 등장' in msg, f"QK1 경고 없음: {msg}"

    def test_majority_keywords_present_passes(self):
        """topic="신한금융 ROE", 본문에 '신한금융' 3회·'ROE' 3회 → 과반 달성 → 통과"""
        article = self._base_article('신한금융 ROE', self._good_body())
        ok, msg = self._review(article)
        assert '1회 이하 등장' not in msg, f"QK1 오탐: {msg}"

    def test_no_topic_skips_check(self):
        """topic 없음 → QK1 검사 스킵 (경고 없음)"""
        article = self._base_article('', self._good_body())
        ok, msg = self._review(article)
        assert '1회 이하 등장' not in msg, f"topic 없는데 QK1 경고 발생: {msg}"

    def test_stopword_only_topic_no_false_positive(self):
        """topic에 불용어만 있으면 키워드 추출 0개 → 경고 없음"""
        article = self._base_article('현황 전망 이유 방법', self._good_body())
        ok, msg = self._review(article)
        assert '1회 이하 등장' not in msg, f"불용어 topic에서 QK1 오탐: {msg}"


# ──────────────────────────────────────────────────────────────
# QT6: Freshness 신호 — 시의성 주제 제목에 현재 연도 포함
# ──────────────────────────────────────────────────────────────

class TestFreshnessSignal:
    """시의성 주제(금리·환율 등)인데 제목에 연도 없으면 QT6 경고가 나와야 한다."""

    import datetime as _dt
    _YEAR = str(_dt.datetime.now().year)

    def _review(self, article):
        from bots.prompt_layer.writer_review import presentation_review
        import re
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s+', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _base_article(self, title, topic):
        return {
            'title': title,
            'meta': f'{title}.',
            'topic': topic,
            'corner': '쉬운세상',
            'body': (
                '<h2>금리 인상 원인</h2>'
                '<p>한국은행이 기준금리를 0.25%p 인상했다. 대출 이자가 즉시 오른다. '
                '변동금리 대출자는 월 3만 원 이상 부담이 늘어난다.</p>'
                '<p>금리 인상의 파급효과는 3개월 내에 체감된다. '
                '전세 대출 이자도 연간 120만 원 증가한다.</p>'
                '<p>금리 상승기에는 고정금리 전환이 유리하다.</p>'
                '<h2>대출 전략</h2>'
                '<p>금리가 오를 때는 변동금리를 고정금리로 전환해야 한다. '
                '전환 비용은 평균 50만 원이지만 장기적으로 이득이다.</p>'
                '<p>은행 5곳 이상 비교하면 금리 차이가 0.3%p 이상 난다.</p>'
                '<p>대출 만기 구조도 함께 점검해야 한다.</p>'
                '<h2>지금 해야 할 것</h2>'
                '<p>금리 인상 전에 고정금리로 전환하는 것이 핵심이다. '
                '3개월 안에 결정해야 한다.</p>'
                '<p>주거래 은행보다 인터넷 은행이 금리가 낮을 수 있다.</p>'
                '<p>금리 비교 앱을 활용하면 최저 금리를 쉽게 찾을 수 있다.</p>'
                '<ul><li>변동→고정 전환</li><li>5개 은행 비교</li></ul>'
                '<strong>금리</strong>'
            ),
        }

    def test_timely_topic_no_year_triggers_warning(self):
        """시의성 주제(topic에 '금리'), 제목에 연도 없음 → QT6 경고 + 현재 연도 포함"""
        import datetime
        article = self._base_article(
            title='금리 인상 전에 고정금리로 바꿔야 하는 이유',
            topic='금리 인상 대출 전략',
        )
        ok, msg = self._review(article)
        assert '연도' in msg, f"QT6 경고 없음: {msg}"
        current_year = str(datetime.datetime.now().year)
        assert current_year in msg, f"메시지에 현재 연도({current_year}) 없음: {msg}"

    def test_timely_topic_with_year_passes(self):
        """시의성 주제, 제목에 현재 연도 포함 → QT6 통과"""
        import datetime
        year = datetime.datetime.now().year
        article = self._base_article(
            title=f'{year}년 금리 인상 전에 고정금리로 바꿔야 하는 이유',
            topic='금리 인상 대출 전략',
        )
        ok, msg = self._review(article)
        assert '연도' not in msg, f"QT6 오탐: {msg}"

    def test_non_timely_topic_skips_check(self):
        """시의성 없는 주제(건강 관리) → QT6 검사 스킵"""
        article = self._base_article(
            title='건강 관리 방법으로 면역력을 높이는 3가지',
            topic='건강 관리 방법',
        )
        ok, msg = self._review(article)
        assert '연도' not in msg, f"비시의성 주제에서 QT6 오탐: {msg}"

    def test_message_uses_dynamic_year_not_hardcoded(self):
        """경고 메시지에 하드코딩된 연도(2025·2026 등) 대신 datetime으로 생성된 값만 있어야 한다."""
        import datetime
        article = self._base_article(
            title='환율 상승기에 해외여행 비용 줄이는 방법',
            topic='환율 상승 해외 여행',
        )
        ok, msg = self._review(article)
        current_year = str(datetime.datetime.now().year)
        if '연도' in msg:
            # 메시지에 연도가 있으면 현재 연도여야 함
            assert current_year in msg, f"하드코딩 연도 의심 — 현재 연도({current_year})가 없음: {msg}"


# ──────────────────────────────────────────────────────────────
# QP1: 플레이스홀더 앱명 감지 (e.g. "Blank." 패턴)
# ──────────────────────────────────────────────────────────────

class TestPlaceholderAppName:
    """제목·본문에 'Word. 한국어' 형태의 플레이스홀더처럼 보이는 앱명이 있으면 경고"""

    def _review(self, article):
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _base_article(self, title, body=None, topic=None):
        default_body = (
            '<h2>Gemma 모델 비교 분석</h2>'
            '<p>Gemma 4 모델은 Google이 2026년에 출시한 오픈소스 LLM이다. '
            '기존 Gemma 3보다 성능이 크게 향상되어 많은 개발자들이 주목하고 있다. '
            '특히 한국어 처리 능력이 개선되어 한국어 서비스에 활용하기 좋다.</p>'
            '<ul><li>Gemma 4 매개변수: 27B</li><li>Gemma 3 대비 성능 향상: 약 30%</li>'
            '<li>지원 언어: 한국어 포함 140개 언어</li></ul>'
            '<h2>Gemma 4 성능 벤치마크 결과</h2>'
            '<p>벤치마크 테스트에서 Gemma 4는 기존 모델 대비 우수한 성능을 보였다. '
            'MMLU 점수는 87.3점으로 동급 오픈소스 모델 중 최상위권이다. '
            '특히 수학 및 코딩 능력이 크게 개선된 것이 특징이다.</p>'
            '<p>실제 사용 시나리오에서도 Gemma 4의 강점이 드러난다. '
            '응답 속도는 평균 0.8초로 실시간 서비스에 적합하다. '
            '메모리 효율도 개선되어 4GB GPU에서도 실행 가능하다.</p>'
            '<p>Gemma 4를 실제 프로젝트에 적용한 결과 생산성이 향상되었다. '
            '코드 리뷰 시간이 40% 단축되었고 버그 발견율도 높아졌다. '
            '팀 전체의 개발 속도가 빨라지는 효과를 얻었다.</p>'
            '<h2>선택 기준 정리</h2>'
            '<p>Gemma 4 모델 선택 시 핵심 기준을 정리하면 다음과 같다. '
            '먼저 목적에 맞는 모델 크기를 선택해야 한다. '
            'Gemma 4 27B는 고품질 출력이 필요한 작업에 적합하다.</p>'
        )
        return {
            'title': title,
            'body': body or default_body,
            'meta': 'Gemma 4 전환 후 영단어 앱의 정답 중복 버그가 사라진 이유를 분석한다.',
            'topic': topic or 'Gemma 4 모델 비교 성능',
        }

    def _qp1_issues(self, msg):
        return [l for l in msg.split('\n') if '앱명' in l]

    def test_title_with_word_dot_pattern_triggers_warning(self):
        """제목에 'Word. 한국어' 패턴(플레이스홀더 의심) → QP1 경고"""
        article = self._base_article(title='Blank. 정답이 자꾸 같다면')
        ok, msg = self._review(article)
        assert self._qp1_issues(msg), f"QP1 경고 없음: {msg}"

    def test_title_with_real_app_name_no_warning(self):
        """정상 제목(앱명 없이) → QP1 경고 없음"""
        article = self._base_article(
            title='Gemma 4 전환 후 영단어 앱 정답 5개 중복 버그가 사라진 이유'
        )
        ok, msg = self._review(article)
        assert not self._qp1_issues(msg), f"QP1 오탐: {msg}"

    def test_body_with_word_dot_korean_triggers_warning(self):
        """본문에 'Word. 한국어' 패턴 → QP1 경고"""
        body_with_placeholder = (
            '<h2>Gemma 모델 분석</h2>'
            '<p>Blank. 앱은 영단어 학습을 돕는다. Gemma 4 기반으로 동작한다.</p>'
            '<ul><li>Gemma 4 성능: 우수</li><li>지원 언어: 다수</li></ul>'
            '<h2>Gemma 4 성능 결과</h2>'
            '<p>Gemma 4 벤치마크에서 높은 점수를 기록했다. 성능이 뛰어난 모델이다.</p>'
            '<p>Gemma 4를 사용하면 효율이 높아진다. 실제 테스트에서 확인되었다.</p>'
            '<p>세 번째 단락이다. 추가 설명을 제공한다.</p>'
            '<p>네 번째 단락이다. 더 많은 내용을 담고 있다.</p>'
            '<p>다섯 번째 단락이다. 핵심 내용을 강조한다.</p>'
            '<h2>선택 기준</h2>'
            '<p>Gemma 4 선택 시 고려할 기준을 정리했다. 성능과 비용을 함께 고려해야 한다.</p>'
        )
        article = self._base_article(
            title='Gemma 4 기반 영단어 앱 버그 해결 방법 3가지',
            body=body_with_placeholder,
        )
        ok, msg = self._review(article)
        assert self._qp1_issues(msg), f"QP1 본문 경고 없음: {msg}"

    def test_legitimate_english_no_warning(self):
        """정상 영어가 제목에 있어도 'Word. 한국어' 패턴이 아니면 경고 없음"""
        article = self._base_article(
            title='Gemma 4 성능 비교 이유와 선택 기준 3가지'
        )
        ok, msg = self._review(article)
        assert not self._qp1_issues(msg), f"QP1 오탐(정상 영문): {msg}"

# ──────────────────────────────────────────────────────────────
# 재발방지: check_safety QP1 게이트
# ──────────────────────────────────────────────────────────────

class TestPublisherQP1Gate:
    """check_safety()가 'Word. 한국어' 패턴 제목을 수동 검토로 보낸다."""

    def _safety_cfg(self):
        return {
            'always_manual_review': ['팩트체크'],
            'crypto_keywords': [], 'criticism_keywords': [],
            'investment_keywords': [], 'legal_keywords': [],
            'criticism_phrases': [],
            'min_sources_required': 0,
            'min_quality_score_for_auto': 0,
        }

    def _good_article(self, title: str, body: str = '') -> dict:
        return {
            'title': title,
            'corner': '쉬운세상',
            'body': body or '<h2>소개</h2><p>본문입니다.</p>',
            'sources': [],
            'quality_score': 100,
        }

    def test_word_dot_title_triggers_manual_review(self):
        """'Word. 한국어' 제목 → check_safety가 needs_review=True 반환"""
        from bots.publisher_bot import check_safety
        article = self._good_article('Blank. 정답이 자꾸 같다면 의심할 점 3가지')
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is True, f"QP1 제목 자동 발행됨: reason={reason}"
        assert '앱명' in reason, f"이유에 '앱명' 없음: {reason}"

    def test_word_dot_body_triggers_manual_review(self):
        """본문에 'Word. 한국어' 패턴 → check_safety가 needs_review=True 반환"""
        from bots.publisher_bot import check_safety
        body = '<h2>소개</h2><p>Blank. 앱은 영단어 학습을 돕는다.</p>'
        article = self._good_article('영단어 앱 버그 해결 방법 3가지', body=body)
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is True, f"QP1 본문 자동 발행됨: reason={reason}"
        assert '앱명' in reason, f"이유에 '앱명' 없음: {reason}"

    def test_normal_title_with_english_passes(self):
        """정상 영어 포함 제목 → QP1 오탐 없음"""
        from bots.publisher_bot import check_safety
        article = self._good_article('Gemma 4 전환 후 버그가 사라진 이유 3가지')
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is False or '앱명' not in reason, \
            f"QP1 오탐: reason={reason}"

# ──────────────────────────────────────────────────────────────
# 재발방지: approve_pending QP1 경고
# ──────────────────────────────────────────────────────────────

class TestApprovePendingQP1Warning:
    """approve_pending()이 QP1 패턴 발견 시 Telegram 경고를 보낸다."""

    def test_approve_pending_warns_on_qp1_pattern(self, tmp_path):
        """QP1 패턴 있는 pending 파일 승인 시 Telegram 경고 전송"""
        import json
        from unittest.mock import patch, MagicMock

        pending_file = tmp_path / 'pending.json'
        pending_file.write_text(json.dumps({
            'title': 'Blank. 정답이 자꾸 같다면',
            'body': '<h2>소개</h2><p>Blank. 앱은 영단어 학습을 돕는다.</p>',
            'meta': '테스트 메타 설명.',
            'sources': [],
            'quality_score': 80,
            'corner': '쉬운세상',
        }), encoding='utf-8')

        with patch('bots.publisher_bot.publish_to_blogger') as mock_pub, \
             patch('bots.publisher_bot.get_google_credentials'), \
             patch('bots.publisher_bot.send_telegram') as mock_tg, \
             patch('bots.publisher_bot.log_published'), \
             patch('bots.publisher_bot.submit_to_search_console'):
            mock_pub.return_value = {'url': 'http://example.com/test', 'id': '123'}
            from bots.publisher_bot import approve_pending
            approve_pending(str(pending_file))

        # 텔레그램으로 경고 메시지가 전송되어야 함
        calls = [str(c) for c in mock_tg.call_args_list]
        warning_sent = any('앱명' in c or 'QP1' in c or '플레이스홀더' in c for c in calls)
        assert warning_sent, f"QP1 경고 Telegram 미전송. 호출: {calls}"

    def test_approve_pending_no_warning_for_normal_article(self, tmp_path):
        """정상 제목 pending 승인 시 QP1 경고 없음"""
        import json
        from unittest.mock import patch

        pending_file = tmp_path / 'pending.json'
        pending_file.write_text(json.dumps({
            'title': 'Gemma 4 전환 후 버그가 사라진 이유 3가지',
            'body': '<h2>소개</h2><p>Gemma 4로 전환한 후 문제가 해결됐다.</p>',
            'meta': '정상 메타 설명이다.',
            'sources': [],
            'quality_score': 80,
            'corner': '쉬운세상',
        }), encoding='utf-8')

        with patch('bots.publisher_bot.publish_to_blogger') as mock_pub, \
             patch('bots.publisher_bot.get_google_credentials'), \
             patch('bots.publisher_bot.send_telegram') as mock_tg, \
             patch('bots.publisher_bot.log_published'), \
             patch('bots.publisher_bot.submit_to_search_console'):
            mock_pub.return_value = {'url': 'http://example.com/test', 'id': '123'}
            from bots.publisher_bot import approve_pending
            approve_pending(str(pending_file))

        calls = [str(c) for c in mock_tg.call_args_list]
        qp1_warning = any('앱명' in c or 'QP1' in c for c in calls)
        assert not qp1_warning, f"QP1 오탐 경고 전송됨: {calls}"

# ──────────────────────────────────────────────────────────────
# 재발방지: normalize_title_text 잘림 → check_safety 오탐
# ──────────────────────────────────────────────────────────────

class TestNormalizeTitleTruncationSafety:
    """normalize_title_text 잘림으로 클릭 패턴이 사라져도 check_safety에서 원본 제목으로 체크해야 함"""

    def _safety_cfg(self):
        return {
            'always_manual_review': ['팩트체크'],
            'crypto_keywords': [], 'criticism_keywords': [],
            'investment_keywords': [], 'legal_keywords': [],
            'criticism_phrases': [],
            'min_sources_required': 0,
            'min_quality_score_for_auto': 0,
        }

    def test_sanitized_long_title_with_click_pattern_passes_check_safety(self):
        """publish_with_result 실제 흐름: sanitize 후 잘린 제목으로 check_safety 호출해도 통과"""
        from bots.publisher_bot import check_safety, sanitize_article_for_publish
        article = {
            'title': 'Spring AI Playground에서 MCP 도구를 테스트하면 검증이 몇 초 안에 된다',
            'corner': '쉬운세상',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'sources': [],
            'quality_score': 100,
        }
        # publish_with_result 흐름 재현: sanitize → check_safety
        sanitized = sanitize_article_for_publish(article)
        assert len(sanitized['title']) <= 38, f"normalize 안됨: {sanitized['title']}"
        # 잘린 sanitized article로 check_safety 호출 → 통과해야 함 (RED: 현재 실패)
        needs_review, reason = check_safety(sanitized, self._safety_cfg())
        assert needs_review is False or '클릭' not in reason, \
            f"sanitize 후 잘린 제목이 클릭 패턴 없다고 차단됨: reason={reason}"

    def test_title_with_method_pattern_still_passes(self):
        """'방법' 포함 제목은 truncation 여부 관계없이 통과"""
        from bots.publisher_bot import check_safety
        article = {
            'title': 'Spring AI Playground로 MCP 도구 검증하는 방법',
            'corner': '쉬운세상',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'sources': [],
            'quality_score': 100,
        }
        needs_review, reason = check_safety(article, self._safety_cfg())
        assert needs_review is False or '클릭' not in reason, \
            f"'방법' 포함 제목이 차단됨: reason={reason}"

# ──────────────────────────────────────────────────────────────
# 재발방지: 수치 체크 - 한글 수량 표현 인식
# ──────────────────────────────────────────────────────────────

class TestNumericExpressionRecognition:
    """'몇 초', '몇 분' 같은 한글 수량 표현도 수치로 인식해야 함"""

    def _count_numbers(self, body):
        import re
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: re.split(r'(?<=[.!?다])\s', t)
        article = {
            'title': '테스트 제목으로 검증하는 방법 3가지',
            'body': body,
            'meta': '테스트 메타 설명입니다. 충분히 긴 설명입니다.',
            'topic': '테스트 주제',
        }
        ok, msg = presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)
        return '수치가 부족' in msg

    def test_korean_quantity_expression_counts_as_number(self):
        """'몇 초'가 포함된 본문 → 수치 부족 경고 없음"""
        body = (
            '<h2>테스트 섹션 1</h2>'
            '<p>이 도구를 쓰면 몇 초 안에 결과가 나온다. 속도가 빠른 이유는 캐싱 때문이다.</p>'
            '<p>이전 방식은 몇 분이 걸렸다. 새 방식은 훨씬 빠르다.</p>'
            '<ul><li>항목 1</li><li>항목 2</li></ul>'
            '<h2>섹션 2</h2>'
            '<p>여러 단락으로 구성된 본문 내용이다. 최소 길이를 충족하기 위해 긴 설명을 추가한다.</p>'
            '<p>두 번째 단락이다. 구체적인 내용을 담고 있다. 독자가 이해하기 쉽게 작성한다.</p>'
            '<p>세 번째 단락이다. 추가적인 설명을 제공한다. 전체 글의 논지를 지지한다.</p>'
            '<p>네 번째 단락이다. 더 많은 내용을 추가한다. 본문 길이를 충족한다.</p>'
            '<p>다섯 번째 단락이다. 핵심 내용을 다시 강조한다. 독자에게 유익한 정보를 제공한다.</p>'
            '<h2>결론</h2>'
            '<p>결론 단락이다. 핵심 내용을 정리하고 독자에게 행동을 촉구한다. 이 글을 읽은 독자는 바로 실천할 수 있다.</p>'
        )
        assert not self._count_numbers(body), "'몇 초' + '몇 분' 포함 본문에서 수치 부족 경고"

# ──────────────────────────────────────────────────────────────
# 재발방지: meta에 "테스트" 포함 시 is_test_article 오탐
# ──────────────────────────────────────────────────────────────

class TestIsTestArticleMeta:
    """meta 설명에 '테스트'가 포함돼도 is_test_article이 True 반환하면 안 됨"""

    def test_meta_with_test_word_not_test_article(self):
        """meta에 '테스트' 포함 → is_test_article=False (실제 글 설명에 빈번)"""
        from bots.publisher_bot import is_test_article
        article = {
            'title': 'Spring AI Playground로 MCP 도구 검증하는 방법',
            'meta': 'Spring AI Playground는 MCP 도구를 10초 안에 테스트·검증할 수 있는 앱이다.',
            'slug': 'spring-ai-playground-mcp',
        }
        assert not is_test_article(article), "meta의 '테스트' 단어로 오탐"

    def test_title_with_test_marker_is_test(self):
        """제목에 '테스트' 포함 → is_test_article=True (의도된 동작)"""
        from bots.publisher_bot import is_test_article
        article = {
            'title': '테스트 글입니다',
            'meta': '일반 설명입니다.',
            'slug': 'test-article',
        }
        assert is_test_article(article), "제목 테스트 마커 감지 안됨"

# ──────────────────────────────────────────────────────────────
# 정책 변경: check_safety 결과에 관계없이 바로 발행 (pending 없음)
# ──────────────────────────────────────────────────────────────

class TestPublishWithoutPending:
    """check_safety가 True여도 pending 저장 없이 바로 발행됨"""

    def _article(self, title='신한금융의 ROE 목표와 배당 현황'):
        return {
            'title': title,
            'corner': '쉬운세상',
            'body': '<h2>소개</h2><p>본문입니다.</p>',
            'meta': '설명입니다.',
            'sources': [],
            'quality_score': 100,
        }

    def test_check_safety_violation_still_publishes(self):
        """check_safety=True(클릭 패턴 없음)여도 발행 시도"""
        from unittest.mock import patch, MagicMock
        from bots.publisher_bot import publish_with_result

        with patch('bots.publisher_bot.find_duplicate_publication', return_value=''), \
             patch('bots.publisher_bot.load_config', return_value={
                 'always_manual_review': [], 'crypto_keywords': [], 'criticism_keywords': [],
                 'investment_keywords': [], 'legal_keywords': [], 'criticism_phrases': [],
                 'min_sources_required': 0, 'min_quality_score_for_auto': 0,
             }), \
             patch('bots.publisher_bot.save_pending_review') as mock_save, \
             patch('bots.publisher_bot.markdown_to_html', return_value=('', '')), \
             patch('bots.publisher_bot.insert_adsense_placeholders', return_value=''), \
             patch('bots.publisher_bot.build_full_html', return_value=''), \
             patch('bots.publisher_bot.get_google_credentials'), \
             patch('bots.publisher_bot.publish_to_blogger', return_value={'url': 'http://x.com', 'id': '1'}), \
             patch('bots.publisher_bot.log_published'), \
             patch('bots.publisher_bot.submit_to_search_console'), \
             patch('bots.publisher_bot.send_telegram'), \
             patch('bots.publisher_bot.is_test_article', return_value=False):

            ok, reason = publish_with_result(self._article())

        # pending 저장 안 함
        mock_save.assert_not_called()
        # 발행 성공
        assert ok is True, f"check_safety 위반에도 발행 실패: {reason}"

    def test_duplicate_still_blocked(self):
        """중복 발행은 여전히 차단"""
        from unittest.mock import patch
        from bots.publisher_bot import publish_with_result

        with patch('bots.publisher_bot.find_duplicate_publication', return_value='중복: 동일 제목'), \
             patch('bots.publisher_bot.load_config', return_value={}):
            ok, reason = publish_with_result(self._article())

        assert ok is False
        assert '중복' in reason


# ──────────────────────────────────────────────────────────────
# CTR 10%: QT1 강한/약한 패턴 분기 검증
# ──────────────────────────────────────────────────────────────

class TestTitleCTRStrength:
    """QT1: 강한 패턴이면 [경고] 없음, 약한 패턴만이면 [경고] 포함"""

    @staticmethod
    def _review(article):
        import re as _re
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: _re.split(r'(?<=[.!?다])\s+', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    @staticmethod
    def _make_article(title, topic='ROE 배당주 투자'):
        return {
            'title': title,
            'topic': topic,
            'meta': f'{title}.',
            'corner': '쉬운세상',
            'body': (
                '<h2>첫 번째 섹션</h2><p>본문 내용이다.</p><p>두 번째 문단이다.</p>'
                '<h2>두 번째 섹션</h2><p>세 번째 문단이다.</p><p>네 번째 문단이다.</p>'
                '<h2>세 번째 섹션</h2><p>다섯 번째 문단이다.</p><p>여섯 번째 문단이다.</p>'
            ),
        }

    def test_strong_action_result_passes(self):
        """손실 프레임('낮아진다') STRONG → [경고] 없음"""
        article = self._make_article('ROE가 낮으면 내 통장 이자도 낮아진다')
        _, msg = self._review(article)
        assert '[경고]' not in msg, f"STRONG 제목에 [경고] 오탐: {msg}"

    def test_strong_loss_passes(self):
        """손실 프레임('손해') STRONG → [경고] 없음"""
        article = self._make_article('CEO가 주식 팔 때 따라 팔면 손해')
        _, msg = self._review(article)
        assert '[경고]' not in msg, f"STRONG 제목에 [경고] 오탐: {msg}"

    def test_strong_number_time_passes(self):
        """시간+만에 STRONG → [경고] 없음"""
        article = self._make_article('3개월 만에 Google 상위 노출 달성하는 법')
        _, msg = self._review(article)
        assert '[경고]' not in msg, f"STRONG 시간 패턴에 [경고] 오탐: {msg}"

    def test_weak_how_to_alone_warns(self):
        """이유 단독 WEAK → [경고] 포함"""
        article = self._make_article('WTI 오르는 이유')
        _, msg = self._review(article)
        assert '[경고]' in msg, f"WEAK 이유 제목에 [경고] 없음: {msg}"

    def test_weak_method_alone_warns(self):
        """방법 단독 WEAK → [경고] 포함"""
        article = self._make_article('내부 링크 삽입 방법')
        _, msg = self._review(article)
        assert '[경고]' in msg, f"WEAK 방법 제목에 [경고] 없음: {msg}"

    def test_strong_plus_weak_no_warn(self):
        """숫자(STRONG) + 방법(WEAK) 결합 → [경고] 없음"""
        article = self._make_article('5가지 방법으로 Google 체류시간이 늘어난다')
        _, msg = self._review(article)
        assert '[경고]' not in msg, f"STRONG+WEAK 결합인데 [경고] 오탐: {msg}"

    def test_no_pattern_fails_qt1(self):
        """패턴 없는 설명체 제목 → ok=False, [경고] 아닌 하드 FAIL"""
        article = self._make_article('AI의 미래와 인간 사회')
        ok, msg = self._review(article)
        assert ok is False, f"패턴 없는 제목이 ok=True: {msg}"
        assert '클릭 유발 패턴 없음' in msg, f"하드 FAIL 메시지 없음: {msg}"

    def test_ability_pattern_warns(self):
        """능력형 결말('쓸 수 있다') → [경고] 포함"""
        article = self._make_article('git 저장소에 프롬프트 모으면 모든 도구에서 쓸 수 있다')
        _, msg = self._review(article)
        assert '[경고]' in msg, f"능력형 결말에 [경고] 없음: {msg}"


# ──────────────────────────────────────────────────────────────
# CTR 10%: [경고]만 있으면 ok=True (발행 허용)
# ──────────────────────────────────────────────────────────────

class TestWeakPatternWarningDoesNotBlock:
    """[경고] prefix 이슈만 있으면 presentation_review가 ok=True 반환"""

    def _review(self, article):
        import re as _re
        from bots.prompt_layer.writer_review import presentation_review
        split_sentences = lambda t: _re.split(r'(?<=[.!?다])\s+', t)
        return presentation_review(article, raw_term_replacements={}, split_sentences=split_sentences)

    def _full_article(self, title, topic='배당주 선택 기준'):
        """Q5·QK1·QT2·강조·약어 등 다른 hard issue 없는 배당주 본문 (900자+ 무공백)."""
        return {
            'title': title,
            'topic': topic,
            'meta': '배당주를 고르면 매년 배당금 수익이 생기고 주가 상승도 함께 노릴 수 있다.',
            'corner': '쉬운세상',
            'body': (
                '<h2>배당주의 핵심 개념과 특징</h2>'
                '<p><strong>배당주</strong>는 매년 기업이 이익의 일부를 주주에게 나눠주는 주식이다. '
                '분기마다 배당금을 받아 월세 수익과 유사한 효과를 낼 수 있다. '
                '한국 배당주 평균 배당수익률은 약 3.2%이며 우량 배당주는 4.5% 수준이다.</p>'
                '<p>배당주에 투자하면 주가 상승 수익과 배당 수익 두 가지를 동시에 노릴 수 있다. '
                '장기 보유할수록 복리 효과로 수익이 불어난다. '
                '코스피 우량 배당주 상위 10종목 평균 배당성향은 35% 수준이다.</p>'
                '<p>배당주 투자 시 가장 중요한 지표는 배당수익률과 배당성향이다. '
                '배당수익률이 높아도 배당성향이 90% 이상이면 지속 가능성이 낮다. '
                '적정 배당성향은 30~60% 사이가 안정적이다.</p>'
                '<p>배당 투자는 복리 효과 덕분에 오래 보유할수록 유리하다. '
                '10년 이상 보유한 배당주 투자자의 평균 수익률은 시장 평균을 웃돌았다. '
                '배당 재투자 전략을 쓰면 자산이 더 빠르게 불어난다.</p>'
                '<ul><li>배당수익률: 주가 대비 배당금 비율</li>'
                '<li>배당성향: 순이익 대비 배당금 비율</li>'
                '<li>배당 안정성: 최근 5년 배당 지속 여부</li></ul>'
                '<h2>배당주 선택 기준 비교</h2>'
                '<p><strong>배당주 선택</strong>의 첫 번째 기준은 자기자본이익률이다. '
                '자기자본이익률이 10% 이상인 기업을 우량 배당주로 볼 수 있다. '
                '이 수치가 낮으면 배당금이 줄거나 중단될 위험이 있다.</p>'
                '<p>두 번째 기준은 부채비율이다. 부채비율이 100% 미만인 기업이 배당 안정성이 높다. '
                '부채가 많으면 이자 비용이 늘어나 배당 여력이 줄어든다. '
                '금융주는 부채비율 기준이 다르니 업종별로 비교해야 한다.</p>'
                '<p>세 번째 기준은 영업이익 성장세다. 최근 3년 영업이익이 꾸준히 오른 기업은 배당 증가 가능성이 높다. '
                '실적이 정체되면 배당금도 늘지 않는다. 성장 배당주를 골라야 복리 효과가 극대화된다.</p>'
                '<p>배당 성장 기업을 찾을 때는 최근 5년 배당금 증가 이력을 먼저 확인해야 한다. '
                '배당금이 매년 5% 이상 오른 기업은 앞으로도 꾸준히 오를 가능성이 높다.</p>'
                '<h2>배당주 투자 주의사항</h2>'
                '<p><strong>배당락일</strong>과 세금을 놓치면 손해다. '
                '배당락일 이후 주가 하락 폭이 배당금보다 크면 전체 수익은 마이너스가 된다. '
                '배당소득세는 15.4%로 자동 원천징수된다.</p>'
                '<p>금융소득이 연 2,000만 원을 넘으면 종합소득세 대상이 된다. '
                '절세 전략을 세우면 실수익이 달라진다. '
                '개인종합자산관리계좌를 활용하면 절세 혜택을 받을 수 있다.</p>'
                '<p>분산 투자가 중요하다. 한 종목에 집중하면 기업 실적 악화 시 큰 손실이 난다. '
                '배당주 포트폴리오는 최소 5종목 이상으로 구성하는 것이 안전하다. '
                '금융·제조·통신·에너지 등 업종을 다양하게 나눠야 위험이 줄어든다.</p>'
            ),
        }

    def test_weak_method_title_ok_is_true(self):
        """방법 단독 WEAK 제목 → [경고] 포함 + ok=True (발행 허용)"""
        article = self._full_article('배당주를 고르는 방법과 선택 기준')
        ok, msg = self._review(article)
        assert '[경고]' in msg, f"WEAK 제목에 [경고] 없음: {msg}"
        assert ok is True, f"WEAK 제목이 차단됨 — ok=False: {msg}"

    def test_no_pattern_ok_is_false(self):
        """패턴 없는 제목 → ok=False"""
        article = self._full_article('배당주 선택 시 고려할 사항')
        ok, msg = self._review(article)
        assert ok is False, f"패턴 없는 제목이 ok=True: {msg}"


# ──────────────────────────────────────────────────────────────
# CTR 10%: publisher_bot + pipeline 패턴 동기화 검증
# ──────────────────────────────────────────────────────────────

class TestTitlePatternSync:
    """TITLE_STRONG/WEAK_PATTERNS가 publisher_bot·pipeline 모두에서 동일하게 사용됨"""

    def test_손해_recognized_publisher(self):
        """publisher_bot: '손해' → True"""
        from bots.publisher_bot import _title_has_click_pattern
        assert _title_has_click_pattern('CEO가 주식 팔 때 따라 팔면 손해')

    def test_time_result_recognized_publisher(self):
        """publisher_bot: '3개월 만에' → True"""
        from bots.publisher_bot import _title_has_click_pattern
        assert _title_has_click_pattern('3개월 만에 Google 상위 노출 달성')

    def test_낮아진다_recognized_publisher(self):
        """publisher_bot: '낮아진다' → True"""
        from bots.publisher_bot import _title_has_click_pattern
        assert _title_has_click_pattern('ROE가 낮으면 내 통장 이자도 낮아진다')

    def test_pipeline_늘어난다_recognized(self):
        """pipeline: '늘어난다' → True (기존 publisher_bot에는 없던 패턴)"""
        from bots.pipeline import _title_has_click_pattern
        assert _title_has_click_pattern('내부 링크 넣으면 체류시간이 늘어난다'), \
            "pipeline._title_has_click_pattern이 '늘어난다'를 인식하지 못함"

    def test_pipeline_손해_recognized(self):
        """pipeline: '손해' → True"""
        from bots.pipeline import _title_has_click_pattern
        assert _title_has_click_pattern('팔면 손해')
