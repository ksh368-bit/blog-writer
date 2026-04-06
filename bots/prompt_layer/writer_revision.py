"""
bots/prompt_layer/writer_revision.py
Revision and section prompt builders for writer flow.
"""

import re


def compose_section_prompt(
    *,
    topic: str,
    corner: str,
    article_title: str,
    description: str,
    source: str,
    prev_h2: str,
    current_h2: str,
    next_h2: str,
    h2_titles: list[str],
    feedback: str = '',
) -> str:
    prompt = f"""아래 블로그 글의 섹션 본문만 작성해줘.

주제: {topic}
코너: {corner}
제목: {article_title}
설명: {description}
출처: {source}
이전 섹션: {prev_h2}
현재 섹션: {current_h2}
다음 섹션: {next_h2}
전체 섹션 순서: {' | '.join(h2_titles)}

출력 형식:
---SECTION_BODY---
<p>...</p>
<p>...</p>
<p>...</p>

중요:
- 지금은 현재 섹션의 본문만 쓴다. <h2>는 쓰지 마.
- 2~3개의 <p>만 써.
- 각 문단은 2~4문장으로 짧고 또렷하게 써.
- 쉬운세상이라면 섹션 전체에서 독자가 겪어본 생활/업무 장면을 최소 1번만 넣어. 모든 문단에 억지로 넣지 마.
- 출처에 없는 절감 시간, 분 단위 효과, 주간/월간 합산 시간은 쓰지 마.
- 장면을 쓰더라도 "그래서 판단이 쉬워진다" 정도로만 닫아. "10분이 20분이 된다", "주 5일이면 50분" 같은 계산은 금지다.
- 예시를 들면 왜 중요한지 바로 닫아.
- 고유명사를 여러 개 늘어놓지 말고 문장을 나눠.
- 문장을 시작했으면 끝까지 닫아. 중간에서 끊기면 안 된다.
- 제품 브리핑체, 보도체, 뜬구름 잡는 총론은 금지.
- "쉽게 말하면", "첫 구분은", "마지막 기준은", "즉 이제" 같은 정리 도입구 뒤에는 반드시 숫자·고유명사·구체 장면이 바로 와야 한다. 추상어로만 끝내지 마.
- 같은 시작어로 문장을 2번 이상 반복하지 마. 특히 문단 첫 문장들이 모두 같은 단어로 시작하면 실패다.
- 각 섹션 핵심 표현 1~2개는 <strong>로 강조해.
- 영문 약어(LHC, FPGA, CERN 등)나 외국 조직명이 이 섹션에서 처음 등장하면 괄호 안에 한국어 풀이를 넣어. 예: 'FPGA(현장 프로그래밍 가능 게이트 어레이)'. 글 전체에서 이미 나온 약어는 괄호 없이 써도 된다.
"""
    if feedback:
        prompt += f"\n[이전 시도 수정 피드백]\n{feedback}\n위 문제를 모두 고쳐서 같은 섹션만 다시 써."
    return prompt


def compose_revision_feedback(feedback: str, attempt: int, min_revision_rounds: int) -> str:
    repeated_starters = re.findall(r'"([^"]+)"로 시작하는 문장이 여러 번 반복돼 리듬이 단조롭다', feedback)
    starter_rules = ''
    if repeated_starters:
        rules = []
        for starter in repeated_starters[:3]:
            rules.append(f'- "{starter}"로 시작하는 문장은 이번 원고에서 한 번만 써. 같은 시작어를 반복하지 마.')
        starter_rules = '\n'.join(rules) + '\n'

    actionability_rules = ''
    if '[제목/도입 행동성 검수 실패]' in feedback or '제목에서 행동과 결과가 함께 바로 보이지 않는다' in feedback:
        actionability_rules = (
            '- 제목은 반드시 "[무엇을 하면] [무엇이 달라진다]" 한 줄로 다시 써.\n'
            '- 제목 예시 형식: "위험 이전 문구부터 보면 계약 뜻이 바로 잡힌다"\n'
            '- 제목은 38자 안쪽으로 줄여. 뒤에 설명을 덧붙이지 말고 행동과 결과만 남겨.\n'
            '- META 첫 문장도 같은 구조로 써. 무엇을 보면/하면 무엇이 달라지는지 먼저 써.\n'
            '- META 예시 형식: "위험 이전 문구부터 보면 이 계약을 새 투자로 오해하지 않게 된다."\n'
            '- META는 "배경을 설명한다", "핵심을 정리한다" 같은 추상 문장을 쓰지 마.\n'
            '- 첫 문단 첫 문장은 독자가 바로 할 행동 하나와 얻는 결과 하나를 같이 말해.\n'
        )

    structure_rules = ''
    if '[구조 검수 실패]' in feedback:
        structure_rules = (
            '- 첫 문단 첫 문장은 바로 핵심으로 들어가. "[무엇을 먼저 보면] [무슨 오해를 줄일 수 있다]" 구조로 시작해.\n'
            '- 첫 문단 둘째 문장에는 왜 그 오해가 생기는지 기사 제목이나 숫자나 문구 하나를 붙여.\n'
            '- 마지막 문단 마지막 문장은 "그래서 다음에 이런 제목을 보면 어디부터 확인하면 된다" 식의 행동 기준으로 닫아.\n'
            '- 도입과 결말을 추상 정리로 쓰지 말고, 독자가 다음 기사에서 바로 써먹을 판단 기준을 남겨.\n'
        )

    acronym_rules = ''
    acronym_matches = re.findall(r'다음 약어/고유명사가 첫 등장 시 설명 없이 사용됨: ([^\.]+)\.', feedback)
    if acronym_matches:
        acronyms = []
        for chunk in acronym_matches:
            acronyms.extend([item.strip() for item in chunk.split(',') if item.strip()])
        acronyms = acronyms[:3]
        if acronyms:
            lines = []
            for acronym in acronyms:
                lines.append(
                    f'- "{acronym}"가 처음 나오면 바로 괄호 설명을 붙여. 예: "{acronym}(회사명 또는 한국어 풀이)".'
                )
            lines.append('- 약어만 단독으로 던지지 말고, 첫 등장 문장에서 정체를 같이 설명해.')
            acronym_rules = '\n'.join(lines) + '\n'

    focus_map = {
        2: '제목과 첫 문단을 가장 먼저 갈아엎어. 첫 문장은 바로 숫자, 고유명사, 사건으로 시작해.',
        3: '문단 중간의 연결 문장을 정리해. 짧은 예고 문장 없이 한 문장 안에서 설명까지 끝내.',
        4: '마지막 문장들을 다시 써. 추상적 총평 대신 구체적 귀결, 손실, 변화, 계산 결과로 닫아.',
        5: '각 문단마다 정보 밀도를 더 올려. 최소 한 문장씩 숫자, 사례, 제품명, 회사명, 인명 중 하나를 추가해.',
        6: '리듬을 손봐. 같은 어순과 비슷한 문장 길이가 반복되지 않게 문장 구조를 섞어.',
    }
    focus = focus_map.get(attempt, '이전 실패 문장을 반복하지 말고, 정보 밀도와 문단 리듬을 동시에 더 날카롭게 다듬어.')
    return (
        "[수정 규칙]\n"
        "- 실패한 문장은 삭제하거나 완전히 다시 써.\n"
        "- 추상적인 문장은 구체 정보, 숫자, 사례, 장면 묘사로 교체해.\n"
        "- 질문만 던지는 문장은 바로 답까지 포함한 설명형 문장으로 바꿔.\n"
        "- 감상만 말하는 문장은 왜 그런지 근거를 붙여.\n"
        "- 비교나 나열을 시작한 문장은 반드시 끝까지 닫아. 중간에 끊긴 문장은 새로 써.\n"
        "- 고유명사나 서비스 이름을 여러 개 늘어놓기 시작하면 문장을 둘로 나누고, 마지막엔 의미를 닫아.\n"
        "- 예시를 꺼냈으면 왜 그 예시가 중요한지 바로 이어서 써.\n"
        "- 문장 시작 리듬이 반복되면 어순과 리듬을 바꿔.\n"
        "- 단정이 강한 문장은 수치, 사례, 고유명사로 받쳐.\n"
        "- 출처에 없는 시간 절감 수치, 분 단위 계산, 주간 합산 효과는 모두 삭제해.\n"
        "- 앞 문장을 다시 요약하는 문장은 삭제하고, 대신 새 기준이나 새 장면으로 바꿔.\n"
        "- '읽고 나면', '남는다', '복잡하지 않다' 같은 정리 문장은 구체 문장으로 갈아엎어.\n"
        "- '이 글은', '이 구분이', '이 차이는', '끝까지 읽고'처럼 글 자체를 설명하는 메타 문장은 삭제해.\n"
        f"{starter_rules}"
        f"{actionability_rules}"
        f"{structure_rules}"
        f"{acronym_rules}"
        "- 이번 출력에서는 실패 문장을 절대 재사용하지 마.\n\n"
        "[이번 회차 우선 과제]\n"
        f"- {focus}\n\n"
        "[검수 실패 목록]\n"
        f"{feedback}"
    )


def compose_min_revision_feedback(attempt: int, min_revision_rounds: int) -> str:
    focus_map = {
        1: '제목과 첫 문단을 가장 먼저 갈아엎어. 첫 문장은 바로 숫자, 고유명사, 사건으로 시작해.',
        2: '문단 중간의 연결 문장을 정리해. 짧은 예고 문장 없이 한 문장 안에서 설명까지 끝내.',
        3: '마지막 문장들을 다시 써. 추상적 총평 대신 구체적 귀결, 손실, 변화, 계산 결과로 닫아.',
        4: '각 문단마다 정보 밀도를 더 올려. 최소 한 문장씩 숫자, 사례, 제품명, 회사명, 인명 중 하나를 추가해.',
        5: '리듬을 손봐. 같은 어순과 비슷한 문장 길이가 반복되지 않게 문장 구조를 섞어.',
    }
    focus = focus_map.get(attempt, '정보 밀도와 문단 리듬을 동시에 더 날카롭게 다듬어.')
    return (
        "[최소 재작성 횟수 미달]\n"
        f"- 현재 시도는 {attempt}회차다. 최소 {min_revision_rounds}번의 재작성을 거친 뒤에만 최종 통과할 수 있다.\n"
        f"- 이번 회차 우선 과제: {focus}\n"
        "- 각 문단마다 최소 한 문장은 숫자, 고유명사, 사례, 장면 중 하나를 더 분명하게 넣어.\n"
        "- 실패 문장뿐 아니라 제목, 도입, 결론의 밀도도 함께 끌어올려."
    )


def compose_section_revision_feedback(feedback: str, attempt: int, current_h2: str) -> str:
    repeated_starters = re.findall(r'"([^"]+)"로 시작하는 문장이 여러 번 반복돼 리듬이 단조롭다', feedback)
    starter_lines = []
    for starter in repeated_starters[:3]:
        starter_lines.append(f'- "{starter}"로 시작하는 문장은 이 섹션에서 한 번만 써. 첫 단어를 모두 다르게 바꿔.')

    acronym_matches = re.findall(r'다음 약어/고유명사가 첫 등장 시 설명 없이 사용됨: ([^\.]+)\.', feedback)
    acronym_lines = []
    if acronym_matches:
        acronyms = []
        for chunk in acronym_matches:
            acronyms.extend([item.strip() for item in chunk.split(',') if item.strip()])
        for acronym in acronyms[:3]:
            acronym_lines.append(f'- "{acronym}"가 처음 나오면 바로 괄호 설명을 붙여.')

    relatable_line = ''
    if '생활 장면이 부족하다' in feedback:
        relatable_line = '- 이 섹션 한 군데에는 회의 직전, 브라우저 탭, 노트북 화면처럼 독자가 떠올릴 장면을 꼭 넣어.'

    extra_rules = []
    if starter_lines:
        extra_rules.extend(starter_lines)
    if acronym_lines:
        extra_rules.extend(acronym_lines)
    if relatable_line:
        extra_rules.append(relatable_line)

    lines = [
        f"[섹션 재작성 {attempt}회차]",
        f"- 현재 섹션 제목: {current_h2}",
        "- 문장을 더 짧고 또렷하게 끊어.",
        "- 예시를 시작했으면 그 의미를 바로 닫아.",
        "- 나열식 문장을 둘로 나누고, 마지막엔 반드시 결론까지 써.",
        "- 제품 브리핑처럼 설명만 하지 말고 독자가 떠올릴 장면을 한 번은 넣어.",
    ]
    lines.extend(extra_rules)
    lines.append(feedback)
    return '\n'.join(lines)
