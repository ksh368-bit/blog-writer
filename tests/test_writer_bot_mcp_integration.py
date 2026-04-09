import json
from pathlib import Path

from blogwriter_mcp.tools.creative_dna import CreativeDNA, NarrativeDNA
from bots import writer_bot


class DummyWriter:
    def __init__(self, raw_output: str):
        self.raw_output = raw_output
        self.calls: list[dict] = []

    def write(self, prompt: str, system: str = "") -> str:
        self.calls.append({"prompt": prompt, "system": system})
        return self.raw_output


RAW_OUTPUT = """---TITLE---
AI를 써보면 업무 처리가 쉬워진다

---META---
AI를 써보면 반복 작업이 줄어든다.

---SLUG---
test-slug

---TAGS---
AI, 업무자동화
---CORNER---
쉬운세상

---BODY---
<h2>AI가 업무를 바꾸는 방식</h2>
<p><strong>AI를 사용하면</strong> 반복 작업이 줄어든다. 2024년 기준으로 자동화를 도입한 40%의 팀이 처리 속도 향상을 체감했다. 이전에는 시간이 걸리던 단순 작업들이 빠르게 처리된다.</p>
<p>처음에는 자동완성 정도라 생각했다. 직접 써보면 다르다. 맥락을 파악하고 흐름 전체를 제안한다. 단순한 도구 이상의 역할을 한다.</p>
<p>회의 자료를 준비하던 30분이 줄어든다. 보고서 초안을 다듬던 반복 작업도 마찬가지다. 노트북 앞에서 하던 단순 반복 업무 3개 이상이 자동화된다. 남은 시간을 판단에 쓸 수 있다.</p>
<p>브라우저 탭을 여러 개 열어 자료를 찾던 방식도 달라진다. 폴더 안에서 파일을 뒤지던 시간이 줄어든다. 찾아야 할 정보를 AI에게 물으면 바로 나온다. 이전 방식으로 돌아가기 어렵다.</p>
<p>처음 2주는 어색하다. 기존 방식이 익숙하기 때문이다. 그런데 한 달이 지나면 AI가 없는 업무 방식이 오히려 답답하게 느껴진다. 이 변화가 개인 수준을 넘어 팀 전체로 퍼진다.</p>
<h2>사람이 적응하는 구조</h2>
<p>새 도구가 등장하면 사람이 적응한다. <strong>모바일이 바꾼 것처럼</strong> AI도 판단 방식을 바꾼다. 출근 후 맥북을 열면 이미 AI가 준비한 요약이 기다린다.</p>
<p>의사가 AI 진단 도구를 쓸 때 어느 정도를 신뢰할지 결정해야 한다. 개발자가 생성 코드를 검토할 때도 같다. 언론인이 언어 모델로 기사 초안을 쓸 때도 마찬가지다. 판단 기준이 달라진다.</p>
<p>이것이 새로운 리터러시다. 화면 앞에서가 아니라 실제 업무 흐름 안에서 익힌다. <strong>기준 없이</strong> AI를 쓰면 잘못된 결과를 걸러내지 못한다. 퇴근 후에도 그 감각이 쌓인다.</p>
<h2>변하지 않는 것의 값어치</h2>
<p>의미와 연결에 대한 욕구는 줄어들지 않는다. AI가 모방할수록 진짜 판단의 <strong>값어치가 올라간다.</strong> 도구를 잘 쓰려면 결과를 검증하는 눈이 있어야 한다.</p>
<p>한 번 써보면 차이를 직접 느낄 수 있다. 그 경험이 기준이 된다. AI를 언제 써야 하는지 감이 생기면 쓰지 않아야 할 때도 보인다. 이것이 쌓이면 달라진다.</p>
<p>결국 AI를 쓰면 쉬워지는 것은 판단의 속도다. 정보를 모으고 정리하는 시간이 줄고 결정에 집중할 수 있다. 처음에는 낯설지만 익숙해지면 이전으로 돌아가기 어렵다. 업무 흐름 자체가 달라지기 때문이다. 그 차이는 직접 써보면 바로 느낀다.</p>
<p>AI 도구는 혼자 쓰면 좋고 팀이 함께 쓰면 더 좋다. 같은 도구를 쓰는 팀은 맥락 전달이 빨라진다. 회의에서 요약을 공유하고 로그를 함께 검토하면 소통 비용이 줄어든다. 이것이 개인 효율을 넘어 조직 역량으로 이어진다.</p>
<ul><li>반복 작업 자동화</li><li>판단 속도 향상</li><li>팀 소통 비용 절감</li></ul>

---KEY_POINTS---
- AI를 사용하면 반복 작업이 줄어들고 처리 속도가 향상된다
- AI를 잘 활용하려면 결과를 검증하는 판단 기준이 필요하다

---COUPANG_KEYWORDS---
노트북
---SOURCES---
https://example.com | AI 활용 사례 연구 | 2026-04-02

---DISCLAIMER---
참고용 정보입니다
"""


def test_generate_article_supports_style_prefix_without_persisting():
    topic_data = {
        "topic": "AI and the future of humans",
        "corner": "Easy World",
        "description": "Description",
        "source_url": "https://example.com",
        "published_at": "2026-04-02T00:00:00",
    }
    dummy = DummyWriter(RAW_OUTPUT)

    article = writer_bot.generate_article(
        topic_data,
        writer=dummy,
        style_prefix="[Creative DNA]\n",
        skip_review=True,
    )

    assert "쉬워진다" in article["title"]
    assert article["slug"] == "test-slug"
    assert dummy.calls[0]["system"].startswith("[Creative DNA]\n")


def test_generate_article_accepts_full_narrative_dna_prefix():
    topic_data = {
        "topic": "Why one small object stays with us",
        "corner": "Easy World",
        "description": "Description",
        "source_url": "https://example.com",
        "published_at": "2026-04-02T00:00:00",
    }
    dummy = DummyWriter(RAW_OUTPUT)
    dna = CreativeDNA(
        themes=["wonder", "memory"],
        writing_style_summary="Short and reflective sentences.",
        emotional_register="Quiet but warm.",
        structural_tendency="Begin close and widen toward meaning.",
        philosophical_worldview="Meaning grows through attention to ordinary life.",
        vocabulary_register="Simple words with emotional precision.",
        narrative_dna=NarrativeDNA(
            opening_hook="Start with one ordinary detail.",
            tension_engine="Delay the emotional explanation until the reader leans in.",
            signature_move="Cross realism with allegorical reflection.",
            resolution_pattern="End with a quiet realization.",
        ),
        forbidden_tones=["didactic"],
        key_prop_tendency="One object should carry the emotional turn.",
        sample_sentence="The room changes when one object starts carrying memory.",
    )

    writer_bot.generate_article(
        topic_data,
        writer=dummy,
        style_prefix=dna.to_prompt_context(include_narrative=True),
        skip_review=True,
    )

    assert "Opening hook" in dummy.calls[0]["system"]
    assert "Resolution pattern" in dummy.calls[0]["system"]


def test_write_article_persists_generated_article_with_style_prefix(tmp_path: Path):
    topic_data = {
        "topic": "AI and the future of humans",
        "corner": "Easy World",
        "description": "Description",
        "source_url": "https://example.com",
        "published_at": "2026-04-02T00:00:00",
    }
    dummy = DummyWriter(RAW_OUTPUT)
    output_path = tmp_path / "article.json"

    article = writer_bot.write_article(
        topic_data,
        output_path,
        writer=dummy,
        style_prefix="[Creative DNA]\n",
        skip_review=True,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert "쉬워진다" in article["title"]
    assert "쉬워진다" in saved["title"]
    assert dummy.calls[0]["system"].startswith("[Creative DNA]\n")
