"""
approve_pending() 발행 전 검증 연동 테스트
"""
import pytest

VALID_ARTICLE = {
    'title': '기준금리 동결',
    'body': '<p>기준금리 동결 ' + '본문 ' * 100 + '</p>',
    'sources': [{'url': 'https://example.com'}],
    'quality_score': 80,
}
INVALID_ARTICLE = {'title': '', 'body': '', 'sources': [], 'quality_score': 0}


def _patch_downstream(monkeypatch):
    """publish_to_blogger 이후 함수들 일괄 no-op 처리"""
    import bots.publisher_bot as pb
    monkeypatch.setattr(pb, 'get_google_credentials', lambda: None)
    monkeypatch.setattr(pb, 'markdown_to_html', lambda b: ('<p/>', ''))
    monkeypatch.setattr(pb, 'insert_adsense_placeholders', lambda h: h)
    monkeypatch.setattr(pb, 'build_full_html', lambda *a: '<html/>')
    monkeypatch.setattr(pb, 'is_test_article', lambda a: False)
    monkeypatch.setattr(pb, 'log_published', lambda *a: None)
    monkeypatch.setattr('pathlib.Path.unlink', lambda self, missing_ok=False: None)


class TestApprovePendingDuplicateBlock:
    """approve_pending() — 중복 출처 글 발행 차단"""

    def test_blocks_duplicate_source_article(self, monkeypatch, tmp_path):
        """이미 발행된 출처 URL 동일 글 → False 반환, publish_to_blogger 미호출"""
        import bots.publisher_bot as pb
        article = {**VALID_ARTICLE, 'sources': [{'url': 'https://example.com/news/1'}]}
        monkeypatch.setattr(pb, 'load_pending_review_file', lambda fp: article.copy())
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: '기발행 글과 출처 URL 중복: https://example.com/news/1')
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {})
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        result = pb.approve_pending(str(tmp_path / 'fake.json'))
        assert result is False
        assert publish_calls == []

    def test_allows_unique_article(self, monkeypatch, tmp_path):
        """중복 없음 → 발행 진행"""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'load_pending_review_file', lambda fp: VALID_ARTICLE.copy())
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: '')
        monkeypatch.setattr(pb, 'validate_article_before_publish', lambda a: (True, []))
        monkeypatch.setattr(pb, 'markdown_to_html', lambda b: ('<p/>', ''))
        monkeypatch.setattr(pb, 'insert_adsense_placeholders', lambda h: h)
        monkeypatch.setattr(pb, 'build_full_html', lambda *a: '<html/>')
        monkeypatch.setattr(pb, 'get_google_credentials', lambda: None)
        monkeypatch.setattr(pb, 'is_test_article', lambda a: False)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {'url': 'https://x', 'id': '1'})
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        monkeypatch.setattr(pb, 'log_published', lambda *a: None)
        monkeypatch.setattr(pb, 'submit_to_search_console', lambda *a: None)
        monkeypatch.setattr(pb, '_inject_post_url', lambda h, u: h)
        monkeypatch.setattr('pathlib.Path.unlink', lambda self, missing_ok=False: None)
        pb.approve_pending(str(tmp_path / 'fake.json'))
        assert len(publish_calls) == 1


class TestPublishWithResultNoDualSave:
    """publish_with_result() — pending 시 save_pending_review 미호출 (pipeline.py가 처리)"""

    def test_pending_does_not_call_save_internally(self, monkeypatch):
        """_force_pending=True → save_pending_review 호출 안 함 (caller에 위임)"""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: None)
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'load_config', lambda f: {})
        monkeypatch.setattr(pb, 'check_safety',
            lambda a, c: (True, '제목 클릭 유발 패턴 없음: "LLM 응답 지연"'))
        save_calls = []
        monkeypatch.setattr(pb, 'save_pending_review', lambda a, r: save_calls.append(r))
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: {})
        article = {'title': 'LLM 응답 지연', '_write_quality_passed': False}
        ok, reason = pb.publish_with_result(article)
        assert ok is False
        assert isinstance(reason, str)
        assert save_calls == [], f"pipeline.py가 저장 담당 — publish_with_result 내부 저장 금지. 실제 호출: {save_calls}"


class TestApprovePendingValidation:
    def test_blocks_invalid_article(self, monkeypatch, tmp_path):
        """검증 실패 → False 반환, publish_to_blogger 미호출"""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'load_pending_review_file', lambda fp: INVALID_ARTICLE.copy())
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {})
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        assert pb.approve_pending(str(tmp_path / 'fake.json')) is False
        assert publish_calls == []

    def test_proceeds_valid_article(self, monkeypatch, tmp_path):
        """검증 통과 → publish_to_blogger 호출됨"""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'load_pending_review_file', lambda fp: VALID_ARTICLE.copy())
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: '')  # 중복 없음
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {'url': 'https://x', 'id': '1'})
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        _patch_downstream(monkeypatch)
        pb.approve_pending(str(tmp_path / 'fake.json'))
        assert len(publish_calls) == 1

    def test_telegram_sent_on_validation_failure(self, monkeypatch, tmp_path):
        """검증 실패 → send_telegram에 ⛔ 포함 메시지 전송"""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'load_pending_review_file', lambda fp: INVALID_ARTICLE.copy())
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: {})
        msgs = []
        monkeypatch.setattr(pb, 'send_telegram', lambda msg, **kw: msgs.append(msg))
        pb.approve_pending(str(tmp_path / 'fake.json'))
        assert any('⛔' in m for m in msgs)


class TestPublishWithResultSafetyGate:
    def _base_mocks(self, monkeypatch):
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: None)
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'load_config', lambda f: {})

    def _patch_downstream(self, monkeypatch):
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'get_google_credentials', lambda: None)
        monkeypatch.setattr(pb, 'markdown_to_html', lambda b: ('<p/>', ''))
        monkeypatch.setattr(pb, 'insert_adsense_placeholders', lambda h: h)
        monkeypatch.setattr(pb, 'build_full_html', lambda *a: '<html/>')
        monkeypatch.setattr(pb, 'is_test_article', lambda a: False)
        monkeypatch.setattr(pb, 'log_published', lambda *a: None)

    def test_quality_failed_weak_title_goes_to_pending(self, monkeypatch):
        """_write_quality_passed=False + 제목 약함 → False 반환, publish 미호출, 내부 저장 없음(caller 위임)"""
        import bots.publisher_bot as pb
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(pb, 'check_safety', lambda a, c: (True, '제목 클릭 유발 패턴 없음'))
        save_calls = []
        monkeypatch.setattr(pb, 'save_pending_review', lambda a, r: save_calls.append(r))
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {})
        article = {'title': 'OpenAI는 $300B 밸류', '_write_quality_passed': False}
        ok, reason = pb.publish_with_result(article)
        assert ok is False
        assert save_calls == [], "이중 저장 방지 — pipeline.py가 저장 담당"
        assert publish_calls == []
        assert isinstance(reason, str), f"pipeline.py dict 키 오류 방지 — str 필수, 실제: {type(reason)}"

    def test_quality_passed_weak_title_publishes(self, monkeypatch):
        """_write_quality_passed=True + 제목 약함 → 경고만, 발행 진행"""
        import bots.publisher_bot as pb
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(pb, 'check_safety', lambda a, c: (True, '제목 클릭 유발 패턴 없음'))
        monkeypatch.setattr(pb, 'save_pending_review', lambda *a: None)
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {'url': 'https://x'})
        self._patch_downstream(monkeypatch)
        article = {'title': 'OpenAI는 $300B 밸류', '_write_quality_passed': True, 'body': '본문'}
        pb.publish_with_result(article)
        assert len(publish_calls) == 1

    def test_no_flag_weak_title_publishes(self, monkeypatch):
        """_write_quality_passed 플래그 없음 + 제목 약함 → 경고만, 발행 진행 (approve_pending 경로 보호)"""
        import bots.publisher_bot as pb
        self._base_mocks(monkeypatch)
        monkeypatch.setattr(pb, 'check_safety', lambda a, c: (True, '제목 클릭 유발 패턴 없음'))
        monkeypatch.setattr(pb, 'save_pending_review', lambda *a: None)
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {'url': 'https://x'})
        self._patch_downstream(monkeypatch)
        article = {'title': 'OpenAI는 $300B 밸류', 'body': '본문'}  # 플래그 없음
        pb.publish_with_result(article)
        assert len(publish_calls) == 1

    def test_quality_failed_strong_title_still_pending(self, monkeypatch):
        """_write_quality_passed=False + check_safety 통과(강한 제목) → 여전히 pending

        근본 원인 재현: VPN 글처럼 click_pattern은 통과하지만 _write_quality_passed=False인 경우.
        check_safety가 (False, '')를 반환해도 _write_quality_passed=False면 pending이어야 한다.
        현재 버그: _write_quality_passed 체크가 'if needs_review:' 블록 안에 갇혀 있어서
        check_safety가 False를 반환하면 아예 도달하지 못함.
        """
        import bots.publisher_bot as pb
        self._base_mocks(monkeypatch)
        # check_safety는 통과 (click_pattern OK, 안전 키워드 없음)
        monkeypatch.setattr(pb, 'check_safety', lambda a, c: (False, ''))
        save_calls = []
        monkeypatch.setattr(pb, 'save_pending_review', lambda a, r: save_calls.append(r))
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {})
        # _write_quality_passed=False: 작성 단계에서 품질 검수 미완료 (토큰 초과 강제 저장)
        article = {
            'title': 'VPN 대신 Cloudflare Mesh로 에이전트 권한 관리하면 한 곳에서만 수정된다',
            '_write_quality_passed': False,
            'body': '본문',
        }
        ok, reason = pb.publish_with_result(article)
        assert ok is False, "품질 검수 미완료 원고는 check_safety 통과 여부와 무관하게 pending이어야 함"
        assert publish_calls == [], "발행 호출 없어야 함"
        assert isinstance(reason, str)


class TestNewsHeadlineTitleDetection:
    """check_safety() 뉴스 헤드라인 감지 + publish_with_result() pending 연계"""

    def _safety_cfg(self):
        # 출처/품질 체크 비활성화 — 제목 감지만 테스트
        return {'min_sources_required': 0, 'min_quality_score_for_auto': 0}

    def test_ellipsis_in_title_triggers_safety(self):
        """… 포함 제목 → (True, '뉴스 헤드라인...') — 22억 있어도 먼저 차단"""
        import bots.publisher_bot as pb
        article = {
            'title': '\u2018재테크 달인\u2019 신현송이 22억 경고\u2026',  # '…' U+2026
            'body': '본문', 'sources': [], 'quality_score': 80,
        }
        needs_review, reason = pb.check_safety(article, self._safety_cfg())
        assert needs_review is True
        assert '뉴스 헤드라인' in reason

    def test_curly_quote_start_triggers_safety(self):
        """U+2018(') 로 시작하는 제목 → (True, '뉴스 헤드라인...')"""
        import bots.publisher_bot as pb
        article = {
            'title': '\u2018재테크 달인\u2019 신현송의 조언',  # 줄임표 없지만 ' 시작
            'body': '본문', 'sources': [], 'quality_score': 80,
        }
        needs_review, reason = pb.check_safety(article, self._safety_cfg())
        assert needs_review is True
        assert '뉴스 헤드라인' in reason

    def test_normal_title_with_large_number_passes(self):
        """22억 포함 정상 제목 (줄임표/인용 없음) → (False, '') — 회귀 없음"""
        import bots.publisher_bot as pb
        article = {
            'title': '22억 모은 직장인의 3가지 습관',  # 강한 패턴(억+3가지), 헤드라인 아님
            'body': '본문', 'sources': [], 'quality_score': 80,
        }
        needs_review, _ = pb.check_safety(article, self._safety_cfg())
        assert needs_review is False

    def test_news_headline_goes_to_pending_even_with_quality_passed(self, monkeypatch):
        """뉴스 헤드라인 감지 → _write_quality_passed=True여도 pending (기존 분기 우회 방지)"""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: None)
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'load_config', lambda f: {})
        monkeypatch.setattr(pb, 'check_safety',
            lambda a, c: (True, '뉴스 헤드라인 형식 제목 감지 — 블로그 제목으로 변환 필요: "..."'))
        saved = []
        monkeypatch.setattr(pb, 'save_pending_review', lambda a, r: saved.append(r))
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        publish_calls = []
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: publish_calls.append(1) or {})
        article = {'title': '\u2018재테크 달인\u2019 신현송이 경고\u2026', '_write_quality_passed': True}
        ok, reason = pb.publish_with_result(article)
        assert ok is False
        assert saved == [], "이중 저장 방지 — publish_with_result 내부 저장 제거됨, pipeline.py가 담당"
        assert publish_calls == []
        assert isinstance(reason, str), f"pipeline.py가 dict 키로 사용하므로 반드시 str이어야 함, 실제: {type(reason)}"


class TestApprovePendingLinkerBot:
    """approve_pending() — 관련 글 링크 삽입 (linker_bot.process) 호출 확인"""

    def _base_mocks(self, monkeypatch, tmp_path):
        import bots.publisher_bot as pb
        article = {
            'title': 'Option+Space로 Gemini 사용하기',
            'body': '<p>Gemini 앱을 macOS에서 쓰는 방법</p>',
            'sources': [{'url': 'https://example.com'}],
            'quality_score': 85,
            'tags': ['AI', 'macOS'],
        }
        monkeypatch.setattr(pb, 'load_pending_review_file', lambda fp: article.copy())
        monkeypatch.setattr(pb, 'sanitize_article_for_publish', lambda a: a)
        monkeypatch.setattr(pb, 'find_duplicate_publication', lambda a: '')
        monkeypatch.setattr(pb, 'validate_article_before_publish', lambda a: (True, []))
        monkeypatch.setattr(pb, 'get_google_credentials', lambda: None)
        monkeypatch.setattr(pb, 'markdown_to_html', lambda b: ('<p>body</p>', ''))
        monkeypatch.setattr(pb, 'insert_adsense_placeholders', lambda h: h)
        monkeypatch.setattr(pb, 'build_full_html', lambda *a: '<html><body><article><p>body</p></article></body></html>')
        monkeypatch.setattr(pb, 'is_test_article', lambda a: False)
        monkeypatch.setattr(pb, 'publish_to_blogger', lambda *a, **kw: {'url': 'https://x', 'id': '1'})
        monkeypatch.setattr(pb, 'log_published', lambda *a: None)
        monkeypatch.setattr(pb, 'send_telegram', lambda *a, **kw: None)
        monkeypatch.setattr(pb, '_inject_post_url', lambda h, u: h)
        monkeypatch.setattr(pb, 'submit_to_search_console', lambda *a: None)
        monkeypatch.setattr('pathlib.Path.unlink', lambda self, missing_ok=False: None)
        return tmp_path / 'fake.json'

    def test_linker_bot_called_in_approve_pending(self, monkeypatch, tmp_path):
        """approve_pending() → linker_bot.process() 반드시 호출되어야 함"""
        import bots.publisher_bot as pb
        fp = self._base_mocks(monkeypatch, tmp_path)

        linker_calls = []

        import bots.linker_bot as lb
        monkeypatch.setattr(lb, 'process', lambda article, html: linker_calls.append(1) or html)

        pb.approve_pending(str(fp))

        assert linker_calls, "approve_pending()은 linker_bot.process()를 호출해야 관련 글 링크가 삽입됨"


class TestSeoMetadataInjection:
    """_inject_post_url() — 발행 후 JSON-LD @id + og:url 주입"""

    def test_updates_json_ld_id(self):
        """빈 @id → 실제 URL로 교체"""
        from bots.publisher_bot import _inject_post_url
        html = '<script type="application/ld+json">{"@id": ""}</script>'
        result = _inject_post_url(html, 'https://example.com/post')
        assert '"@id": "https://example.com/post"' in result

    def test_adds_og_url_before_twitter_card(self):
        """og:url 없으면 twitter:card 앞에 삽입"""
        from bots.publisher_bot import _inject_post_url
        html = '<meta name="twitter:card" content="summary"/>'
        result = _inject_post_url(html, 'https://example.com/post')
        assert 'og:url' in result
        assert 'https://example.com/post' in result
        assert result.index('og:url') < result.index('twitter:card')

    def test_does_not_duplicate_og_url(self):
        """og:url 이미 있으면 중복 삽입 안 함"""
        from bots.publisher_bot import _inject_post_url
        html = '<meta property="og:url" content="https://old.com"/>'
        result = _inject_post_url(html, 'https://new.com/post')
        assert result.count('og:url') == 1

    def test_noop_on_empty_url(self):
        """post_url 빈 문자열이면 HTML 변경 없음"""
        from bots.publisher_bot import _inject_post_url
        html = '<script type="application/ld+json">{"@id": ""}</script>'
        assert _inject_post_url(html, '') == html
