"""
tests/test_load_published_records.py

load_published_records() — drafts/ 폴더 스캔 시
published_at 없는 파일(발행 대기 큐)은 제외해야 한다.
"""
import json
import pytest
from pathlib import Path
import unittest.mock as mock


def _write(directory: Path, filename: str, data: dict) -> Path:
    f = directory / filename
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return f


class TestLoadPublishedRecords:

    def test_pending_draft_excluded(self, tmp_path, monkeypatch):
        """drafts/에 published_at 없는 파일은 records에 포함되지 않는다."""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, "DATA_DIR", tmp_path)

        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        _write(drafts_dir, "20260424_pending.json", {
            "title": "대기 중 글", "slug": "pending-slug",
            "corner": "쉬운세상", "body": "본문",
            # published_at 없음 — 발행 대기 큐
        })

        records = pb.load_published_records()
        slugs = [r.get("slug") for r in records]
        assert "pending-slug" not in slugs, "대기 큐 draft가 published records에 포함되면 안 됨"

    def test_blogger_draft_included(self, tmp_path, monkeypatch):
        """drafts/에 published_at 있는 파일(Blogger DRAFT 발행)은 포함된다."""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, "DATA_DIR", tmp_path)

        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        _write(drafts_dir, "20260424_blogger_draft.json", {
            "title": "블로거 드래프트", "slug": "blogger-draft-slug",
            "published_at": "2026-04-24T09:00:00Z",  # log_published()가 기록
        })

        records = pb.load_published_records()
        slugs = [r.get("slug") for r in records]
        assert "blogger-draft-slug" in slugs, "Blogger DRAFT 발행 기록은 포함돼야 함"

    def test_published_dir_always_included(self, tmp_path, monkeypatch):
        """published/ 폴더 파일은 published_at 여부 무관하게 포함된다."""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, "DATA_DIR", tmp_path)

        published_dir = tmp_path / "published"
        published_dir.mkdir()
        _write(published_dir, "20260424_pub.json", {
            "title": "발행 완료 글", "slug": "published-slug",
            "published_at": "2026-04-24T09:00:00Z",
        })

        records = pb.load_published_records()
        slugs = [r.get("slug") for r in records]
        assert "published-slug" in slugs

    def test_two_pending_drafts_same_source_no_false_duplicate(self, tmp_path, monkeypatch):
        """같은 소스 URL의 draft 두 개가 서로를 중복으로 잡지 않는다."""
        import bots.publisher_bot as pb
        monkeypatch.setattr(pb, "DATA_DIR", tmp_path)

        drafts_dir = tmp_path / "drafts"
        drafts_dir.mkdir()
        src_url = "https://example.com/tesla-article"

        _write(drafts_dir, "20260424_aaa.json", {
            "title": "Tesla A", "slug": "tesla-a",
            "sources": [{"url": src_url}],
            # published_at 없음
        })
        _write(drafts_dir, "20260424_bbb.json", {
            "title": "Tesla B", "slug": "tesla-b",
            "sources": [{"url": src_url}],
            # published_at 없음
        })

        article = {"title": "Tesla A", "slug": "tesla-a",
                   "sources": [{"url": src_url}]}
        result = pb.find_duplicate_publication(article)
        assert not result, f"대기 큐 간 오탐 차단이 발생하면 안 됨: {result}"
