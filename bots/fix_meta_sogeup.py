"""
META 소급 수정 스크립트 (fix_meta_sogeup.py)
이미 발행된 Blogger 글 중 플레이스홀더 META가 있는 글을 찾아
본문 첫 문장으로 searchDescription을 업데이트한다.
"""
import json
import logging
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from publisher_bot import (
    _META_PLACEHOLDERS,
    get_google_credentials,
    BLOG_MAIN_ID,
)
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

DATA_DIR = BASE_DIR / 'data'
PUBLISHED_DIR = DATA_DIR / 'published'
ORIGINALS_DIR = DATA_DIR / 'originals'


def _extract_meta_clean(body: str, title: str = '') -> str:
    """
    본문 HTML에서 첫 번째 실제 <p> 태그 텍스트를 META로 추출.
    H2/H3 헤더는 건너뜀. 줄바꿈 정리 후 160자 이내로 반환.
    """
    soup = BeautifulSoup(body or '', 'html.parser')
    for p in soup.find_all('p'):
        text = p.get_text(separator=' ', strip=True)
        # 짧은 레이블, 날짜, 소제목 형태 제외
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) < 20:
            continue
        # 소제목처럼 끝이 ":" 혹은 줄바꿈 없이 짧은 문장 제외
        if text.endswith(':') or text.endswith('—'):
            continue
        return text[:160]
    # fallback: 전체 텍스트 첫 문장
    plain = soup.get_text(separator=' ', strip=True)
    plain = re.sub(r'\s+', ' ', plain)
    first = re.split(r'(?<=[.!?다])\s', plain)[0][:160].strip()
    return first if len(first) >= 20 else ''


def _load_originals_by_title() -> dict[str, dict]:
    """originals/*.json → {title: article_dict}"""
    result = {}
    for f in ORIGINALS_DIR.glob('*.json'):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            title = d.get('title', '').strip()
            if title:
                # 같은 제목이 여러 개면 최신 파일 우선 (파일명이 날짜순)
                if title not in result or f.name > result[title].get('_fname', ''):
                    d['_fname'] = f.name
                    result[title] = d
        except Exception as e:
            logger.debug(f"originals 로드 실패 {f.name}: {e}")
    return result


def _is_placeholder(meta: str) -> bool:
    return not meta.strip() or any(ph in meta for ph in _META_PLACEHOLDERS)


def collect_targets(dry_run: bool = False) -> list[dict]:
    """플레이스홀더 META가 있는 발행 글 목록 반환"""
    originals = _load_originals_by_title()
    targets = []

    for f in sorted(PUBLISHED_DIR.glob('*.json')):
        d = json.loads(f.read_text(encoding='utf-8'))
        post_id = d.get('post_id', '')
        title = d.get('title', '').strip()

        if not post_id or title in ('테스트 글',):
            continue

        orig = originals.get(title)
        if not orig:
            logger.warning(f"originals 매칭 실패 — 건너뜀: {title[:40]}")
            continue

        current_meta = orig.get('meta', '')
        if not _is_placeholder(current_meta):
            logger.info(f"META 정상 — 건너뜀: {title[:40]}")
            continue

        new_meta = _extract_meta_clean(orig.get('body', ''), title)
        if not new_meta:
            logger.warning(f"META 추출 실패 — 건너뜀: {title[:40]}")
            continue

        targets.append({
            'post_id': post_id,
            'title': title,
            'old_meta': current_meta,
            'new_meta': new_meta,
            '_orig_file': orig.get('_fname', ''),
        })
        logger.info(f"대상 발견: [{post_id}] {title[:40]}")
        logger.info(f"  → {new_meta[:80]}…")

    return targets


def patch_blogger_meta(targets: list[dict], dry_run: bool = False) -> None:
    """Blogger API posts().patch()로 customMetaData 업데이트"""
    if not targets:
        logger.info("수정할 글 없음.")
        return

    if not BLOG_MAIN_ID:
        logger.error("BLOG_MAIN_ID 환경변수 없음 — 종료")
        return

    if dry_run:
        logger.info(f"[DRY RUN] {len(targets)}개 글을 수정할 예정 (실제 API 호출 없음)")
        for t in targets:
            print(f"  post_id={t['post_id']} | {t['title'][:40]}")
            print(f"    new_meta: {t['new_meta'][:80]}")
        return

    creds = get_google_credentials()
    service = build('blogger', 'v3', credentials=creds)

    success = 0
    for t in targets:
        try:
            service.posts().patch(
                blogId=BLOG_MAIN_ID,
                postId=t['post_id'],
                body={'customMetaData': t['new_meta']},
            ).execute()
            logger.info(f"✓ 수정 완료: [{t['post_id']}] {t['title'][:40]}")
            logger.info(f"  META: {t['new_meta'][:80]}")
            success += 1
        except Exception as e:
            logger.error(f"✗ 수정 실패: [{t['post_id']}] {t['title'][:40]} — {e}")

    logger.info(f"\n소급 수정 완료: {success}/{len(targets)}개 성공")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='META 소급 수정')
    parser.add_argument('--dry-run', action='store_true', help='실제 API 호출 없이 대상만 확인')
    args = parser.parse_args()

    logger.info("=== META 소급 수정 시작 ===")
    targets = collect_targets()
    patch_blogger_meta(targets, dry_run=args.dry_run)
    logger.info("=== META 소급 수정 종료 ===")


if __name__ == '__main__':
    main()
