"""
tests/test_novel_pipeline.py

소설 파이프라인 job 함수 테스트 (TDD RED 단계)

테스트 대상: bots/scheduler.job_novel_pipeline()
- run_all()이 {'novel_id', 'success'} 형태만 반환할 때 KeyError 없이 동작해야 함
"""
import types
import sys
import unittest.mock as mock
import pytest


class TestJobNovelPipeline:

    def _make_novel_manager(self, results):
        """NovelManager를 fake로 만들어 반환."""
        FakeManager = mock.MagicMock()
        FakeManager.return_value.run_all.return_value = results
        return FakeManager

    def test_no_keyerror_on_success_result(self, monkeypatch):
        """run_all()이 episode_num 없는 결과를 반환해도 KeyError가 나지 않는다."""
        import bots.scheduler as sch

        fake_manager_cls = self._make_novel_manager(
            [{'novel_id': 'shadow-protocol', 'success': True}]
        )

        fake_novel_mod = types.ModuleType("novel.novel_manager")
        fake_novel_mod.NovelManager = fake_manager_cls
        monkeypatch.setitem(sys.modules, "novel.novel_manager", fake_novel_mod)

        # 예외 없이 실행돼야 함
        sch.job_novel_pipeline()

    def test_no_keyerror_on_failure_result(self, monkeypatch):
        """run_all()이 success=False 결과를 반환해도 KeyError가 나지 않는다."""
        import bots.scheduler as sch

        fake_manager_cls = self._make_novel_manager(
            [{'novel_id': 'shadow-protocol', 'success': False}]
        )

        fake_novel_mod = types.ModuleType("novel.novel_manager")
        fake_novel_mod.NovelManager = fake_manager_cls
        monkeypatch.setitem(sys.modules, "novel.novel_manager", fake_novel_mod)

        sch.job_novel_pipeline()  # 예외 없이 실행돼야 함

    def test_empty_results_no_error(self, monkeypatch):
        """run_all()이 빈 리스트를 반환하면 '오늘 발행 예정 소설 없음' 로그."""
        import bots.scheduler as sch

        fake_manager_cls = self._make_novel_manager([])

        fake_novel_mod = types.ModuleType("novel.novel_manager")
        fake_novel_mod.NovelManager = fake_manager_cls
        monkeypatch.setitem(sys.modules, "novel.novel_manager", fake_novel_mod)

        sch.job_novel_pipeline()  # 예외 없이 실행돼야 함

    def test_logs_success(self, monkeypatch, caplog):
        """성공 시 '소설 에피소드 완료' 로그가 기록된다."""
        import bots.scheduler as sch
        import logging

        fake_manager_cls = self._make_novel_manager(
            [{'novel_id': 'shadow-protocol', 'success': True}]
        )

        fake_novel_mod = types.ModuleType("novel.novel_manager")
        fake_novel_mod.NovelManager = fake_manager_cls
        monkeypatch.setitem(sys.modules, "novel.novel_manager", fake_novel_mod)

        with caplog.at_level(logging.INFO):
            sch.job_novel_pipeline()

        assert any("소설 에피소드 완료" in r.message for r in caplog.records), \
            "성공 시 '소설 에피소드 완료' 로그가 없음"

    def test_logs_failure(self, monkeypatch, caplog):
        """실패 시 에러 로그가 기록된다."""
        import bots.scheduler as sch
        import logging

        fake_manager_cls = self._make_novel_manager(
            [{'novel_id': 'shadow-protocol', 'success': False}]
        )

        fake_novel_mod = types.ModuleType("novel.novel_manager")
        fake_novel_mod.NovelManager = fake_manager_cls
        monkeypatch.setitem(sys.modules, "novel.novel_manager", fake_novel_mod)

        with caplog.at_level(logging.ERROR):
            sch.job_novel_pipeline()

        assert any("shadow-protocol" in r.message for r in caplog.records), \
            "실패 시 novel_id가 포함된 로그가 없음"
