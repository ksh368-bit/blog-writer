"""
링크봇 (linker_bot.py)
역할: 글 본문에 쿠팡 파트너스 링크와 어필리에이트 링크 자동 삽입
"""
import hashlib
import hmac
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'linker.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

COUPANG_ACCESS_KEY = os.getenv('COUPANG_ACCESS_KEY', '')
COUPANG_SECRET_KEY = os.getenv('COUPANG_SECRET_KEY', '')
COUPANG_API_BASE = 'https://api-gateway.coupang.com'


def load_config(filename: str) -> dict:
    with open(CONFIG_DIR / filename, 'r', encoding='utf-8') as f:
        return json.load(f)


# ─── 쿠팡 파트너스 API ────────────────────────────────

def _generate_coupang_hmac(method: str, url: str, query: str) -> dict:
    """쿠팡 HMAC 서명 생성"""
    datetime_str = datetime.now(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    path = url.split(COUPANG_API_BASE)[-1].split('?')[0]
    message = datetime_str + method + path + query
    signature = hmac.new(
        COUPANG_SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return {
        'Authorization': f'CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, '
                         f'signed-date={datetime_str}, signature={signature}',
        'Content-Type': 'application/json;charset=UTF-8',
    }


def search_coupang_products(keyword: str, limit: int = 3) -> list[dict]:
    """쿠팡 파트너스 API로 상품 검색"""
    if not COUPANG_ACCESS_KEY or not COUPANG_SECRET_KEY:
        logger.warning("쿠팡 API 키 없음 — 링크 삽입 건너뜀")
        return []

    path = '/v2/providers/affiliate_api/apis/openapi/products/search'
    params = {
        'keyword': keyword,
        'limit': limit,
        'subId': 'blog-writer',
    }
    query_string = urlencode(params)
    url = f'{COUPANG_API_BASE}{path}?{query_string}'

    try:
        headers = _generate_coupang_hmac('GET', url, query_string)
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        products = data.get('data', {}).get('productData', [])
        return [
            {
                'name': p.get('productName', keyword),
                'price': p.get('productPrice', 0),
                'url': p.get('productUrl', ''),
                'image': p.get('productImage', ''),
            }
            for p in products[:limit]
        ]
    except Exception as e:
        logger.warning(f"쿠팡 API 오류 ({keyword}): {e}")
        return []


def build_coupang_link_html(product: dict) -> str:
    """쿠팡 상품 링크 HTML 생성"""
    name = product.get('name', '')
    url = product.get('url', '')
    price = product.get('price', 0)
    price_str = f"{int(price):,}원" if price else ''
    return (
        f'<p class="coupang-link">'
        f'🛒 <a href="{url}" target="_blank" rel="nofollow">{name}</a>'
        f'{" — " + price_str if price_str else ""}'
        f'</p>\n'
    )


# ─── 본문 링크 삽입 ──────────────────────────────────

def _insert_coupang_block(soup, block_html: str) -> None:
    """결론 H2 앞 또는 본문 끝에 쿠팡 블록 삽입"""
    for h2 in soup.find_all('h2'):
        if any(kw in h2.get_text() for kw in ['결론', '마무리', '정리', '요약']):
            h2.insert_before(BeautifulSoup(block_html, 'html.parser'))
            return
    soup.append(BeautifulSoup(block_html, 'html.parser'))


def insert_links_into_html(html_content: str, coupang_keywords: list[str],
                            fixed_links: list[dict],
                            fallback_coupang_url: str = '') -> str:
    """HTML 본문에 쿠팡 링크와 고정 링크 삽입"""
    soup = BeautifulSoup(html_content, 'html.parser')

    # 고정 링크 (키워드 텍스트가 본문에 있으면 첫 번째 등장 위치에 링크)
    for fixed in fixed_links:
        kw = fixed.get('keyword', '')
        link_url = fixed.get('url', '')
        label = fixed.get('label', kw)
        if not kw or not link_url:
            continue
        for p in soup.find_all(['p', 'li']):
            text = p.get_text()
            if kw in text:
                # 이미 링크가 있으면 건너뜀
                if p.find('a', string=re.compile(re.escape(kw))):
                    break
                new_html = p.decode_contents().replace(
                    kw,
                    f'<a href="{link_url}" target="_blank">{kw}</a>',
                    1
                )
                new_tag = BeautifulSoup(f'<{p.name}>{new_html}</{p.name}>', 'html.parser').find(p.name)
                p.replace_with(new_tag)
                break

    inserted_coupang_block = False

    if coupang_keywords:
        if COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY:
            # API 키 있음 → 상품 검색 후 박스 삽입
            coupang_block_parts = []
            for kw in coupang_keywords[:3]:
                products = search_coupang_products(kw, limit=2)
                for product in products:
                    coupang_block_parts.append(build_coupang_link_html(product))

            if coupang_block_parts:
                block_html = (
                    '<div class="coupang-products">\n'
                    '<p><strong>관련 상품 추천</strong></p>\n'
                    + ''.join(coupang_block_parts) +
                    '</div>\n'
                )
                _insert_coupang_block(soup, block_html)
                inserted_coupang_block = True

        elif fallback_coupang_url:
            # API 키 없음 → 기본 쿠팡 링크 삽입
            keyword_label = ', '.join(coupang_keywords[:3])
            block_html = (
                '<div class="coupang-products">\n'
                f'<p>🛒 <a href="{fallback_coupang_url}" target="_blank" rel="nofollow">'
                f'{keyword_label} 관련 상품 보기 (쿠팡)</a></p>\n'
                '</div>\n'
            )
            _insert_coupang_block(soup, block_html)
            inserted_coupang_block = True
            logger.info(f"API 키 없음 — 기본 쿠팡 링크 삽입: {keyword_label}")

    if not inserted_coupang_block and fallback_coupang_url:
        block_html = (
            '<div class="coupang-products">\n'
            '<p>🛒 <a href="{url}" target="_blank" rel="nofollow">'
            '추천 상품 보기 (쿠팡)</a></p>\n'
            '</div>\n'
        ).format(url=fallback_coupang_url)
        _insert_coupang_block(soup, block_html)
        logger.info("쿠팡 키워드 없음 — 기본 쿠팡 링크 삽입")

    return str(soup)


def add_disclaimer(html_content: str, disclaimer_text: str) -> str:
    """쿠팡 필수 면책 문구 추가 (이미 있으면 건너뜀)"""
    if disclaimer_text in html_content:
        return html_content
    disclaimer_html = (
        f'\n<hr/>\n'
        f'<p class="affiliate-disclaimer"><small>⚠️ {disclaimer_text}</small></p>\n'
    )
    return html_content + disclaimer_html


# ─── 내부 링크 ───────────────────────────────────────

DATA_DIR = BASE_DIR / 'data'
_STOP_WORDS = {
    '있다', '없다', '하다', '되다', '이다', '같다', '보다',
    '이', '그', '저', '이것', '그것', '저것',
    # 주제와 무관한 일반 명사
    '기초', '가이드', '방법', '소개', '이해', '정리', '완벽', '총정리',
    '입문', '튜토리얼', '사용법', '활용법', '알아보기', '살펴보기',
}


def _load_published_index() -> list[dict]:
    """발행 이력 로드: [{title, url, tags}]"""
    published_dir = DATA_DIR / 'published'
    records = []
    if not published_dir.exists():
        return records
    for f in sorted(published_dir.glob('*.json')):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            url = d.get('url', '')
            title = d.get('title', '')
            tags = d.get('tags', [])
            if url and title:
                records.append({'title': title, 'url': url, 'tags': tags})
        except Exception:
            pass
    return records


def _score_relevance(candidate_title: str, candidate_tags: list[str],
                     current_title: str, current_body_plain: str) -> float:
    """현재 글과 후보 글의 관련도 점수 (0~1)"""
    score = 0.0
    combined = (current_title + ' ' + current_body_plain).lower()
    for word in re.findall(r'[가-힣a-zA-Z0-9]{2,}', candidate_title):
        if word.lower() in _STOP_WORDS:
            continue
        if word.lower() in combined:
            score += 0.3
    for tag in candidate_tags:
        if tag.lower() in combined:
            score += 0.2
    return min(score, 1.0)


def insert_internal_links(html_content: str, article: dict, max_links: int = 3) -> str:
    """발행된 다른 글과의 내부 링크 + 하단 '관련 글' 섹션 삽입"""
    current_title = article.get('title', '')
    published = _load_published_index()
    if not published:
        return html_content

    soup = BeautifulSoup(html_content, 'html.parser')
    plain_body = soup.get_text()

    # 관련도 점수 계산 (현재 글 제외, 최소 임계값 0.25 이상만 포함)
    scored = []
    for rec in published:
        if rec['title'] == current_title:
            continue
        score = _score_relevance(rec['title'], rec['tags'], current_title, plain_body)
        if score >= 0.25:
            scored.append((score, rec))
    scored.sort(key=lambda x: -x[0])
    top_related = [rec for _, rec in scored[:max_links]]

    if not top_related:
        return html_content

    # 하단 '관련 글' 섹션 생성
    items_html = '\n'.join(
        f'<li><a href="{r["url"]}">{r["title"]}</a></li>'
        for r in top_related
    )
    related_html = (
        '<div class="t4p-related" style="margin:2em 0;padding:1rem 1.1rem;'
        'border:1px solid #e5e7eb;border-radius:14px;background:#f9fafb">\n'
        '<p style="font-weight:700;margin:0 0 .6em">관련 글</p>\n'
        f'<ul style="margin:.4em 0 0 1.2em;padding:0">\n{items_html}\n</ul>\n'
        '</div>\n'
    )

    # article 태그 닫기 전 또는 본문 끝에 삽입
    article_tag = soup.find('article')
    if article_tag:
        article_tag.append(BeautifulSoup(related_html, 'html.parser'))
    else:
        soup.append(BeautifulSoup(related_html, 'html.parser'))

    logger.info(f"내부 링크 {len(top_related)}개 삽입: {[r['title'][:30] for r in top_related]}")
    return str(soup)


# ─── 메인 함수 ───────────────────────────────────────

def process(article: dict, html_content: str) -> str:
    """
    링크봇 메인: HTML 본문에 쿠팡/어필리에이트 링크 + 내부 링크 삽입 후 반환
    """
    logger.info(f"링크 삽입 시작: {article.get('title', '')}")
    affiliate_cfg = load_config('affiliate_links.json')

    coupang_keywords = article.get('coupang_keywords', [])
    fixed_links = affiliate_cfg.get('fixed_links', [])
    disclaimer_text = affiliate_cfg.get('disclaimer_text', '')

    # fixed_links 중 type=coupang인 항목의 URL을 fallback으로 사용
    fallback_coupang_url = next(
        (f['url'] for f in fixed_links if f.get('type') == 'coupang' and f.get('url')),
        ''
    )

    # 내부 링크 삽입
    html_content = insert_internal_links(html_content, article)

    # 링크 삽입
    html_content = insert_links_into_html(
        html_content, coupang_keywords, fixed_links, fallback_coupang_url
    )

    # 쿠팡 링크/배너가 들어갔으면 면책 문구 추가
    if 'coupang-products' in html_content and disclaimer_text:
        html_content = add_disclaimer(html_content, disclaimer_text)

    logger.info("링크 삽입 완료")
    return html_content


if __name__ == '__main__':
    sample_html = '''
    <h2>ChatGPT 소개</h2>
    <p>ChatGPT Plus를 사용하면 더 빠른 응답을 받을 수 있습니다.</p>
    <h2>키보드 추천</h2>
    <p>좋은 키보드는 생산성을 높입니다.</p>
    <h2>결론</h2>
    <p>AI 도구를 잘 활용하세요.</p>
    '''
    sample_article = {
        'title': '테스트 글',
        'coupang_keywords': ['키보드', '마우스'],
    }
    result = process(sample_article, sample_html)
    print(result[:500])
