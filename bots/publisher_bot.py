# The 4th Path: ⟨H⊕A⟩ ↦ Ω
# Human × AI → a better world.
# 22B Labs | the4thpath.com
"""
발행봇 (publisher_bot.py)
역할: AI가 작성한 글을 Blogger에 자동 발행
- 마크다운 → HTML 변환
- 목차 자동 생성
- AdSense 플레이스홀더 삽입
- Schema.org Article JSON-LD
- 안전장치 (팩트체크/위험 키워드/출처 부족 → 수동 검토)
- Blogger API v3 발행
- Search Console URL 제출
- Telegram 알림
"""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from bots.prompt_layer.writer_review import TITLE_STRONG_PATTERNS, TITLE_WEAK_PATTERNS
from bots.publish_validation import validate_article_before_publish
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import markdown
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
TOKEN_PATH = BASE_DIR / 'token.json'
LOG_DIR.mkdir(exist_ok=True)
PENDING_REVIEW_DIR = DATA_DIR / 'pending_review'
PENDING_REVIEW_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        RotatingFileHandler(LOG_DIR / 'publisher.log', maxBytes=5*1024*1024, backupCount=3, encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
BLOG_MAIN_ID = os.getenv('BLOG_MAIN_ID', '')
RAW_TERM_REPLACEMENTS = {
    'claude/': '전용 자동화 브랜치 접두어',
    '/loop': '로컬 반복 실행 모드',
    '/schedule': 'CLI 예약 명령',
}
TEST_MARKERS = ('테스트', '샘플', 'dummy', '[test]', '(test)')

SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/webmasters',
    # 'https://www.googleapis.com/auth/indexing',  # ← Cloud Console에서 Indexing API 활성화 후 주석 해제 + token.json 삭제 후 재발급
]


def load_config(filename: str) -> dict:
    with open(CONFIG_DIR / filename, 'r', encoding='utf-8') as f:
        return json.load(f)


# ─── Google 인증 ─────────────────────────────────────

def get_google_credentials() -> Credentials:
    from google.auth.exceptions import RefreshError
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(TOKEN_PATH, 'w') as f:
                    f.write(creds.to_json())
            except RefreshError as e:
                raise RuntimeError(f"invalid_grant: Token has been expired or revoked. scripts/get_token.py 재실행 필요. ({e})") from e
    if not creds or not creds.valid:
        raise RuntimeError("Google 인증 실패. scripts/get_token.py 를 먼저 실행하세요.")
    return creds


# ─── 안전장치 ─────────────────────────────────────────

# 뉴스 헤드라인 형식 감지 — 줄임표(…) 또는 인용 닉네임('달인' …)으로 시작
# U+2026(…), U+0027(ASCII '), U+2018('), U+2019(') 모두 포함
_NEWS_HEADLINE_RE = re.compile(r'…|^[\u0027\u2018\u2019]')


def check_safety(article: dict, safety_cfg: dict) -> tuple[bool, str]:
    """
    수동 검토가 필요한지 판단.
    Returns: (needs_review, reason)
    """
    corner = article.get('corner', '')
    body = article.get('body', '')
    sources = article.get('sources', [])
    quality_score = article.get('quality_score', 100)

    # 팩트체크 코너는 무조건 수동 검토
    manual_corners = safety_cfg.get('always_manual_review', ['팩트체크'])
    if corner in manual_corners:
        return True, f'코너 "{corner}" 는 항상 수동 검토 필요'

    # 위험 키워드 감지
    all_keywords = (
        safety_cfg.get('crypto_keywords', []) +
        safety_cfg.get('criticism_keywords', []) +
        safety_cfg.get('investment_keywords', []) +
        safety_cfg.get('legal_keywords', [])
    )
    all_phrases = safety_cfg.get('criticism_phrases', [])
    for kw in all_keywords:
        if kw in body:
            return True, f'위험 키워드 감지: "{kw}"'
    for phrase in all_phrases:
        if phrase in body:
            return True, f'위험 구문 감지: "{phrase}"'

    # 출처 2개 미만
    min_sources = safety_cfg.get('min_sources_required', 2)
    if len(sources) < min_sources:
        return True, f'출처 {len(sources)}개 — {min_sources}개 이상 필요'

    # 품질 점수 미달
    min_score = safety_cfg.get('min_quality_score_for_auto', 75)
    if quality_score < min_score:
        return True, f'품질 점수 {quality_score}점 (자동 발행 최소: {min_score}점)'

    # 제목 공통 변수 — 아래 2개 검사에서 재사용
    title = article.get('title', '')
    _has_korean = bool(re.search(r'[가-힣]', title))

    # 뉴스 헤드라인 형식 감지 — 클릭 패턴 검사보다 먼저 실행 (22억 등이 있어도 차단)
    if title and _has_korean and _NEWS_HEADLINE_RE.search(title):
        return True, f'뉴스 헤드라인 형식 제목 감지 — 블로그 제목으로 변환 필요: "{title[:40]}"'

    # 제목 클릭 유발 패턴 검사 (조회수 1만+ 블로그 분석 기준, 한국어 제목만 적용)
    # normalize_title_text 잘림으로 패턴이 소실됐을 때를 대비해 원본 제목도 함께 체크
    _original_title = article.get('_original_title', title)
    if title and _has_korean and not (_title_has_click_pattern(title) or _title_has_click_pattern(_original_title)):
        return True, f'제목 클릭 유발 패턴 없음: "{title}" — 손실 프레임·숫자·역발상·질문·방법·행동→결과 중 하나 필요'

    # QP1: 플레이스홀더 앱명 감지 — 'Word. 한국어' 패턴 (defense-in-depth)
    _PLACEHOLDER_APP = re.compile(r'\b[A-Z][A-Za-z]{1,}\.[ \u00a0][가-힣]')
    _body_plain = re.sub(r'<[^>]+>', ' ', body)
    if (title and _PLACEHOLDER_APP.search(title)) or _PLACEHOLDER_APP.search(_body_plain):
        return True, f'앱명 플레이스홀더 패턴 감지 ("Word. 한국어" 형태) — 실제 앱명으로 교체 필요'

    return False, ''


def _title_has_click_pattern(title: str) -> bool:
    """조회수 1만+ 블로그 분석 기반 제목 클릭 유발 패턴 검사 (writer_review 공통 상수 사용)."""
    return any(p.search(title) for p in TITLE_STRONG_PATTERNS + TITLE_WEAK_PATTERNS)


def replace_raw_terms(text: str) -> str:
    normalized = text
    for raw, replacement in RAW_TERM_REPLACEMENTS.items():
        normalized = normalized.replace(raw, replacement)
    return normalized


def normalize_h2_text(text: str) -> str:
    cleaned = re.sub(r'<[^>]+>', '', replace_raw_terms(text)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if len(cleaned) <= 26:
        return cleaned
    parts = re.split(r'[:|,]| - | — | – |\?', cleaned)
    for part in parts:
        candidate = part.strip()
        if 8 <= len(candidate) <= 26:
            return candidate
    return cleaned[:26].rstrip()


def normalize_title_text(text: str) -> str:
    cleaned = re.sub(r'<[^>]+>', '', replace_raw_terms(text)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if len(cleaned) <= 38:
        return cleaned
    parts = re.split(r'[:|]| - | — | – ', cleaned)
    for part in parts:
        candidate = part.strip()
        if 14 <= len(candidate) <= 38:
            return candidate
    # 구분자로 적절히 분리되지 않는 경우: 잘라내지 않고 전체 반환 (잘린 제목 방지)
    return cleaned


_AI_INSTRUCTION_RE = re.compile(
    r'(\*{0,2}주의\*{0,2}\s*[:：]|'
    r'현재는\s+아웃라인\s+단계|'
    r'최종\s+원고를?\s+완성|'
    r'각\s+섹션\s+제목\s+아래|'
    r'다음\s+단계에서\s*[:：]|'
    r'지금\s+보이는\s+이\s+아웃라인|'
    r'진행할까요|'
    r'조정하고\s+시작할까요)',
    re.IGNORECASE,
)


def _sanitize_disclaimer(text: str) -> str:
    """마크다운 수평선 또는 AI 지시문 패턴 이후 내용 제거."""
    lines = []
    for line in text.splitlines():
        if re.match(r'^\s*-{3,}\s*$', line):
            break
        lines.append(line)
    cleaned = '\n'.join(lines).strip()
    m = _AI_INSTRUCTION_RE.search(cleaned)
    if m:
        cleaned = cleaned[:m.start()].strip()
    return cleaned


_META_PLACEHOLDERS = (
    '핵심 문구부터 보면 뜻이 바로 잡힌다',
    '핵심 문구부터 보면',
    '뜻이 바로 잡힌다',
    'META_DESCRIPTION',
)


def _extract_meta_from_body(body: str, title: str = '') -> str:
    """본문 첫 <p> 태그 내용에서 META 설명을 추출 (플레이스홀더 폴백용).
    H2 텍스트가 포함되지 않도록 <p> 태그 내용만 사용한다.
    """
    # 첫 번째 <p> 태그 내용만 추출 (H2 텍스트 혼입 방지)
    p_match = re.search(r'<p[^>]*>(.*?)</p>', body or '', flags=re.IGNORECASE | re.DOTALL)
    if p_match:
        plain = re.sub(r'<[^>]+>', '', p_match.group(1)).strip()
        first_sentence = re.split(r'(?<=[.!?다])\s', plain)[0][:160].strip()
        if len(first_sentence) >= 20:
            return first_sentence
    return title[:160] if title else ''


_DANGLING_ENDINGS = re.compile(
    r'(을|를|이|가|은|는|도|만|와|과|의|에|서|로|으로|열려도|되어도|있어도|없어도|하면|보면|쓰면|되면|읽으면)$'
)
_RESULT_PRESENT = re.compile(
    r'(된다|않는다|있다|없다|이다|한다|받는다|바뀐다|달라진다|줄어|커진다|생긴다|'
    r'보인다|나온다|해결된다|사라진다|빨라진다|늘어난다|알게 된다|이유|방법|원리|비결|차이)'
)


def _fix_dangling_title(title: str, article: dict) -> str:
    """끊긴 제목 감지 → 글감 topic + 본문 첫 문단에서 자동 수정."""
    if not title:
        return title

    # 결과어가 이미 있으면 정상 제목
    if _RESULT_PRESENT.search(title):
        return title

    # 끊긴 패턴 감지
    if not _DANGLING_ENDINGS.search(title):
        return title

    # topic 기반 폴백 제목 생성
    topic = article.get('topic', '') or article.get('_topic_data', {}).get('topic', '')
    if topic:
        # topic에서 특수문자·따옴표 제거, 42자 이내 정리
        fixed = re.sub(r'[&\"\'\[\]<>（）【】「」]', '', topic).strip()
        fixed = re.sub(r'\s+', ' ', fixed)[:42]
        if fixed and fixed != title:
            logger.warning(f"[제목 자동 수정] 끊긴 제목 감지: '{title}' → '{fixed}'")
            return fixed

    # topic도 없으면 본문 첫 h2를 제목으로
    body = article.get('body', '')
    h2s = re.findall(r'<h2>(.*?)</h2>', body, re.IGNORECASE | re.DOTALL)
    if h2s:
        fallback = re.sub(r'<[^>]+>', '', h2s[0]).strip()[:42]
        if fallback and fallback != title:
            logger.warning(f"[제목 자동 수정] 첫 H2로 대체: '{title}' → '{fallback}'")
            return fallback

    return title


def sanitize_article_for_publish(article: dict) -> dict:
    sanitized = dict(article)
    if not sanitized.get('meta') and sanitized.get('meta_description'):
        sanitized['meta'] = sanitized.get('meta_description', '')
    if not sanitized.get('meta_description') and sanitized.get('meta'):
        sanitized['meta_description'] = sanitized.get('meta', '')
    for key in ('title', 'meta', 'disclaimer'):
        if isinstance(sanitized.get(key), str):
            sanitized[key] = replace_raw_terms(sanitized[key]).strip()

    # META가 플레이스홀더이면 본문 첫 문장으로 대체
    meta = sanitized.get('meta', '')
    if not meta or any(ph in meta for ph in _META_PLACEHOLDERS):
        fallback = _extract_meta_from_body(sanitized.get('body', ''), sanitized.get('title', ''))
        if fallback:
            logger.info(f"META 플레이스홀더 감지 — 본문 첫 문장으로 대체: {fallback[:60]}…")
            sanitized['meta'] = fallback
            sanitized['meta_description'] = fallback

    # disclaimer에 AI 지시문이 혼입된 경우 제거 (2차 방어)
    if isinstance(sanitized.get('disclaimer'), str):
        sanitized['disclaimer'] = _sanitize_disclaimer(sanitized['disclaimer'])

    if isinstance(sanitized.get('title'), str):
        _pre_normalize_title = sanitized['title']
        sanitized['title'] = normalize_title_text(sanitized['title'])
        sanitized['title'] = _fix_dangling_title(sanitized['title'], sanitized)
        # 잘린 경우 원본 제목 보존 — check_safety의 클릭 패턴 오탐 방지
        if sanitized['title'] != _pre_normalize_title:
            sanitized.setdefault('_original_title', _pre_normalize_title)
    if isinstance(sanitized.get('meta'), str):
        sanitized['meta_description'] = sanitized['meta']

    if isinstance(sanitized.get('body'), str):
        body = replace_raw_terms(sanitized['body'])

        def _normalize_h2(match: re.Match) -> str:
            return f"<h2>{normalize_h2_text(match.group(1))}</h2>"

        body = re.sub(r'<h2>(.*?)</h2>', _normalize_h2, body, flags=re.IGNORECASE | re.DOTALL)
        body = re.sub(r'\n{3,}', '\n\n', body)
        sanitized['body'] = body.strip()

    if isinstance(sanitized.get('key_points'), list):
        sanitized['key_points'] = [
            replace_raw_terms(str(point)).strip()
            for point in sanitized['key_points']
            if str(point).strip()
        ]

    return sanitized


def is_test_article(article: dict) -> bool:
    if article.get('_test_mode') is True:
        return True
    # meta는 제외 — "테스트·검증" 같은 설명 문구가 포함될 수 있음
    haystacks = [
        str(article.get('title', '')),
        str(article.get('slug', '')),
    ]
    lowered = ' '.join(haystacks).lower()
    return any(marker in lowered for marker in TEST_MARKERS)


# ─── HTML 변환 ─────────────────────────────────────────

def markdown_to_html(md_text: str) -> str:
    """마크다운 → HTML 변환 (목차 extension 포함)"""
    md = markdown.Markdown(
        extensions=['toc', 'tables', 'fenced_code', 'attr_list'],
        extension_configs={
            'toc': {
                'title': '목차',
                'toc_depth': '2-3',
            }
        }
    )
    html = md.convert(md_text)
    toc = md.toc  # 목차 HTML
    return html, toc


def insert_adsense_placeholders(html: str) -> str:
    """두 번째 H2 뒤와 결론 섹션 앞에 AdSense 플레이스홀더 삽입"""
    AD_SLOT_1 = '\n<!-- AD_SLOT_1 -->\n'
    AD_SLOT_2 = '\n<!-- AD_SLOT_2 -->\n'

    soup = BeautifulSoup(html, 'lxml')
    h2_tags = soup.find_all('h2')

    # 두 번째 H2 뒤에 AD_SLOT_1 삽입
    if len(h2_tags) >= 2:
        second_h2 = h2_tags[1]
        ad_tag = BeautifulSoup(AD_SLOT_1, 'html.parser')
        second_h2.insert_after(ad_tag)

    # 결론 H2 앞에 AD_SLOT_2 삽입
    for h2 in soup.find_all('h2'):
        if any(kw in h2.get_text() for kw in ['결론', '마무리', '정리', '요약', 'conclusion']):
            ad_tag2 = BeautifulSoup(AD_SLOT_2, 'html.parser')
            h2.insert_before(ad_tag2)
            break

    return str(soup)


def _inject_post_url(html: str, post_url: str) -> str:
    """발행 후 확정된 URL을 JSON-LD @id 와 og:url 메타태그에 주입.
    Blogger 발행 직후 posts().patch() 로 전달하기 위한 헬퍼.
    """
    if not post_url:
        return html
    # JSON-LD @id 업데이트 (빈 문자열 → 실제 URL)
    html = re.sub(r'"@id":\s*""', f'"@id": "{post_url}"', html)
    # og:url 미존재 시 twitter:card 앞에 삽입 (OG 그룹 마지막 위치)
    if 'og:url' not in html:
        html = html.replace(
            '<meta name="twitter:card"',
            f'<meta property="og:url" content="{post_url}"/>\n<meta name="twitter:card"',
            1,
        )
    return html


def build_json_ld(article: dict, blog_url: str = '') -> str:
    """Schema.org Article JSON-LD 생성"""
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.get('title', ''),
        "description": article.get('meta', ''),
        "datePublished": datetime.now(timezone.utc).isoformat(),
        "dateModified": datetime.now(timezone.utc).isoformat(),
        "author": {
            "@type": "Person",
            "name": "테크인사이더"
        },
        "publisher": {
            "@type": "Organization",
            "name": "테크인사이더",
            "logo": {
                "@type": "ImageObject",
                "url": ""
            }
        },
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": blog_url
        }
    }
    return f'<script type="application/ld+json">\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n</script>'


def build_og_tags(article: dict) -> str:
    """Open Graph + Twitter Card 메타 태그 생성"""
    title = article.get('title', '')
    meta = article.get('meta_description', article.get('meta', ''))
    url = article.get('url', '')
    tags = [
        f'<meta property="og:type" content="article"/>',
        f'<meta property="og:title" content="{title}"/>',
        f'<meta property="og:description" content="{meta}"/>',
        f'<meta name="twitter:card" content="summary"/>',
        f'<meta name="twitter:title" content="{title}"/>',
        f'<meta name="twitter:description" content="{meta}"/>',
    ]
    if url:
        tags.append(f'<meta property="og:url" content="{url}"/>')
    return '\n'.join(tags)


def build_full_html(article: dict, body_html: str, toc_html: str) -> str:
    """최종 HTML 조합: OG태그 + JSON-LD + 목차 + 본문 + 면책 문구"""
    og_tags = build_og_tags(article)
    json_ld = build_json_ld(article)
    disclaimer = article.get('disclaimer', '')
    style_block = """
<style>
.t4p-post{font-size:17px;line-height:1.9;color:#1f2937;word-break:keep-all}
.t4p-post h2{margin:2.2em 0 .8em;font-size:1.5rem;line-height:1.4;font-weight:800;color:#111827;letter-spacing:-0.01em}
.t4p-post p{margin:0 0 1.1em}
.t4p-post strong{font-weight:800;color:#111827;background:linear-gradient(transparent 62%, #fde68a 0)}
.t4p-post code{padding:.15em .4em;border-radius:6px;background:#f3f4f6;color:#7c2d12;font-size:.92em}
.t4p-post .toc-wrapper{margin:0 0 1.6em;padding:1rem 1.1rem;border:1px solid #e5e7eb;border-radius:14px;background:#fafaf9}
.t4p-post .toc-wrapper ul{margin:.5em 0 0 1.1em;padding:0}
.t4p-post .toc-wrapper li{margin:.35em 0}
.t4p-post hr{margin:2.2em 0;border:none;border-top:1px solid #e5e7eb}
.t4p-post .disclaimer{color:#6b7280;font-size:.94rem}
</style>
""".strip()

    html_parts = [og_tags, json_ld, style_block, '<article class="t4p-post">']
    if toc_html:
        html_parts.append(f'<div class="toc-wrapper">{toc_html}</div>')
    html_parts.append(body_html)
    if disclaimer:
        html_parts.append(f'<hr/><p class="disclaimer"><small>{disclaimer}</small></p>')
    html_parts.append('</article>')

    return '\n'.join(html_parts)


# ─── Blogger API ──────────────────────────────────────

def publish_to_blogger(article: dict, html_content: str, creds: Credentials, is_draft: bool = False) -> dict:
    """Blogger API v3로 글 발행"""
    service = build('blogger', 'v3', credentials=creds)
    blog_id = BLOG_MAIN_ID

    labels = [article.get('corner', '')]
    tags = article.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',')]
    labels.extend(tags)
    labels = list(set(filter(None, labels)))

    meta_desc = article.get('meta_description', article.get('meta', ''))

    body = {
        'title': article.get('title', ''),
        'content': html_content,
        'labels': labels,
    }
    if meta_desc:
        body['customMetaData'] = meta_desc

    result = service.posts().insert(
        blogId=blog_id,
        body=body,
        isDraft=is_draft,
    ).execute()

    return result


def submit_to_search_console(url: str, creds: Credentials):
    """Google Indexing API로 URL 색인 요청 (URL_UPDATED)"""
    try:
        import googleapiclient.errors
        service = build('indexing', 'v3', credentials=creds)
        body = {'url': url, 'type': 'URL_UPDATED'}
        response = service.urlNotifications().publish(body=body).execute()
        logger.info(f"Indexing API 제출 완료: {url} → {response.get('urlNotificationMetadata', {}).get('url', url)}")
    except Exception as e:
        # Indexing API는 Blogger/News/Podcast 사이트에만 허용됨.
        # 거부되면 Blogger 내장 sitemap에 의존 (무해한 실패)
        logger.warning(f"Indexing API 제출 실패 (비치명적): {e}")


# ─── Telegram ────────────────────────────────────────

def send_telegram(text: str, parse_mode: str = 'HTML'):
    """Telegram 메시지 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram 설정 없음 — 알림 건너뜀")
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': parse_mode,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Telegram 전송 실패: {e}")


def send_pending_review_alert(article: dict, reason: str):
    """수동 검토 대기 알림 (Telegram)"""
    title = article.get('title', '(제목 없음)')
    corner = article.get('corner', '')
    preview = article.get('body', '')[:300].replace('<', '&lt;').replace('>', '&gt;')
    msg = (
        f"🔍 <b>[수동 검토 필요]</b>\n\n"
        f"📌 <b>{title}</b>\n"
        f"코너: {corner}\n"
        f"사유: {reason}\n\n"
        f"미리보기:\n{preview}...\n\n"
        f"명령: <code>승인</code> 또는 <code>거부</code>"
    )
    send_telegram(msg)


# ─── 발행 이력 ───────────────────────────────────────

def log_published(article: dict, post_result: dict):
    """발행 이력 저장"""
    published_dir = DATA_DIR / ('drafts' if post_result.get('status') == 'DRAFT' else 'published')
    published_dir.mkdir(exist_ok=True)
    record = {
        'title': article.get('title', ''),
        'slug': article.get('slug', ''),
        'corner': article.get('corner', ''),
        'url': post_result.get('url', ''),
        'post_id': post_result.get('id', ''),
        'published_at': datetime.now(timezone.utc).isoformat(),
        'quality_score': article.get('quality_score', 0),
        'tags': article.get('tags', []),
        'sources': article.get('sources', []),
        'status': post_result.get('status', 'LIVE'),
        # 내부 링크 및 향후 재활용을 위한 핵심 필드
        'topic': article.get('topic', ''),
        'meta': article.get('meta', '') or article.get('meta_description', ''),
        'key_points': article.get('key_points', []),
    }
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{record['post_id']}.json"
    with open(published_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


def load_published_records() -> list[dict]:
    records = []
    for dirname in ('published', 'drafts'):
        target_dir = DATA_DIR / dirname
        if not target_dir.exists():
            continue
        for f in sorted(target_dir.glob('*.json')):
            try:
                records.append(json.loads(f.read_text(encoding='utf-8')))
            except Exception:
                continue
    return records


def find_duplicate_publication(article: dict, similarity_threshold: float = 0.88) -> str:
    slug = str(article.get('slug', '')).strip()
    title = str(article.get('title', '')).strip()
    source_urls = {
        str(item.get('url', '')).strip()
        for item in (article.get('sources') or [])
        if str(item.get('url', '')).strip()
    }

    for record in load_published_records():
        published_slug = str(record.get('slug', '')).strip()
        published_title = str(record.get('title', '')).strip()
        published_source_urls = {
            str(item.get('url', '')).strip()
            for item in (record.get('sources') or [])
            if str(item.get('url', '')).strip()
        }

        if slug and published_slug and slug == published_slug:
            return f'기발행 slug 중복: "{slug}"'

        if title and published_title:
            similarity = SequenceMatcher(None, title, published_title).ratio()
            if similarity >= similarity_threshold:
                return f'기발행 제목과 유사도 {similarity*100:.0f}% 이상'

        if source_urls and published_source_urls and source_urls & published_source_urls:
            overlap = next(iter(source_urls & published_source_urls))
            return f'기발행 글과 출처 URL 중복: {overlap}'

    return ''


def save_pending_review(article: dict, reason: str):
    """수동 검토 대기 글 저장"""
    record = {**article, 'pending_reason': reason, 'created_at': datetime.now().isoformat()}
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pending.json"
    with open(PENDING_REVIEW_DIR / filename, 'w', encoding='utf-8') as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return PENDING_REVIEW_DIR / filename


def load_pending_review_file(filepath: str) -> dict:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_existing_pending_review(article: dict, reason: str) -> Path | None:
    """같은 제목 + 같은 사유의 대기 파일이 이미 있으면 반환"""
    title = article.get('title', '').strip()
    for f in sorted(PENDING_REVIEW_DIR.glob('*_pending.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        if data.get('title', '').strip() == title and data.get('pending_reason', '') == reason:
            return f
    return None


# ─── 메인 발행 함수 ──────────────────────────────────

def publish_with_result(article: dict) -> tuple[bool, str]:
    """
    article: OpenClaw blog-writer가 출력한 파싱된 글 dict
    {
        title, meta, slug, tags, corner, body (markdown),
        coupang_keywords, sources, disclaimer, quality_score
    }
    Returns: (발행 성공 여부, 실패/대기 사유)
    """
    # 원본 제목 보존 — normalize_title_text 잘림으로 클릭 패턴이 소실되는 것 방지
    _original_title = article.get('title', '')
    article = sanitize_article_for_publish(article)
    # 잘린 경우 원본 제목을 check_safety 판단용으로 복원
    if _original_title and article.get('title') != _original_title:
        article['_original_title'] = _original_title
    logger.info(f"발행 시도: {article.get('title', '')}")
    safety_cfg = load_config('safety_keywords.json')

    duplicate_reason = find_duplicate_publication(article)
    if duplicate_reason:
        logger.warning(f"중복 발행 차단: {duplicate_reason}")
        return False, duplicate_reason

    # _write_quality_passed=False: 작성 단계에서 품질 검수 미완료 (토큰 초과/최대 재시도)
    # check_safety 결과와 무관하게 독립적으로 보류 처리 — 이 체크가 'if needs_review:' 안에
    # 있으면 check_safety가 False를 반환할 때 도달하지 못하는 버그가 생김 (VPN 제목 잘림 원인)
    if not article.get('_write_quality_passed', True):
        _qfail_reason = '품질 검수 미완료 — 토큰 예산 초과 또는 최대 재시도 도달'
        logger.warning(f"[발행 보류] {_qfail_reason}: {article.get('title', '')}")
        return False, _qfail_reason

    needs_review, review_reason = check_safety(article, safety_cfg)
    if needs_review:
        # 뉴스 헤드라인 형식 → 항상 pending
        if '뉴스 헤드라인 형식' in review_reason:
            logger.warning(f"[발행 보류] {review_reason}: {article.get('title', '')}")
            return False, review_reason
        else:
            logger.warning(f"[안전장치 경고] {review_reason} — 바로 발행 진행")

    # 변환봇이 미리 생성한 HTML이 있으면 재사용, 없으면 직접 변환
    if article.get('_html_content'):
        full_html = article['_html_content']
    else:
        # 마크다운 → HTML (fallback)
        body_html, toc_html = markdown_to_html(article.get('body', ''))
        body_html = insert_adsense_placeholders(body_html)
        full_html = build_full_html(article, body_html, toc_html)

    # 쿠팡 파트너스 / 고정 어필리에이트 링크 삽입
    try:
        import bots.linker_bot as linker_bot
        full_html = linker_bot.process(article, full_html)
    except Exception as e:
        logger.warning(f"링크 삽입 건너뜀: {e}")

    # Google 인증
    try:
        creds = get_google_credentials()
    except RuntimeError as e:
        logger.error(str(e))
        return False, str(e)

    test_mode = is_test_article(article)

    # Blogger 발행
    try:
        post_result = publish_to_blogger(article, full_html, creds, is_draft=test_mode)
        post_url = post_result.get('url', '')
        logger.info(f"{'초안 저장' if test_mode else '발행 완료'}: {post_url}")
    except Exception as e:
        logger.error(f"Blogger 발행 실패: {e}")
        return False, f'Blogger 발행 실패: {e}'

    # JSON-LD @id + og:url 주입 — 발행 후 확정된 URL로 업데이트
    if post_url and not test_mode:
        updated_html = _inject_post_url(full_html, post_url)
        if updated_html != full_html:
            try:
                _svc = build('blogger', 'v3', credentials=creds)
                _svc.posts().patch(
                    blogId=BLOG_MAIN_ID,
                    postId=post_result.get('id', ''),
                    body={'content': updated_html},
                ).execute()
                logger.info(f"JSON-LD @id + og:url 업데이트: {post_url}")
            except Exception as e:
                logger.warning(f"메타데이터 URL 업데이트 실패 (비치명적): {e}")

    # Search Console 제출
    if post_url and not test_mode:
        submit_to_search_console(post_url, creds)

    # 발행 이력 저장
    log_published(article, post_result)

    # Telegram 알림
    title = article.get('title', '')
    corner = article.get('corner', '')
    if test_mode:
        send_telegram(
            f"🧪 <b>테스트 초안 저장</b>\n\n"
            f"📌 <b>{title}</b>\n"
            f"코너: {corner}\n"
            f"URL: {post_url}"
        )
    else:
        send_telegram(
            f"✅ <b>발행 완료!</b>\n\n"
            f"📌 <b>{title}</b>\n"
            f"코너: {corner}\n"
            f"URL: {post_url}"
        )

    return True, ''


def publish(article: dict) -> bool:
    success, _ = publish_with_result(article)
    return success


def approve_pending(filepath: str) -> bool:
    """수동 검토 대기 글 승인 후 발행"""
    try:
        article = sanitize_article_for_publish(load_pending_review_file(filepath))
        article.pop('pending_reason', None)
        article.pop('created_at', None)

        # 중복 발행 차단 — approve_pending은 check_safety를 우회하므로 여기서 직접 체크
        duplicate_reason = find_duplicate_publication(article)
        if duplicate_reason:
            logger.warning(f"[중복 차단] approve_pending: {duplicate_reason} — {article.get('title', '')}")
            send_telegram(
                f"⛔ <b>[중복 차단]</b> 이미 발행된 출처와 동일\n\n"
                f"📌 {article.get('title', '')}\n"
                f"사유: {duplicate_reason}"
            )
            return False

        # QP1: 플레이스홀더 앱명 감지 경고 (차단은 아님 — 수동 승인이므로 운영자 판단 우선)
        _PLACEHOLDER_APP = re.compile(r'\b[A-Z][A-Za-z]{1,}\.[ \u00a0][가-힣]')
        _title = article.get('title', '')
        _body_plain = re.sub(r'<[^>]+>', ' ', article.get('body', ''))
        if _PLACEHOLDER_APP.search(_title) or _PLACEHOLDER_APP.search(_body_plain):
            logger.warning(f"[QP1] 앱명 플레이스홀더 패턴 감지 — 발행 전 수정 권장: {_title}")
            send_telegram(
                f"⚠️ <b>[QP1 경고] 앱명 플레이스홀더 패턴</b>\n\n"
                f"📌 {_title}\n"
                f'"Word. 한국어" 패턴이 제목 또는 본문에 있습니다. '
                f'실제 앱명으로 교체 후 재발행을 권장합니다.'
            )

        # 발행 전 검증 (제목-본문 일치, 품질, 출처)
        is_valid, validation_errors = validate_article_before_publish(article)
        if not is_valid:
            err_summary = ' | '.join(validation_errors[:3])
            logger.warning(f"[발행 전 검증 실패] {article.get('title', '')} — {err_summary}")
            send_telegram(
                f"⛔ <b>[검증 실패] 발행 차단</b>\n\n"
                f"📌 {article.get('title', '')}\n"
                f"사유: {err_summary}"
            )
            return False

        # 안전장치 우회하여 강제 발행
        body_html, toc_html = markdown_to_html(article.get('body', ''))
        body_html = insert_adsense_placeholders(body_html)
        full_html = build_full_html(article, body_html, toc_html)

        # 관련 글 링크 삽입
        try:
            import bots.linker_bot as linker_bot
            full_html = linker_bot.process(article, full_html)
        except Exception as e:
            logger.warning(f"링크 삽입 건너뜀: {e}")

        creds = get_google_credentials()
        test_mode = is_test_article(article)
        post_result = publish_to_blogger(article, full_html, creds, is_draft=test_mode)
        post_url = post_result.get('url', '')
        log_published(article, post_result)

        # 대기 파일 삭제
        Path(filepath).unlink(missing_ok=True)

        if test_mode:
            send_telegram(
                f"🧪 <b>[수동 승인] 테스트 초안 저장</b>\n\n"
                f"📌 {article.get('title', '')}\n"
                f"URL: {post_url}"
            )
            logger.info(f"수동 승인 테스트 초안 저장: {post_url}")
        else:
            send_telegram(
                f"✅ <b>[수동 승인] 발행 완료!</b>\n\n"
                f"📌 {article.get('title', '')}\n"
                f"URL: {post_url}"
            )
            logger.info(f"수동 승인 발행 완료: {post_url}")
        return True
    except Exception as e:
        logger.error(f"승인 발행 실패: {e}")
        return False


def reject_pending(filepath: str):
    """수동 검토 대기 글 거부 (파일 삭제)"""
    try:
        article = load_pending_review_file(filepath)
        Path(filepath).unlink(missing_ok=True)
        send_telegram(f"🗑 <b>[거부]</b> {article.get('title', '')} — 폐기됨")
        logger.info(f"수동 검토 거부: {filepath}")
    except Exception as e:
        logger.error(f"거부 처리 실패: {e}")


def get_pending_list() -> list[dict]:
    """수동 검토 대기 목록 반환"""
    result = []
    for f in sorted(PENDING_REVIEW_DIR.glob('*_pending.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            data['_filepath'] = str(f)
            result.append(data)
        except Exception:
            pass
    return result


def run_approve_all_pending() -> int:
    """pending_review 전체 글 자동 발행. 성공 건수 반환 (17시 자동화용)."""
    pending = get_pending_list()
    if not pending:
        logger.info("대기 중인 글 없음")
        return 0
    success_count = 0
    for item in pending:
        fp = item.get('_filepath', '')
        if fp and approve_pending(fp):
            success_count += 1
    logger.info(f"자동 발행 완료: {success_count}/{len(pending)}편")
    return success_count


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'approve_pending':
        run_approve_all_pending()
    elif cmd == 'approve_one' and len(sys.argv) > 2:
        sys.exit(0 if approve_pending(sys.argv[2]) else 1)
    else:
        print("Usage: python3 -m bots.publisher_bot approve_pending")
        print("       python3 -m bots.publisher_bot approve_one <filepath>")
        sys.exit(1)
