#!/bin/bash
# blog-writer 자동 파이프라인 실행 스크립트
# launchd에서 호출됨 — 수집 → 글 작성 → 발행

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 가상환경 활성화
if [ -d "$PROJECT_DIR/venv" ]; then
    source "$PROJECT_DIR/venv/bin/activate"
fi

# .env 로드
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR"

exec python3 -m bots.pipeline
