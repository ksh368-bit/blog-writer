"""
글쓰기 봇 (bots/writer_bot.py)
역할: topics 폴더의 글감을 읽어 EngineLoader 글쓰기 엔진으로 원고를 생성하고
      data/originals/에 저장하는 독립 실행형 스크립트.

호출:
  python bots/writer_bot.py             — 오늘 날짜 미처리 글감 전부 처리
  python bots/writer_bot.py --topic "..." — 직접 글감 지정 (대화형 사용)
  python bots/writer_bot.py --file path/to/topic.json

대시보드 manual-write 엔드포인트에서도 subprocess로 호출.
"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / 'bots'))

from prompt_layer.writer_prompt import compose_writer_prompt
from prompt_layer.writer_memory import (
    append_writer_memory,
    build_memory_guidance,
    build_learned_rules_section,
    extract_memory_points,
)
from prompt_layer.writer_review import (
    ABSTRACT_INTRO_MARKERS,
    ABSTRACT_MARKERS,
    DANGLING_PATTERNS,
    FACT_REVIEW_TEMPLATE,
    GENERIC_ENDINGS,
    META_OPENERS,
    presentation_review as layer_presentation_review,
    RECAP_MARKERS,
    RELATABLE_MARKERS,
    REPORT_MARKERS,
    structure_review as layer_structure_review,
    UNSUPPORTED_EFFECT_MARKERS,
    WEAK_START_PATTERNS,
)
from prompt_layer.writer_revision import (
    compose_min_revision_feedback,
    compose_revision_feedback,
    compose_section_prompt,
    compose_section_revision_feedback,
)

DATA_DIR = BASE_DIR / 'data'
CONFIG_DIR = BASE_DIR / 'config'
WRITER_MEMORY_PATH = DATA_DIR / 'writer_memory.json'
FAILED_SOURCES_PATH = DATA_DIR / 'failed_sources.json'
FAILED_WRITES_DIR = DATA_DIR / 'failed_writes'
LOG_DIR = BASE_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'writer.log', encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

MAX_WRITE_RETRIES = 12  # 최대 시도 횟수 (첫 시도 포함)
MAX_WRITE_ELAPSED_SECONDS = 900  # 한 글감당 최대 작성 시간 (ClaudeCodeWriter 기준 15분)
MAX_SAME_FEEDBACK_REPEATS = 3  # 실질적으로 같은 피드백이 반복될 때만 다음 글감으로 넘김
MIN_REVISION_ROUNDS = 1  # 최소 재작성 횟수. 최종 통과는 최소 2번째 시도부터 가능
RAW_TERM_REPLACEMENTS = {
    'claude/': '전용 자동화 브랜치 접두어',
    '/loop': '로컬 반복 실행 모드',
    '/schedule': 'CLI 예약 명령',
}
FACT_REVIEW_SOURCE_LIMIT = 2
FACT_REVIEW_SNIPPET_LIMIT = 1800
SECTION_WRITE_RETRIES = 6
FEW_SHOT_LIMIT = 3
FAILED_SOURCE_CACHE: dict[str, str] = {}
KNOWN_ACRONYM_EXPLANATIONS = {
    'LLM': '거대 언어 모델',
    'GPT': '생성형 언어 모델 계열',
    'EPUB': '전자책 파일 형식',
    'PDF': '문서 파일 형식',
    'IPO': '기업공개',
    'ETF': '상장지수펀드',
    'HEV': '하이브리드 차량',
    'EV': '전기차',
    'EPS': '주당순이익',
    'FX': '외환',
    'WGBI': '세계국채지수',
    'OTP': '일회용 인증 비밀번호',
    'API': '애플리케이션 프로그래밍 인터페이스',
    'UI': '사용자 화면',
    'UX': '사용 경험',
}


class WriteBlockedError(RuntimeError):
    """현재 글감이 장시간 정체되거나 반복 실패해 다음 글감으로 넘어가야 할 때 사용."""


def _feedback_bucket(feedback: str) -> str:
    if not feedback:
        return ''
    lines = [line.strip() for line in feedback.splitlines() if line.strip()]
    if not lines:
        return ''
    if len(lines) >= 2 and lines[1].startswith('-'):
        return f'{lines[0]} | {lines[1]}'
    return lines[0]


def _save_failed_write(
    topic_data: dict,
    output_path: Path,
    reason: str,
    article: dict | None = None,
    feedback: str = '',
) -> Path:
    FAILED_WRITES_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(article or {})
    payload.setdefault('title', topic_data.get('topic', topic_data.get('title', '')))
    payload['topic'] = topic_data.get('topic', '')
    payload['corner'] = payload.get('corner') or topic_data.get('corner', '쉬운세상')
    payload['description'] = topic_data.get('description', '')
    payload['quality_score'] = topic_data.get('quality_score', 0)
    payload['source'] = topic_data.get('source', '')
    payload['source_url'] = topic_data.get('source_url') or topic_data.get('source') or ''
    payload['published_at'] = topic_data.get('published_at', '')
    payload['failed_reason'] = reason
    payload['last_feedback'] = feedback
    payload['failed_at'] = datetime.now().isoformat()
    payload['status'] = 'failed_write'
    failed_path = FAILED_WRITES_DIR / output_path.name
    failed_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.warning(f"미완성 원고 저장 완료: {failed_path.name}")
    return failed_path


# ─── 유틸 ────────────────────────────────────────────

def _safe_slug(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return slug or datetime.now().strftime('article-%Y%m%d-%H%M%S')


def _replace_raw_terms(text: str) -> str:
    normalized = text
    for raw, replacement in RAW_TERM_REPLACEMENTS.items():
        normalized = normalized.replace(raw, replacement)
    return normalized


def _normalize_h2_text(text: str) -> str:
    cleaned = re.sub(r'<[^>]+>', '', _replace_raw_terms(text)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    if len(cleaned) <= 26:
        return cleaned
    parts = re.split(r'[:|,]| - | — | – |\?', cleaned)
    for part in parts:
        candidate = part.strip()
        if 8 <= len(candidate) <= 26:
            return candidate
    return cleaned[:26].rstrip()


def _normalize_title_text(text: str) -> str:
    cleaned = re.sub(r'<[^>]+>', '', _replace_raw_terms(text)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r',\s*.+$', '', cleaned)
    cleaned = re.sub(r'\s*(그리고|인데|인데도|왜|무엇이냐|무슨 뜻|다음 선택지).+$', '', cleaned)
    if len(cleaned) <= 38:
        return cleaned
    parts = re.split(r'[:|]| - | — | – ', cleaned)
    for part in parts:
        candidate = part.strip()
        if 14 <= len(candidate) <= 38:
            return candidate
    return cleaned[:38].rstrip()


def _extract_marked_block(text: str, label: str) -> str:
    match = re.search(
        rf'---{re.escape(label)}---\s*(.*?)(?=\n---[A-Z_]+---|\Z)',
        text,
        flags=re.DOTALL,
    )
    return match.group(1).strip() if match else ''


def _replace_first_acronym(text: str, acronym: str, explanation: str) -> tuple[str, bool]:
    pattern = rf'(?<![A-Za-z]){re.escape(acronym)}(?![A-Za-z])'
    for match in re.finditer(pattern, text):
        after = text[match.end():match.end() + 4]
        if after.lstrip().startswith(('(', '（')):
            continue
        replaced = f'{acronym}({explanation})'
        return text[:match.start()] + replaced + text[match.end():], True
    return text, False


def _apply_acronym_repairs(article: dict, feedback: str) -> dict:
    repaired = dict(article)
    matches = re.findall(r'다음 약어/고유명사가 첫 등장 시 설명 없이 사용됨: ([^\.]+)\.', feedback)
    acronyms = []
    for chunk in matches:
        acronyms.extend([item.strip() for item in chunk.split(',') if item.strip()])

    for acronym in acronyms:
        explanation = KNOWN_ACRONYM_EXPLANATIONS.get(acronym)
        if not explanation:
            continue
        for field in ('title', 'meta', 'body'):
            updated, changed = _replace_first_acronym(str(repaired.get(field, '')), acronym, explanation)
            repaired[field] = updated
            if changed:
                break
    return repaired


def _repair_acronym_explanations(writer, article: dict, feedback: str) -> dict | None:
    prompt = f"""아래 블로그 글에서 약어/고유명사 첫 등장 설명 누락만 고쳐줘.

검수 피드백:
{feedback}

현재 제목:
{article.get('title', '')}

현재 META:
{article.get('meta', '')}

현재 BODY:
{article.get('body', '')}

출력 형식:
---TITLE---
수정된 제목

---META---
수정된 META

---BODY---
수정된 BODY 전체

규칙:
- 첫 등장 약어에만 괄호 설명을 붙여.
- 이미 설명된 약어는 다시 풀지 마.
- 제목, META, BODY의 의미와 구조는 유지하고 약어 설명만 보강해.
- 다른 검수 항목은 건드리지 마.
"""
    raw = writer.write(prompt)
    if not raw:
        return None
    new_title = _extract_marked_block(raw, 'TITLE')
    new_meta = _extract_marked_block(raw, 'META')
    new_body = _extract_marked_block(raw, 'BODY')
    if not (new_title and new_meta and new_body):
        return None
    repaired = dict(article)
    repaired['title'] = new_title.strip()
    repaired['meta'] = new_meta.strip()
    repaired['body'] = new_body.strip()
    return repaired


def _repair_actionability(writer, topic_data: dict, article: dict, feedback: str) -> dict | None:
    title = re.sub(r'<[^>]+>', '', article.get('title', '')).strip()
    meta = re.sub(r'<[^>]+>', '', article.get('meta', '')).strip()
    paragraphs = re.findall(r'<p>.*?</p>', article.get('body', ''), flags=re.IGNORECASE | re.DOTALL)
    first_paragraph = paragraphs[0].strip() if paragraphs else '<p></p>'
    prompt = f"""아래 블로그 글의 제목, META, 첫 문단만 고쳐줘.

주제: {topic_data.get('topic', '')}
코너: {topic_data.get('corner', '쉬운세상')}
현재 제목: {title}
현재 META: {meta}
현재 첫 문단:
{first_paragraph}

검수 피드백:
{feedback}

출력 형식:
---TITLE---
행동과 결과가 함께 보이는 38자 이하 제목

---META---
무엇을 보면/하면 무엇이 달라지는지 바로 드러나는 1문장

---FIRST_PARAGRAPH---
<p>첫 문단</p>

규칙:
- 제목은 반드시 "[무엇을 보면/하면] [무엇이 쉬워지거나 달라진다]" 구조로 써.
- 제목 첫머리에 독자가 할 행동을 넣어.
- 결과는 추상어 말고 "오해를 줄인다", "판단이 쉬워진다", "뜻이 바로 잡힌다"처럼 바로 이해되는 말로 써.
- META도 같은 구조로 한 문장만 써.
- 첫 문단 첫 문장도 독자가 취할 행동과 얻는 결과를 같이 말해.
- BODY의 나머지 구조는 건드리지 마.
"""
    raw = writer.write(prompt)
    if not raw:
        return None
    new_title = _extract_marked_block(raw, 'TITLE')
    new_meta = _extract_marked_block(raw, 'META')
    new_first = _extract_marked_block(raw, 'FIRST_PARAGRAPH')
    if not (new_title and new_meta and new_first):
        return None

    repaired = dict(article)
    repaired['title'] = _normalize_title_text(new_title)
    repaired['meta'] = re.sub(r'\s+', ' ', new_meta).strip()
    body = str(article.get('body', ''))
    if paragraphs:
        repaired['body'] = body.replace(paragraphs[0], new_first, 1)
    else:
        repaired['body'] = new_first + '\n' + body
    return repaired


def _has_action_result_shape(text: str) -> tuple[bool, bool]:
    normalized = re.sub(r'<[^>]+>', '', text).strip()
    if not normalized:
        return False, False

    has_action = bool(
        re.search(
            r'(해보면|하면|보면|읽으면|읽어두면|걸면|걸어두면|고르면|바꾸면|정하면|넣으면|묶으면|돌리면|확인하면|확인해보면|체크해보면)',
            normalized,
        )
    )
    has_result = bool(
        re.search(
            r'(된다|안 된다|안읽힌다|안 읽힌다|보인다|줄어든다|덜하다|쉬워진다|정리된다|잡힌다|바로 잡힌다|뜻이 잡힌다|뜻이 달라진다|오해가 줄어든다|오해하지 않게 된다|헷갈림이 줄어든다|덜 보게 된다|잘못 읽지 않게 된다|읽히지 않는다|안 보게 된다)',
            normalized,
        )
    )
    return has_action, has_result


def _normalize_meta_text(meta: str, title: str = '', description: str = '') -> str:
    cleaned = re.sub(r'<[^>]+>', '', _replace_raw_terms(meta)).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    has_action, has_result = _has_action_result_shape(cleaned)
    if has_action and has_result and len(cleaned) <= 150:
        return cleaned

    normalized_title = _normalize_title_text(title) if title else ''
    title_action, title_result = _has_action_result_shape(normalized_title)
    if title_action and title_result:
        cleaned = f'{normalized_title}. 헷갈리는 포인트만 바로 정리했다.'
    else:
        desc = re.sub(r'<[^>]+>', '', description).strip()
        desc = re.sub(r'\s+', ' ', desc)
        if len(desc) > 80:
            desc = desc[:80].rstrip()
        cleaned = f'{desc}를 읽으면 무엇이 달라지는지 바로 정리했다.' if desc else '핵심 문구부터 보면 뜻이 바로 잡힌다.'

    if len(cleaned) <= 150:
        return cleaned
    return cleaned[:150].rstrip()


def _sanitize_body_html(body: str) -> str:
    if not body.strip():
        return body

    normalized = _replace_raw_terms(body)

    def _normalize_h2(match: re.Match) -> str:
        inner = match.group(1)
        return f"<h2>{_normalize_h2_text(inner)}</h2>"

    normalized = re.sub(r'<h2>(.*?)</h2>', _normalize_h2, normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r'<h2>\s*</h2>', '', normalized, flags=re.IGNORECASE)
    normalized = re.sub(
        r'주\s*\d+일(?:이면|에)?\s*\d+\s*(분|시간)(?:이|을)?\s*(다시\s*생긴다|돌아온다|아낀다|절약한다)',
        '업무 부담이 눈에 띄게 덜할 수 있다',
        normalized,
    )
    normalized = re.sub(
        r'\d+\s*(분|시간)(?:이|을)?\s*\d+\s*(분|시간)(?:으로)?\s*(바뀐다|되돌아온다)',
        '읽고 판단하는 흐름이 더 단순해질 수 있다',
        normalized,
    )
    normalized = re.sub(
        r'(매일|한 달이면|4주면)\s*\d+\s*(분|시간)(?:씩)?\s*(통째로\s*비게\s*된다|절약된다|돌아온다)',
        '반복하던 손일이 줄어들 수 있다',
        normalized,
    )
    normalized = re.sub(
        r'아침\s*\d+\s*분(?:이|을)?\s*(자료 수집이 아니라 판단 시간으로 바뀐다|다시 손에 돌아온다)',
        '아침 흐름이 덜 끊길 수 있다',
        normalized,
    )
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)
    return normalized.strip()


def _sanitize_article(article: dict) -> dict:
    sanitized = dict(article)
    if not sanitized.get('meta') and sanitized.get('meta_description'):
        sanitized['meta'] = sanitized.get('meta_description', '')
    if not sanitized.get('meta_description') and sanitized.get('meta'):
        sanitized['meta_description'] = sanitized.get('meta', '')
    for key in ('title', 'meta', 'disclaimer'):
        if isinstance(sanitized.get(key), str):
            sanitized[key] = _replace_raw_terms(sanitized[key]).strip()

    if isinstance(sanitized.get('title'), str):
        sanitized['title'] = _normalize_title_text(sanitized['title'])

    if isinstance(sanitized.get('meta'), str):
        sanitized['meta'] = _normalize_meta_text(
            sanitized['meta'],
            sanitized.get('title', ''),
            sanitized.get('description', ''),
        )
        sanitized['meta_description'] = sanitized['meta']

    if isinstance(sanitized.get('body'), str):
        sanitized['body'] = _sanitize_body_html(sanitized['body'])

    if isinstance(sanitized.get('key_points'), list):
        sanitized['key_points'] = [
            _replace_raw_terms(str(point)).strip()
            for point in sanitized['key_points']
            if str(point).strip()
        ]

    if isinstance(sanitized.get('tags'), list):
        sanitized['tags'] = [_replace_raw_terms(str(tag)).strip() for tag in sanitized['tags'] if str(tag).strip()]

    return sanitized


def _fetch_source_snippet(url: str) -> str:
    _load_failed_sources_cache()
    if url in FAILED_SOURCE_CACHE:
        return ''
    try:
        resp = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
    except Exception as e:
        FAILED_SOURCE_CACHE[url] = str(e)
        _save_failed_sources_cache()
        logger.warning(f"출처 본문 수집 실패: {url} ({e})")
        return ''

    soup = BeautifulSoup(resp.text, 'html.parser')
    for tag in soup(['script', 'style', 'noscript']):
        tag.decompose()

    text = ' '.join(soup.get_text(' ', strip=True).split())
    if len(text) > FACT_REVIEW_SNIPPET_LIMIT:
        text = text[:FACT_REVIEW_SNIPPET_LIMIT].rstrip() + '...'
    return text


def _empty_writer_memory() -> dict:
    return {}


def _load_failed_sources_cache() -> None:
    global FAILED_SOURCE_CACHE
    if FAILED_SOURCE_CACHE:
        return
    if not FAILED_SOURCES_PATH.exists():
        return
    try:
        data = json.loads(FAILED_SOURCES_PATH.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            FAILED_SOURCE_CACHE.update({str(k): str(v) for k, v in data.items()})
    except Exception:
        return


def _save_failed_sources_cache() -> None:
    FAILED_SOURCES_PATH.write_text(
        json.dumps(FAILED_SOURCE_CACHE, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _ensure_memory_shape(data: dict) -> dict:
    return data


def _load_writer_memory() -> dict:
    from prompt_layer.writer_memory import load_writer_memory
    return load_writer_memory(WRITER_MEMORY_PATH)


def _save_writer_memory(memory: dict) -> None:
    from prompt_layer.writer_memory import save_writer_memory
    save_writer_memory(WRITER_MEMORY_PATH, memory)


def _classify_memory_point(text: str) -> tuple[str, str]:
    return 'body', text


def _append_writer_memory(kind: str, items: list[str], corner: str = '전체') -> None:
    append_writer_memory(WRITER_MEMORY_PATH, kind, items, corner=corner)


def _extract_memory_points(feedback: str) -> list[str]:
    return extract_memory_points(feedback)


def _top_memory_items(counts: dict, limit: int = 5) -> list[str]:
    return []


def _build_memory_guidance(corner: str = '전체') -> str:
    return build_memory_guidance(WRITER_MEMORY_PATH, corner)


def register_pipeline_feedback(corner: str, feedback: str, success: bool = False) -> None:
    points = _extract_memory_points(feedback)
    if not points:
        normalized = re.sub(r'\s+', ' ', str(feedback)).strip()
        if normalized:
            points = [normalized]
    if not points:
        return
    _append_writer_memory('success' if success else 'failure', points, corner=corner or '전체')


def _build_source_context(article: dict, topic_data: dict) -> str:
    sources = article.get('sources') or []
    fallback_url = topic_data.get('source_url') or topic_data.get('source') or ''
    if not sources and fallback_url:
        sources = [{'url': fallback_url, 'title': '참고 출처', 'date': topic_data.get('published_at', '')}]

    blocks = []
    for source in sources[:FACT_REVIEW_SOURCE_LIMIT]:
        url = str(source.get('url', '')).strip()
        # 섹션 구분자나 비URL 문자열 방어 (파서가 흘려보낸 경우 2차 차단)
        if not url or not url.startswith(('http://', 'https://')):
            if url:
                logger.warning(f"유효하지 않은 출처 URL 건너뜀: {url!r}")
            continue
        snippet = _fetch_source_snippet(url)
        if not snippet:
            continue
        title = str(source.get('title', '참고 출처')).strip() or '참고 출처'
        blocks.append(f"[출처] {title}\nURL: {url}\n본문 발췌: {snippet}")

    return '\n\n'.join(blocks)


def _extract_first_paragraph(body_html: str) -> str:
    paragraphs = re.findall(r'<p>(.*?)</p>', body_html or '', flags=re.IGNORECASE | re.DOTALL)
    if paragraphs:
        return re.sub(r'<[^>]+>', '', paragraphs[0]).strip()
    plain = re.sub(r'<[^>]+>', ' ', body_html or '')
    plain = re.sub(r'\s+', ' ', plain).strip()
    return plain[:140].rstrip()


def _load_few_shot_examples(corner: str, topic_data: dict) -> str:
    originals_dir = DATA_DIR / 'originals'
    if not originals_dir.exists():
        return ''

    current_topic = str(topic_data.get('topic', '')).strip()
    examples = []
    for path in sorted(originals_dir.glob('*.json'), reverse=True):
        try:
            article = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue

        if article.get('corner') != corner:
            continue
        if str(article.get('topic', '')).strip() == current_topic:
            continue

        score = int(article.get('quality_score', 0) or 0)
        if score < 75:
            continue

        title = re.sub(r'\s+', ' ', str(article.get('title', '')).strip())
        meta = re.sub(r'\s+', ' ', str(article.get('meta', '')).strip())
        intro = re.sub(r'\s+', ' ', _extract_first_paragraph(str(article.get('body', ''))))
        if not title or not meta or not intro:
            continue

        examples.append(
            {
                'title': title[:60].rstrip(),
                'meta': meta[:120].rstrip(),
                'intro': intro[:140].rstrip(),
            }
        )
        if len(examples) >= FEW_SHOT_LIMIT:
            break

    if not examples:
        return ''

    lines = ['[최근 잘 통과한 글 예시]']
    for idx, item in enumerate(examples, start=1):
        lines.extend(
            [
                f'예시 {idx}',
                f'- 제목: {item["title"]}',
                f'- META: {item["meta"]}',
                f'- 도입 첫 문단: {item["intro"]}',
            ]
        )
    return '\n'.join(lines).strip()


def _build_prompt(topic_data: dict, style_prefix: str = "") -> tuple[str, str]:
    topic = topic_data.get('topic', '').strip()
    corner = topic_data.get('corner', '쉬운세상').strip() or '쉬운세상'
    description = topic_data.get('description', '').strip()
    source = topic_data.get('source_url') or topic_data.get('source') or ''
    published_at = topic_data.get('published_at', '')
    ref_parts = []
    if topic_data.get('reference_views'):
        ref_parts.append(f"YouTube 조회수 {topic_data['reference_views']:,}회 영상")
    if topic_data.get('reference_score'):
        ref_parts.append(f"Reddit score {topic_data['reference_score']:,} 인기글 (댓글 {topic_data.get('reference_comments', 0):,}개)")
    if topic_data.get('reference_title'):
        ref_parts.append(f"원본 제목: \"{topic_data['reference_title']}\"")

    ref_section = ''
    if ref_parts:
        ref_section = (
            '\n\n[참고 콘텐츠 — 이미 검증된 인기 콘텐츠]\n'
            + '\n'.join(f'- {p}' for p in ref_parts)
            + '\n위 콘텐츠가 왜 인기를 끌었는지 패턴을 파악하고, 같은 방향성으로 작성해줘.'
        )

    memory_guidance = _build_memory_guidance(corner)
    memory_section = f"\n\n{memory_guidance}" if memory_guidance else ''
    few_shot_guidance = _load_few_shot_examples(corner, topic_data)
    few_shot_section = f"\n\n{few_shot_guidance}" if few_shot_guidance else ''

    # 누적 학습 규칙 (임계값 이상 반복된 피드백이 자동 승격된 영구 규칙)
    learned_rules = build_learned_rules_section(WRITER_MEMORY_PATH, corner)
    learned_section = f"\n\n{learned_rules}" if learned_rules else ''

    system, prompt = compose_writer_prompt(
        topic=topic,
        corner=corner,
        description=description,
        source=source,
        published_at=published_at,
        ref_section=ref_section,
        memory_section=memory_section,
        few_shot_section=few_shot_section,
        learned_section=learned_section,
    )
    if style_prefix:
        system = style_prefix + system
    return system, prompt


# ─── 품질 검사 ───────────────────────────────────────

def _check_article_quality(article: dict) -> tuple[bool, str]:
    """
    룰 기반 품질 검사. AI 호출 없음.
    Returns: (passed: bool, feedback: str)
    """
    issues = []

    if not article.get('title', '').strip():
        issues.append('제목(TITLE)이 비어 있습니다. 반드시 제목을 작성해줘.')
    else:
        title = article.get('title', '').strip()
        if len(title) < 10:
            issues.append('제목이 너무 짧습니다. 행동과 결과가 함께 보여야 합니다.')

    body_text = re.sub(r'<[^>]+>', '', article.get('body', ''))
    word_count = len(body_text.split())
    if word_count < 300:
        issues.append(
            f'본문이 너무 짧습니다 (현재 약 {word_count}단어). '
            f'최소 300단어 이상의 충실한 본문을 작성해줘.'
        )

    if len(article.get('key_points', [])) < 2:
        issues.append(
            f'KEY_POINTS가 {len(article.get("key_points", []))}개입니다. '
            f'독자에게 유용한 핵심 포인트를 최소 2개 이상 작성해줘.'
        )

    valid_sources = [s for s in article.get('sources', []) if s.get('url', '').strip()]
    if not valid_sources:
        issues.append('SOURCES가 비어 있습니다. 출처 URL을 최소 1개 이상 포함해줘.')

    if issues:
        return False, '\n'.join(f'- {i}' for i in issues)
    return True, ''


# ─── 검수 로직 ───────────────────────────────────────

def _build_review_prompt(body: str) -> str:
    plain = re.sub(r'<[^>]+>', '', body)
    return f"""아래 블로그 본문의 각 문장을 검토해줘.

검토 기준:
1. 이 문장이 독자에게 새로운 정보나 관점을 주는가?
2. 이 문장을 읽으면 감각적 임팩트나 느낌이 오는가?
3. 이 문장이 너무 딱딱한 제품 브리핑체나 보도체가 아니라, 실제 사람이 쉽게 풀어쓴 설명처럼 읽히는가?
4. 적어도 몇 문장은 독자가 자기 경험을 떠올릴 수 있는 생활 장면이나 업무 순간을 포함하는가?

두 기준 중 하나도 해당하지 않는 문장은 FAIL이다.
중요:
- 1번과 2번은 동등하다.
- 2번만 강하게 만족해도 PASS 가능하다.
- 장면이 떠오르거나, 리듬이 살아 있거나, 독자의 인식을 번쩍 바꾸는 문장은 정보량이 다소 적어도 PASS로 본다.
- 다만 말투가 지나치게 딱딱하거나, 출처에 없는 보도체 표현이면 PASS로 보지 마라.
특히 아래 문장은 엄격하게 FAIL 처리해:
- 전환만 하는 문장
- 질문만 던지고 정보가 없는 문장
- 추상적 감상만 있는 문장
- 이전 문맥이 없으면 힘이 사라지는 문장
- 누구나 예상할 수 있는 뻔한 정리 문장
- 숫자, 사례, 고유명사, 구체 장면 없이 두루뭉술하게 끝나는 문장
- 비슷한 리듬이나 시작어를 반복해 쓴 문장
- "보도된", "알려졌다", "업계에서는", "관계자는"처럼 출처에 없는 보도체 문장
- 뜻은 맞더라도 너무 딱딱해서 일반 독자 입장에서 한 번에 안 읽히는 문장
- 끝까지 설명만 있고 독자가 자기 상황을 떠올릴 장면이 전혀 없는 문장 묶음
- "쉽게 말하면", "첫 구분은", "마지막 기준은", "즉 이제" 뒤에 숫자·고유명사·이분 선택 없이 추상어만 오는 문장

[본문]
{plain}

출력 형식 (반드시 아래 형식만 사용):
REVIEW_RESULT: PASS 또는 FAIL
FAILED_SENTENCES:
- "실패한 문장" → 이유
"""


def _title_actionability_review(article: dict) -> tuple[bool, str]:
    issues = []
    title = re.sub(r'<[^>]+>', '', article.get('title', '')).strip()
    meta = re.sub(r'<[^>]+>', '', article.get('meta', '')).strip()
    body = re.sub(r'<[^>]+>', ' ', article.get('body', ''))

    if title:
        has_action, has_result = _has_action_result_shape(title)
        if not (has_action and has_result):
            issues.append(f'- "{title}" → 제목에서 행동과 결과가 함께 바로 보이지 않는다.')
        if has_result and not has_action:
            issues.append(f'- "{title}" → 결과만 있고, 독자가 뭘 해야 하는지가 제목에 없다.')
        if has_action and not has_result:
            issues.append(f'- "{title}" → 행동은 보이지만, 그 결과가 제목에서 바로 안 보인다.')
        if len(title) > 38:
            issues.append(f'- "{title}" → 제목이 길다. 행동+결과는 유지하되 38자 안쪽으로 줄여야 한다.')

    first_paragraphs = re.findall(r'<p>(.*?)</p>', article.get('body', ''), flags=re.IGNORECASE | re.DOTALL)
    first_paragraph = re.sub(r'<[^>]+>', '', first_paragraphs[0]).strip() if first_paragraphs else body[:180]
    if first_paragraph and not any(token in first_paragraph for token in ('하면', '고르면', '쓰면', '예약', '자동화', '줄어', '쉬워', '바로')):
        issues.append('- 첫 문단에서 독자가 바로 취할 행동이나 얻는 결과가 선명하지 않다.')

    meta_action, meta_result = _has_action_result_shape(meta)
    if not meta:
        issues.append('- META 설명이 비어 있다. 무엇을 보면/하면 무엇이 달라지는지 한 문장으로 반드시 채워야 한다.')
    elif not (meta_action and meta_result):
        issues.append('- META 설명이 추상적이다. 무엇을 하면 무엇이 달라지는지 더 분명해야 한다.')

    if issues:
        return False, '\n'.join(issues)
    return True, ''


def _extract_h2_titles(body: str) -> list[str]:
    return [
        _normalize_h2_text(re.sub(r'<[^>]+>', '', h2).strip())
        for h2 in re.findall(r'<h2>(.*?)</h2>', body, flags=re.IGNORECASE | re.DOTALL)
        if re.sub(r'<[^>]+>', '', h2).strip()
    ]


def _parse_section_output(raw_output: str) -> str:
    normalized = raw_output.replace('\r\n', '\n').replace('\r', '\n').strip()
    if normalized.startswith('```'):
        normalized = re.sub(r'^```[a-zA-Z0-9_-]*\n', '', normalized)
        normalized = re.sub(r'\n```$', '', normalized).strip()

    match = re.search(
        r'^\s*---\s*SECTION_BODY\s*---\s*\n(.*)$',
        normalized,
        flags=re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )
    if match:
        normalized = match.group(1).strip()

    paragraphs = re.findall(r'<p>.*?</p>', normalized, flags=re.IGNORECASE | re.DOTALL)
    return '\n'.join(p.strip() for p in paragraphs)


def _build_section_prompt(
    topic_data: dict,
    article: dict,
    h2_titles: list[str],
    section_index: int,
    feedback: str = '',
) -> str:
    current_h2 = h2_titles[section_index]
    prev_h2 = h2_titles[section_index - 1] if section_index > 0 else '없음'
    next_h2 = h2_titles[section_index + 1] if section_index + 1 < len(h2_titles) else '없음'
    corner = article.get('corner') or topic_data.get('corner', '쉬운세상')
    description = topic_data.get('description', '')
    source = topic_data.get('source_url') or topic_data.get('source') or ''
    return compose_section_prompt(
        topic=topic_data.get('topic', ''),
        corner=corner,
        article_title=article.get('title', ''),
        description=description,
        source=source,
        prev_h2=prev_h2,
        current_h2=current_h2,
        next_h2=next_h2,
        h2_titles=h2_titles,
        feedback=feedback,
    )


def _build_fact_review_prompt(body: str, source_context: str) -> str:
    plain = re.sub(r'<[^>]+>', '', body)
    return FACT_REVIEW_TEMPLATE.format(source_context=source_context, plain=plain)


def _parse_review(result: str) -> tuple[bool, str]:
    """검수 결과 파싱. Returns: (passed, feedback)"""
    if not result.strip():
        logger.warning("검수 엔진 응답 없음")
        return False, '검수 엔진 응답이 비어 있습니다. 반드시 REVIEW_RESULT 형식으로 검수 결과를 반환해줘.'

    if 'REVIEW_RESULT: PASS' in result:
        return True, ''

    lines = result.split('\n')
    failed_lines = []
    capture = False
    for line in lines:
        if 'FAILED_SENTENCES:' in line:
            capture = True
            continue
        if capture and line.strip().startswith('-'):
            failed_lines.append(line.strip())

    feedback = '\n'.join(failed_lines) if failed_lines else '기준 미달 문장 있음 (상세 없음)'
    return False, feedback


def _build_revision_feedback(feedback: str, attempt: int) -> str:
    return compose_revision_feedback(feedback, attempt, MIN_REVISION_ROUNDS)


def _build_min_revision_feedback(attempt: int) -> str:
    return compose_min_revision_feedback(attempt, MIN_REVISION_ROUNDS)


def _split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r'\s+', ' ', text).strip()
    if not cleaned:
        return []
    parts = re.split(r'(?<=[.!?])\s+', cleaned)
    return [p.strip() for p in parts if p.strip()]


def _heuristic_review(body: str, require_relatable: bool = True) -> tuple[bool, str]:
    plain = re.sub(r'<[^>]+>', ' ', body)
    sentences = _split_sentences(plain)
    if not sentences:
        return False, '본문 문장 분리가 되지 않았습니다. 문장을 더 명확하게 작성해줘.'

    issues = []

    seen_normalized = {}
    starter_counts = {}

    for i, sentence in enumerate(sentences):
        next_sentence = sentences[i + 1] if i + 1 < len(sentences) else ''
        normalized = re.sub(r'[^0-9a-zA-Z가-힣]+', ' ', sentence).strip().lower()
        if not normalized:
            continue

        seen_normalized[normalized] = seen_normalized.get(normalized, 0) + 1

        first_word = normalized.split()[0]
        starter_counts[first_word] = starter_counts.get(first_word, 0) + 1

        if len(sentence) < 18:
            issues.append(f'- "{sentence}" → 너무 짧아 정보나 감각의 밀도가 부족하다.')
            continue

        if sentence.endswith(('는', '은', '가', '을', '를', '와', '과', '및', '처럼', '보다')):
            issues.append(f'- "{sentence}" → 문장이 끝맺히지 않고 끊겼다.')
            continue

        if any(sentence.startswith(pattern) for pattern in DANGLING_PATTERNS) and not re.search(r'(이다|다\.|다$|된다|했다|있다|없다|좋다|맞다|낫다|편하다)', sentence):
            issues.append(f'- "{sentence}" → 비교나 나열을 시작만 하고 끝맺지 않았다.')
            continue

        if (
            sentence.startswith(WEAK_START_PATTERNS)
            and len(sentence) < 28  # 34 → 28: 짧은 도입문이 다음 문장 내용을 예고하는 경우 false positive 방지
            and not re.search(r'\d|%|원|달러|명|개|건|배|위|개월|년|월|일|[A-Z]{2,}|[가-힣A-Za-z]+[0-9]', sentence)
        ):
            issues.append(f'- "{sentence}" → 전환 문장에 가깝고 구체 정보가 약하다.')
            continue

        if any(marker in sentence for marker in ABSTRACT_MARKERS) and not re.search(r'\d|%|원|달러|명|개|건|배|위|개월|년|월|일', sentence):
            if len(sentence) < 38:
                issues.append(f'- "{sentence}" → 추상어 비중이 높고 구체 근거가 부족하다.')

        if any(marker in sentence for marker in REPORT_MARKERS):
            issues.append(f'- "{sentence}" → 출처 확인 없이 보도체 표현을 쓰고 있어 내 글처럼 읽히지 않는다.')

        if any(marker in sentence for marker in RECAP_MARKERS) and not re.search(r'\d|%|원|달러|명|개|건|배|위|개월|년|월|일|아침|회의|출근|로그|브라우저', sentence):
            issues.append(f'- "{sentence}" → 앞 문장을 다시 요약하거나 다음 문장을 예고하는 정리 문장에 가깝다.')

        if sentence.startswith(META_OPENERS):
            issues.append(f'- "{sentence}" → 글의 역할이나 읽는 순서를 설명하는 메타 문장이다. 바로 사실이나 장면으로 들어가야 한다.')

        if any(marker in sentence for marker in ABSTRACT_INTRO_MARKERS):
            if not re.search(
                r'\d|%|원|달러|명|개|건|배|위|개월|년|월|일'
                r'|[A-Z]{2,}|[가-힣]{2,}[0-9]'
                r'|삼성|애플|구글|테슬라|엔비디아|깃허브|슬랙|노션|ChatGPT|Claude|Gemini|GPT'
                r'|이냐.{1,20}이냐|인지.{1,20}인지|냐.{1,10}냐',  # 이분 선택 패턴
                sentence,
            ):
                issues.append(f'- "{sentence}" → 정리 도입구("{sentence[:10]}...") 뒤에 숫자·고유명사·구체 장면이 없다. 추상어만으로 끝내지 마.')

        if sentence.endswith(GENERIC_ENDINGS) and not re.search(r'\d|%|원|달러|명|개|건|배|위|개월|년|월|일|삼성|애플|구글|테슬라|엔비디아|코스피|코스닥|미국|한국|이란|CEO|AI|LLM', sentence):
            issues.append(f'- "{sentence}" → 결론은 세지만 구체 근거가 부족한 상투 문장이다.')

        if len(sentence) > 80 and not any(token in sentence for token in ('쉽게 말하면', '즉', '예를 들면', '이를테면')):
            issues.append(f'- "{sentence}" → 문장이 너무 길고 딱딱하다. 일반 독자 눈높이에서 한 번 더 풀어줘야 한다.')

        capitalized_terms = re.findall(r'[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?', sentence)
        unique_caps = {term.strip() for term in capitalized_terms}
        if len(unique_caps) >= 3:
            issues.append(f'- "{sentence}" → 고유명사나 서비스 이름을 한 문장에 너무 많이 몰아 넣었다.')

        if '예를 들어' in sentence:
            # 같은 문장 + 바로 다음 문장 합쳐서 이유 확인 (다음 문장에서 닫아도 OK)
            combined = sentence + ' ' + next_sentence
            if not any(token in combined for token in ('그래서', '즉', '결국', '때문에', '이라서', '차이', '덕분', '때문')):
                issues.append(f'- "{sentence}" → 예시를 들었지만 왜 중요한지 이어지는 문장에서도 닫지 않았다.')

        if (
            re.search(r'\d+\s*(분|시간|일|주|개월|달|주일|%)', sentence)
            and any(marker in sentence for marker in UNSUPPORTED_EFFECT_MARKERS)
            and not any(token in sentence for token in ('문서를 보면', '출처 기준', '공식 설명', '자료에 따르면'))
        ):
            issues.append(f'- "{sentence}" → 출처 확인 없는 시간 절감이나 효과 수치를 단정하고 있다.')

        if (
            any(token in sentence for token in ('주 5일', '4주면', '한 달이면', '매일'))
            and any(marker in sentence for marker in ('분이 다시 생긴다', '시간이 돌아온다', '통째로 비게 된다', '절약된다'))
        ):
            issues.append(f'- "{sentence}" → 주간/월간 합산 효과를 근거 없이 계산하고 있다.')

    repeated_sentences = [s for s, count in seen_normalized.items() if count > 1]
    for normalized in repeated_sentences:
        issues.append(f'- "{normalized}" → 같은 문장을 반복하고 있다.')

    repetitive_starters = [
        word
        for word, count in starter_counts.items()
        if count >= 4
        and len(word) >= 2
        and word not in {'이번', '그때', '다음에', '그래서', '반대로'}
        and count / max(len(sentences), 1) >= 0.22
    ]
    for word in repetitive_starters:
        issues.append(f'- "{word}"로 시작하는 문장이 여러 번 반복돼 리듬이 단조롭다.')

    relatable_hint_pattern = re.compile(
        r'(출근|퇴근|회의|메신저|브라우저|탭|메일|문서|설정|업무|작업|회사|집|출근길|버튼|화면|노트북|휴대폰|이어폰|지하철|사무실)'
    )
    if require_relatable and not any(marker in plain for marker in RELATABLE_MARKERS) and not relatable_hint_pattern.search(plain):
        issues.append('- 글 전체에 독자가 자기 경험을 떠올릴 생활 장면이 부족하다.')

    if issues:
        return False, '\n'.join(dict.fromkeys(issues))
    return True, ''


def _presentation_review(article: dict) -> tuple[bool, str]:
    return layer_presentation_review(
        article,
        raw_term_replacements=RAW_TERM_REPLACEMENTS,
        split_sentences=_split_sentences,
    )


def _structure_review(article: dict) -> tuple[bool, str]:
    return layer_structure_review(
        article,
        has_action_result_shape=_has_action_result_shape,
    )


def _build_section_revision_feedback(feedback: str, attempt: int, current_h2: str) -> str:
    return compose_section_revision_feedback(feedback, attempt, current_h2)


def _generate_section_body(
    writer,
    reviewer,
    topic_data: dict,
    article: dict,
    h2_titles: list[str],
    section_index: int,
    source_context: str,
) -> tuple[bool, str]:
    current_h2 = h2_titles[section_index]
    section_feedback = ''
    last_section_html = ''

    for attempt in range(1, SECTION_WRITE_RETRIES + 1):
        from engine_loader import get_token_budget as _get_budget
        # 재시도 전 budget 초과면 마지막 생성 결과로 즉시 반환
        if attempt > 1 and _get_budget().is_exceeded():
            if last_section_html:
                logger.warning(
                    f"TokenBudget: 섹션 '{current_h2}' 재시도 건너뜀 — 예산 초과, 이전 결과 사용"
                )
                return True, last_section_html
            break

        prompt = _build_section_prompt(
            topic_data,
            article,
            h2_titles,
            section_index,
            section_feedback if attempt > 1 else '',
        )
        raw_section = writer.write(prompt).strip()
        if not raw_section:
            section_feedback = '- 섹션 출력이 비어 있다. 지정한 SECTION_BODY 형식으로 다시 써.'
            continue

        section_html = _parse_section_output(raw_section)
        last_section_html = section_html or raw_section[:300]
        paragraphs = re.findall(r'<p>.*?</p>', section_html, flags=re.IGNORECASE | re.DOTALL)

        if len(paragraphs) < 2:
            section_feedback = '- 섹션 문단이 부족하다. <p> 문단 2~3개로 다시 써.'
            continue

        section_review_target = f'<h2>{current_h2}</h2>\n{section_html}'

        if reviewer is not None:
            if _get_budget().is_exceeded():
                # 예산 초과 — 리뷰 건너뛰고 현재 섹션 내용 그대로 사용
                logger.warning(
                    f"TokenBudget: 섹션 '{current_h2}' 리뷰 건너뜀 — 예산 초과"
                )
            else:
                r2_passed, r2_feedback = _parse_review(reviewer.write(_build_review_prompt(section_review_target)))
                if not r2_passed:
                    section_feedback = _build_section_revision_feedback(r2_feedback, attempt, current_h2)
                    continue

        r3_passed, r3_feedback = _heuristic_review(section_review_target, require_relatable=False)
        if not r3_passed:
            if _get_budget().is_exceeded():
                logger.warning(
                    f"TokenBudget: 섹션 '{current_h2}' 룰 검수 실패지만 예산 초과 — 현재 결과 사용"
                )
            else:
                section_feedback = _build_section_revision_feedback(r3_feedback, attempt, current_h2)
                continue

        return True, section_html

    return False, last_section_html or f'<p>{current_h2} 섹션 생성 실패</p>'


def _compose_body_from_outline(
    writer,
    reviewer,
    topic_data: dict,
    article: dict,
    source_context: str,
    deadline: float = 0.0,
) -> tuple[bool, str]:
    h2_titles = _extract_h2_titles(article.get('body', ''))
    if len(h2_titles) < 3:
        return False, 'BODY 아웃라인의 H2가 3개 미만이다. 최소 3개 이상의 섹션 제목이 필요하다.'

    from engine_loader import get_token_budget as _get_budget
    section_blocks = []
    for index, h2_title in enumerate(h2_titles):
        # 타임아웃 초과 + 앞 섹션 있으면 partial body 발행
        if deadline and time.monotonic() >= deadline and section_blocks:
            logger.warning(
                f"섹션 루프 타임아웃: {len(section_blocks)}/{len(h2_titles)} 섹션 완성 — 여기까지 발행"
            )
            break
        # 이전 섹션까지 완성된 상태에서 budget 초과 → partial body로 즉시 반환
        if _get_budget().is_exceeded() and section_blocks:
            logger.warning(
                f"TokenBudget: {len(section_blocks)}/{len(h2_titles)} 섹션 완성 후 예산 초과 — partial body 발행"
            )
            break
        passed, section_html = _generate_section_body(
            writer,
            reviewer,
            topic_data,
            article,
            h2_titles,
            index,
            source_context,
        )
        if not passed:
            # budget 초과로 실패했고 앞 섹션이 있으면 partial로 발행
            if _get_budget().is_exceeded() and section_blocks:
                logger.warning(
                    f"TokenBudget: 섹션 '{h2_title}' 실패 + 예산 초과 — {len(section_blocks)}개 섹션으로 발행"
                )
                break
            return False, f'섹션 "{h2_title}" 생성 실패:\n{section_html}'
        section_blocks.append(f'<h2>{h2_title}</h2>\n{section_html}')

    if not section_blocks:
        return False, '섹션을 하나도 생성하지 못했습니다.'
    return True, '\n\n'.join(section_blocks)


# ─── 핵심 로직 ───────────────────────────────────────

def _build_publish_gate_feedback(feedback: str) -> str:
    return (
        "[발행 단계 피드백]\n"
        "- 이번 원고는 작성 검수는 통과했지만 발행 단계 자동 게이트에서 막혔다.\n"
        "- 아래 발행 피드백을 직접 반영해서 처음부터 다시 써.\n"
        "- 제목, META, 첫 문단, 마지막 문단에서 독자가 바로 얻는 기준과 결과를 더 선명하게 만들어.\n"
        "- 정보 밀도는 유지하되, 실제로 바로 써먹을 선택 기준이 남게 써.\n\n"
        f"{feedback}"
    )


def generate_article(topic_data: dict, writer=None, reviewer=None, style_prefix: str = "",
                     skip_review: bool = False, initial_feedback: str = "",
                     output_path: 'Path | None' = None) -> dict:
    """
    topic_data → EngineLoader 호출 → article dict 생성.
    Returns: article dict (저장 없음)
    Raises: RuntimeError — 글 작성 또는 파싱 실패 시
    """
    from engine_loader import EngineLoader, get_token_budget
    from article_parser import parse_output

    get_token_budget().reset()  # 글 단위로 예산 초기화 — 이전 글이 예산 소진해도 이 글은 독립 예산
    corner = topic_data.get('corner', '전체')
    system, prompt = _build_prompt(topic_data, style_prefix=style_prefix)
    base_prompt = prompt
    loader = EngineLoader()
    writer = writer or loader.get_writer()
    reviewer = reviewer or loader.get_reviewer()
    raw_output = writer.write(prompt, system=system).strip()

    article = None
    write_succeeded = False
    feedback = ''
    last_parse_error = ''
    started_at = time.monotonic()
    last_feedback_bucket = ''
    same_feedback_repeats = 0
    consecutive_empty = 0  # 연속 빈 응답 횟수 (엔진 장애 감지용)
    MAX_CONSECUTIVE_EMPTY = 3  # 이 횟수 연속으로 비면 엔진 장애로 판단하고 중단

    def _is_publishable(a: dict | None) -> bool:
        """최소 발행 조건: title과 body가 모두 있는지"""
        if not a:
            return False
        return bool(a.get('title', '').strip()) and bool(a.get('body', '').strip())

    try:
        for attempt in range(1, MAX_WRITE_RETRIES + 1):
            elapsed = time.monotonic() - started_at
            if elapsed >= MAX_WRITE_ELAPSED_SECONDS:
                if _is_publishable(article):
                    logger.warning(
                        f'작성 시간 초과 ({int(elapsed)}초) — 현재 원고 강제 발행'
                    )
                    write_succeeded = True
                    break
                raise WriteBlockedError(
                    f'작성 시간 초과 ({int(elapsed)}초) - 다음 글감으로 넘김'
                )

            # 토큰 예산 초과 처리
            if get_token_budget().is_exceeded():
                if _is_publishable(article):
                    # 룰 기반 제목 검사 (AI 호출 없이) — 예산 초과라도 제목 품질은 확인
                    _r4_ok, _r4_fb = _presentation_review(article)
                    _r4b_ok, _r4b_fb = _title_actionability_review(article)
                    _has_review_issues = not _r4_ok or not _r4b_ok
                    _title_issues = '\n'.join(filter(None, [_r4_fb, _r4b_fb]))
                    # ── Fix: 토큰 예산 초과 강제 발행 시 품질 점수 명시 ───────────
                    # quality_score가 없으면 topic_data에서 가져와 article에 기록
                    # publisher_bot quality_gate(75점)가 올바르게 차단할 수 있도록
                    if not article.get('quality_score'):
                        article['quality_score'] = topic_data.get('quality_score', 0)
                    if _has_review_issues:
                        logger.warning(
                            f"[시도 {attempt}] 토큰 예산 초과 + 제목/표현 검수 미달 "
                            f"— 강제 발행 (미해결):\n{_title_issues}"
                        )
                    else:
                        logger.warning(
                            f"[시도 {attempt}] 토큰 예산 초과 ({get_token_budget().usage_pct():.1f}%) "
                            f"— 현재 원고 강제 발행"
                        )
                    write_succeeded = True
                    break
                else:
                    raise WriteBlockedError(
                        f"토큰 예산 초과 ({get_token_budget().usage_pct():.1f}%) "
                        f"— 발행 가능한 원고 없음, 글 작성 중단"
                    )

            if attempt == 1 and initial_feedback:
                prompt = base_prompt + '\n\n' + _build_publish_gate_feedback(initial_feedback) + '\n위 문제를 반영해서 처음부터 다시 작성해줘.'
            elif attempt == 1:
                prompt = base_prompt
            else:
                logger.info(f"재시도 {attempt}/{MAX_WRITE_RETRIES} — 피드백:\n{feedback}")
                prompt = (
                    base_prompt
                    + '\n\n'
                    + _build_revision_feedback(feedback, attempt)
                    + '\n위 문제를 반드시 고쳐서 처음부터 다시 작성해줘.'
                )

            raw_output = writer.write(prompt, system=system).strip()

            if not raw_output:
                consecutive_empty += 1
                engine_error = getattr(writer, 'last_error', '') or ''
                feedback = '글쓰기 엔진 응답이 비어 있습니다. 반드시 지정된 섹션 형식으로 응답해줘.'
                if engine_error:
                    feedback += f'\n엔진 상태 참고: {engine_error}'
                if 'gateway' in engine_error.lower() or 'closed' in engine_error.lower():
                    feedback += '\nOpenClaw 게이트웨이 연결이 불안정했습니다. 이번 시도에서는 더 짧고 안정적으로 파싱 가능한 형식으로만 응답해줘.'
                logger.warning(f"[시도 {attempt}] 엔진 응답 비어있음 (연속 {consecutive_empty}회)")
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    raise WriteBlockedError(
                        f'엔진 응답이 {consecutive_empty}회 연속 비어 있음 - 다음 글감으로 넘김'
                    )
                continue

            consecutive_empty = 0  # 응답 있으면 초기화

            # ── Fix: AI가 글 대신 정보 요청/질문을 반환하는 패턴 조기 감지 ──────
            # 증상: 출처 데이터가 기사 제목 수준일 때 Claude가 글 대신 질문 반환
            # 대응: 1~2시도 안에 감지해서 WriteBlockedError → 다음 글감으로 넘김
            _INFO_REQUEST_SIGNALS = (
                '정보를 먼저 주시면', '아래 정보를 주시면', '다음 정보가 필요합니다',
                '더 많은 정보가', '출처가 부족', '정확한 정보가 없어', '정보가 불충분',
                '확인이 필요합니다', '정확히 알 수 없어', 'WebFetch 권한',
                '다음을 알려주시면', '먼저 알려주시면',
            )
            if attempt <= 2 and any(sig in raw_output for sig in _INFO_REQUEST_SIGNALS):
                raise WriteBlockedError(
                    f'[시도 {attempt}] 출처 정보 불충분 — AI가 글 대신 정보 요청 반환. '
                    '글감 출처가 기사 제목 수준이므로 다음 글감으로 넘김'
                )

            parsed = parse_output(raw_output)
            if not parsed:
                last_parse_error = raw_output[:200]
                logger.warning(
                    f"[시도 {attempt}] 파싱 실패 — 실제 출력 앞부분:\n{raw_output[:400]}"
                )
                feedback = (
                    '출력 파싱에 실패했습니다. 아래 형식을 그대로 사용해서 다시 작성해줘.\n\n'
                    '---TITLE---\n제목\n\n'
                    '---META---\n설명\n\n'
                    '---SLUG---\nslug\n\n'
                    '---TAGS---\n태그1, 태그2\n\n'
                    '---CORNER---\n코너명\n\n'
                    '---BODY---\n<h2>섹션1</h2>\n<p>문단1...</p>\n<p>문단2...</p>\n<h2>섹션2</h2>\n<p>문단1...</p>\n\n'
                    '---KEY_POINTS---\n- 핵심1\n\n'
                    '---COUPANG_KEYWORDS---\n키워드\n\n'
                    '---SOURCES---\nhttps://example.com | 출처명 | 날짜\n\n'
                    '---DISCLAIMER---\n'
                    '\n주의: 섹션 헤더는 반드시 ---대문자--- 형식. 다른 마크다운 헤더(# 등) 사용 금지.'
                )
                current_bucket = _feedback_bucket(feedback)
                if current_bucket == last_feedback_bucket:
                    same_feedback_repeats += 1
                else:
                    last_feedback_bucket = current_bucket
                    same_feedback_repeats = 1
                if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                    raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                continue

            source_context = _build_source_context(parsed, topic_data)

            # body에 이미 <p> 문단이 있으면 single-pass 완성 원고 → 아웃라인 확장 건너뜀
            body_text = parsed.get('body', '')
            if re.search(r'<p\b', body_text, re.IGNORECASE):
                logger.info(f"[시도 {attempt}] 완성 본문 감지 — 섹션 확장 건너뜀")
                parsed = _sanitize_article(parsed)
            else:
                _deadline = started_at + MAX_WRITE_ELAPSED_SECONDS
                body_built, body_or_feedback = _compose_body_from_outline(
                    writer,
                    reviewer,
                    topic_data,
                    parsed,
                    source_context,
                    deadline=_deadline,
                )
                if not body_built:
                    if get_token_budget().is_exceeded():
                        # 섹션 생성 실패 + 예산 초과 → 아웃라인(H2 골격)만 있는 상태로 발행
                        logger.warning(
                            f"[시도 {attempt}] 섹션 생성 실패 + 토큰 예산 초과 — 아웃라인 상태로 발행"
                        )
                        parsed = _sanitize_article(parsed)
                        article = parsed
                        write_succeeded = True
                        break
                    feedback = body_or_feedback
                    article = parsed
                    logger.warning(f"[시도 {attempt}] 섹션 생성 실패:\n{feedback}")
                    continue

                parsed['body'] = body_or_feedback
                parsed = _sanitize_article(parsed)

            # 룰 기반 품질 검사
            passed, quality_feedback = _check_article_quality(parsed)
            if not passed:
                feedback = quality_feedback
                article = parsed
                _append_writer_memory('failure', _extract_memory_points(quality_feedback), corner=corner)
                logger.warning(f"[시도 {attempt}] 품질 미달:\n{feedback}")
                current_bucket = _feedback_bucket(feedback)
                if current_bucket == last_feedback_bucket:
                    same_feedback_repeats += 1
                else:
                    last_feedback_bucket = current_bucket
                    same_feedback_repeats = 1
                if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                    raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                continue

            body = parsed.get('body', '')

            # 토큰 예산 초과 시 현재까지 개선된 글로 즉시 발행
            _budget = get_token_budget()
            if _budget.is_exceeded():
                _r4_ok, _r4_fb = _presentation_review(parsed)
                _r4b_ok, _r4b_fb = _title_actionability_review(parsed)
                if not _r4_ok or not _r4b_ok:
                    _title_issues = '\n'.join(filter(None, [_r4_fb, _r4b_fb]))
                    logger.warning(
                        f"[시도 {attempt}] 토큰 예산 초과 + 제목/표현 검수 미달 "
                        f"— 강제 발행 (미해결):\n{_title_issues}"
                    )
                else:
                    logger.warning(
                        f"[시도 {attempt}] 토큰 예산 초과 ({_budget.used():,} / {_budget.budget:,} 토큰, "
                        f"{_budget.usage_pct():.1f}%) — 리뷰 중단, 현재 글로 발행"
                    )
                article = parsed
                write_succeeded = True
                break

            if skip_review:
                logger.info(f"[시도 {attempt}] 검수 건너뜀 (--skip-review)")
            else:
                # 검수: Sonnet — 크로스체크
                r2_passed, r2_feedback = _parse_review(reviewer.write(_build_review_prompt(body)))
                if not r2_passed:
                    feedback = f'[Claude 검수 실패]\n{r2_feedback}'
                    article = parsed
                    _append_writer_memory('failure', _extract_memory_points(r2_feedback), corner=corner)
                    logger.warning(f"[시도 {attempt}] Claude 검수 실패:\n{r2_feedback}")
                    current_bucket = _feedback_bucket(feedback)
                    if current_bucket == last_feedback_bucket:
                        same_feedback_repeats += 1
                    else:
                        last_feedback_bucket = current_bucket
                        same_feedback_repeats = 1
                    if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                        raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                    continue

                # 3차 검수: 룰 기반 문장 밀도/반복 점검
                r3_passed, r3_feedback = _heuristic_review(body)
                if not r3_passed:
                    feedback = f'[룰 기반 검수 실패]\n{r3_feedback}'
                    article = parsed
                    _append_writer_memory('failure', _extract_memory_points(r3_feedback), corner=corner)
                    logger.warning(f"[시도 {attempt}] 룰 기반 검수 실패:\n{r3_feedback}")
                    current_bucket = _feedback_bucket(feedback)
                    if current_bucket == last_feedback_bucket:
                        same_feedback_repeats += 1
                    else:
                        last_feedback_bucket = current_bucket
                        same_feedback_repeats = 1
                    if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                        raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                    continue

            r4_passed, r4_feedback = _presentation_review(parsed)
            if not r4_passed:
                repaired = None
                if '약어/고유명사가 첫 등장 시 설명 없이 사용됨' in r4_feedback:
                    repaired = _apply_acronym_repairs(parsed, r4_feedback)
                    r4_retry_passed, r4_retry_feedback = _presentation_review(repaired)
                    if not r4_retry_passed and not get_token_budget().is_exceeded():
                        prompt_repaired = _repair_acronym_explanations(writer, repaired, r4_retry_feedback)
                        if prompt_repaired is not None:
                            repaired = prompt_repaired
                            r4_retry_passed, r4_retry_feedback = _presentation_review(repaired)
                    if r4_retry_passed:
                        parsed = repaired
                        logger.info(f"[시도 {attempt}] 약어 자동 보정 후 표현/가독성 검수 통과")
                    else:
                        r4_feedback = r4_retry_feedback

                if not repaired or not _presentation_review(parsed)[0]:
                    feedback = f'[표현/가독성 검수 실패]\n{r4_feedback}'
                    article = parsed
                    _append_writer_memory('failure', _extract_memory_points(r4_feedback), corner=corner)
                    logger.warning(f"[시도 {attempt}] 표현/가독성 검수 실패:\n{r4_feedback}")
                    current_bucket = _feedback_bucket(feedback)
                    if current_bucket == last_feedback_bucket:
                        same_feedback_repeats += 1
                    else:
                        last_feedback_bucket = current_bucket
                        same_feedback_repeats = 1
                    if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                        raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                    continue

            r4b_passed, r4b_feedback = _title_actionability_review(parsed)
            if not r4b_passed:
                repaired = _repair_actionability(writer, topic_data, parsed, r4b_feedback) if not get_token_budget().is_exceeded() else None
                if repaired is not None:
                    r4b_retry_passed, r4b_retry_feedback = _title_actionability_review(repaired)
                    if r4b_retry_passed:
                        parsed = repaired
                        logger.info(f"[시도 {attempt}] 제목/도입 국소 보정 후 행동성 검수 통과")
                    else:
                        r4b_feedback = r4b_retry_feedback

                if not r4b_passed and (repaired is None or not _title_actionability_review(parsed)[0]):
                    feedback = f'[제목/도입 행동성 검수 실패]\n{r4b_feedback}'
                    article = parsed
                    _append_writer_memory('failure', _extract_memory_points(r4b_feedback), corner=corner)
                    logger.warning(f"[시도 {attempt}] 제목/도입 행동성 검수 실패:\n{r4b_feedback}")
                    current_bucket = _feedback_bucket(feedback)
                    if current_bucket == last_feedback_bucket:
                        same_feedback_repeats += 1
                    else:
                        last_feedback_bucket = current_bucket
                        same_feedback_repeats = 1
                    if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                        raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                    continue

            r5_passed, r5_feedback = _structure_review(parsed)
            if not r5_passed:
                feedback = f'[구조 검수 실패]\n{r5_feedback}'
                article = parsed
                _append_writer_memory('failure', _extract_memory_points(r5_feedback), corner=corner)
                logger.warning(f"[시도 {attempt}] 구조 검수 실패:\n{r5_feedback}")
                current_bucket = _feedback_bucket(feedback)
                if current_bucket == last_feedback_bucket:
                    same_feedback_repeats += 1
                else:
                    last_feedback_bucket = current_bucket
                    same_feedback_repeats = 1
                if same_feedback_repeats >= MAX_SAME_FEEDBACK_REPEATS:
                    raise WriteBlockedError(f'{current_bucket} 반복 - 다음 글감으로 넘김')
                continue

            if attempt <= MIN_REVISION_ROUNDS:
                feedback = _build_min_revision_feedback(attempt)
                article = parsed
                logger.warning(f"[시도 {attempt}] 최소 재작성 횟수 미달")
                continue

            _append_writer_memory(
                'success',
                [
                    f'제목은 행동과 결과가 함께 보여야 한다: {parsed.get("title", "")}',
                    '도입은 바로 사실이나 장면이나 선택 기준으로 들어간다.',
                    '정리만 하는 메타 문장보다 바로 써먹는 기준을 먼저 준다.',
                ],
                corner=corner,
            )
            logger.info(f"[시도 {attempt}] 품질 + AI 검수 + 룰 기반 검수 + 표현/구조 검수 모두 통과")
            article = parsed
            feedback = ''
            write_succeeded = True
            break
    except WriteBlockedError as e:
        _save_failed_write(
            topic_data=topic_data,
            output_path=output_path,
            reason=str(e),
            article=article,
            feedback=feedback,
        )
        raise

    if article is None:
        _save_failed_write(
            topic_data=topic_data,
            output_path=output_path,
            reason=f'모든 시도({MAX_WRITE_RETRIES}회)에서 파싱 실패',
            article=None,
            feedback=last_parse_error,
        )
        raise RuntimeError(
            f'모든 시도({MAX_WRITE_RETRIES}회)에서 파싱 실패. '
            f'마지막 출력 앞부분: {last_parse_error}'
        )

    if not write_succeeded and feedback:
        if _is_publishable(article):
            logger.warning(
                f"최대 재시도 횟수({MAX_WRITE_RETRIES}) 소진. "
                f"품질 검수 미달이나 발행 가능한 원고 있음 — 강제 발행. 미해결 문제:\n{feedback}"
            )
            write_succeeded = True
        else:
            _save_failed_write(
                topic_data=topic_data,
                output_path=output_path,
                reason=f'최대 재시도 횟수({MAX_WRITE_RETRIES}회) 소진',
                article=article,
                feedback=feedback,
            )
            logger.warning(
                f"최대 재시도 횟수({MAX_WRITE_RETRIES}) 소진. "
                f"발행 가능한 원고 없음. 미해결 문제:\n{feedback}"
            )
            raise WriteBlockedError(f'최대 재시도 횟수({MAX_WRITE_RETRIES}회) 소진 - 다음 글감으로 넘김')

    article = _sanitize_article(article)

    return article


def write_article(topic_data: dict, output_path: Path, writer=None, style_prefix: str = "",
                  skip_review: bool = False, initial_feedback: str = "") -> dict:
    """
    topic_data → EngineLoader 호출 → article dict 저장.
    Returns: article dict (저장 완료)
    Raises: RuntimeError — 글 작성 또는 파싱 실패 시
    """
    title = topic_data.get('topic', topic_data.get('title', ''))
    logger.info(f"글 작성 시작: {title}")

    article = generate_article(topic_data, writer=writer, style_prefix=style_prefix,
                               skip_review=skip_review, initial_feedback=initial_feedback,
                               output_path=output_path)

    article.setdefault('title', title)
    article['slug'] = article.get('slug') or _safe_slug(article['title'])
    article['corner'] = article.get('corner') or topic_data.get('corner', '쉬운세상')
    article['topic'] = topic_data.get('topic', '')
    article['description'] = topic_data.get('description', '')
    article['quality_score'] = topic_data.get('quality_score', 0)
    article['source'] = topic_data.get('source', '')
    article['source_url'] = topic_data.get('source_url') or topic_data.get('source') or ''
    article['published_at'] = topic_data.get('published_at', '')
    article['created_at'] = datetime.now().isoformat()
    # 글감 추적: 어떤 topic 파일에서 생성됐는지 기록
    if topic_data.get('_source_file'):
        article['_source_topic_file'] = topic_data['_source_file']

    # 쿠팡 파트너스 키워드 자동 추출 (본문에 등장하는 카테고리 매핑 키워드)
    try:
        affiliate_cfg = json.loads((CONFIG_DIR / 'affiliate_links.json').read_text(encoding='utf-8'))
        category_map: dict = affiliate_cfg.get('coupang_category_map', {})
        plain_body = re.sub(r'<[^>]+>', '', article.get('body', ''))
        found_keywords = [kw for kw in category_map if kw in plain_body]
        article['coupang_keywords'] = found_keywords[:3]  # 최대 3개
        if found_keywords:
            logger.info(f"쿠팡 키워드 추출: {found_keywords[:3]}")
    except Exception as e:
        logger.warning(f"쿠팡 키워드 추출 실패: {e}")
        article.setdefault('coupang_keywords', [])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(article, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    logger.info(f"원고 저장 완료: {output_path.name}")
    return article


def run_pending(
    limit: int = 3,
    skip_review: bool = False,
    corner: str | None = None,
    exclude_files: set[str] | None = None,
) -> list[dict]:
    """
    data/topics/ 에서 오늘 날짜 미처리 글감을 최대 limit개 처리.
    Returns: 처리 결과 리스트 [{'slug':..., 'success':..., 'error':...}]
    """
    topics_dir = DATA_DIR / 'topics'
    originals_dir = DATA_DIR / 'originals'
    originals_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime('%Y%m%d')
    topic_files = sorted(topics_dir.glob(f'{today}_*.json'))

    if not topic_files:
        logger.info("오늘 날짜 글감 없음")
        return []

    ranked_topics = _rank_pending_topics(topic_files, originals_dir, corner=corner)
    excluded = exclude_files or set()

    from engine_loader import get_token_budget
    results = []
    processed = 0
    for topic_file, topic_data, _priority, _reasons in ranked_topics:
        if processed >= limit:
            break
        if topic_file.name in excluded:
            continue
        # 예산 초과 시 새 글 시작 자체를 중단
        if get_token_budget().is_exceeded():
            logger.warning(
                f"TokenBudget: 예산 초과 ({get_token_budget().usage_pct():.0f}%) "
                f"— 추가 글 작성 중단 (남은 글감 건너뜀)"
            )
            break
        output_path = originals_dir / topic_file.name
        topic_data['_source_file'] = topic_file.name
        try:
            article = write_article(topic_data, output_path, skip_review=skip_review)
            results.append({
                'file': topic_file.name,
                'title': topic_data.get('topic', ''),
                'slug': article.get('slug', ''),
                'success': True,
            })
            processed += 1
        except Exception as e:
            logger.error(f"글 작성 실패 [{topic_file.name}]: {e}")
            results.append({
                'file': topic_file.name,
                'title': topic_data.get('topic', ''),
                'slug': '',
                'success': False,
                'error': str(e),
            })
            processed += 1

    return results


def _writer_priority(topic_data: dict, memory: dict) -> tuple[float, list[str]]:
    topic = str(topic_data.get('topic', ''))
    source_name = str(topic_data.get('source_name') or topic_data.get('source') or '')
    source_url = str(topic_data.get('source_url') or '')
    corner = str(topic_data.get('corner') or '쉬운세상')
    source_count = len(topic_data.get('sources') or [])

    score = 0.0
    reasons: list[str] = []

    quality_score = float(topic_data.get('quality_score') or 0)
    topic_fit = float(topic_data.get('topic_fit_score') or 0)
    novelty = float(topic_data.get('novelty_score') or 0)
    impact = float(topic_data.get('impact_score') or 0)
    trust = float(topic_data.get('_trust_score') or 0)

    score += quality_score * 1.0
    score += topic_fit * 1.5
    score += novelty * 1.2
    score += impact * 0.8
    score += trust * 0.4
    reasons.append(f'quality={quality_score:.0f}')

    if corner == '쉬운세상':
        score += 6
        reasons.append('쉬운세상+6')

    if source_name in {'GeekNews', 'GitHub Trending', 'Hacker News', 'Google Trends', 'YouTube Trending'}:
        score += 6
        reasons.append(f'{source_name}+6')
    elif source_name in {'Maeil Economy', 'Yonhap Economy'}:
        score += 6
        reasons.append(f'{source_name}+6')
    elif source_name == 'Investing Korea':
        score -= 10
        reasons.append('Investing-10')

    if source_count >= 2:
        score += 8
        reasons.append(f'sources={source_count}+8')
    elif source_count <= 1:
        score -= 4
        reasons.append('single-source-4')

    _load_failed_sources_cache()
    if source_url and source_url in FAILED_SOURCE_CACHE:
        score -= 18
        reasons.append('failed-source-18')

    lower_topic = topic.lower()
    if any(token in lower_topic for token in ('show gn', 'guide', '가이드', '비쥬얼 가이드', 'workflow', '사용자명 변경', 'airpods max', '에어팟')):
        score += 8
        reasons.append('easy-headline+8')
    if any(token in lower_topic for token in ('ceo', '매수', '주식', '계약 체결', '목표 주가', '52주 최고치', '사상 최고치')):
        score -= 6
        reasons.append('hard-finance-6')

    failure_counts = memory.get('failure_counts', {}) if isinstance(memory, dict) else {}
    failure_keys = ' '.join(str(k) for k in failure_counts.keys())
    if 'META 설명이 추상적이다' in failure_keys and source_name == 'Investing Korea':
        score -= 5
        reasons.append('meta-risk-5')
    if '약어/고유명사가 첫 등장 시 설명 없이 사용됨' in failure_keys and re.search(r'\b[A-Z]{3,}\b', topic):
        score -= 6
        reasons.append('acronym-risk-6')
    if '리듬이 단조롭다' in failure_keys and topic:
        first_word = topic.split()[0]
        if len(first_word) >= 2:
            score -= 2
            reasons.append('starter-risk-2')

    return score, reasons


_THEME_CLUSTERS: dict[str, list[str]] = {
    'ai_tech': [
        'ai', 'gpt', 'claude', 'gemini', 'llm', '인공지능', 'agent', '에이전트',
        'coding', 'code', 'github', '개발', '프로그래밍', 'show gn', 'hacker news',
        '오픈소스', 'open source', '딥러닝', '머신러닝', 'machine learning',
    ],
    'finance': [
        '주식', 'etf', '투자', '나스닥', '코스피', '코스닥', 'bitcoin', 'btc',
        '금리', '펀드', '배당', '증시', '환율', '달러', '테슬라', '엔비디아',
        '반도체', '실적', '어닝', '시황',
    ],
    'health': [
        '건강', '운동', '다이어트', '수면', '혈당', '단백질', '영양', '헬스',
        '비타민', '식단', '근력',
    ],
    'realestate': [
        '부동산', '청약', '전세', '월세', '집값', '대출', '아파트', '분양',
    ],
}


def _detect_theme(text: str) -> str | None:
    """텍스트에서 가장 많이 매칭되는 테마 클러스터 반환"""
    lower = text.lower()
    best_theme, best_count = None, 0
    for theme, keywords in _THEME_CLUSTERS.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count > best_count:
            best_theme, best_count = theme, count
    return best_theme if best_count >= 1 else None


def _load_today_written_themes(originals_dir: Path) -> set[str]:
    """오늘 이미 작성된 글의 테마 클러스터 집합 반환"""
    today = datetime.now().strftime('%Y%m%d')
    themes: set[str] = set()
    for f in originals_dir.glob(f'{today}_*.json'):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            text = f"{data.get('title', '')} {data.get('topic', '')} {data.get('description', '')}"
            theme = _detect_theme(text)
            if theme:
                themes.add(theme)
        except Exception:
            pass
    return themes


def _rank_pending_topics(topic_files: list[Path], originals_dir: Path, corner: str | None = None) -> list[tuple[Path, dict, float, list[str]]]:
    memory = _load_writer_memory()
    written_themes = _load_today_written_themes(originals_dir)
    if written_themes:
        logger.info(f"오늘 이미 작성된 테마: {written_themes} — 동일 테마 글감 페널티 적용")

    ranked: list[tuple[Path, dict, float, list[str]]] = []
    for topic_file in topic_files:
        output_path = originals_dir / topic_file.name
        if output_path.exists():
            logger.debug(f"이미 처리됨: {topic_file.name}")
            continue
        try:
            topic_data = json.loads(topic_file.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"글감 읽기 실패 [{topic_file.name}]: {e}")
            continue
        if corner and topic_data.get('corner') != corner:
            continue
        priority, reasons = _writer_priority(topic_data, memory)

        # 오늘 이미 작성된 테마와 겹치면 페널티
        if written_themes:
            candidate_text = f"{topic_data.get('topic', '')} {topic_data.get('description', '')}"
            candidate_theme = _detect_theme(candidate_text)
            if candidate_theme and candidate_theme in written_themes:
                priority -= 40
                reasons.append(f'동일테마({candidate_theme})-40')

        ranked.append((topic_file, topic_data, priority, reasons))

    ranked.sort(key=lambda item: (-item[2], item[0].name))
    if ranked:
        preview = ', '.join(
            f"{item[0].name}:{item[2]:.1f}"
            for item in ranked[:5]
        )
        logger.info(f"글감 우선순위 상위: {preview}")
    return ranked


def run_from_topic(topic: str, corner: str = '쉬운세상', style_prefix: str = "", skip_review: bool = False) -> dict:
    """
    직접 주제 문자열로 글 작성.
    Returns: article dict
    """
    originals_dir = DATA_DIR / 'originals'
    originals_dir.mkdir(parents=True, exist_ok=True)

    slug = _safe_slug(topic)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}.json"
    output_path = originals_dir / filename

    topic_data = {
        'topic': topic,
        'corner': corner,
        'description': '',
        'source': '',
        'published_at': datetime.now().isoformat(),
    }
    return write_article(topic_data, output_path, style_prefix=style_prefix, skip_review=skip_review)


def run_from_file(file_path: str, style_prefix: str = "") -> dict:
    """
    JSON 파일에서 topic_data를 읽어 글 작성.
    """
    originals_dir = DATA_DIR / 'originals'
    originals_dir.mkdir(parents=True, exist_ok=True)

    topic_file = Path(file_path)
    topic_data = json.loads(topic_file.read_text(encoding='utf-8'))
    output_path = originals_dir / topic_file.name
    return write_article(topic_data, output_path, style_prefix=style_prefix)


# ─── CLI 진입점 ──────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='The 4th Path 글쓰기 봇')
    parser.add_argument('--topic', type=str, help='직접 글감 지정')
    parser.add_argument('--corner', type=str, default='쉬운세상', help='코너 지정 (기본: 쉬운세상)')
    parser.add_argument('--file', type=str, help='글감 JSON 파일 경로')
    parser.add_argument('--limit', type=int, default=3, help='최대 처리 글 수 (기본: 3)')
    args = parser.parse_args()

    if args.topic:
        try:
            article = run_from_topic(args.topic, corner=args.corner)
            print(f"[완료] 제목: {article.get('title', '')} | slug: {article.get('slug', '')}")
            sys.exit(0)
        except Exception as e:
            print(f"[오류] {e}", file=sys.stderr)
            sys.exit(1)

    if args.file:
        try:
            article = run_from_file(args.file)
            print(f"[완료] 제목: {article.get('title', '')} | slug: {article.get('slug', '')}")
            sys.exit(0)
        except Exception as e:
            print(f"[오류] {e}", file=sys.stderr)
            sys.exit(1)

    # 기본: 오늘 날짜 미처리 글감 처리
    results = run_pending(limit=args.limit, corner=args.corner)
    if not results:
        print("[완료] 처리할 글감 없음")
        sys.exit(0)

    ok = sum(1 for r in results if r['success'])
    fail = len(results) - ok
    print(f"[완료] 성공 {ok}건 / 실패 {fail}건")
    for r in results:
        status = '✅' if r['success'] else '❌'
        err = f" ({r.get('error', '')})" if not r['success'] else ''
        print(f"  {status} {r['file']}{err}")

    sys.exit(0 if fail == 0 else 1)


if __name__ == '__main__':
    main()
