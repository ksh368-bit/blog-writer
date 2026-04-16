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
    # 동사/형용사 어간
    '있다', '없다', '하다', '되다', '이다', '같다', '보다', '받다', '주다',
    '오다', '가다', '나다', '들다', '쓰다', '알다', '말다', '두다',
    # 지시어
    '이', '그', '저', '이것', '그것', '저것', '여기', '거기', '저기',
    # 범용 명사 (주제 구분력 없음)
    '기초', '가이드', '방법', '소개', '이해', '정리', '완벽', '총정리',
    '입문', '튜토리얼', '사용법', '활용법', '알아보기', '살펴보기',
    '이유', '경우', '상황', '문제', '결과', '내용', '부분', '기준',
    '서비스', '기능', '사용', '적용', '관련', '최신', '변화', '시작',
    '관리', '설정', '확인', '지원', '제공', '공개', '발표', '업데이트',
    '한국', '국내', '해외', '글로벌', '세계', '시장', '업계', '분야',
    '사람', '사용자', '독자', '기업', '회사', '정부', '기관', '팀',
    # 2글자 수 단위·접속사·조사류
    '이번', '지난', '최근', '올해', '내년', '작년', '현재', '앞으로',
    '이미', '아직', '또한', '그리고', '하지만', '그러나', '따라서',
}

# 테마 클러스터 (writer_bot._THEME_CLUSTERS 와 동기화)
_THEME_CLUSTERS: dict[str, list[str]] = {
    'ai_tech': [
        'ai', 'gpt', 'claude', 'gemini', 'llm', '인공지능', 'agent', '에이전트',
        'coding', 'code', 'github', '개발', '프로그래밍', '오픈소스', '딥러닝',
        '머신러닝', '모델', '챗봇', '자동화',
    ],
    'finance': [
        '주식', 'etf', '투자', '나스닥', '코스피', '금리', '펀드', '배당',
        '증시', '환율', '달러', '반도체', '실적', '유가', '물가', '경제',
        '인플레이션', '금융', '대출', '부동산',
    ],
    'health': [
        '건강', '운동', '다이어트', '수면', '혈당', '단백질', '영양', '헬스',
        '비타민', '식단', '근력', '질병', '치료',
    ],
    'realestate': [
        '부동산', '청약', '전세', '월세', '집값', '아파트', '분양', '임대',
    ],
}


def _detect_theme(text: str) -> str | None:
    lower = text.lower()
    best_theme, best_count = None, 0
    for theme, keywords in _THEME_CLUSTERS.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count > best_count:
            best_theme, best_count = theme, count
    return best_theme if best_count >= 1 else None


def _load_published_index() -> list[dict]:
    """발행 이력 로드: [{title, url, tags, meta, topic, key_points}]"""
    published_dir = DATA_DIR / 'published'
    records = []
    if not published_dir.exists():
        return records
    for f in sorted(published_dir.glob('*.json')):
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
            url = d.get('url', '')
            title = d.get('title', '')
            if url and title:
                records.append({
                    'title': title,
                    'url': url,
                    'tags': d.get('tags', []),
                    'meta': d.get('meta', ''),
                    'topic': d.get('topic', ''),
                    'key_points': d.get('key_points', []),
                })
        except Exception:
            pass
    return records


def _score_relevance(candidate: dict, current_title: str, current_body_plain: str) -> float:
    """현재 글과 후보 글의 관련도 점수 (0~1)

    신호별 기여 상한을 두어 흔한 단어 하나로 과대평가되는 것을 방지:
      - 제목 단어:  단어당 0.15, 상한 0.30
      - tags:       태그당 0.15, 상한 0.25
      - key_points: 포인트당 0.20, 상한 0.35  ← 핵심 신호
      - meta 단어:  단어당 0.08, 상한 0.15
      - topic 단어: 단어당 0.08, 상한 0.15
      - 동일 테마:  +0.20 보너스
    """
    combined = (current_title + ' ' + current_body_plain).lower()

    def _matched_words(text: str, per: float, cap: float) -> float:
        total = 0.0
        for word in re.findall(r'[가-힣a-zA-Z0-9]{2,}', text):
            if word.lower() not in _STOP_WORDS and word.lower() in combined:
                total += per
                if total >= cap:
                    return cap
        return total

    score = 0.0
    _no_kp = not candidate.get('key_points')
    score += _matched_words(candidate.get('title', ''), 0.30 if _no_kp else 0.15, 0.45 if _no_kp else 0.30)
    score += _matched_words(candidate.get('meta', ''), 0.08, 0.15)
    score += _matched_words(candidate.get('topic', ''), 0.08, 0.15)

    # tags
    tag_score = 0.0
    for tag in candidate.get('tags', []):
        if tag.lower() in combined:
            tag_score += 0.15
            if tag_score >= 0.25:
                break
    score += tag_score

    # key_points — 가장 강한 관련성 신호
    kp_score = 0.0
    for kp in candidate.get('key_points', []):
        kp_words = re.findall(r'[가-힣a-zA-Z0-9]{2,}', str(kp))
        kp_hits = sum(1 for w in kp_words if w.lower() not in _STOP_WORDS and w.lower() in combined)
        if kp_hits >= 2:  # key_point 내 단어 2개 이상 매칭 시에만 유효
            kp_score += 0.20
            if kp_score >= 0.35:
                break
    score += kp_score

    # 동일 테마 보너스
    candidate_text = f"{candidate.get('title', '')} {candidate.get('topic', '')} {candidate.get('meta', '')}"
    current_text = f"{current_title} {current_body_plain[:300]}"
    if _detect_theme(candidate_text) and _detect_theme(candidate_text) == _detect_theme(current_text):
        score += 0.20

    return min(score, 1.0)


def insert_internal_links(html_content: str, article: dict, max_links: int = 3) -> str:
    """발행된 다른 글과의 내부 링크 + 하단 '관련 글' 섹션 삽입"""
    current_title = article.get('title', '')
    published = _load_published_index()
    if not published:
        return html_content

    soup = BeautifulSoup(html_content, 'html.parser')
    plain_body = soup.get_text()

    # 관련도 점수 계산 (현재 글 제외, 최소 임계값 0.50 이상만 포함)
    scored = []
    for rec in published:
        if rec['title'] == current_title:
            continue
        score = _score_relevance(rec, current_title, plain_body)
        if score >= 0.40:
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
