"""
스케줄러 (scheduler.py)
역할: 모든 봇의 실행 시간 관리 + Telegram 수동 명령 리스너
라이브러리: APScheduler + python-telegram-bot
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import anthropic

load_dotenv()

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

log_handler = RotatingFileHandler(
    LOG_DIR / 'scheduler.log',
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8',
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[log_handler, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

_claude_client: anthropic.Anthropic | None = None
_conversation_history: dict[int, list] = {}

CLAUDE_SYSTEM_PROMPT = """당신은 The 4th Path 블로그 자동 수익 엔진의 AI 어시스턴트입니다.
이 시스템(v3)은 4계층 구조로 운영됩니다:

[LAYER 1] AI 콘텐츠 생성: OpenClaw(GPT-5.4)가 원본 마크다운 1개 생성
[LAYER 2] 변환 엔진: 원본 → 블로그HTML / 인스타카드 / X스레드 / 뉴스레터 자동 변환
[LAYER 3] 배포 엔진: Blogger / Instagram / X / TikTok / YouTube 순차 발행
[LAYER 4] 분석봇: 성과 수집 + 주간 리포트 + 피드백 루프

봇 구성:
- collector_bot: 트렌드/RSS 수집 (07:00)
- ai_writer: OpenClaw 글 작성 트리거 (08:00)
- blog_converter: 마크다운→HTML (08:30)
- card_converter: 인스타 카드 1080×1080 (08:30)
- thread_converter: X 스레드 변환 (08:30)
- publisher_bot: Blogger 발행 (09:00)
- instagram_bot: 인스타 발행 (10:00)
- x_bot: X 스레드 게시 (11:00)
- analytics_bot: 분석/리포트 (22:00)

사용 가능한 텔레그램 명령:
/status — 봇 상태
/topics — 오늘 수집된 글감
/pending — 검토 대기 글 목록
/approve [번호] — 글 승인 및 발행
/reject [번호] — 글 거부
/report — 주간 리포트
/images — 이미지 제작 현황
/convert — 수동 변환 실행

사용자의 자연어 요청을 이해하고 적절히 안내하거나 답변해주세요.
한국어로 간결하게 답변하세요."""
IMAGE_MODE = os.getenv('IMAGE_MODE', 'manual').lower()
# request 모드에서 이미지 대기 시 사용하는 상태 변수
# {chat_id: prompt_id} — 다음에 받은 이미지를 어느 프롬프트에 연결할지 기억
_awaiting_image: dict[int, str] = {}

_publish_enabled = True


def load_schedule() -> dict:
    with open(CONFIG_DIR / 'schedule.json', 'r', encoding='utf-8') as f:
        return json.load(f)


# ─── 스케줄 작업 ──────────────────────────────────────

def job_collector():
    logger.info("[스케줄] 수집봇 시작")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import collector_bot
        collector_bot.run()
    except Exception as e:
        logger.error(f"수집봇 오류: {e}")


def job_ai_writer():
    logger.info("[스케줄] AI 글 작성 트리거")
    if not _publish_enabled:
        logger.info("발행 중단 상태 — 건너뜀")
        return
    try:
        _trigger_openclaw_writer()
    except Exception as e:
        logger.error(f"AI 글 작성 트리거 오류: {e}")


def _trigger_openclaw_writer():
    topics_dir = DATA_DIR / 'topics'
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    topic_files = sorted(topics_dir.glob(f'{today}_*.json'))
    if not topic_files:
        logger.info("오늘 처리할 글감 없음")
        return
    for topic_file in topic_files[:3]:
        draft_check = drafts_dir / topic_file.name
        if draft_check.exists():
            continue
        topic_data = json.loads(topic_file.read_text(encoding='utf-8'))
        logger.info(f"글 작성 요청: {topic_data.get('topic', '')}")
        _call_openclaw(topic_data, draft_check)


def _call_openclaw(topic_data: dict, output_path: Path):
    logger.info(f"OpenClaw 호출 (플레이스홀더): {topic_data.get('topic', '')}")
    # OpenClaw 연동 완료 후 아래 주석 해제:
    # import subprocess
    # result = subprocess.run(
    #     ['openclaw', 'run', 'blog-writer', '--input', json.dumps(topic_data)],
    #     capture_output=True, text=True
    # )
    # output = result.stdout
    topic_data['_pending_openclaw'] = True
    output_path.write_text(json.dumps(topic_data, ensure_ascii=False, indent=2), encoding='utf-8')


def job_convert():
    """08:30 — 변환 엔진: 원본 마크다운 → 5개 포맷 생성"""
    if not _publish_enabled:
        logger.info("[스케줄] 발행 중단 — 변환 건너뜀")
        return
    logger.info("[스케줄] 변환 엔진 시작")
    try:
        _run_conversion_pipeline()
    except Exception as e:
        logger.error(f"변환 엔진 오류: {e}")


def _run_conversion_pipeline():
    """originals/ 폴더의 미변환 원본을 5개 포맷으로 변환"""
    originals_dir = DATA_DIR / 'originals'
    originals_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    converters_path = str(BASE_DIR / 'bots' / 'converters')
    sys.path.insert(0, converters_path)
    sys.path.insert(0, str(BASE_DIR / 'bots'))

    for orig_file in sorted(originals_dir.glob(f'{today}_*.json')):
        converted_flag = orig_file.with_suffix('.converted')
        if converted_flag.exists():
            continue
        try:
            article = json.loads(orig_file.read_text(encoding='utf-8'))
            slug = article.get('slug', 'article')

            # 1. 블로그 HTML
            import blog_converter
            blog_converter.convert(article, save_file=True)

            # 2. 인스타 카드
            import card_converter
            card_path = card_converter.convert(article, save_file=True)
            if card_path:
                article['_card_path'] = card_path

            # 3. X 스레드
            import thread_converter
            thread_converter.convert(article, save_file=True)

            # 4. 쇼츠 영상 (Phase 2 — card 생성 후 시도, 실패해도 계속)
            if card_path:
                try:
                    import shorts_converter
                    shorts_converter.convert(article, card_path=card_path, save_file=True)
                except Exception as shorts_err:
                    logger.debug(f"쇼츠 변환 건너뜀 (Phase 2): {shorts_err}")

            # 5. 뉴스레터 발췌 (주간 묶음용 — 개별 저장은 weekly_report에서)
            # newsletter_converter는 주간 단위로 묶어서 처리

            # 변환 완료 플래그
            converted_flag.touch()
            logger.info(f"변환 완료: {slug}")

            # drafts에 복사 (발행봇이 읽도록)
            drafts_dir = DATA_DIR / 'drafts'
            drafts_dir.mkdir(exist_ok=True)
            draft_path = drafts_dir / orig_file.name
            if not draft_path.exists():
                draft_path.write_text(
                    orig_file.read_text(encoding='utf-8'), encoding='utf-8'
                )
        except Exception as e:
            logger.error(f"변환 오류 ({orig_file.name}): {e}")


def job_publish(slot: int):
    """09:00 — 블로그 발행 (슬롯별)"""
    if not _publish_enabled:
        logger.info(f"[스케줄] 발행 중단 — 슬롯 {slot} 건너뜀")
        return
    logger.info(f"[스케줄] 발행봇 (슬롯 {slot})")
    try:
        _publish_next()
    except Exception as e:
        logger.error(f"발행봇 오류: {e}")


def job_distribute_instagram():
    """10:00 — 인스타그램 카드 발행"""
    if not _publish_enabled:
        return
    logger.info("[스케줄] 인스타그램 발행")
    try:
        _distribute_instagram()
    except Exception as e:
        logger.error(f"인스타그램 배포 오류: {e}")


def _distribute_instagram():
    sys.path.insert(0, str(BASE_DIR / 'bots' / 'distributors'))
    import instagram_bot
    today = datetime.now().strftime('%Y%m%d')
    outputs_dir = DATA_DIR / 'outputs'
    for card_file in sorted(outputs_dir.glob(f'{today}_*_card.png')):
        ig_flag = card_file.with_suffix('.ig_done')
        if ig_flag.exists():
            continue
        slug = card_file.stem.replace(f'{today}_', '').replace('_card', '')
        article = _load_article_by_slug(today, slug)
        if not article:
            logger.warning(f"Instagram: 원본 article 없음 ({slug})")
            continue
        # image_host.py가 로컬 경로 → 공개 URL 변환 처리
        success = instagram_bot.publish_card(article, str(card_file))
        if success:
            ig_flag.touch()
            logger.info(f"Instagram 발행 완료: {card_file.name}")


def job_distribute_x():
    """11:00 — X 스레드 게시"""
    if not _publish_enabled:
        return
    logger.info("[스케줄] X 스레드 게시")
    try:
        _distribute_x()
    except Exception as e:
        logger.error(f"X 배포 오류: {e}")


def _distribute_x():
    sys.path.insert(0, str(BASE_DIR / 'bots' / 'distributors'))
    import x_bot
    today = datetime.now().strftime('%Y%m%d')
    outputs_dir = DATA_DIR / 'outputs'
    for thread_file in sorted(outputs_dir.glob(f'{today}_*_thread.json')):
        x_flag = thread_file.with_suffix('.x_done')
        if x_flag.exists():
            continue
        slug = thread_file.stem.replace(f'{today}_', '').replace('_thread', '')
        article = _load_article_by_slug(today, slug)
        if not article:
            continue
        thread_data = json.loads(thread_file.read_text(encoding='utf-8'))
        success = x_bot.publish_thread(article, thread_data)
        if success:
            x_flag.touch()


def job_distribute_tiktok():
    """18:00 — TikTok 쇼츠 업로드"""
    if not _publish_enabled:
        return
    logger.info("[스케줄] TikTok 쇼츠 업로드")
    try:
        _distribute_shorts('tiktok')
    except Exception as e:
        logger.error(f"TikTok 배포 오류: {e}")


def job_distribute_youtube():
    """20:00 — YouTube 쇼츠 업로드"""
    if not _publish_enabled:
        return
    logger.info("[스케줄] YouTube 쇼츠 업로드")
    try:
        _distribute_shorts('youtube')
    except Exception as e:
        logger.error(f"YouTube 배포 오류: {e}")


def _distribute_shorts(platform: str):
    """틱톡/유튜브 쇼츠 MP4 배포 공통 로직"""
    sys.path.insert(0, str(BASE_DIR / 'bots' / 'distributors'))
    if platform == 'tiktok':
        import tiktok_bot as dist_bot
    else:
        import youtube_bot as dist_bot

    today = datetime.now().strftime('%Y%m%d')
    outputs_dir = DATA_DIR / 'outputs'
    for shorts_file in sorted(outputs_dir.glob(f'{today}_*_shorts.mp4')):
        done_flag = shorts_file.with_suffix(f'.{platform}_done')
        if done_flag.exists():
            continue
        slug = shorts_file.stem.replace(f'{today}_', '').replace('_shorts', '')
        article = _load_article_by_slug(today, slug)
        if not article:
            logger.warning(f"{platform}: 원본 article 없음 ({slug})")
            continue
        success = dist_bot.publish_shorts(article, str(shorts_file))
        if success:
            done_flag.touch()


def _load_article_by_slug(date_str: str, slug: str) -> dict:
    """날짜+slug로 원본 article 로드"""
    originals_dir = DATA_DIR / 'originals'
    for f in originals_dir.glob(f'{date_str}_*{slug}*.json'):
        try:
            return json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _publish_next():
    drafts_dir = DATA_DIR / 'drafts'
    drafts_dir.mkdir(exist_ok=True)
    for draft_file in sorted(drafts_dir.glob('*.json')):
        try:
            article = json.loads(draft_file.read_text(encoding='utf-8'))
            if article.get('_pending_openclaw'):
                continue
            sys.path.insert(0, str(BASE_DIR / 'bots'))
            sys.path.insert(0, str(BASE_DIR / 'bots' / 'converters'))
            import publisher_bot
            import blog_converter
            # 변환봇으로 HTML 생성 (이미 변환된 경우 outputs에서 읽음)
            html = blog_converter.convert(article, save_file=False)
            article['_html_content'] = html
            article['_body_is_html'] = True
            publisher_bot.publish(article)
            draft_file.unlink(missing_ok=True)
            break
        except Exception as e:
            logger.error(f"드래프트 처리 오류 ({draft_file.name}): {e}")


def job_analytics_daily():
    logger.info("[스케줄] 분석봇 일일 리포트")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import analytics_bot
        analytics_bot.daily_report()
    except Exception as e:
        logger.error(f"분석봇 오류: {e}")


def job_analytics_weekly():
    logger.info("[스케줄] 분석봇 주간 리포트")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import analytics_bot
        analytics_bot.weekly_report()
    except Exception as e:
        logger.error(f"분석봇 주간 리포트 오류: {e}")


def job_image_prompt_batch():
    """request 모드 전용 — 매주 월요일 10:00 프롬프트 배치 전송"""
    if IMAGE_MODE != 'request':
        return
    logger.info("[스케줄] 이미지 프롬프트 배치 전송")
    try:
        sys.path.insert(0, str(BASE_DIR / 'bots'))
        import image_bot
        image_bot.send_prompt_batch()
    except Exception as e:
        logger.error(f"이미지 배치 오류: {e}")


# ─── Telegram 명령 핸들러 ────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "🟢 발행 활성" if _publish_enabled else "🔴 발행 중단"
    mode_label = {'manual': '수동', 'request': '요청', 'auto': '자동'}.get(IMAGE_MODE, IMAGE_MODE)
    await update.message.reply_text(
        f"블로그 엔진 상태: {status}\n이미지 모드: {mode_label} ({IMAGE_MODE})"
    )


async def cmd_stop_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _publish_enabled
    _publish_enabled = False
    await update.message.reply_text("🔴 발행이 중단되었습니다.")


async def cmd_resume_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _publish_enabled
    _publish_enabled = True
    await update.message.reply_text("🟢 발행이 재개되었습니다.")


async def cmd_show_topics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topics_dir = DATA_DIR / 'topics'
    today = datetime.now().strftime('%Y%m%d')
    files = sorted(topics_dir.glob(f'{today}_*.json'))
    if not files:
        await update.message.reply_text("오늘 수집된 글감이 없습니다.")
        return
    lines = [f"📋 오늘 수집된 글감 ({len(files)}개):"]
    for f in files[:10]:
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            lines.append(f"  [{data.get('quality_score',0)}점][{data.get('corner','')}] {data.get('topic','')[:50]}")
        except Exception:
            pass
    await update.message.reply_text('\n'.join(lines))


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import publisher_bot
    pending = publisher_bot.get_pending_list()
    if not pending:
        await update.message.reply_text("수동 검토 대기 글이 없습니다.")
        return
    lines = [f"🔍 수동 검토 대기 ({len(pending)}개):"]
    for i, item in enumerate(pending[:5], 1):
        lines.append(f"  {i}. [{item.get('corner','')}] {item.get('title','')[:50]}")
        lines.append(f"     사유: {item.get('pending_reason','')}")
    lines.append("\n/approve [번호]  /reject [번호]")
    await update.message.reply_text('\n'.join(lines))


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import publisher_bot
    pending = publisher_bot.get_pending_list()
    if not pending:
        await update.message.reply_text("대기 글이 없습니다.")
        return
    args = context.args
    idx = int(args[0]) - 1 if args and args[0].isdigit() else 0
    if not (0 <= idx < len(pending)):
        await update.message.reply_text("잘못된 번호입니다.")
        return
    success = publisher_bot.approve_pending(pending[idx].get('_filepath', ''))
    await update.message.reply_text(
        f"✅ 승인 완료: {pending[idx].get('title','')}" if success else "❌ 발행 실패. 로그 확인."
    )


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import publisher_bot
    pending = publisher_bot.get_pending_list()
    if not pending:
        await update.message.reply_text("대기 글이 없습니다.")
        return
    args = context.args
    idx = int(args[0]) - 1 if args and args[0].isdigit() else 0
    if not (0 <= idx < len(pending)):
        await update.message.reply_text("잘못된 번호입니다.")
        return
    publisher_bot.reject_pending(pending[idx].get('_filepath', ''))
    await update.message.reply_text(f"🗑 거부 완료: {pending[idx].get('title','')}")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("주간 리포트 생성 중...")
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import analytics_bot
    analytics_bot.weekly_report()


async def cmd_convert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """수동 변환 실행"""
    await update.message.reply_text("변환 엔진 실행 중...")
    try:
        _run_conversion_pipeline()
        outputs_dir = DATA_DIR / 'outputs'
        today = datetime.now().strftime('%Y%m%d')
        blogs = len(list(outputs_dir.glob(f'{today}_*_blog.html')))
        cards = len(list(outputs_dir.glob(f'{today}_*_card.png')))
        threads = len(list(outputs_dir.glob(f'{today}_*_thread.json')))
        await update.message.reply_text(
            f"변환 완료\n"
            f"블로그 HTML: {blogs}개\n"
            f"인스타 카드: {cards}개\n"
            f"X 스레드: {threads}개"
        )
    except Exception as e:
        await update.message.reply_text(f"변환 오류: {e}")


# ─── 이미지 관련 명령 (request 모드) ────────────────

async def cmd_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """대기 중인 이미지 프롬프트 목록 표시"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot
    pending = image_bot.get_pending_prompts('pending')
    selected = image_bot.get_pending_prompts('selected')
    done = image_bot.get_pending_prompts('done')

    if not pending and not selected:
        await update.message.reply_text(
            f"🎨 대기 중인 이미지 요청이 없습니다.\n"
            f"완료된 이미지: {len(done)}개\n\n"
            f"/imgbatch — 지금 바로 배치 전송 요청"
        )
        return

    lines = [f"🎨 이미지 제작 현황\n"]
    if pending:
        lines.append(f"⏳ 대기 ({len(pending)}건):")
        for p in pending:
            lines.append(f"  #{p['id']} {p['topic'][:40]}")
    if selected:
        lines.append(f"\n🔄 진행 중 ({len(selected)}건):")
        for p in selected:
            lines.append(f"  #{p['id']} {p['topic'][:40]}")
    lines.append(f"\n✅ 완료: {len(done)}건")
    lines.append(
        f"\n/imgpick [번호] — 프롬프트 받기\n"
        f"/imgbatch — 전체 목록 재전송"
    )
    await update.message.reply_text('\n'.join(lines))


async def cmd_imgpick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """특정 번호 프롬프트 선택 → 전체 프롬프트 전송 + 이미지 대기 상태 진입"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("사용법: /imgpick [번호]\n예) /imgpick 3")
        return

    prompt_id = args[0]
    prompt = image_bot.get_prompt_by_id(prompt_id)
    if not prompt:
        await update.message.reply_text(f"#{prompt_id} 번 프롬프트를 찾을 수 없습니다.\n/images 로 목록 확인")
        return

    if prompt['status'] == 'done':
        await update.message.reply_text(f"#{prompt_id} 는 이미 완료된 항목입니다.")
        return

    # 단일 프롬프트 전송 (Telegram 메시지 길이 제한 고려해 분리 전송)
    image_bot.send_single_prompt(prompt_id)

    # 이미지 대기 상태 등록
    chat_id = update.message.chat_id
    _awaiting_image[chat_id] = prompt_id
    logger.info(f"이미지 대기 등록: chat={chat_id}, prompt=#{prompt_id}")


async def cmd_imgbatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """전체 대기 프롬프트 배치 전송 (수동 트리거)"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot
    image_bot.send_prompt_batch()
    await update.message.reply_text("📤 프롬프트 배치 전송 완료.")


async def cmd_imgcancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """이미지 대기 상태 취소"""
    chat_id = update.message.chat_id
    if chat_id in _awaiting_image:
        pid = _awaiting_image.pop(chat_id)
        await update.message.reply_text(f"❌ #{pid} 이미지 대기 취소.")
    else:
        await update.message.reply_text("현재 대기 중인 이미지 요청이 없습니다.")


# ─── 이미지/파일 수신 핸들러 ─────────────────────────

async def _receive_image(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         file_getter, caption: str):
    """공통 이미지 수신 처리 (photo / document)"""
    sys.path.insert(0, str(BASE_DIR / 'bots'))
    import image_bot

    chat_id = update.message.chat_id

    # 프롬프트 ID 결정: 대기 상태 > 캡션 파싱 > 없음
    prompt_id = _awaiting_image.get(chat_id)
    if not prompt_id and caption:
        # 캡션에 #번호 형식이 있으면 추출
        m = __import__('re').search(r'#(\d+)', caption)
        if m:
            prompt_id = m.group(1)

    if not prompt_id:
        await update.message.reply_text(
            "⚠ 어느 주제의 이미지인지 알 수 없습니다.\n\n"
            "방법 1: /imgpick [번호] 로 먼저 선택 후 이미지 전송\n"
            "방법 2: 이미지 캡션에 #번호 입력 (예: #3)\n\n"
            "/images — 현재 대기 목록 확인"
        )
        return

    # Telegram에서 파일 다운로드
    try:
        tg_file = await file_getter()
        file_bytes = (await tg_file.download_as_bytearray())
    except Exception as e:
        await update.message.reply_text(f"❌ 파일 다운로드 실패: {e}")
        return

    # 저장 및 프롬프트 완료 처리
    image_path = image_bot.save_image_from_telegram(bytes(file_bytes), prompt_id)
    if not image_path:
        await update.message.reply_text(f"❌ 저장 실패. #{prompt_id} 번이 존재하는지 확인하세요.")
        return

    # 대기 상태 해제
    _awaiting_image.pop(chat_id, None)

    prompt = image_bot.get_prompt_by_id(prompt_id)
    topic = prompt['topic'] if prompt else ''
    await update.message.reply_text(
        f"✅ <b>이미지 저장 완료!</b>\n\n"
        f"#{prompt_id} {topic}\n"
        f"경로: <code>{image_path}</code>\n\n"
        f"이 이미지는 해당 만평 글 발행 시 자동으로 사용됩니다.",
        parse_mode='HTML',
    )
    logger.info(f"이미지 수령 완료: #{prompt_id} → {image_path}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram 사진 수신"""
    caption = update.message.caption or ''
    photo = update.message.photo[-1]  # 가장 큰 해상도
    await _receive_image(
        update, context,
        file_getter=lambda: context.bot.get_file(photo.file_id),
        caption=caption,
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telegram 파일(문서) 수신 — 고해상도 이미지 전송 시"""
    doc = update.message.document
    mime = doc.mime_type or ''
    if not mime.startswith('image/'):
        return  # 이미지 파일만 처리
    caption = update.message.caption or ''
    await _receive_image(
        update, context,
        file_getter=lambda: context.bot.get_file(doc.file_id),
        caption=caption,
    )


# ─── 텍스트 명령 ─────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.message.chat_id

    cmd_map = {
        '발행 중단': cmd_stop_publish,
        '발행 재개': cmd_resume_publish,
        '오늘 수집된 글감 보여줘': cmd_show_topics,
        '이번 주 리포트': cmd_report,
        '대기 중인 글 보여줘': cmd_pending,
        '이미지 목록': cmd_images,
        '변환 실행': cmd_convert,
        '오늘 뭐 발행했어?': cmd_status,
    }
    if text in cmd_map:
        await cmd_map[text](update, context)
        return

    # Claude API로 자연어 처리
    if not ANTHROPIC_API_KEY:
        await update.message.reply_text(
            "Claude API 키가 없습니다. .env 파일에 ANTHROPIC_API_KEY를 입력하세요."
        )
        return

    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    history = _conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": text})

    # 대화 기록이 너무 길면 최근 20개만 유지
    if len(history) > 20:
        history[:] = history[-20:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        response = _claude_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=CLAUDE_SYSTEM_PROMPT,
            messages=history,
        )
        reply = response.content[0].text
        history.append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Claude API 오류: {e}")
        await update.message.reply_text(f"오류가 발생했습니다: {e}")


# ─── 스케줄러 설정 + 메인 ─────────────────────────────

def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone='Asia/Seoul')
    schedule_cfg = load_schedule()

    # schedule.json 기반 동적 잡 (기존)
    job_map = {
        'collector': job_collector,
        'ai_writer': job_ai_writer,
        'publish_1': lambda: job_publish(1),
        'publish_2': lambda: job_publish(2),
        'publish_3': lambda: job_publish(3),
        'analytics': job_analytics_daily,
    }
    for job in schedule_cfg.get('jobs', []):
        fn = job_map.get(job['id'])
        if fn:
            scheduler.add_job(fn, 'cron', hour=job['hour'], minute=job['minute'], id=job['id'])

    # v3 고정 스케줄: 시차 배포
    # 07:00 수집봇 (schedule.json에서 관리)
    # 08:00 AI 글 작성 (schedule.json에서 관리)
    scheduler.add_job(job_convert, 'cron', hour=8, minute=30, id='convert')       # 08:30 변환
    scheduler.add_job(lambda: job_publish(1), 'cron',
                      hour=9, minute=0, id='blog_publish')                         # 09:00 블로그
    scheduler.add_job(job_distribute_instagram, 'cron',
                      hour=10, minute=0, id='instagram_dist')                      # 10:00 인스타
    scheduler.add_job(job_distribute_x, 'cron',
                      hour=11, minute=0, id='x_dist')                             # 11:00 X
    scheduler.add_job(job_distribute_tiktok, 'cron',
                      hour=18, minute=0, id='tiktok_dist')                         # 18:00 틱톡
    scheduler.add_job(job_distribute_youtube, 'cron',
                      hour=20, minute=0, id='youtube_dist')                        # 20:00 유튜브
    scheduler.add_job(job_analytics_daily, 'cron',
                      hour=22, minute=0, id='daily_report')                        # 22:00 분석
    scheduler.add_job(job_analytics_weekly, 'cron',
                      day_of_week='sun', hour=22, minute=30, id='weekly_report')   # 일요일 주간

    # request 모드: 매주 월요일 10:00 이미지 프롬프트 배치 전송
    if IMAGE_MODE == 'request':
        scheduler.add_job(job_image_prompt_batch, 'cron',
                          day_of_week='mon', hour=10, minute=0, id='image_batch')
        logger.info("이미지 request 모드: 매주 월요일 10:00 배치 전송 등록")

    logger.info("스케줄러 설정 완료 (v3 시차 배포 포함)")
    return scheduler


async def main():
    logger.info("=== 블로그 엔진 스케줄러 시작 ===")
    scheduler = setup_scheduler()
    scheduler.start()

    if TELEGRAM_BOT_TOKEN:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # 발행 관련
        app.add_handler(CommandHandler('status', cmd_status))
        app.add_handler(CommandHandler('approve', cmd_approve))
        app.add_handler(CommandHandler('reject', cmd_reject))
        app.add_handler(CommandHandler('pending', cmd_pending))
        app.add_handler(CommandHandler('report', cmd_report))
        app.add_handler(CommandHandler('topics', cmd_show_topics))
        app.add_handler(CommandHandler('convert', cmd_convert))

        # 이미지 관련 (request / manual 공통 사용 가능)
        app.add_handler(CommandHandler('images', cmd_images))
        app.add_handler(CommandHandler('imgpick', cmd_imgpick))
        app.add_handler(CommandHandler('imgbatch', cmd_imgbatch))
        app.add_handler(CommandHandler('imgcancel', cmd_imgcancel))

        # 이미지 파일 수신
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))

        # 텍스트 명령
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

        logger.info("Telegram 봇 시작")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            logger.info("종료 신호 수신")
        finally:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
            scheduler.shutdown()
    else:
        logger.warning("TELEGRAM_BOT_TOKEN 없음 — 스케줄러만 실행")
        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()

    logger.info("=== 블로그 엔진 스케줄러 종료 ===")


if __name__ == '__main__':
    asyncio.run(main())
