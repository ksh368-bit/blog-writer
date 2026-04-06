"""
수집봇 (collector_bot.py)
역할: 트렌드/도구/사례 수집 + 품질 점수 계산 + 폐기 규칙 적용
실행: 매일 07:00 (스케줄러 호출)
"""
import json
import logging
import os
import re
import hashlib
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / 'config'
DATA_DIR = BASE_DIR / 'data'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'collector.log', encoding='utf-8'),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# 코너별 타입
CORNER_TYPES = {
    'easy_guide': '쉬운세상',
    'hidden_gems': '숨은보물',
    'vibe_report': '바이브리포트',
    'fact_check': '팩트체크',
    'one_cut': '한컷',
}

# 글감 타입 비율: 에버그린 50%, 트렌드 30%, 개성 20%
TOPIC_RATIO = {'evergreen': 0.5, 'trending': 0.3, 'personality': 0.2}


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def load_config(filename: str) -> dict:
    with open(CONFIG_DIR / filename, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_published_titles() -> list[str]:
    """발행/작성/대기 이력에서 제목+topic 목록 통합 로드 (중복 감지용)"""
    titles = []
    for subdir in ('published', 'originals', 'topics'):
        folder = DATA_DIR / subdir
        if not folder.exists():
            continue
        for f in folder.glob('*.json'):
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                for key in ('title', 'topic'):
                    val = data.get(key, '').strip()
                    if val and val not in titles:
                        titles.append(val)
            except Exception:
                pass
    return titles


def title_similarity(a: str, b: str) -> float:
    """핵심 명사 중심 유사도: SequenceMatcher + Jaccard 키워드 겹침의 최댓값"""
    import re
    _STOP = {'보면', '읽으면', '하면', '되면', '알면', '이해하기', '완벽정리', '총정리',
             '소개', '정리', '방법', '알아보기', '살펴보기', '가이드', '입문', '활용법',
             '동시에', '한번에', '모두', '전부', '같이', '함께', '이후', '이전', '최신'}

    def tokenize(s: str) -> set[str]:
        tokens = re.findall(r'[가-힣a-zA-Z0-9]{2,}', s.lower())
        return {t for t in tokens if t not in _STOP}

    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    # 부분 문자열 포함 매칭 (예: '지식' ⊂ '지식저장소')
    def soft_intersect(s1: set, s2: set) -> int:
        count = 0
        for t in s1:
            if any(t in u or u in t for u in s2):
                count += 1
        return count

    inter = soft_intersect(ta, tb)

    # Jaccard: 공통 / 합집합
    jaccard = inter / len(ta | tb)

    # Coverage: 짧은 제목 기준 포함률 (짧은 제목이 긴 제목의 부분집합)
    coverage = inter / min(len(ta), len(tb))

    # SequenceMatcher (불용어 제거 후)
    na = ' '.join(sorted(ta))
    nb = ' '.join(sorted(tb))
    seq = SequenceMatcher(None, na, nb).ratio()

    return max(jaccard, coverage * 0.90, seq)


def is_duplicate(title: str, published_titles: list[str], threshold: float = 0.65) -> bool:
    for pub_title in published_titles:
        if title_similarity(title, pub_title) >= threshold:
            return True
    return False


def parse_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return None
    return None


def calc_freshness_score(published_at: datetime | None, rules: dict) -> int:
    """발행 시간 기준 신선도 점수"""
    freshness_cfg = rules['scoring']['freshness']
    max_score = freshness_cfg['max']
    full_score_hours = freshness_cfg.get('hours_full_score', 24)
    zero_score_hours = freshness_cfg.get('hours_zero_score', 168)
    missing_date_score = freshness_cfg.get('missing_date_score', 0)

    if published_at is None:
        return missing_date_score
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = (now - published_at).total_seconds() / 3600
    age_hours = max(age_hours, 0)
    if age_hours <= full_score_hours:
        return max_score
    elif age_hours >= zero_score_hours:
        return 0
    else:
        ratio = 1 - (age_hours - full_score_hours) / max((zero_score_hours - full_score_hours), 1)
        return int(max_score * ratio)


def calc_korean_relevance(text: str, rules: dict) -> int:
    """한국 독자 관련성 점수"""
    max_score = rules['scoring']['korean_relevance']['max']
    keywords = rules['scoring']['korean_relevance']['keywords']

    # 한국어 문자(가-힣) 비율 체크 — 한국어 콘텐츠 자체에 기본점수 부여
    korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    korean_ratio = korean_chars / max(len(text), 1)
    if korean_ratio >= 0.15:
        base = 15  # 한국어 텍스트면 기본 15점
    elif korean_ratio >= 0.05:
        base = 8
    else:
        base = 0

    # 브랜드/지역 키워드 보너스
    matched = sum(1 for kw in keywords if kw in text)
    bonus = min(matched * 5, max_score - base)

    return min(base + bonus, max_score)


def calc_source_trust(source_url: str, rules: dict) -> tuple[int, str]:
    """출처 신뢰도 점수 + 레벨"""
    trust_cfg = rules['scoring']['source_trust']
    high_src = trust_cfg.get('high_sources', [])
    low_src = trust_cfg.get('low_sources', [])
    unknown_score = trust_cfg['levels'].get('unknown', 0)
    if not source_url:
        return unknown_score, 'unknown'

    parsed = urlparse(source_url if '://' in source_url else f'https://{source_url}')
    host = (parsed.netloc or '').lower()
    if not host:
        return unknown_score, 'unknown'

    url_lower = source_url.lower()
    for s in low_src:
        if s in url_lower or s in host:
            return trust_cfg['levels']['low'], 'low'
    for s in high_src:
        if s in url_lower or s in host:
            return trust_cfg['levels']['high'], 'high'
    return trust_cfg['levels']['medium'], 'medium'


def calc_monetization(text: str, rules: dict) -> int:
    """수익 연결 가능성 점수"""
    keywords = rules['scoring']['monetization']['keywords']
    matched = sum(1 for kw in keywords if kw in text)
    return min(matched * 5, rules['scoring']['monetization']['max'])


def calc_topic_fit(text: str, rules: dict) -> int:
    """핵심 주제군 적합도 점수"""
    cfg = rules['scoring'].get('topic_fit', {})
    keywords = cfg.get('keywords', [])
    if not keywords:
        return 0

    text_lower = text.lower()
    matched = sum(1 for kw in keywords if kw.lower() in text_lower)
    return min(matched * 5, cfg.get('max', 0))


def calc_negative_topic_fit(text: str, rules: dict) -> int:
    """비핵심 주제 감점"""
    cfg = rules['scoring'].get('negative_topic_fit', {})
    keywords = cfg.get('keywords', [])
    if not keywords:
        return 0

    text_lower = text.lower()
    matched = sum(1 for kw in keywords if kw.lower() in text_lower)
    return min(matched * 5, cfg.get('max', 0))


def calc_novelty_score(item: dict, rules: dict) -> int:
    """글감 자체가 새롭게 느껴지는 정도"""
    cfg = rules['scoring'].get('novelty', {})
    text = f"{item.get('topic', '')} {item.get('description', '')}".lower()
    score = 0

    for kw in cfg.get('keywords', []):
        if kw.lower() in text:
            score += 3

    topic = item.get('topic', '')
    if re.search(r'\d', text):
        score += 2
    if any(mark in topic for mark in [':', '—', '→']):
        score += 1
    if item.get('reference_views', 0) or item.get('reference_score', 0):
        score += 1

    return min(score, cfg.get('max', 0))


def calc_impact_score(item: dict, rules: dict) -> int:
    """글감 제목/설명만 읽어도 감각적 인상이 오는 정도"""
    cfg = rules['scoring'].get('impact', {})
    topic = item.get('topic', '')
    description = item.get('description', '')
    text = f"{topic} {description}".lower()
    score = 0

    for kw in cfg.get('keywords', []):
        if kw.lower() in text:
            score += 3

    if re.search(r'[!?]', topic):
        score += 2
    if any(mark in topic for mark in ['달', '우주', '폭격', '책임', '경계', '자립']):
        score += 2
    if any(mark in description for mark in ['손으로', '바느질', '직접', '현실', '장면', '압도적']):
        score += 2
    if len(topic) >= 18:
        score += 1

    return min(score, cfg.get('max', 0))


def is_evergreen(title: str, rules: dict) -> bool:
    evergreen_kws = rules.get('evergreen_keywords', [])
    return any(kw in title for kw in evergreen_kws)


def apply_discard_rules(item: dict, rules: dict, published_titles: list[str]) -> str | None:
    """
    폐기 규칙 적용. 폐기 사유 반환(None이면 통과).
    """
    title = item.get('topic', '')
    text = title + ' ' + item.get('description', '')
    discard_rules = rules.get('discard_rules', [])

    for rule in discard_rules:
        rule_id = rule['id']

        if rule_id == 'no_korean_relevance':
            if item.get('korean_relevance_score', 0) == 0:
                return '한국 독자 관련성 없음'

        elif rule_id == 'unverified_source':
            if item.get('source_trust_level') == 'unknown':
                return '출처 불명'

        elif rule_id == 'duplicate_topic':
            threshold = rule.get('similarity_threshold', 0.8)
            if is_duplicate(title, published_titles, threshold):
                return f'기발행 주제와 유사도 {threshold*100:.0f}% 이상'

        elif rule_id == 'stale_trend':
            if not item.get('is_evergreen', False):
                max_days = rule.get('max_age_days', 7)
                pub_at = item.get('published_at')
                if pub_at:
                    if isinstance(pub_at, str):
                        try:
                            pub_at = datetime.fromisoformat(pub_at)
                        except Exception:
                            pub_at = None
                    if pub_at:
                        if pub_at.tzinfo is None:
                            pub_at = pub_at.replace(tzinfo=timezone.utc)
                        age_days = (datetime.now(timezone.utc) - pub_at).days
                        if age_days > max_days:
                            return f'{age_days}일 지난 트렌드'

        elif rule_id == 'promotional':
            kws = rule.get('keywords', [])
            if any(kw in text for kw in kws):
                return '광고성/홍보성 콘텐츠'

        elif rule_id == 'clickbait':
            patterns = rule.get('patterns', [])
            if any(p in text for p in patterns):
                return '클릭베이트성 주제'

        elif rule_id == 'lacks_novelty_and_impact':
            max_novelty = rule.get('max_novelty_score', 5)
            max_impact = rule.get('max_impact_score', 5)
            if item.get('novelty_score', 0) <= max_novelty and item.get('impact_score', 0) <= max_impact:
                return '새로움과 임팩트가 모두 약함'

    return None


def assign_corner(item: dict, topic_type: str) -> str:
    """글감에 코너 배정"""
    title = item.get('topic', '').lower()
    text = f"{item.get('topic', '')} {item.get('description', '')}".lower()
    source = item.get('source', 'rss').lower()
    philosophy_kws = ['윤리', '도덕', '철학', '가치관', '삶', '태도', '시각', '관점', '책임', '인간']

    if topic_type == 'evergreen':
        if any(kw in title for kw in ['가이드', '방법', '사용법', '입문', '튜토리얼', '기초']):
            return '쉬운세상'
        return '숨은보물'
    elif topic_type == 'trending':
        if any(kw in text for kw in philosophy_kws):
            return '바이브리포트'
        if source in ['github', 'product_hunt']:
            return '숨은보물'
        return '쉬운세상'
    else:  # personality
        return '바이브리포트'


def calculate_quality_score(item: dict, rules: dict) -> int:
    """0-100점 품질 점수 계산"""
    text = item.get('topic', '') + ' ' + item.get('description', '')
    source_url = item.get('source_url', '')
    pub_at_str = item.get('published_at')
    pub_at = parse_datetime(pub_at_str)

    kr_score = calc_korean_relevance(text, rules)
    fresh_score = calc_freshness_score(pub_at, rules)
    # search_demand: pytrends 연동 후 실제값 사용 (RSS 기본값 12)
    search_score = item.get('search_demand_score', 12)
    # 신뢰도: _trust_override 이미 설정된 경우 우선 사용
    if '_trust_score' in item:
        trust_score = item['_trust_score']
        trust_level = item.get('source_trust_level', 'medium')
    else:
        trust_score, trust_level = calc_source_trust(source_url, rules)
    mono_score = calc_monetization(text, rules)
    topic_fit_score = calc_topic_fit(text, rules)
    negative_topic_fit_score = calc_negative_topic_fit(text, rules)
    novelty_score = calc_novelty_score(item, rules)
    impact_score = calc_impact_score(item, rules)

    item['korean_relevance_score'] = kr_score
    item['source_trust_level'] = trust_level
    item['is_evergreen'] = is_evergreen(item.get('topic', ''), rules)
    item['topic_fit_score'] = topic_fit_score
    item['negative_topic_fit_score'] = negative_topic_fit_score
    item['novelty_score'] = novelty_score
    item['impact_score'] = impact_score

    total = (
        kr_score + fresh_score + search_score + trust_score + mono_score
        + topic_fit_score + novelty_score + impact_score - negative_topic_fit_score
    )
    return min(total, 100)


# ─── 수집 소스별 함수 ─────────────────────────────────

def _parse_google_trends_traffic(value: str) -> int:
    text = (value or '').strip().replace(',', '')
    match = re.match(r'(\d+)([천만]?)\+?', text)
    if not match:
        return 0

    number = int(match.group(1))
    unit = match.group(2)
    if unit == '천':
        number *= 1_000
    elif unit == '만':
        number *= 10_000
    return number


def collect_google_trends() -> list[dict]:
    """Google Trends RSS — 한국 실시간 인기 검색어"""
    items = []
    try:
        url = 'https://trends.google.com/trending/rss?geo=KR'
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7',
            'Referer': 'https://trends.google.com/trending?geo=KR&hl=ko',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        for entry in feed.entries[:20]:
            keyword = entry.get('title', '').strip()
            if not keyword:
                continue

            approx_traffic = entry.get('ht_approx_traffic', '')
            traffic_value = _parse_google_trends_traffic(approx_traffic)
            if traffic_value >= 50_000:
                search_score = 20
            elif traffic_value >= 10_000:
                search_score = 17
            elif traffic_value >= 5_000:
                search_score = 14
            elif traffic_value >= 1_000:
                search_score = 11
            else:
                search_score = 8

            news_title = entry.get('ht_news_item_title', '')
            news_snippet = entry.get('ht_news_item_snippet', '')
            news_source = entry.get('ht_news_item_source', '')
            description_parts = [part for part in [approx_traffic, news_title, news_snippet, news_source] if part]
            published_at = None
            if entry.get('published'):
                pub_dt = parsedate_to_datetime(entry.get('published'))
                published_at = pub_dt.astimezone(timezone.utc).isoformat() if pub_dt else None

            items.append({
                'topic': keyword,
                'description': ' | '.join(description_parts)[:300] or f'Google Trends 한국 트렌딩 키워드: {keyword}',
                'source': 'google_trends',
                'source_url': f'https://trends.google.com/trending?geo=KR&hl=ko',
                'published_at': published_at,
                'search_demand_score': search_score,
                'topic_type': 'trending',
                'reference_title': news_title or keyword,
                'reference_source': news_source,
                'reference_traffic': approx_traffic,
            })
    except Exception as e:
        logger.warning(f"Google Trends 수집 실패: {e}")
    return items


def collect_github_trending(sources_cfg: dict) -> list[dict]:
    """GitHub Trending 크롤링"""
    items = []
    cfg = sources_cfg.get('github_trending', {})
    languages = cfg.get('languages', [''])
    since = cfg.get('since', 'daily')

    for lang in languages:
        url = f"https://github.com/trending/{lang}?since={since}"
        try:
            resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(resp.text, 'lxml')
            repos = soup.select('article.Box-row')
            for repo in repos[:10]:
                name_el = repo.select_one('h2 a')
                desc_el = repo.select_one('p')
                stars_el = repo.select_one('a[href*="stargazers"]')
                if not name_el:
                    continue
                repo_path = name_el.get('href', '').strip('/')
                topic = repo_path.replace('/', ' / ')
                desc = desc_el.get_text(strip=True) if desc_el else ''
                stars = stars_el.get_text(strip=True) if stars_el else '0'
                items.append({
                    'topic': topic,
                    'description': desc,
                    'source': 'github',
                    'source_url': f'https://github.com/{repo_path}',
                    'published_at': datetime.now(timezone.utc).isoformat(),
                    'search_demand_score': 12,
                    'topic_type': 'trending',
                    'extra': {'stars': stars},
                })
        except Exception as e:
            logger.warning(f"GitHub Trending 수집 실패 ({lang}): {e}")
    return items


def collect_hacker_news(sources_cfg: dict) -> list[dict]:
    """Hacker News API 상위 스토리"""
    items = []
    cfg = sources_cfg.get('hacker_news', {})
    api_url = cfg.get('url', 'https://hacker-news.firebaseio.com/v0/topstories.json')
    top_n = cfg.get('top_n', 30)
    try:
        resp = requests.get(api_url, timeout=10)
        story_ids = resp.json()[:top_n]
        for sid in story_ids:
            story_resp = requests.get(
                f'https://hacker-news.firebaseio.com/v0/item/{sid}.json', timeout=5
            )
            story = story_resp.json()
            if not story or story.get('type') != 'story':
                continue
            pub_ts = story.get('time')
            pub_at = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat() if pub_ts else None
            items.append({
                'topic': story.get('title', ''),
                'description': story.get('url', ''),
                'source': 'hacker_news',
                'source_url': story.get('url', f'https://news.ycombinator.com/item?id={sid}'),
                'published_at': pub_at,
                'search_demand_score': 8,
                'topic_type': 'trending',
            })
    except Exception as e:
        logger.warning(f"Hacker News 수집 실패: {e}")
    return items


def collect_product_hunt(sources_cfg: dict) -> list[dict]:
    """Product Hunt RSS"""
    items = []
    cfg = sources_cfg.get('product_hunt', {})
    rss_url = cfg.get('rss_url', 'https://www.producthunt.com/feed')
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:15]:
            pub_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                pub_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
            items.append({
                'topic': entry.get('title', ''),
                'description': entry.get('summary', ''),
                'source': 'product_hunt',
                'source_url': entry.get('link', ''),
                'published_at': pub_at,
                'search_demand_score': 10,
                'topic_type': 'trending',
            })
    except Exception as e:
        logger.warning(f"Product Hunt 수집 실패: {e}")
    return items


def collect_rss_feeds(sources_cfg: dict) -> list[dict]:
    """설정된 RSS 피드 수집"""
    items = []
    feeds = sources_cfg.get('rss_feeds', [])
    for feed_cfg in feeds:
        url = feed_cfg.get('url', '')
        trust = feed_cfg.get('trust_level', 'medium')
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                pub_at = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
                items.append({
                    'topic': entry.get('title', ''),
                    'description': entry.get('summary', '') or entry.get('description', ''),
                    'source': 'rss',
                    'source_name': feed_cfg.get('name', ''),
                    'source_url': entry.get('link', ''),
                    'published_at': pub_at,
                    'search_demand_score': 8,
                    'topic_type': 'trending',
                    '_trust_override': trust,
                })
        except Exception as e:
            logger.warning(f"RSS 수집 실패 ({url}): {e}")
    return items


def collect_youtube_trending(sources_cfg: dict, rules: dict) -> list[dict]:
    """YouTube Data API v3 — 한국 인기 동영상 (Science & Technology 카테고리)"""
    items = []
    cfg = sources_cfg.get('youtube_trending', {})
    api_key = os.getenv(cfg.get('api_key_env', 'YOUTUBE_API_KEY'), '')
    if not api_key:
        logger.warning("YOUTUBE_API_KEY 없음 — YouTube Trending 수집 건너뜀")
        return items

    region = cfg.get('region', 'KR')
    category_id = cfg.get('category_id', '28')
    max_results = cfg.get('max_results', 20)
    min_views = rules.get('engagement_filters', {}).get('youtube_min_views', 50000)

    try:
        url = 'https://www.googleapis.com/youtube/v3/videos'
        params = {
            'part': 'snippet,statistics',
            'chart': 'mostPopular',
            'regionCode': region,
            'videoCategoryId': category_id,
            'maxResults': max_results,
            'key': api_key,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for video in data.get('items', []):
            stats = video.get('statistics', {})
            snippet = video.get('snippet', {})
            view_count = int(stats.get('viewCount', 0))
            like_count = int(stats.get('likeCount', 0))

            if view_count < min_views:
                continue

            if view_count >= 5_000_000:
                search_score = 20
            elif view_count >= 500_000:
                search_score = 15
            elif view_count >= 100_000:
                search_score = 10
            else:
                search_score = 5

            video_id = video.get('id', '')
            pub_at = snippet.get('publishedAt', '')
            items.append({
                'topic': snippet.get('title', ''),
                'description': snippet.get('description', '')[:300],
                'source': 'youtube',
                'source_url': f'https://www.youtube.com/watch?v={video_id}',
                'published_at': pub_at,
                'search_demand_score': search_score,
                'topic_type': 'trending',
                'reference_title': snippet.get('title', ''),
                'reference_views': view_count,
                'reference_likes': like_count,
            })
    except Exception as e:
        logger.warning(f"YouTube Trending 수집 실패: {e}")
    return items


def collect_x_trending(sources_cfg: dict, rules: dict) -> list[dict]:
    """X API v2 Recent Search — 키워드 기반 최근 포스트 수집"""
    items = []
    cfg = sources_cfg.get('x_search', {})
    enabled = env_flag('X_SOURCE_ENABLED', cfg.get('enabled', False))
    if not enabled:
        logger.info("X 수집 비활성화됨 — sources.json 또는 X_SOURCE_ENABLED로 활성화 가능")
        return items

    bearer_token = os.getenv('X_BEARER_TOKEN', '')
    if not bearer_token:
        logger.warning("X_BEARER_TOKEN 없음 — X 수집 건너뜀")
        return items

    keywords = cfg.get('keywords') or sources_cfg.get('x_keywords', [])
    if not keywords:
        return items

    max_results = min(max(int(cfg.get('max_results', 10)), 10), 100)
    lang = cfg.get('lang', 'ko')
    sort_order = cfg.get('sort_order', 'relevancy')
    exclude_replies = cfg.get('exclude_replies', True)
    eng = rules.get('engagement_filters', {})
    min_likes = int(cfg.get('min_like_count', eng.get('x_min_like_count', 50)))
    min_retweets = int(cfg.get('min_retweet_count', eng.get('x_min_retweet_count', 10)))
    min_replies = int(cfg.get('min_reply_count', eng.get('x_min_reply_count', 3)))

    headers = {
        'Authorization': f'Bearer {bearer_token}',
        'User-Agent': 'blog-writer/1.0',
    }
    seen_ids = set()

    for keyword in keywords:
        query_parts = [f'"{keyword}"']
        if lang:
            query_parts.append(f'lang:{lang}')
        query_parts.append('-is:retweet')
        if exclude_replies:
            query_parts.append('-is:reply')

        params = {
            'query': ' '.join(query_parts),
            'max_results': max_results,
            'sort_order': sort_order,
            'tweet.fields': 'created_at,public_metrics,lang',
        }

        try:
            resp = requests.get(
                'https://api.x.com/2/tweets/search/recent',
                headers=headers,
                params=params,
                timeout=15,
            )
            if resp.status_code == 402:
                try:
                    error_data = resp.json()
                except Exception:
                    error_data = {}
                if error_data.get('title') == 'CreditsDepleted':
                    logger.warning(
                        "X 수집 중단 — 현재 계정의 X API 크레딧이 소진됨. "
                        "console.x.com 에서 크레딧 충전 후 재시도 필요"
                    )
                    return items
            resp.raise_for_status()
            data = resp.json()

            for tweet in data.get('data', []):
                tweet_id = tweet.get('id', '')
                if not tweet_id or tweet_id in seen_ids:
                    continue

                metrics = tweet.get('public_metrics', {})
                like_count = int(metrics.get('like_count', 0))
                retweet_count = int(metrics.get('retweet_count', 0))
                reply_count = int(metrics.get('reply_count', 0))
                quote_count = int(metrics.get('quote_count', 0))

                if (
                    like_count < min_likes
                    and retweet_count < min_retweets
                    and reply_count < min_replies
                ):
                    continue

                engagement = like_count + (retweet_count * 3) + (reply_count * 2) + (quote_count * 2)
                if engagement >= 5000:
                    search_score = 18
                elif engagement >= 1000:
                    search_score = 15
                elif engagement >= 300:
                    search_score = 12
                else:
                    search_score = 9

                text = re.sub(r'\s+', ' ', tweet.get('text', '')).strip()
                items.append({
                    'topic': text[:120],
                    'description': text[:300],
                    'source': 'x',
                    'source_url': f'https://x.com/i/web/status/{tweet_id}',
                    'published_at': tweet.get('created_at', ''),
                    'search_demand_score': search_score,
                    'topic_type': 'trending',
                    'reference_title': text[:120],
                    'reference_likes': like_count,
                    'reference_retweets': retweet_count,
                    'reference_replies': reply_count,
                    'related_keywords': [keyword],
                })
                seen_ids.add(tweet_id)
        except Exception as e:
            logger.warning(f"X 수집 실패 ({keyword}): {e}")
    return items


def collect_reddit_trending(sources_cfg: dict, rules: dict) -> list[dict]:
    """Reddit PRAW — 인기 서브레딧 상위 글 (score + upvote_ratio 필터)"""
    items = []
    cfg = sources_cfg.get('reddit', {})
    enabled = env_flag('REDDIT_SOURCE_ENABLED', cfg.get('enabled', False))
    if not enabled:
        logger.info("Reddit 수집 비활성화됨 — sources.json 또는 REDDIT_SOURCE_ENABLED로 활성화 가능")
        return items

    client_id = os.getenv('REDDIT_CLIENT_ID', '')
    client_secret = os.getenv('REDDIT_CLIENT_SECRET', '')
    if not client_id or not client_secret:
        logger.warning("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET 없음 — Reddit 수집 건너뜀")
        return items

    subreddits = cfg.get('subreddits', ['technology', 'programming', 'LocalLLaMA', 'ChatGPT'])
    time_filter = cfg.get('time_filter', 'day')
    limit = cfg.get('limit', 25)
    eng = rules.get('engagement_filters', {})
    min_score = eng.get('reddit_min_score', 300)
    min_ratio = eng.get('reddit_min_upvote_ratio', 0.85)

    try:
        import praw
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent='blog-writer/1.0',
        )
        for sub_name in subreddits:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.top(time_filter=time_filter, limit=limit):
                    if post.score < min_score or post.upvote_ratio < min_ratio:
                        continue

                    if post.score >= 10_000:
                        search_score = 20
                    elif post.score >= 1_000:
                        search_score = 15
                    else:
                        search_score = 10

                    pub_at = datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat()
                    items.append({
                        'topic': post.title,
                        'description': (post.selftext or post.url)[:300],
                        'source': 'reddit',
                        'source_url': f'https://reddit.com{post.permalink}',
                        'published_at': pub_at,
                        'search_demand_score': search_score,
                        'topic_type': 'trending',
                        'reference_title': post.title,
                        'reference_score': post.score,
                        'reference_comments': post.num_comments,
                    })
            except Exception as e:
                logger.warning(f"Reddit r/{sub_name} 수집 실패: {e}")
    except ImportError:
        logger.warning("praw 미설치 — Reddit 수집 건너뜀 (pip install praw)")
    except Exception as e:
        logger.warning(f"Reddit 수집 실패: {e}")
    return items


def extract_coupang_keywords(topic: str, description: str) -> list[str]:
    """글감에서 쿠팡 검색 키워드 추출"""
    product_keywords = [
        '마이크', '웹캠', '키보드', '마우스', '모니터', '노트북', '이어폰',
        '헤드셋', '외장하드', 'USB허브', '책상', '의자', '서적', '책', '스피커',
    ]
    text = topic + ' ' + description
    found = [kw for kw in product_keywords if kw in text]
    if not found:
        # IT 기기 류 글이면 기본 키워드
        if any(kw in text for kw in ['도구', '앱', '툴', '소프트웨어', '서비스']):
            found = ['키보드', '마우스']
    return found


def save_discarded(item: dict, reason: str):
    """폐기된 글감 로그 저장"""
    discard_dir = DATA_DIR / 'discarded'
    discard_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    log_file = discard_dir / f'{today}_discarded.jsonl'
    record = {**item, 'discard_reason': reason, 'discarded_at': datetime.now().isoformat()}
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def save_topic(item: dict):
    """합격한 글감을 data/topics/에 저장"""
    topics_dir = DATA_DIR / 'topics'
    topics_dir.mkdir(exist_ok=True)
    topic_id = hashlib.md5(item['topic'].encode()).hexdigest()[:8]
    filename = f"{datetime.now().strftime('%Y%m%d')}_{topic_id}.json"
    with open(topics_dir / filename, 'w', encoding='utf-8') as f:
        json.dump(item, f, ensure_ascii=False, indent=2)


def run():
    logger.info("=== 수집봇 시작 ===")
    rules = load_config('quality_rules.json')
    sources_cfg = load_config('sources.json')
    published_titles = load_published_titles()
    min_score = rules.get('min_score', 70)
    duplicate_rule = next(
        (rule for rule in rules.get('discard_rules', []) if rule.get('id') == 'duplicate_topic'),
        {}
    )
    duplicate_threshold = duplicate_rule.get('similarity_threshold', 0.8)

    # 수집
    all_items = []
    all_items += collect_google_trends()
    all_items += collect_github_trending(sources_cfg)
    all_items += collect_product_hunt(sources_cfg)
    all_items += collect_hacker_news(sources_cfg)
    all_items += collect_rss_feeds(sources_cfg)
    all_items += collect_youtube_trending(sources_cfg, rules)
    all_items += collect_x_trending(sources_cfg, rules)
    all_items += collect_reddit_trending(sources_cfg, rules)

    logger.info(f"수집 완료: {len(all_items)}개")

    passed = []
    candidates = []
    discarded_count = 0

    for item in all_items:
        if not item.get('topic'):
            continue

        # 신뢰도 오버라이드 (RSS 피드별 설정)
        trust_override = item.pop('_trust_override', None)
        if trust_override:
            trust_levels = rules['scoring']['source_trust']['levels']
            item['source_trust_level'] = trust_override
            item['_trust_score'] = trust_levels.get(trust_override, trust_levels['medium'])

        # 품질 점수 계산
        score = calculate_quality_score(item, rules)
        item['quality_score'] = score

        # 폐기 규칙 검사
        discard_reason = apply_discard_rules(item, rules, published_titles)
        if discard_reason:
            save_discarded(item, discard_reason)
            discarded_count += 1
            logger.debug(f"폐기: [{score}점] {item['topic']} — {discard_reason}")
            continue

        if score < min_score:
            save_discarded(item, f'품질 점수 미달 ({score}점 < {min_score}점)')
            discarded_count += 1
            logger.debug(f"폐기: [{score}점] {item['topic']}")
            continue

        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            item.get('quality_score', 0),
            item.get('search_demand_score', 0),
            item.get('_trust_score', 0),
        ),
        reverse=True,
    )
    selected_titles = []

    for item in candidates:
        if is_duplicate(item.get('topic', ''), selected_titles, duplicate_threshold):
            save_discarded(item, f'동일 배치 내 중복 주제 (유사도 {duplicate_threshold*100:.0f}% 이상)')
            discarded_count += 1
            logger.debug(f"폐기: [{item['quality_score']}점] {item['topic']} — 동일 배치 중복")
            continue

        # 코너 배정
        topic_type = item.get('topic_type', 'trending')
        corner = assign_corner(item, topic_type)
        item['corner'] = corner

        # 쿠팡 키워드 추출
        item['coupang_keywords'] = extract_coupang_keywords(
            item.get('topic', ''), item.get('description', '')
        )

        # 트렌딩 경과 시간 표시
        pub_at_str = item.get('published_at')
        if pub_at_str:
            try:
                pub_at = datetime.fromisoformat(pub_at_str)
                if pub_at.tzinfo is None:
                    pub_at = pub_at.replace(tzinfo=timezone.utc)
                hours_ago = int((datetime.now(timezone.utc) - pub_at).total_seconds() / 3600)
                item['trending_since'] = f'{hours_ago}시간 전' if hours_ago < 24 else f'{hours_ago // 24}일 전'
            except Exception:
                item['trending_since'] = '알 수 없음'

        # sources 필드 정리
        item['sources'] = [{'url': item.get('source_url', ''), 'title': item.get('topic', ''),
                             'date': item.get('published_at', '')}]
        item['related_keywords'] = item.get('topic', '').split()[:5]

        passed.append(item)
        selected_titles.append(item.get('topic', ''))

    # 테마 다양성 쿼터: AI/테크 최대 3개, 나머지 카테고리 최대 각 2개
    _COLLECTOR_THEME_CLUSTERS: dict[str, list[str]] = {
        'ai_tech': [
            'ai', 'gpt', 'claude', 'gemini', 'llm', '인공지능', 'agent', '에이전트',
            'coding', 'code', 'github', '개발', '프로그래밍', 'show gn',
            '오픈소스', 'open source', '딥러닝', '머신러닝', 'machine learning',
        ],
        'finance': [
            '주식', 'etf', '투자', '나스닥', '코스피', '코스닥', 'bitcoin', 'btc',
            '금리', '펀드', '배당', '증시', '환율', '달러', '테슬라', '엔비디아',
            '반도체', '실적', '시황',
        ],
        'health': [
            '건강', '운동', '다이어트', '수면', '혈당', '단백질', '영양', '헬스',
            '비타민', '식단', '근력',
        ],
        'realestate': [
            '부동산', '청약', '전세', '월세', '집값', '대출', '아파트', '분양',
        ],
    }
    THEME_MAX = {'ai_tech': 3, 'finance': 2, 'health': 2, 'realestate': 2}
    DEFAULT_THEME_MAX = 2

    def _collector_detect_theme(item: dict) -> str:
        text = f"{item.get('topic', '')} {item.get('description', '')}".lower()
        best, best_count = 'other', 0
        for theme, keywords in _COLLECTOR_THEME_CLUSTERS.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > best_count:
                best, best_count = theme, count
        return best if best_count >= 1 else 'other'

    theme_counts: dict[str, int] = {}
    quota_passed: list[dict] = []
    for item in passed:
        theme = _collector_detect_theme(item)
        limit = THEME_MAX.get(theme, DEFAULT_THEME_MAX)
        if theme_counts.get(theme, 0) >= limit:
            save_discarded(item, f'테마 쿼터 초과 ({theme} {limit}개 제한)')
            discarded_count += 1
            logger.debug(f"쿼터 초과 폐기: [{item['quality_score']}점][{theme}] {item['topic']}")
            continue
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        quota_passed.append(item)

    passed = quota_passed

    # 에버그린/트렌드/개성 비율 맞추기
    total_target = len(passed)
    evergreen = [i for i in passed if i.get('is_evergreen')]
    trending = [i for i in passed if not i.get('is_evergreen') and i.get('topic_type') == 'trending']
    personality = [i for i in passed if i.get('topic_type') == 'personality']

    logger.info(
        f"합격: {len(passed)}개 (에버그린 {len(evergreen)}, 트렌드 {len(trending)}, "
        f"개성 {len(personality)}) / 폐기: {discarded_count}개 / 테마: {theme_counts}"
    )

    # 글감 저장
    for item in passed:
        save_topic(item)
        logger.info(f"[{item['quality_score']}점][{item['corner']}] {item['topic']}")

    logger.info("=== 수집봇 완료 ===")
    return passed


if __name__ == '__main__':
    run()
