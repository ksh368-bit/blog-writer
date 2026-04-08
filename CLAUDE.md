# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 보안 규칙

### .env 파일 접근 금지

절대로 `.env` 파일을 읽거나, 내용을 출력하거나, 다른 곳에 복사하지 않는다.
디버깅 목적이라도 예외 없다.

금지 대상: `.env`, `.env.local`, `.env.*` (`.env.production`, `.env.development` 등)

환경 변수 확인이 필요하면 `.env.example`만 참조한다.

## 개발 정책

### TDD (테스트 주도 개발) — 예외 없음

**모든 코드 변경은 TDD 순서를 반드시 따른다. 예외 없다.**

버그 수정, 새 기능, 리팩터링, 프롬프트 관련 로직 변경 모두 해당한다.

#### 순서

1. **RED** — 실패하는 테스트를 먼저 작성한다
   - `pytest tests/` 실행해서 새 테스트가 FAIL임을 확인한다
   - FAIL 확인 없이 구현 코드를 건드리지 않는다
2. **GREEN** — 테스트를 통과시키는 최소한의 코드를 구현한다
   - `pytest tests/` 실행해서 전체 테스트 스위트가 PASS임을 확인한다
3. **REFACTOR** — 코드를 정리한다. 정리 후 다시 전체 테스트 통과 확인한다

#### 규칙

- 테스트 파일 위치: `tests/test_*.py`
- 테스트 없이 구현 코드를 먼저 작성하는 것은 금지다
- "간단한 수정"이라도 예외 없다 — 한 줄 수정도 테스트를 먼저 작성한다
- 테스트 작성이 어려운 경우(외부 API 호출 등) → 핵심 로직을 순수 함수로 추출한 뒤 그 함수를 테스트한다
