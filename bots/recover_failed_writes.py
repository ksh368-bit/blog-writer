"""
실패 원고 복구 스크립트 (recover_failed_writes.py)

실패 유형별 처리:
  - body=0 (엔진 빈 응답): 글감으로 복구 → data/topics/ 재등록
  - body<200 (시간 초과):  글감으로 복구 → data/topics/ 재등록
  - body>=200 (재시도 소진): 발행 가능 여부 확인 후 직접 발행 시도
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

FAILED_DIR = BASE_DIR / 'data' / 'failed_writes'
TOPICS_DIR = BASE_DIR / 'data' / 'topics'
ORIGINALS_DIR = BASE_DIR / 'data' / 'originals'

# 발행 가능 판단 최소 body 길이
MIN_PUBLISHABLE_BODY = 200

TOPIC_FIELDS = [
    'topic', 'description', 'source', 'source_name', 'source_url',
    'published_at', 'quality_score', 'corner', 'coupang_keywords',
    'search_demand_score', 'topic_type', 'source_trust_level',
    'korean_relevance_score', 'is_evergreen', 'topic_fit_score',
    'novelty_score', 'impact_score', 'trending_since',
    'sources', 'related_keywords',
]


def _is_already_written(topic: str) -> bool:
    """같은 topic이 originals나 topics에 이미 있는지 확인"""
    for f in ORIGINALS_DIR.glob('*.json'):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            if d.get('topic', '').strip() == topic.strip():
                return True
        except Exception:
            pass
    for f in TOPICS_DIR.glob('*.json'):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            if d.get('topic', '').strip() == topic.strip():
                return True
        except Exception:
            pass
    return False


def recover_as_topic(failed: dict, stem: str) -> bool:
    """실패 원고를 글감으로 복구해 topics/ 재등록"""
    topic = failed.get('topic', '').strip()
    if not topic:
        logger.warning(f"topic 필드 없음 — 건너뜀: {stem}")
        return False

    if _is_already_written(topic):
        logger.info(f"이미 작성/등록된 글감 — 건너뜀: {topic[:50]}")
        return False

    topic_data = {k: failed.get(k, '') for k in TOPIC_FIELDS}
    topic_data['topic'] = topic
    topic_data['_recovered_from'] = stem
    topic_data['_recovered_at'] = datetime.now().isoformat()

    out_path = TOPICS_DIR / f"recovered_{stem}.json"
    out_path.write_text(json.dumps(topic_data, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"✓ 글감 복구: {topic[:50]} → {out_path.name}")
    return True


def try_publish(failed: dict, stem: str, dry_run: bool = False) -> bool:
    """body가 충분한 실패 원고를 originals로 이동 후 발행 시도"""
    title = failed.get('title', '').strip()
    body = failed.get('body', '').strip()
    if not title or not body:
        logger.warning(f"title/body 없음 — 글감으로 복구 전환: {stem}")
        return recover_as_topic(failed, stem)

    # originals에 저장
    slug = failed.get('slug') or stem
    out_path = ORIGINALS_DIR / f"recovered_{stem}.json"

    article = dict(failed)
    article.pop('failed_reason', None)
    article.pop('last_feedback', None)
    article.pop('failed_at', None)
    article['status'] = 'recovered'
    article['_recovered_from'] = stem
    article['_recovered_at'] = datetime.now().isoformat()

    if dry_run:
        logger.info(f"[DRY RUN] 발행 시도 예정: {title[:50]} (body {len(body)}자)")
        return True

    out_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding='utf-8')

    # pipeline의 publish 단계 직접 호출
    try:
        import publisher_bot
        import linker_bot

        creds = publisher_bot.get_google_credentials()
        body_html, toc_html = publisher_bot.markdown_to_html(body)
        html = publisher_bot.build_full_html(article, body_html, toc_html)
        html = linker_bot.process(article, html)
        html = publisher_bot.sanitize_html(html)

        result = publisher_bot.publish_to_blogger(article, html, creds, is_draft=False)
        publisher_bot.log_published(article, result)
        publisher_bot.submit_to_search_console(result.get('url', ''), creds)
        logger.info(f"✓ 발행 완료: {title[:50]} → {result.get('url','')}")
        return True
    except Exception as e:
        logger.error(f"✗ 발행 실패: {title[:50]} — {e}")
        # 발행 실패해도 originals에는 남겨둠
        return False


def main(dry_run: bool = False):
    logger.info("=== 실패 원고 복구 시작 ===")
    TOPICS_DIR.mkdir(parents=True, exist_ok=True)

    recovered_topic = 0
    attempted_publish = 0
    skipped = 0

    for f in sorted(FAILED_DIR.glob('*.json')):
        if f.stem.startswith('test_'):
            continue
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"읽기 실패 {f.name}: {e}")
            continue

        body_len = len(d.get('body', ''))
        reason = d.get('failed_reason', '')
        topic = d.get('topic', '')[:50]

        logger.info(f"\n{f.name} | body={body_len} | {reason[:40]}")

        # body가 있어도 품질 미달로 실패한 원고는 글감으로 복구 후 파이프라인 재작성
        logger.info(f"  → 글감 복구: {topic}")
        ok = recover_as_topic(d, f.stem)
        if ok:
            recovered_topic += 1
        else:
            skipped += 1

    logger.info(f"\n=== 복구 완료 ===")
    logger.info(f"글감 재등록: {recovered_topic}개")
    logger.info(f"발행 시도:   {attempted_publish}개")
    logger.info(f"건너뜀:      {skipped}개")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='실패 원고 복구')
    parser.add_argument('--dry-run', action='store_true', help='실제 발행 없이 확인만')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
