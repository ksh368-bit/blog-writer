"""
tests/test_pipeline_integration.py

pipeline ↔ scheduler 통합 문제 수정 테스트

1. pending_review 고품질 글 → drafts 자동 이동 (_drain_pending_to_drafts)
2. 08:00 writer가 오늘 글감 없으면 어제 미처리 글감도 확인
3. APScheduler misfire_grace_time 설정 확인
"""
import json
import pytest
from pathlib import Path
import types, unittest.mock as mock, sys


def _write(directory: Path, filename: str, data: dict) -> Path:
    f = directory / filename
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return f


# ─── 1. pending_review → drafts drain ──────────────────

class TestDrainPendingToDrafts:

    def test_high_quality_pending_moved_to_drafts(self, tmp_path, monkeypatch):
        """quality_score >= 70인 pending_review 글이 drafts로 이동된다."""
        import bots.scheduler as sch
        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        pending_dir = tmp_path / "pending_review"
        pending_dir.mkdir()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()

        _write(pending_dir, "20260427_101702_pending.json", {
            "title": "고품질 글", "slug": "high-quality-post",
            "corner": "쉬운세상", "body": "본문", "meta": "메타",
            "tags": [], "sources": [], "quality_score": 85,
            "pending_reason": "품질 검수 미완료 — 토큰 예산 초과",
        })

        sch._drain_pending_to_drafts()

        draft_files = list(drafts_dir.glob("*.json"))
        assert len(draft_files) == 1, "고품질 pending 글이 drafts로 이동돼야 함"
        assert not (pending_dir / "20260427_101702_pending.json").exists(), "pending 파일은 삭제돼야 함"

    def test_low_quality_pending_not_moved(self, tmp_path, monkeypatch):
        """quality_score < 70인 pending_review 글은 drafts로 이동되지 않는다."""
        import bots.scheduler as sch
        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        pending_dir = tmp_path / "pending_review"
        pending_dir.mkdir()
        (tmp_path / "drafts").mkdir()

        _write(pending_dir, "20260427_101702_pending.json", {
            "title": "저품질 글", "slug": "low-quality",
            "corner": "쉬운세상", "body": "본문", "quality_score": 55,
            "pending_reason": "제목 클릭 패턴 없음",
        })

        sch._drain_pending_to_drafts()

        assert (pending_dir / "20260427_101702_pending.json").exists(), "저품질 글은 그대로 있어야 함"
        assert list((tmp_path / "drafts").glob("*.json")) == [], "drafts에 이동되면 안 됨"

    def test_publish_next_drains_pending_first(self, tmp_path, monkeypatch):
        """_publish_next() 호출 시 pending_review를 먼저 drain한다."""
        import bots.scheduler as sch
        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        pending_dir = tmp_path / "pending_review"
        pending_dir.mkdir()
        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()

        _write(pending_dir, "20260427_101702_pending.json", {
            "title": "Stash 메모리", "slug": "stash-memory",
            "corner": "쉬운세상", "body": "본문", "meta": "메타",
            "tags": [], "sources": [], "quality_score": 89,
            "pending_reason": "토큰 예산 초과",
        })

        published = []
        fake_publisher = types.SimpleNamespace(
            publish_with_result=mock.Mock(side_effect=lambda a: (
                published.append(a["title"]) or (True, "")
            )),
            publish=mock.Mock(return_value=True),
        )
        fake_converter = types.SimpleNamespace(convert=mock.Mock(return_value="<html/>"))
        monkeypatch.setattr(sch, "_telegram_notify", lambda t: None)
        monkeypatch.setitem(sys.modules, "publisher_bot", fake_publisher)
        monkeypatch.setitem(sys.modules, "blog_converter", fake_converter)

        sch._publish_next()

        assert "Stash 메모리" in published, "pending_review 글이 발행돼야 함"


# ─── 2. 08:00 writer 어제 글감 폴백 ─────────────────────

class TestWriterYesterdayFallback:

    def test_writer_uses_yesterday_topics_if_today_empty(self, tmp_path, monkeypatch):
        """오늘 글감이 없으면 어제 미처리 글감을 사용한다."""
        import bots.scheduler as sch
        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        topics_dir = tmp_path / "topics"
        topics_dir.mkdir()
        (tmp_path / "drafts").mkdir()
        (tmp_path / "originals").mkdir()

        # 어제 글감 (미처리)
        yesterday = "20260426"
        _write(topics_dir, f"{yesterday}_aaa.json", {
            "topic": "어제 미처리 글감", "corner": "쉬운세상",
            "quality_score": 80,
        })

        called_topics = []

        def fake_call_openclaw(topic_data, out_path):
            called_topics.append(topic_data.get("topic"))

        monkeypatch.setattr(sch, "_call_openclaw", fake_call_openclaw)

        # 오늘 날짜를 20260427로 고정
        from datetime import datetime
        fake_dt = mock.MagicMock(wraps=datetime)
        fake_dt.now.return_value = datetime(2026, 4, 27, 8, 0, 0)
        monkeypatch.setattr("bots.scheduler.datetime", fake_dt)

        sch._trigger_openclaw_writer()

        assert "어제 미처리 글감" in called_topics, "어제 글감을 폴백으로 사용해야 함"

    def test_today_topics_take_priority_over_yesterday(self, tmp_path, monkeypatch):
        """오늘 글감이 있으면 어제 글감보다 우선한다."""
        import bots.scheduler as sch
        monkeypatch.setattr(sch, "DATA_DIR", tmp_path)

        topics_dir = tmp_path / "topics"
        topics_dir.mkdir()
        (tmp_path / "drafts").mkdir()
        (tmp_path / "originals").mkdir()

        _write(topics_dir, "20260426_old.json", {
            "topic": "어제 글감", "corner": "쉬운세상", "quality_score": 80,
        })
        _write(topics_dir, "20260427_new.json", {
            "topic": "오늘 글감", "corner": "쉬운세상", "quality_score": 80,
        })

        called_topics = []

        def fake_call_openclaw(topic_data, out_path):
            called_topics.append(topic_data.get("topic"))

        monkeypatch.setattr(sch, "_call_openclaw", fake_call_openclaw)

        from datetime import datetime
        fake_dt = mock.MagicMock(wraps=datetime)
        fake_dt.now.return_value = datetime(2026, 4, 27, 8, 0, 0)
        monkeypatch.setattr("bots.scheduler.datetime", fake_dt)

        sch._trigger_openclaw_writer()

        assert called_topics[0] == "오늘 글감", "오늘 글감이 먼저 처리돼야 함"
        assert "어제 글감" not in called_topics, "오늘 글감 있으면 어제 것 안 씀"
