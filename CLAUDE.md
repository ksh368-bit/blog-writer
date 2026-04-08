# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 보안 규칙

### .env 파일 접근 금지

절대로 `.env` 파일을 읽거나, 내용을 출력하거나, 다른 곳에 복사하지 않는다.
디버깅 목적이라도 예외 없다.

금지 대상: `.env`, `.env.local`, `.env.*` (`.env.production`, `.env.development` 등)

환경 변수 확인이 필요하면 `.env.example`만 참조한다.

## 개발 정책

### TDD (테스트 주도 개발) 필수

새 기능 추가 또는 버그 수정 시 반드시 TDD 순서를 따른다:

1. **RED**: 실패하는 테스트를 먼저 작성한다
2. **GREEN**: 테스트를 통과시키는 최소한의 코드를 구현한다
3. **REFACTOR**: 코드를 정리한다

- 테스트 파일 위치: `tests/test_*.py`
- 구현 전 `pytest tests/` 로 RED 확인 필수
- 구현 후 전체 테스트 스위트 통과 확인 필수
