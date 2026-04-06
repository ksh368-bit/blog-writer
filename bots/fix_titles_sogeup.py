"""
제목 소급 수정 스크립트 (fix_titles_sogeup.py)
SEO 최적화 제목으로 Blogger 기발행 글 업데이트
"""
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from publisher_bot import get_google_credentials, BLOG_MAIN_ID
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# post_id → 새 제목
TITLE_FIXES = {
    '6086211194754031920': '미국이 해상 재보험을 400억 달러로 늘린 이유 — 호르무즈 해협 리스크 완전 정리',
    '1513003684426052335': 'AI 조직이 사람 없이 자체 버그를 고치는 방법 — 2026년 AI 경영 5가지 원칙',
    '4100582485918689982': 'Physical AI에 VC가 다시 몰리는 이유 — 휴머노이드 로봇 투자 사이클 완전 정리',
    '5979641181749518402': 'Google Gemma 4 완전 정리 — 4가지 모델 크기와 멀티모달 기능 비교',
    '2176445137932542353': 'Ravenclaw로 Claude Code·Gemini CLI 작업 맥락 공유하는 법',
    '7342191678383834055': 'Claude Code 내부 구조 완전 분석 — 804개 파일과 에이전트 루프 동작 원리',
    '5626446161597869343': 'LLM-Wiki로 개인 지식저장소 만드는 법 — Andrej Karpathy 방식 따라하기',
}


def main(dry_run: bool = False):
    if not BLOG_MAIN_ID:
        logger.error("BLOG_MAIN_ID 환경변수 없음 — 종료")
        return

    if dry_run:
        logger.info(f"[DRY RUN] {len(TITLE_FIXES)}개 제목 수정 예정")
        for post_id, title in TITLE_FIXES.items():
            print(f"  {post_id} → {title}")
        return

    creds = get_google_credentials()
    service = build('blogger', 'v3', credentials=creds)

    success = 0
    for post_id, new_title in TITLE_FIXES.items():
        try:
            service.posts().patch(
                blogId=BLOG_MAIN_ID,
                postId=post_id,
                body={'title': new_title},
            ).execute()
            logger.info(f"✓ [{post_id}] → {new_title}")
            success += 1
        except Exception as e:
            logger.error(f"✗ [{post_id}] 실패: {e}")

    logger.info(f"\n제목 수정 완료: {success}/{len(TITLE_FIXES)}개 성공")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    main(dry_run=args.dry_run)
