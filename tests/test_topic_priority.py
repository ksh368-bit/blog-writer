"""
tests/test_topic_priority.py

전장반도체 토픽 우선순위 정렬 테스트 (TDD RED 단계)

테스트 대상: bots/scheduler._prioritize_topic_files()
- 인사이트 메모 토픽 (user_insight 있음) → 최우선
- 전장반도체 코너 토픽 (corner='전장반도체') → 두 번째
- 나머지 → 파일명 순
"""
import json
import pytest
from pathlib import Path


def _write_topic(directory: Path, filename: str, data: dict) -> Path:
    f = directory / filename
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return f


class TestPrioritizeTopicFiles:

    def test_insight_memo_comes_first(self, tmp_path):
        """user_insight 있는 토픽이 맨 앞에 온다."""
        import bots.scheduler as sch

        normal  = _write_topic(tmp_path, "20260419_aaa.json", {"topic": "일반 글감", "corner": "쉬운세상"})
        insight = _write_topic(tmp_path, "20260419_bbb_insight_1745123456.json",
                               {"topic": "전장반도체 인사이트", "corner": "전장반도체", "user_insight": "내 메모"})

        result = sch._prioritize_topic_files([normal, insight])
        assert result[0] == insight

    def test_automotive_corner_before_others(self, tmp_path):
        """전장반도체 코너가 일반 코너보다 앞에 온다."""
        import bots.scheduler as sch

        normal = _write_topic(tmp_path, "20260419_aaa.json", {"topic": "일반 글감", "corner": "쉬운세상"})
        auto   = _write_topic(tmp_path, "20260419_bbb.json", {"topic": "NXP 분석", "corner": "전장반도체"})

        result = sch._prioritize_topic_files([normal, auto])
        assert result[0] == auto

    def test_insight_before_automotive_before_normal(self, tmp_path):
        """인사이트 > 전장반도체 > 일반 순서."""
        import bots.scheduler as sch

        normal  = _write_topic(tmp_path, "20260419_aaa.json", {"topic": "일반", "corner": "쉬운세상"})
        auto    = _write_topic(tmp_path, "20260419_bbb.json", {"topic": "NXP", "corner": "전장반도체"})
        insight = _write_topic(tmp_path, "20260419_ccc_insight_111.json",
                               {"topic": "인사이트", "corner": "전장반도체", "user_insight": "메모"})

        result = sch._prioritize_topic_files([normal, auto, insight])
        assert result[0] == insight
        assert result[1] == auto
        assert result[2] == normal

    def test_empty_list_returns_empty(self, tmp_path):
        """빈 리스트 입력 시 빈 리스트 반환."""
        import bots.scheduler as sch
        assert sch._prioritize_topic_files([]) == []

    def test_same_priority_stable_filename_order(self, tmp_path):
        """같은 우선순위 내에서는 파일명 순을 유지한다."""
        import bots.scheduler as sch

        a = _write_topic(tmp_path, "20260419_aaa.json", {"topic": "A", "corner": "쉬운세상"})
        b = _write_topic(tmp_path, "20260419_bbb.json", {"topic": "B", "corner": "쉬운세상"})

        result = sch._prioritize_topic_files([b, a])  # 섞어서 입력
        assert result[0] == a
        assert result[1] == b

    def test_automotive_without_insight_after_insight(self, tmp_path):
        """인사이트 없는 전장반도체 토픽은 인사이트 있는 것 다음에 온다."""
        import bots.scheduler as sch

        auto    = _write_topic(tmp_path, "20260419_aaa.json", {"topic": "NXP", "corner": "전장반도체"})
        insight = _write_topic(tmp_path, "20260419_bbb_insight_111.json",
                               {"topic": "인사이트", "corner": "전장반도체", "user_insight": "메모"})

        result = sch._prioritize_topic_files([auto, insight])
        assert result[0] == insight
        assert result[1] == auto
