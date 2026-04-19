"""
tests/test_scheduler_notify.py

발행 완료 텔레그램 알림 테스트 (TDD RED 단계)

테스트 대상:
- _publish_next(): 발행 성공 시 _telegram_notify 호출 여부
- handle_text() 응답 메시지: 타이밍 안내 문구 포함 여부
"""
import json
import types
import unittest.mock as mock
from pathlib import Path
import pytest


# ─── _publish_next 알림 테스트 ──────────────────────────

class TestPublishNextNotify:
    def _make_article(self, title="테스트 글", slug="test-slug", corner="쉬운세상"):
        return {
            "title": title,
            "slug": slug,
            "corner": corner,
            "body": "## 본문",
            "meta": "테스트 메타",
            "tags": ["태그"],
            "sources": [],
            "quality_score": 80,
        }

    def test_notify_called_on_publish_success(self, tmp_path, monkeypatch):
        """발행 성공 시 _telegram_notify가 호출된다."""
        import bots.scheduler as sch

        article = self._make_article()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        draft_file = drafts_dir / "20260419_abcd1234.json"
        draft_file.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        # publisher_bot 발행 성공 mock
        fake_publisher = types.SimpleNamespace(
            publish_with_result=mock.Mock(return_value=(True, "")),
            publish=mock.Mock(return_value=True),
        )
        fake_converter = types.SimpleNamespace(convert=mock.Mock(return_value="<html>본문</html>"))

        notify_calls = []

        def fake_notify(text):
            notify_calls.append(text)

        monkeypatch.setattr(sch, "_telegram_notify", fake_notify)

        import sys
        monkeypatch.setitem(sys.modules, "publisher_bot", fake_publisher)
        monkeypatch.setitem(sys.modules, "blog_converter", fake_converter)

        sch._publish_next()

        assert len(notify_calls) >= 1, "_telegram_notify가 호출되지 않음"

    def test_notify_contains_title(self, tmp_path, monkeypatch):
        """알림 메시지에 글 제목이 포함된다."""
        import bots.scheduler as sch

        title = "전장반도체 Zonal 아키텍처 투자 분석"
        article = self._make_article(title=title)
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        draft_file = drafts_dir / "20260419_abcd1234.json"
        draft_file.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        fake_publisher = types.SimpleNamespace(
            publish_with_result=mock.Mock(return_value=(True, "")),
            publish=mock.Mock(return_value=True),
        )
        fake_converter = types.SimpleNamespace(convert=mock.Mock(return_value="<html/>" ))

        notify_calls = []
        monkeypatch.setattr(sch, "_telegram_notify", lambda t: notify_calls.append(t))
        import sys
        monkeypatch.setitem(sys.modules, "publisher_bot", fake_publisher)
        monkeypatch.setitem(sys.modules, "blog_converter", fake_converter)

        sch._publish_next()

        combined = " ".join(notify_calls)
        assert title in combined, f"제목 '{title}'이 알림 메시지에 없음"

    def test_notify_contains_url_when_available(self, tmp_path, monkeypatch):
        """발행된 URL이 있으면 알림 메시지에 포함된다."""
        import bots.scheduler as sch

        article = self._make_article()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        draft_file = drafts_dir / "20260419_abcd1234.json"
        draft_file.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")

        expected_url = "https://blog.example.com/post/test-slug"
        article_with_url = {**article, "_published_url": expected_url}

        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        fake_publisher = types.SimpleNamespace(
            publish_with_result=mock.Mock(return_value=(True, "")),
            publish=mock.Mock(return_value=True),
        )
        fake_converter = types.SimpleNamespace(convert=mock.Mock(return_value="<html/>"))

        notify_calls = []
        monkeypatch.setattr(sch, "_telegram_notify", lambda t: notify_calls.append(t))
        import sys
        monkeypatch.setitem(sys.modules, "publisher_bot", fake_publisher)
        monkeypatch.setitem(sys.modules, "blog_converter", fake_converter)

        # publish 후 published 폴더에 URL이 담긴 레코드가 생긴다고 가정
        published_dir = tmp_path / "published"
        published_dir.mkdir()
        record = {"title": article["title"], "slug": article["slug"],
                  "url": expected_url, "published_at": "2026-04-19T09:00:00Z"}
        (published_dir / "20260419_090000_99999.json").write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )

        sch._publish_next()

        combined = " ".join(notify_calls)
        assert expected_url in combined, f"URL '{expected_url}'이 알림 메시지에 없음"

    def test_no_notify_on_publish_failure(self, tmp_path, monkeypatch):
        """중복 차단 시 _telegram_notify가 호출되지 않는다."""
        import bots.scheduler as sch

        article = self._make_article()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        draft_file = drafts_dir / "20260419_abcd1234.json"
        draft_file.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        fake_publisher = types.SimpleNamespace(
            publish_with_result=mock.Mock(return_value=(False, "중복 발행 차단")),
            publish=mock.Mock(return_value=False),
        )
        fake_converter = types.SimpleNamespace(convert=mock.Mock(return_value="<html/>"))

        notify_calls = []
        monkeypatch.setattr(sch, "_telegram_notify", lambda t: notify_calls.append(t))
        import sys
        monkeypatch.setitem(sys.modules, "publisher_bot", fake_publisher)
        monkeypatch.setitem(sys.modules, "blog_converter", fake_converter)

        sch._publish_next()

        assert len(notify_calls) == 0, "중복 차단 시 알림이 호출되면 안 됨"

    def test_duplicate_draft_is_deleted(self, tmp_path, monkeypatch):
        """중복 차단된 draft는 삭제된다 (무한 재시도 방지)."""
        import bots.scheduler as sch

        article = self._make_article()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        draft_file = drafts_dir / "20260419_abcd1234.json"
        draft_file.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")

        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        fake_publisher = types.SimpleNamespace(
            publish_with_result=mock.Mock(return_value=(False, "기발행 slug 중복: test-slug")),
            publish=mock.Mock(return_value=False),
        )
        fake_converter = types.SimpleNamespace(convert=mock.Mock(return_value="<html/>"))

        monkeypatch.setattr(sch, "_telegram_notify", lambda t: None)
        import sys
        monkeypatch.setitem(sys.modules, "publisher_bot", fake_publisher)
        monkeypatch.setitem(sys.modules, "blog_converter", fake_converter)

        sch._publish_next()

        assert not draft_file.exists(), "중복 차단된 draft 파일이 삭제되지 않음"


# ─── 즉시 응답 메시지 타이밍 안내 테스트 ──────────────

class TestInsightMemoReply:
    def test_reply_mentions_schedule_timing(self):
        """즉시 응답 메시지에 스케줄 타이밍 안내가 포함된다."""
        # handle_text의 reply_text에 들어가는 메시지 문자열 검증
        # scheduler.py에서 응답 메시지 상수를 추출해 검증
        import bots.scheduler as sch
        import inspect

        src = inspect.getsource(sch.handle_text)
        # "08:00", "09:00", "내일" 중 하나 이상 포함
        has_timing = any(kw in src for kw in ["08:00", "09:00", "내일", "다음"])
        assert has_timing, "응답 메시지에 스케줄 타이밍 안내가 없음"

    def test_reply_not_claim_immediate_generation(self):
        """즉시 응답 메시지가 '지금 바로' 생성된다고 주장하지 않는다."""
        import bots.scheduler as sch
        import inspect

        src = inspect.getsource(sch.handle_text)
        # "시작합니다" 같은 즉시 생성 암시 문구 제거 확인
        assert "글 생성을 시작합니다" not in src, "'글 생성을 시작합니다' 제거 필요"
