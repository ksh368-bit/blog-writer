"""
bots/automotive_pipeline.py

전장반도체 파이프라인 — 아침 브리핑 및 인사이트 메모 처리

주요 함수:
- filter_automotive_topics(): 수집된 토픽에서 전장/반도체 관련 항목만 필터링
- format_morning_brief(): 텔레그램 아침 브리핑 메시지 포맷
- parse_insight_memo(): 사용자 인사이트 메모 파싱
"""

from __future__ import annotations

import html
import logging
import os
import re
from datetime import date
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


class _HTMLStripper(HTMLParser):
    """HTML 태그를 제거하고 plain text만 추출."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _is_english(text: str) -> bool:
    """텍스트가 주로 영어인지 판단한다. 한국어 문자 비율이 낮으면 영어로 간주."""
    if not text:
        return False
    korean_chars = sum(1 for c in text if '\uac00' <= c <= '\ud7a3')
    korean_ratio = korean_chars / max(len(text), 1)
    ascii_alpha = sum(1 for c in text if c.isascii() and c.isalpha())
    ascii_ratio = ascii_alpha / max(len(text), 1)
    return korean_ratio < 0.1 and ascii_ratio > 0.3


def _translate_to_korean(text: str) -> str:
    """엔진 로더를 통해 영어 텍스트를 한국어로 번역한다."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from engine_loader import EngineLoader

        loader = EngineLoader()
        writer = loader.get_writer()
        prompt = (
            f"다음 전장/반도체 기사 제목이나 요약을 자연스러운 한국어로 번역해줘. "
            f"번역문만 출력하고 다른 설명은 절대 하지 마.\n\n{text}"
        )
        result = writer.write(prompt)
        return result.strip() if result else text
    except Exception as e:
        logger.warning(f"번역 실패 ({e}) — 원문 유지")
        return text


def _translate_batch(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """여러 기사의 (제목, 설명) 쌍을 단 1번의 AI 호출로 번역한다.

    Args:
        items: [(제목, 설명), ...] 리스트

    Returns:
        [(번역제목, 번역설명), ...] — 입력과 동일한 길이
    """
    if not items:
        return []

    # 번호 붙여 한 번에 전송
    lines = []
    for i, (title, desc) in enumerate(items, start=1):
        lines.append(f"[{i}]제목: {title}")
        if desc:
            lines.append(f"[{i}]설명: {desc[:200]}")

    prompt = (
        "다음 전장/반도체 기사들을 자연스러운 한국어로 번역해줘.\n"
        "반드시 아래 형식을 지켜서 출력해. 번호와 '제목:'/'설명:' 태그는 그대로 유지해.\n\n"
        + "\n".join(lines)
    )

    raw = _translate_to_korean(prompt)

    # 응답 파싱: [N]제목: ... / [N]설명: ... 형식 추출
    result = list(items)  # 기본값: 원문 유지
    try:
        title_pat = re.compile(r'\[(\d+)\]제목:\s*(.+)')
        desc_pat = re.compile(r'\[(\d+)\]설명:\s*(.+)')

        titles: dict[int, str] = {}
        descs: dict[int, str] = {}

        for line in raw.splitlines():
            tm = title_pat.match(line.strip())
            if tm:
                titles[int(tm.group(1))] = tm.group(2).strip()
            dm = desc_pat.match(line.strip())
            if dm:
                descs[int(dm.group(1))] = dm.group(2).strip()

        result = [
            (titles.get(i, t), descs.get(i, d))
            for i, (t, d) in enumerate(items, start=1)
        ]
    except Exception as e:
        logger.warning(f"배치 번역 파싱 실패 ({e}) — 원문 유지")

    return result


def _strip_html(text: str) -> str:
    """HTML 태그 제거 + 엔티티 언이스케이프."""
    unescaped = html.unescape(text or "")
    stripper = _HTMLStripper()
    stripper.feed(unescaped)
    result = stripper.get_text()
    # 연속 공백 정리
    return re.sub(r"\s+", " ", result).strip()

# ─── 고신뢰 키워드 (단독 매칭으로 전장 기사 확정) ────────────────
# 짧거나 범용적인 단어(ti, ev, soc, 반도체 등)는 오매칭이 심해 제외
HIGH_CONFIDENCE_KEYWORDS: list[str] = [
    # 전장 아키텍처 표준
    "autosar", "zonal architecture", "zone controller",
    "can bus", "automotive ethernet", "flexray",
    "멀티코어 mcu", "mcal", "autosar adaptive", "autosar classic",
    # 전장 반도체 기업/제품 (구체적)
    "nxp", "s32g", "s32k", "renesas", "rh850", "infineon", "aurix",
    "mobileye", "nvidia drive", "stmicroelectronics", "onsemi",
    # 자동차 기술 (복합어 우선)
    "자율주행", "전장반도체", "차량용 반도체", "전기차 반도체",
    "차량용 메모리", "차량용 이더넷", "자동차 반도체",
    "완성차 oem", "전장 ecu", "전장 mcu",
    # 투자/시장 (구체적)
    "전장용", "차량용 lpddr", "automotive semiconductor",
    "automotive grade", "iso 26262", "functional safety",
]

# ─── 보조 키워드 (2개 이상 동시 출현 시 전장 기사로 판단) ──────────
SUPPORTING_KEYWORDS: list[str] = [
    "전장", "자동차", "완성차", "전기차", "차량용",
    "반도체", "semiconductor", "automotive", "vehicle",
    "ecu", "mcu", "lidar", "radar", "adas",
]


def _is_automotive(topic: dict) -> bool:
    """토픽이 전장/반도체 관련인지 판단한다.

    판단 기준:
    1. 고신뢰 키워드 1개 이상 → 통과
    2. source_category=automotive + 보조 키워드 1개 이상 → 통과
    3. 보조 키워드 2개 이상 동시 출현 → 통과
    """
    text = " ".join([
        topic.get("topic", ""),
        topic.get("title", ""),
        topic.get("description", ""),
        topic.get("source_name", ""),
        topic.get("source", ""),
    ]).lower()

    # 1. 고신뢰 키워드 단독 매칭
    if any(kw in text for kw in HIGH_CONFIDENCE_KEYWORDS):
        return True

    matched_support = sum(1 for kw in SUPPORTING_KEYWORDS if kw in text)

    # 2. 전장 전문 소스 + 보조 키워드 1개
    if topic.get("source_category") == "automotive" and matched_support >= 1:
        return True

    # 3. 보조 키워드 2개 이상
    return matched_support >= 2


def filter_automotive_topics(topics: list[dict]) -> list[dict]:
    """수집된 토픽에서 전장/반도체 관련 항목만 필터링하고 품질 점수 내림차순 정렬."""
    filtered = [t for t in topics if _is_automotive(t)]
    return sorted(filtered, key=lambda t: t.get("quality_score", 0), reverse=True)


def format_morning_brief(topics: list[dict]) -> str:
    """
    텔레그램 아침 브리핑 메시지 포맷.

    토픽 목록을 받아 번호 매긴 요약 메시지를 반환한다.
    토픽이 없으면 없다는 안내 메시지를 반환한다.
    """
    today = date.today().strftime("%Y-%m-%d")

    if not topics:
        return (
            f"📋 [{today}] 오늘의 전장반도체 브리핑\n\n"
            "오늘은 수집된 전장반도체 기사가 없습니다.\n\n"
            "관심 키워드나 인사이트가 있으면 메모로 보내주세요."
        )

    # 영어 기사 제목/설명을 1번 호출로 일괄 번역
    raw_titles = [_strip_html(t.get("topic") or t.get("title") or "(제목 없음)") for t in topics]
    raw_descs  = [_strip_html(t.get("description", "")) for t in topics]

    english_indices = [
        i for i, (ti, de) in enumerate(zip(raw_titles, raw_descs))
        if _is_english(ti) or (de and _is_english(de))
    ]

    if english_indices:
        batch_input = [(raw_titles[i], raw_descs[i][:200]) for i in english_indices]
        batch_output = _translate_batch(batch_input)
        for idx, (tr_title, tr_desc) in zip(english_indices, batch_output):
            if _is_english(raw_titles[idx]):
                raw_titles[idx] = tr_title
            if raw_descs[idx] and _is_english(raw_descs[idx]):
                raw_descs[idx] = tr_desc

    lines = [f"📋 [{today}] 오늘의 전장반도체 브리핑\n"]
    for i, topic in enumerate(topics, start=1):
        title  = raw_titles[i - 1]
        source = topic.get("source_name") or topic.get("source") or ""
        url    = topic.get("source_url", "")
        desc   = raw_descs[i - 1]

        lines.append(f"{i}. 📰 {title}")
        if source:
            lines.append(f"   출처: {source}")
        if desc:
            # 설명이 너무 길면 80자로 자름
            short_desc = desc[:80] + "..." if len(desc) > 80 else desc
            lines.append(f"   {short_desc}")
        if url:
            lines.append(f"   🔗 {url}")
        lines.append("")

    lines.append(
        "💡 읽고 떠오른 인사이트를 답장으로 보내주세요.\n"
        "예) '1번 기사 흥미롭네. NXP 메모리 이슈랑 연결해봐'\n"
        "예) 'Zonal 전환 시 멀티코어 수요 증가 관점으로 써줘'"
    )

    return "\n".join(lines)


def parse_insight_memo(text: str) -> dict | None:
    """
    사용자가 보낸 텍스트를 인사이트 메모로 파싱한다.

    Returns:
        dict with keys:
            - memo (str): 원본 텍스트
            - topic_ref (int | None): 참조한 토픽 번호 (예: '1번 기사' → 1)
        None: 봇 명령어이거나 빈 문자열인 경우
    """
    if not text or not text.strip():
        return None

    stripped = text.strip()

    # /command 형태는 봇 명령어 → 무시
    if stripped.startswith("/"):
        return None

    # 토픽 번호 참조 감지: "1번", "2번 기사", "3번째" 등
    topic_ref: int | None = None
    ref_match = re.search(r"(\d+)\s*번", stripped)
    if ref_match:
        topic_ref = int(ref_match.group(1))

    return {
        "memo": stripped,
        "topic_ref": topic_ref,
    }
