"""
파이프라인 (pipeline.py)
역할: 수집 → 글 작성 → 발행을 한 번에 실행
실행: python3 -m bots.pipeline [옵션]

옵션:
  --topic TEXT       직접 주제 지정 (수집 단계 건너뜀)
  --corner TEXT      코너 지정 (기본: 쉬운세상)
  --limit N          최대 처리 글 수 (기본: 1)
  --skip-collect     수집 단계 건너뜀 (기존 글감 사용)
  --skip-publish     작성만 하고 발행은 하지 않음
  --skip-review      AI/룰 기반 검수 건너뜀 (품질 점수만 확인)
"""
import argparse
import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from bots.prompt_layer.writer_review import TITLE_STRONG_PATTERNS, TITLE_WEAK_PATTERNS

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data'
PIPELINE_SUMMARY_PATH = DATA_DIR / 'pipeline_run_summary.json'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

_log_handlers: list = [logging.FileHandler(LOG_DIR / 'pipeline.log', encoding='utf-8')]
# 터미널에서 직접 실행할 때만 콘솔 출력 추가 (백그라운드 실행 시 리디렉션과 중복 방지)
if sys.stderr.isatty():
    _log_handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)


def _setup_signal_handlers() -> None:
    """SIGHUP/SIGTERM 수신 시 로그를 남기고 종료 (백그라운드 실행 중 강제 종료 추적용)"""
    def _handle(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.error(f"=== 파이프라인 강제 종료 (시그널 {sig_name}) ===")
        sys.exit(1)

    signal.signal(signal.SIGHUP, _handle)
    signal.signal(signal.SIGTERM, _handle)


def _notify_pipeline_issue(message: str) -> None:
    try:
        import bots.publisher_bot as publisher_bot
        publisher_bot.send_telegram(message)
    except Exception as e:
        logger.warning(f"파이프라인 Telegram 알림 실패: {e}")


def _build_attempt_shortfall_message(
    corner: str,
    target_publish_count: int,
    total_summary: dict,
    attempted_writes: int,
    slot: str = "10시",
) -> str:
    achieved = total_summary.get('published', 0) + total_summary.get('retried_then_published', 0)
    reason_counts = total_summary.get('reason_counts', {})
    top_reasons = sorted(reason_counts.items(), key=lambda item: (-int(item[1]), item[0]))[:3]
    reason_text = ', '.join(f'{reason} {count}회' for reason, count in top_reasons) if top_reasons else '주요 차단 사유 없음'
    return (
        f"⚠️ <b>{slot} 발행 자동화 미달</b>\n\n"
        f"코너: {corner}\n"
        f"목표 발행: {target_publish_count}편\n"
        f"실제 발행: {achieved}편\n"
        f"작성 시도: {attempted_writes}건\n"
        f"품질 게이트 실패: {total_summary.get('quality_gate_failures', 0)}건\n"
        f"수동 검토: {total_summary.get('manual_review', 0)}건\n"
        f"주요 사유: {reason_text}\n"
        f"시도한 토픽: {', '.join(total_summary.get('attempted_topics', [])[:3]) or '없음'}"
    )


def step_collect() -> bool:
    logger.info("─── 1단계: 글감 수집 ───")
    try:
        import bots.collector_bot as collector_bot
        collector_bot.run()
        return True
    except Exception as e:
        logger.error(f"수집 실패: {e}")
        return False


def step_write(
    topic: str | None,
    corner: str,
    limit: int,
    skip_review: bool = False,
    exclude_files: set[str] | None = None,
) -> dict:
    """작성 결과와 시도한 토픽 메타데이터 반환"""
    logger.info("─── 2단계: 글 작성 ───")
    try:
        import bots.writer_bot as writer_bot
    except Exception as e:
        logger.error(f"writer_bot 로드 실패: {e}")
        return {'articles': [], 'attempted': []}

    originals_dir = DATA_DIR / 'originals'
    originals_dir.mkdir(parents=True, exist_ok=True)

    if topic:
        try:
            article = writer_bot.run_from_topic(topic, corner, skip_review=skip_review)
            article['_topic_data'] = {
                'topic': topic,
                'corner': corner,
                'description': '',
                'source': '',
                'published_at': article.get('published_at', ''),
                'quality_score': article.get('quality_score', 0),
            }
            return {'articles': [article], 'attempted': [{'file': '', 'title': topic, 'success': True}]}
        except Exception as e:
            logger.error(f"글 작성 실패 [{topic}]: {e}")
            return {'articles': [], 'attempted': [{'file': '', 'title': topic, 'success': False, 'error': str(e)}]}

    results = writer_bot.run_pending(
        limit=limit,
        skip_review=skip_review,
        corner=corner,
        exclude_files=exclude_files,
    )
    articles = []
    for r in results:
        if not r.get('success'):
            logger.warning(f"작성 실패: {r.get('file')} — {r.get('error')}")
            continue
        output_path = originals_dir / r['file']
        if not output_path.exists():
            logger.warning(f"작성 결과 파일 없음: {output_path}")
            continue
        try:
            article = json.loads(output_path.read_text(encoding='utf-8'))
            article['_output_path'] = str(output_path)
            topic_path = DATA_DIR / 'topics' / r['file']
            if topic_path.exists():
                try:
                    article['_topic_data'] = json.loads(topic_path.read_text(encoding='utf-8'))
                except Exception:
                    pass
            articles.append(article)
        except Exception as e:
            logger.error(f"결과 파일 읽기 실패 [{r['file']}]: {e}")
    return {'articles': articles, 'attempted': results}


def _should_retry_publish_reason(reason: str) -> bool:
    return '품질 점수' in reason and '자동 발행 최소' in reason


def _build_publish_retry_feedback(reason: str) -> str:
    return (
        f'발행 단계 피드백: {reason}\n'
        '- 자동 발행 기준을 넘기려면 제목, META, 첫 문단, 마지막 문단에서 독자가 바로 써먹을 기준과 결과를 더 선명하게 써.\n'
        '- 설명만 하지 말고 "무엇을 먼저 보면 오해가 줄어드는지", "다음에 어떤 문구를 확인하면 되는지"를 더 직접적으로 남겨.\n'
    )


def _save_pipeline_summary(summary: dict) -> None:
    PIPELINE_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _summarize_pipeline_run(writer_bot, summary: dict) -> None:
    failure_lessons = []
    success_lessons = []

    if summary.get('published', 0) > 0:
        success_lessons.append(f'- 이번 런에서는 자동 발행까지 바로 간 글이 {summary["published"]}편 있었다.')
    if summary.get('retried_then_published', 0) > 0:
        success_lessons.append(
            f'- 발행 게이트 피드백을 반영해 다시 쓰면 통과한 글이 {summary["retried_then_published"]}편 있었다.'
        )
    if summary.get('quality_gate_failures', 0) > 0:
        failure_lessons.append(
            f'- 이번 런에서 자동 발행 최소 품질 점수에 막힌 글이 {summary["quality_gate_failures"]}편 있었다. '
            '다음 글은 제목, META, 첫 문단, 마지막 문단에서 바로 써먹을 기준을 더 선명하게 써야 한다.'
        )
    if summary.get('manual_review', 0) > 0:
        failure_lessons.append(f'- 재작성 후에도 수동 검토로 남은 글이 {summary["manual_review"]}편 있었다.')

    reason_counts = summary.get('reason_counts', {})
    ranked_reasons = sorted(reason_counts.items(), key=lambda item: (-int(item[1]), item[0]))
    for reason, count in ranked_reasons[:3]:
        if count <= 0:
            continue
        failure_lessons.append(f'- 자주 막힌 사유 {count}회: {reason}')

    success_titles = summary.get('success_titles', [])[:2]
    for title in success_titles:
        success_lessons.append(f'- 이번 런 통과 예시 제목: {title}')

    if failure_lessons:
        writer_bot.register_pipeline_feedback('전체', '\n'.join(failure_lessons), success=False)
    if success_lessons:
        writer_bot.register_pipeline_feedback('전체', '\n'.join(success_lessons), success=True)

    summary['updated_at'] = datetime.now().isoformat()
    _save_pipeline_summary(summary)

    # 자가 개선: 검수 실패 패턴 분석 → heuristic_patterns.json 자동 업데이트
    try:
        import bots.self_improve as self_improve
        self_improve.run()
    except Exception as e:
        logger.warning(f"자가 개선 실행 실패 (비치명적): {e}")


def _merge_pipeline_summary(total: dict, partial: dict) -> dict:
    if not total:
        total = {
            'published': 0,
            'retried_then_published': 0,
            'quality_gate_failures': 0,
            'manual_review': 0,
            'reason_counts': {},
            'success_titles': [],
            'attempted_topics': [],
        }
    for key in ('published', 'retried_then_published', 'quality_gate_failures', 'manual_review'):
        total[key] = int(total.get(key, 0)) + int(partial.get(key, 0))
    for reason, count in (partial.get('reason_counts') or {}).items():
        total['reason_counts'][reason] = int(total['reason_counts'].get(reason, 0)) + int(count)
    total['success_titles'].extend(partial.get('success_titles') or [])
    total['attempted_topics'].extend(partial.get('attempted_topics') or [])
    return total


def _save_unpublished_originals(articles: list[dict]) -> None:
    """publisher_bot 로드 실패 시 원고를 originals/에 보존해 다음 실행에서 재발행 가능하게 함."""
    import json
    originals_dir = DATA_DIR / 'originals'
    originals_dir.mkdir(parents=True, exist_ok=True)
    for article in articles:
        file_key = article.get('_file', '')
        if file_key:
            path = originals_dir / file_key
        else:
            from datetime import datetime
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = originals_dir / f'{ts}_unpublished.json'
        if not path.exists():
            path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding='utf-8')
            logger.info(f"[미발행 원고 보존] {path.name}")


def _title_has_click_pattern(title: str) -> bool:
    """제목에 클릭 유발 패턴이 있는지 검사 (writer_review 공통 상수 사용)."""
    return any(p.search(title) for p in TITLE_STRONG_PATTERNS + TITLE_WEAK_PATTERNS)


def _filter_republishable(
    articles: list[dict],
) -> tuple[list[dict], list[dict]]:
    """재발행 대상 원고를 제목 검수로 필터링한다.

    - _write_quality_passed=True  → 검수 완료된 글, 바로 발행 허용
    - _write_quality_passed=False 또는 플래그 없음 → 제목 클릭 패턴 재검사
        - 통과 시: 발행 허용
        - 실패 시: 차단 (pending_review 이동 대상)

    Returns: (publishable, blocked)
    """
    publishable = []
    blocked = []

    for art in articles:
        quality_passed = art.get('_write_quality_passed')

        if quality_passed is True:
            # 모든 검수를 정상 통과한 글 — 신뢰하고 바로 발행
            publishable.append(art)
            continue

        # force-publish이거나 구버전(플래그 없음) → 제목 클릭 패턴 재검사
        title = art.get('title', '')
        if _title_has_click_pattern(title):
            logger.info(
                f"[재발행 검수] '{title}' — 제목 패턴 통과, 발행 허용"
                f" (force_published={quality_passed is False})"
            )
            publishable.append(art)
        else:
            logger.warning(
                f"[재발행 차단] '{title}' — 제목에 클릭 유발 패턴 없음. "
                f"pending_review로 이동 (재작성 필요)"
            )
            blocked.append(art)

    return publishable, blocked


def _save_blocked_to_pending(blocked: list[dict]) -> None:
    """재발행 차단된 원고를 pending_review/에 저장."""
    import json
    from datetime import datetime
    pending_dir = DATA_DIR / 'pending_review'
    pending_dir.mkdir(parents=True, exist_ok=True)

    for art in blocked:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        fname = f"{ts}_pending.json"
        path = pending_dir / fname
        payload = {**art, '_blocked_reason': '재발행 제목 검수 실패 — 클릭 유발 패턴 없음'}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f"[재발행 차단] pending_review 저장: {fname}")


def _load_unpublished_originals() -> list[dict]:
    """originals/에 있지만 published/ · pending_review/에 없는 원고를 반환 (발행 재시도 대상)."""
    import json
    originals_dir = DATA_DIR / 'originals'
    published_dir = DATA_DIR / 'published'
    pending_dir = DATA_DIR / 'pending_review'
    if not originals_dir.exists():
        return []

    done_slugs: set[str] = set()
    for d_dir in (published_dir, pending_dir):
        if not d_dir or not d_dir.exists():
            continue
        for f in d_dir.glob('*.json'):
            try:
                d = json.loads(f.read_text(encoding='utf-8'))
                slug = d.get('slug', '') or d.get('title', '')
                if slug:
                    done_slugs.add(slug)
            except Exception:
                pass

    # 오늘 생성된 원고만 재시도 (최근 10개, 오늘 날짜 파일)
    from datetime import date
    today_prefix = date.today().strftime('%Y%m%d')
    unpublished = []
    for f in sorted(originals_dir.glob(f'{today_prefix}_*.json'), reverse=True)[:10]:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            slug = d.get('slug', '') or d.get('title', '')
            if slug and slug not in done_slugs:
                d['_file'] = f.name
                unpublished.append(d)
        except Exception:
            pass
    if unpublished:
        logger.info(f"[미발행 원고] originals에서 {len(unpublished)}편 재발행 시도")
    return unpublished


def step_publish(articles: list[dict], summarize: bool = True) -> dict:
    logger.info("─── 3단계: 발행 ───")
    try:
        import bots.publisher_bot as publisher_bot
        import bots.writer_bot as writer_bot
    except Exception as e:
        logger.error(f"publisher_bot 로드 실패: {e}")
        _save_unpublished_originals(articles)
        return {}

    summary = {
        'published': 0,
        'retried_then_published': 0,
        'quality_gate_failures': 0,
        'manual_review': 0,
        'reason_counts': {},
        'success_titles': [],
        'attempted_topics': [],
    }

    for article in articles:
        title = article.get('title', '(제목 없음)')
        try:
            success, reason = publisher_bot.publish_with_result(article)
            if success:
                summary['published'] += 1
                summary['success_titles'].append(title)
                writer_bot.register_pipeline_feedback(
                    article.get('corner', '전체'),
                    f'- 발행 단계까지 바로 통과했다: {title}',
                    success=True,
                )
                logger.info(f"발행 완료: {title}")
                continue

            if _should_retry_publish_reason(reason):
                summary['quality_gate_failures'] += 1
                summary['reason_counts'][reason] = int(summary['reason_counts'].get(reason, 0)) + 1
                writer_bot.register_pipeline_feedback(
                    article.get('corner', '전체'),
                    f'- 발행 단계 자동 게이트 실패 (수동 검토로 저장): {reason}',
                    success=False,
                )
                # ── Fix: 동일 글감 재작성 무한 루프 방지 ──────────────────────────
                # 기존: 같은 출처 데이터로 write_article 재호출 → 동일한 실패 반복
                # 변경: pending_review에 저장하고 해당 글감은 종료
                # 이유: 출처 데이터 품질이 낮으면 재작성해도 동일 문제 발생,
                #       토큰 예산만 소진되고 발행도 안 되는 데드락 발생
                publisher_bot.save_pending_review(article, reason)
                logger.warning(f"품질 게이트 차단 — 수동 검토 저장 (재작성 루프 방지): {title} — {reason}")
            else:
                summary['manual_review'] += 1
                summary['reason_counts'][reason] = int(summary['reason_counts'].get(reason, 0)) + 1
                writer_bot.register_pipeline_feedback(
                    article.get('corner', '전체'),
                    f'- 발행 단계 수동 검토 사유: {reason}',
                    success=False,
                )
                publisher_bot.save_pending_review(article, reason)
                logger.warning(f"수동 검토 대기로 이동: {title}")
        except Exception as e:
            logger.error(f"발행 오류 [{title}]: {e}")

    if summarize:
        _summarize_pipeline_run(writer_bot, summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description='The 4th Path 전체 파이프라인 (수집→작성→발행)')
    parser.add_argument('--topic', type=str, default=None, help='직접 주제 지정 (수집 건너뜀)')
    parser.add_argument('--corner', type=str, default='쉬운세상', help='코너 지정 (기본: 쉬운세상)')
    parser.add_argument('--limit', type=int, default=1, help='최대 처리 글 수 (기본: 1)')
    parser.add_argument('--skip-collect', action='store_true', help='수집 단계 건너뜀')
    parser.add_argument('--skip-publish', action='store_true', help='작성만 하고 발행 안 함')
    parser.add_argument('--skip-review', action='store_true', help='AI/룰 기반 검수 건너뜀')
    parser.add_argument('--slot', type=str, default='10시', help='발행 슬롯 레이블 (알림 메시지용, 예: 10시, 17시)')
    args = parser.parse_args()

    _setup_signal_handlers()
    logger.info("=== 파이프라인 시작 (PID: %s) ===", os.getpid())

    # 1단계: 수집
    if args.topic:
        logger.info("주제 직접 지정 — 수집 단계 건너뜀")
    elif args.skip_collect:
        logger.info("--skip-collect — 수집 단계 건너뜀")
    else:
        ok = step_collect()
        if not ok:
            logger.error("수집 실패로 파이프라인 중단")
            _notify_pipeline_issue(
                f"⚠️ <b>{args.slot} 발행 자동화 실패</b>\n\n코너: {args.corner}\n단계: 수집\n사유: 글감 수집 실패"
            )
            sys.exit(1)

    # 1.5단계: 미발행 원고 재발행 시도 (이전 실행에서 publisher_bot 오류로 누락된 원고)
    if not args.skip_publish and not args.topic:
        unpublished = _load_unpublished_originals()
        if unpublished:
            # 재발행 경로는 generate_article()을 건너뛰므로 검수를 재실행해서 필터링
            publishable, blocked = _filter_republishable(unpublished)
            if blocked:
                _save_blocked_to_pending(blocked)
                logger.warning(
                    f"[재발행] {len(blocked)}편 제목 검수 실패 — pending_review 이동, "
                    f"{len(publishable)}편만 발행 진행"
                )
            if publishable:
                step_publish(publishable)

    # 2단계: 글 작성 / 3단계: 발행
    if args.skip_publish or args.topic:
        write_result = step_write(args.topic, args.corner, args.limit, skip_review=args.skip_review)
        articles = write_result['articles']
        if not articles:
            logger.warning("작성된 글 없음 — 파이프라인 종료")
            _notify_pipeline_issue(
                f"⚠️ <b>{args.slot} 발행 자동화 중단</b>\n\n코너: {args.corner}\n사유: 작성된 글이 없어 발행 단계로 진행하지 못함"
            )
            sys.exit(0)

        logger.info(f"작성 완료: {len(articles)}편")

        if args.skip_publish:
            logger.info("--skip-publish — 발행 단계 건너뜀")
        else:
            summary = step_publish(articles)
            if summary:
                logger.info(
                    "발행 요약: 바로 발행 %s편, 재작성 후 발행 %s편, 품질 게이트 실패 %s편, 수동 검토 %s편",
                    summary.get('published', 0),
                    summary.get('retried_then_published', 0),
                    summary.get('quality_gate_failures', 0),
                    summary.get('manual_review', 0),
                )
    else:
        target_publish_count = max(1, int(args.limit))
        attempted_writes = 0
        max_attempts = max(target_publish_count * 8, 8)
        blocked_topic_files: set[str] = set()
        total_summary = {
            'published': 0,
            'retried_then_published': 0,
            'quality_gate_failures': 0,
            'manual_review': 0,
            'reason_counts': {},
            'success_titles': [],
            'attempted_topics': [],
        }

        while (total_summary['published'] + total_summary['retried_then_published']) < target_publish_count and attempted_writes < max_attempts:
            write_result = step_write(
                None,
                args.corner,
                1,
                skip_review=args.skip_review,
                exclude_files=blocked_topic_files,
            )
            articles = write_result['articles']
            attempted = write_result['attempted']
            for item in attempted:
                title = item.get('title')
                if title:
                    total_summary['attempted_topics'].append(title)
                file_name = item.get('file')
                if file_name:
                    blocked_topic_files.add(file_name)
                if not item.get('success'):
                    reason = item.get('error') or '작성 실패'
                    total_summary['reason_counts'][reason] = int(total_summary['reason_counts'].get(reason, 0)) + 1

            attempted_writes += len(attempted)
            if not articles:
                if attempted:
                    logger.warning("이번 글감은 건너뜀 — 다음 우선순위 글감으로 이동")
                    continue
                logger.warning("추가로 작성할 글감 없음 — 파이프라인 종료")
                break

            logger.info(f"작성 완료: {len(articles)}편")
            partial = step_publish(articles, summarize=False)
            total_summary = _merge_pipeline_summary(total_summary, partial)

        try:
            import bots.writer_bot as writer_bot
            _summarize_pipeline_run(writer_bot, total_summary)
        except Exception as e:
            logger.warning(f"파이프라인 요약 저장 실패: {e}")

        logger.info(
            "발행 요약: 바로 발행 %s편, 재작성 후 발행 %s편, 품질 게이트 실패 %s편, 수동 검토 %s편",
            total_summary.get('published', 0),
            total_summary.get('retried_then_published', 0),
            total_summary.get('quality_gate_failures', 0),
            total_summary.get('manual_review', 0),
        )
        achieved = total_summary.get('published', 0) + total_summary.get('retried_then_published', 0)
        if achieved < target_publish_count:
            logger.warning("목표 발행 수 미달: 목표 %s편 / 실제 %s편", target_publish_count, achieved)
            _notify_pipeline_issue(
                _build_attempt_shortfall_message(
                    args.corner,
                    target_publish_count,
                    total_summary,
                    attempted_writes,
                    slot=args.slot,
                )
            )

    logger.info("=== 파이프라인 완료 ===")


if __name__ == '__main__':
    main()
