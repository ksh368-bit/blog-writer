# 블로그 자동 수익 엔진 v3

**The 4th Path — Independent Tech Media** | by [22B Labs](https://github.com/sinmb79)

원고 하나를 AI로 작성하면 블로그, 인스타그램 카드, X 스레드, 유튜브 쇼츠, 주간 뉴스레터 — **5개 포맷으로 자동 변환·배포**하는 1인 미디어 자동화 시스템입니다.

> Python 기반, Windows 미니PC 24시간 운영 최적화.
> Google Blogger + AdSense + 쿠팡 파트너스 + 멀티플랫폼 수익 구조.

---

## 목차

- [아키텍처](#아키텍처)
- [기능 개요](#기능-개요)
- [프로젝트 구조](#프로젝트-구조)
- [설치](#설치)
- [환경 변수 설정](#환경-변수-설정)
- [Google OAuth 인증](#google-oauth-인증)
- [실행 방법](#실행-방법)
- [봇 상세 설명](#봇-상세-설명)
- [변환 엔진](#변환-엔진-layer-2)
- [배포 엔진](#배포-엔진-layer-3)
- [콘텐츠 코너](#콘텐츠-코너)
- [Telegram 명령어](#telegram-명령어)
- [OpenClaw AI 에이전트 연동](#openclaw-ai-에이전트-연동)
- [배포 스케줄](#배포-스케줄)
- [Phase 현황](#phase-현황)
- [자주 묻는 질문](#자주-묻는-질문)
- [기여 가이드](#기여-가이드)
- [라이선스](#라이선스)

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — AI 콘텐츠 생성                                    │
│  OpenClaw (GPT / Claude) → Blogger-ready HTML 원고 1개       │
└───────────────────────────┬─────────────────────────────────┘
                            │ article dict
┌───────────────────────────▼─────────────────────────────────┐
│  LAYER 2 — 변환 엔진 (Python, AI 없음)                        │
│                                                             │
│  blog_converter   card_converter   thread_converter          │
│  HTML+Schema.org  1080×1080 카드   X 스레드 280자            │
│                                                             │
│  shorts_converter          newsletter_converter              │
│  TTS+ffmpeg 쇼츠 영상       주간 HTML 뉴스레터                │
└───────────────────────────┬─────────────────────────────────┘
                            │ 5개 포맷
┌───────────────────────────▼─────────────────────────────────┐
│  LAYER 3 — 배포 엔진 (Python, AI 없음)                        │
│  Blogger  Instagram  X(Twitter)  TikTok  YouTube            │
└───────────────────────────┬─────────────────────────────────┘
                            │ 지표
┌───────────────────────────▼─────────────────────────────────┐
│  LAYER 4 — 분석 + 피드백                                     │
│  Google Analytics · Search Console · Telegram 리포트         │
└─────────────────────────────────────────────────────────────┘
```

---

## 기능 개요

| 기능 | 설명 | Phase |
|------|------|-------|
| 트렌드 수집 | PyTrends + RSS 멀티소스, 품질 점수 70점 미만 자동 폐기 | 1A ✅ |
| AI 글 작성 | OpenClaw 에이전트 → Blogger-ready HTML 직접 출력 | 1A ✅ |
| 블로그 발행 | Blogger API + Schema.org JSON-LD + AdSense 플레이스홀더 | 1A ✅ |
| 쿠팡 파트너스 | 키워드 자동 링크 삽입 | 1A ✅ |
| 인스타 카드 | Pillow 1080×1080 카드 이미지 생성 + Instagram Graph API | 1B ✅ |
| X 스레드 | 280자 자동 분할 + X API v2 순차 게시 | 1B ✅ |
| 유튜브 쇼츠 | TTS + Pillow 슬라이드 + ffmpeg 영상 합성 + YouTube API | 2 ✅ |
| TikTok | TikTok Content Posting API v2 | 2 ✅ |
| 주간 뉴스레터 | 주간 HTML 뉴스레터 자동 생성 | 1A ✅ |
| 분석봇 | GA4 + Search Console + Telegram 일간/주간 리포트 | 1A ✅ |
| Telegram 제어 | 명령어 + Claude API 자연어 폴백 | 1A ✅ |

---

## 프로젝트 구조

```
blog-writer/
│
├── bots/                          # 핵심 봇 모듈
│   ├── collector_bot.py           # 트렌드 수집 + 품질 필터
│   ├── publisher_bot.py           # Blogger API 발행
│   ├── linker_bot.py              # 쿠팡 파트너스 링크 삽입
│   ├── analytics_bot.py           # 성과 수집 + 리포트
│   ├── image_bot.py               # 만평 이미지 (manual/request/auto)
│   ├── article_parser.py          # 원고 포맷 파서
│   ├── remote_claude.py           # Claude Agent SDK Telegram 연동
│   ├── scheduler.py               # APScheduler + Telegram 리스너
│   │
│   ├── converters/                # LAYER 2 — 변환 엔진
│   │   ├── blog_converter.py      # HTML 정제 + Schema.org + AdSense
│   │   ├── card_converter.py      # 인스타 카드 이미지 (Pillow)
│   │   ├── thread_converter.py    # X 스레드 280자 분할
│   │   ├── newsletter_converter.py# 주간 뉴스레터 HTML
│   │   └── shorts_converter.py    # 쇼츠 영상 (TTS + ffmpeg)
│   │
│   └── distributors/              # LAYER 3 — 배포 엔진
│       ├── image_host.py          # ImgBB 업로드 / 로컬 HTTP 서버
│       ├── instagram_bot.py       # Instagram Graph API
│       ├── x_bot.py               # X API v2 (OAuth1)
│       ├── tiktok_bot.py          # TikTok Content Posting API v2
│       └── youtube_bot.py         # YouTube Data API v3
│
├── config/                        # 설정 파일 (비밀값 없음)
│   ├── platforms.json             # 플랫폼 활성화 여부
│   ├── schedule.json              # 스케줄 시간 설정
│   ├── quality_rules.json         # 품질 필터 규칙
│   ├── safety_keywords.json       # 안전 키워드 목록
│   ├── sources.json               # RSS 피드 + 트렌드 소스
│   ├── blogs.json                 # 블로그 설정
│   └── affiliate_links.json       # 제휴 링크 목록
│
├── templates/
│   └── shorts_template.json       # 쇼츠 코너별 설정 (색상/TTS/트랜지션)
│
├── scripts/
│   ├── setup.bat                  # Windows 최초 설치 스크립트
│   ├── get_token.py               # Google OAuth 토큰 발급
│   └── download_fonts.py          # NotoSansKR / 맑은고딕 설치
│
├── assets/
│   └── fonts/                     # .ttf 파일 (scripts/download_fonts.py로 설치)
│
├── data/                          # 런타임 데이터 (.gitignore)
│   ├── originals/                 # AI 생성 원고
│   ├── outputs/                   # 변환 결과물 (HTML/PNG/MP4/JSON)
│   └── ...
│
├── logs/                          # 로그 (.gitignore)
├── .env.example                   # 환경 변수 템플릿
├── requirements.txt
└── README.md
```

---

## 설치

### 사전 요구사항

- **Python 3.10 이상** — [python.org](https://www.python.org/downloads/)
- **ffmpeg** — 쇼츠 영상 생성 필수. [ffmpeg.org](https://ffmpeg.org/download.html)에서 다운로드 후 PATH 추가 또는 `.env`에 `FFMPEG_PATH` 지정
- Windows 미니PC 권장 (24시간 운영), macOS/Linux도 동작

### 1. 저장소 클론

```bash
git clone https://github.com/sinmb79/blog-writer.git
cd blog-writer
```

### 2. 가상환경 + 패키지 설치

```bash
# Windows — 자동 설치 (권장)
scripts\setup.bat

# 수동 설치
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

`setup.bat`이 처리하는 것:
- Python 가상환경 생성
- 패키지 설치
- `.env` 파일 생성 (`.env.example` 복사)
- `data/`, `logs/` 폴더 생성
- Windows 작업 스케줄러 자동 시작 등록

### 3. 폰트 설치

카드 이미지·쇼츠 영상의 한글 렌더링에 필요합니다.

```bash
python scripts/download_fonts.py
```

Windows: `맑은고딕(malgunbd.ttf)`을 `assets/fonts/`에 자동 복사
macOS/Linux: NotoSansKR을 GitHub에서 다운로드

### 4. 환경 변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 값 입력
```

---

## 환경 변수 설정

`.env.example`을 복사해 `.env`로 저장 후 아래 값을 채웁니다.
`.env` 파일은 절대 커밋하지 마세요 — `.gitignore`에 포함되어 있습니다.

### Phase 1A — 필수

| 변수 | 설명 | 발급처 |
|------|------|--------|
| `GOOGLE_CLIENT_ID` | OAuth 클라이언트 ID | [Google Cloud Console](https://console.cloud.google.com/) |
| `GOOGLE_CLIENT_SECRET` | OAuth 클라이언트 시크릿 | Google Cloud Console |
| `GOOGLE_REFRESH_TOKEN` | `scripts/get_token.py` 실행 후 자동 저장 | — |
| `BLOG_MAIN_ID` | Blogger 블로그 ID | Blogger 대시보드 URL |
| `TELEGRAM_BOT_TOKEN` | Telegram 봇 토큰 | [@BotFather](https://t.me/BotFather) |
| `TELEGRAM_CHAT_ID` | 내 Telegram 채팅 ID | [@userinfobot](https://t.me/userinfobot) |
| `COUPANG_ACCESS_KEY` | 쿠팡 파트너스 액세스 키 | [쿠팡 파트너스](https://partners.coupang.com/) |
| `COUPANG_SECRET_KEY` | 쿠팡 파트너스 시크릿 키 | 쿠팡 파트너스 |

**BLOG_MAIN_ID 확인 방법**
Blogger 관리자 → 블로그 선택 → 주소창:
```
https://www.blogger.com/blog/posts/3856391132195789013
                                   ↑ 이 숫자
```

### Phase 1B — 인스타그램 / X

| 변수 | 설명 | 발급처 |
|------|------|--------|
| `INSTAGRAM_ACCESS_TOKEN` | Instagram Graph API 장기 토큰 | [Facebook Developers](https://developers.facebook.com/) |
| `INSTAGRAM_ACCOUNT_ID` | Instagram 비즈니스 계정 ID | Facebook Developers |
| `X_API_KEY` | X API 키 | [X Developer Portal](https://developer.twitter.com/) |
| `X_API_SECRET` | X API 시크릿 | X Developer Portal |
| `X_ACCESS_TOKEN` | X 액세스 토큰 | X Developer Portal |
| `X_ACCESS_SECRET` | X 액세스 시크릿 | X Developer Portal |
| `IMGBB_API_KEY` | 이미지 공개 URL 변환 (무료) | [ImgBB](https://api.imgbb.com/) |

### Phase 2 — 쇼츠 / TikTok / YouTube

| 변수 | 설명 | 발급처 |
|------|------|--------|
| `GOOGLE_TTS_API_KEY` | Google Cloud TTS REST API | [Google Cloud Console](https://console.cloud.google.com/) |
| `FFMPEG_PATH` | ffmpeg 경로 (PATH 미등록 시만) | — |
| `OPENAI_API_KEY` | DALL-E 3 배경 이미지 (선택) | [OpenAI](https://platform.openai.com/) |
| `TIKTOK_ACCESS_TOKEN` | TikTok Content Posting API | [TikTok Developers](https://developers.tiktok.com/) |
| `TIKTOK_OPEN_ID` | TikTok 사용자 Open ID | TikTok Developers |
| `YOUTUBE_CHANNEL_ID` | YouTube 채널 ID | YouTube Studio |
| `ANTHROPIC_API_KEY` | Telegram 자연어 명령 처리 | [Anthropic Console](https://console.anthropic.com/) |

### 이미지 모드 선택

```env
IMAGE_MODE=manual   # (기본) 발행 시 Telegram으로 프롬프트 전송
IMAGE_MODE=request  # 매주 월요일 프롬프트 목록 일괄 전송
IMAGE_MODE=auto     # DALL-E 3 자동 생성 (OPENAI_API_KEY 필요)
```

---

## Google OAuth 인증

### 1. Google Cloud Console 설정

1. [console.cloud.google.com](https://console.cloud.google.com/) → 새 프로젝트 생성
2. **API 및 서비스 → 라이브러리** 에서 아래 API 활성화:
   - `Blogger API v3`
   - `Google Search Console API`
   - `YouTube Data API v3` (Phase 2)
3. **사용자 인증 정보 → OAuth 클라이언트 ID 만들기**
   - 애플리케이션 유형: **데스크톱 앱**
4. `credentials.json` 다운로드 → 프로젝트 루트에 저장

### 2. 토큰 발급

```bash
venv\Scripts\activate
python scripts\get_token.py
```

브라우저에서 Google 계정 인증 → `token.json` 자동 저장.
`credentials.json`과 `token.json`은 `.gitignore`에 포함 — 절대 커밋하지 마세요.

---

## 실행 방법

### 스케줄러 시작 (권장)

```bash
venv\Scripts\activate
python bots\scheduler.py
```

백그라운드 실행 (Windows):
```bash
pythonw bots\scheduler.py
```

Windows 작업 스케줄러를 통해 PC 시작 시 자동 실행되도록 `setup.bat`이 등록합니다.

### 개별 봇 단독 실행

```bash
python bots\collector_bot.py        # 트렌드 수집
python bots\publisher_bot.py        # 블로그 발행
python bots\analytics_bot.py        # 일간 리포트
python bots\analytics_bot.py weekly # 주간 리포트
python bots\image_bot.py batch      # 이미지 프롬프트 배치 전송

# 변환 엔진
python bots\converters\blog_converter.py
python bots\converters\card_converter.py
python bots\converters\shorts_converter.py
```

---

## 봇 상세 설명

### `collector_bot.py` — 트렌드 수집봇

Google Trends (PyTrends) + RSS 피드 (`config/sources.json`)에서 글감을 수집하고 품질 점수를 계산합니다.

**품질 점수 (0–100):**
- 트렌드 강도, 경쟁 기사 수, 키워드 밀도 반영
- **70점 미만 자동 폐기**
- 75점 미만 또는 위험 키워드 감지 시 Telegram 수동 검토 요청

**출력:** `data/collected/{date}_{slug}.json`

### `publisher_bot.py` — 발행봇

- HTML 본문 감지: AI가 HTML을 직접 출력한 경우 변환 없이 Blogger에 발행
- Schema.org `Article` JSON-LD 삽입
- Google Search Console URL 즉시 색인 요청
- 하루 최대 발행 수 제한, 중복 발행 방지

### `linker_bot.py` — 쿠팡 파트너스 링크봇

`config/affiliate_links.json`의 키워드를 HTML 본문에서 찾아 파트너스 링크로 자동 교체.
같은 키워드는 최대 2회까지만 처리합니다.

### `analytics_bot.py` — 분석봇

- Google Analytics Data API v1 (GA4) + Search Console API
- 매일 22:00 수집 → Telegram 일간 리포트
- 매주 일요일 22:30 주간 종합 리포트

### `image_bot.py` — 이미지봇

| 모드 | 동작 |
|------|------|
| `manual` | 발행 시 DALL-E 프롬프트를 Telegram 전송. 직접 생성 후 저장. |
| `request` | 매주 월요일 프롬프트 목록 전송. 일괄 생성 후 개별 전송. |
| `auto` | DALL-E 3 API 자동 생성. `OPENAI_API_KEY` 필요, 비용 발생. |

### `article_parser.py` — 원고 파서

OpenClaw AI가 출력하는 구조화된 원고를 파싱합니다:

```
---TITLE---        글 제목
---META---         검색 설명 150자
---SLUG---         URL 슬러그
---TAGS---         태그 목록
---CORNER---       코너명
---BODY---         Blogger-ready HTML 본문
---KEY_POINTS---   핵심 3줄 (각 30자 이내, SNS/TTS용)
---COUPANG_KEYWORDS--- 쿠팡 검색 키워드
---SOURCES---      출처 URL 목록
---DISCLAIMER---   면책 문구
```

### `remote_claude.py` — Claude Agent SDK 연동

Telegram 자연어 명령을 Claude Agent SDK로 처리합니다.
코드 생성·수정·실행까지 가능한 자율 에이전트 인터페이스입니다.

---

## 변환 엔진 (LAYER 2)

### `blog_converter.py`

```
입력: article dict (body = HTML 또는 Markdown)
출력: data/outputs/{date}_{slug}_blog.html
```

- **HTML 자동 감지**: AI가 HTML을 직접 출력한 경우 마크다운 변환을 건너뜀
- Schema.org `Article` JSON-LD 삽입
- AdSense 플레이스홀더 삽입 (2번째 H2 뒤, 결론 H2 앞)
- 쿠팡 파트너스 링크봇 호출

### `card_converter.py`

```
입력: article dict
출력: data/outputs/{date}_{slug}_card.png (1080×1080)
```

Pillow로 인스타그램 카드 이미지를 생성합니다:

```
┌─────────────────────────┐
│ ████ 금색 상단 바        │
│                         │
│  [코너 배지]             │
│                         │
│  글 제목                 │
│                         │
│  • 핵심 포인트 1         │
│  • 핵심 포인트 2         │
│  • 핵심 포인트 3         │
│                         │
│ ████ 금색 하단 바 (URL)  │
└─────────────────────────┘
```

코너별 배지 색상: 쉬운세상=파랑, 숨은보물=초록, 바이브리포트=보라, 팩트체크=빨강, 한컷=노랑

### `thread_converter.py`

```
입력: article dict
출력: data/outputs/{date}_{slug}_thread.json
```

- Tweet 1: 제목 + 코너 해시태그
- Tweet 2–4: 번호 매긴 핵심 포인트
- 마지막 Tweet: 블로그 URL + CTA

### `newsletter_converter.py`

```python
generate_weekly(articles: list[dict], urls: list[str] = None) -> str
```

주간 기사 목록으로 HTML 뉴스레터를 생성합니다.
**출력:** `data/outputs/weekly_{date}_newsletter.html`

### `shorts_converter.py`

뉴스 앵커 형식의 세로형 쇼츠 영상을 생성합니다 (1080×1920, 30fps).

**파이프라인:**

```
1. DALL-E 3 배경 이미지 생성 (옵션, 없으면 단색)
         ↓
2. Pillow 슬라이드 합성
   인트로 → 헤드라인 → 포인트1 → 포인트2 → 포인트3 → 데이터(선택) → 아웃트로
         ↓
3. Google Cloud TTS (ko-KR-Wavenet-A) → gTTS 폴백
         ↓
4. ffmpeg zoompan — Ken Burns 효과로 슬라이드별 MP4 클립 생성
         ↓
5. ffmpeg xfade — 코너별 트랜지션으로 클립 연결
         ↓
6. BGM 믹싱 (assets/bgm.mp3, 볼륨 8%)
         ↓
7. SRT 자막 burn-in (흰 텍스트 + 반투명 검정 박스)
         ↓
출력: data/outputs/{date}_{slug}_shorts.mp4
```

**코너별 설정** (`templates/shorts_template.json`):

| 코너 | 색상 | TTS 속도 | 트랜지션 | 특이사항 |
|------|------|----------|---------|---------|
| 쉬운세상 | 보라 `#7c3aed` | 1.0x | fade | — |
| 숨은보물 | 블루 `#1d6fb0` | 1.05x | slideleft | — |
| 바이브리포트 | 코럴 `#d85a30` | 1.1x | slideleft | — |
| 팩트체크 | 레드 `#bf3a3a` | 1.0x | fade | 데이터 카드 강제 |
| 한컷 | 골드 `#8a7a2e` | 1.0x | fade | 최대 20초 |

---

## 배포 엔진 (LAYER 3)

### `image_host.py`

Instagram API는 공개 URL 이미지만 허용하므로 로컬 파일을 업로드합니다:
- **ImgBB API** (기본): 무료 이미지 호스팅, `IMGBB_API_KEY` 필요
- **로컬 HTTP 서버**: 개발/테스트용, `LOCAL_IMAGE_SERVER=true`

### `instagram_bot.py`

Instagram Graph API v19.0 흐름:
1. `POST /media` — 미디어 컨테이너 생성
2. `GET /media/{id}` — `FINISHED` 상태까지 폴링 (최대 2분)
3. `POST /media_publish` — 컨테이너 발행

### `x_bot.py`

X API v2 + OAuth1 (`requests_oauthlib`):
- 이전 트윗 ID를 `reply_to_id`로 넘겨 스레드 구성
- 각 트윗 사이 1초 딜레이로 순서 보장

### `tiktok_bot.py`

TikTok Content Posting API v2 (Direct Post):
1. `POST /v2/post/publish/video/init/` — 업로드 URL + `publish_id` 수령
2. 청크 업로드
3. `POST /v2/post/publish/status/fetch/` — 발행 완료 폴링

### `youtube_bot.py`

YouTube Data API v3:
- 기존 `token.json` Google OAuth 재사용 (별도 인증 불필요)
- 제목 끝에 `#Shorts` 자동 추가
- `google-resumable-media`로 대용량 파일 청크 업로드

---

## 콘텐츠 코너

| 코너 | 성격 | 글 길이 | 안전장치 |
|------|------|---------|---------|
| **쉬운세상** | 복잡한 이슈를 쉽게 해설 | 1,500–2,000자 | 자동 발행 |
| **숨은보물** | 유용하지만 덜 알려진 정보 | 1,500–2,000자 | 자동 발행 |
| **바이브리포트** | 트렌드·문화 분석 | 1,500–2,500자 | 자동 발행 |
| **팩트체크** | [사실]/[의견]/[추정] 명시 검증 | 2,000–2,500자 | **수동 승인 필수** |
| **한컷** | 시사 만평 + 짧은 코멘트 | 300–500자 | 자동 발행 |

**자동 발행 차단 조건 (Telegram 수동 검토):**
- 팩트체크 코너 전체
- 암호화폐/투자/법률 위험 키워드 감지
- 출처 2개 미만
- 품질 점수 75점 미만

---

## Telegram 명령어

스케줄러 실행 중 Telegram 봇에 명령을 보낼 수 있습니다.

### 슬래시 명령

| 명령 | 설명 |
|------|------|
| `/start` | 봇 소개 |
| `/status` | 스케줄러 상태 + 오늘 발행 수 |
| `/collect` | 즉시 트렌드 수집 |
| `/publish` | 즉시 블로그 발행 |
| `/convert` | 즉시 변환 파이프라인 실행 |
| `/report` | 즉시 분석 리포트 |
| `/pause` | 자동 스케줄 일시 중지 |
| `/resume` | 자동 스케줄 재개 |
| `/approve [번호]` | 수동 검토 글 승인 후 발행 |
| `/reject [번호]` | 수동 검토 글 거부 |
| `/images` | 이미지 제작 현황 |
| `/imgbatch` | 이미지 프롬프트 배치 전송 |
| `/help` | 명령어 목록 |

### 자연어 명령 (`ANTHROPIC_API_KEY` 설정 시)

```
"오늘 발행된 글 목록 보여줘"
"쇼츠 변환 다시 실행해줘"
"이번 주 조회수 상위 3개 알려줘"
```

---

## OpenClaw AI 에이전트 연동

이 프로젝트는 [OpenClaw](https://openclaw.ai) AI 에이전트와 함께 사용하도록 설계되었습니다.

**에이전트 설정 파일 위치:**

```
~/.openclaw/agents/blog-writer/SOUL.md
    역할, 글쓰기 원칙, Blogger-ready HTML 출력 조건

~/.openclaw/workspace-blog-writer/templates/output_format.md
    원고 출력 포맷 (섹션 구조 정의)
```

**AI 원고 출력 포맷** (`output_format.md` 기반):

```
---TITLE---      제목 (SEO 키워드 포함, 클릭베이트 없음)
---META---       검색 설명 150자 이내
---SLUG---       URL 슬러그 (영문 소문자, 하이픈)
---TAGS---       태그 쉼표 구분
---CORNER---     코너명
---BODY---       Blogger-ready HTML 본문 (마크다운 금지)
---KEY_POINTS--- 핵심 3줄 (각 30자 이내, SNS/TTS용)
---COUPANG_KEYWORDS--- 쿠팡 검색 키워드
---SOURCES---    출처 URL 목록
---DISCLAIMER--- 면책 문구 (팩트체크 필수)
```

**HTML 본문 필수 구성요소:**
- `<style>` 블록 맨 앞 (`.post-title` 숨김 포함)
- eyebrow 배지 · h1 제목 + 부제 · 메타 정보
- 섹션 트래커 (소문자 영문 앵커) · h3 소제목
- pull quote · 데이터 카드/그리드 · balance-box (반론)
- 출처 cite · 클로징 박스 · 태그 목록
- 저자: `22B Labs · The 4th Path`

OpenClaw 없이도 동작합니다 — 위 포맷에 맞춰 `data/originals/`에 파일을 직접 넣으면 파이프라인이 실행됩니다.

---

## 배포 스케줄

스케줄러 실행 시 매일 자동으로 실행됩니다 (`config/schedule.json`에서 시간 변경 가능):

| 시간 | 작업 |
|------|------|
| 07:00 | 트렌드 수집 (collector_bot) |
| 08:00 | AI 글 작성 트리거 (OpenClaw) |
| 08:30 | 변환 파이프라인 (5개 포맷 동시 생성) |
| 09:00 | 블로그 발행 (Blogger) |
| 10:00 | 인스타그램 카드 게시 |
| 11:00 | X 스레드 게시 |
| 18:00 | TikTok 쇼츠 업로드 |
| 20:00 | YouTube 쇼츠 업로드 |
| 22:00 | 일간 분석 리포트 (Telegram) |
| 일요일 22:30 | 주간 뉴스레터 + 종합 리포트 |

---

## Phase 현황

### Phase 1A — 완료 ✅
모든 핵심 봇 구현 완료. 블로그 자동 수집→작성→발행 파이프라인 작동.

### Phase 1B — 코드 완료 ✅, API 키 설정 필요 ⚙️
- [ ] `IMGBB_API_KEY` 발급 ([api.imgbb.com](https://api.imgbb.com/))
- [ ] Facebook Developer App에서 `INSTAGRAM_ACCESS_TOKEN` / `INSTAGRAM_ACCOUNT_ID` 발급
- [ ] X Developer Portal에서 API 키 4종 발급

### Phase 2 — 코드 완료 ✅, 환경 설정 필요 ⚙️
- [ ] `ffmpeg` 설치 및 PATH 등록
- [ ] `GOOGLE_TTS_API_KEY` 발급 (또는 `gTTS` 무료 사용)
- [ ] `TIKTOK_ACCESS_TOKEN` / `YOUTUBE_CHANNEL_ID` 발급

---

## 자주 묻는 질문

**Q. OpenClaw 없이도 사용할 수 있나요?**
A. 봇 레이어(수집/변환/발행/분석)는 완전히 독립적으로 동작합니다. `data/originals/`에 지정된 포맷으로 원고 파일을 직접 넣으면 파이프라인이 실행됩니다. 다른 AI(GPT API, Gemini 등)로 글을 생성한 후 넣어도 됩니다.

**Q. TTS 없이 쇼츠를 만들 수 있나요?**
A. `GOOGLE_TTS_API_KEY` 없이도 `gTTS`(무료)로 폴백됩니다. 품질은 낮지만 비용 없이 동작합니다. `requirements.txt`에 `gTTS`가 포함되어 있습니다.

**Q. DALL-E 없이 쇼츠를 만들 수 있나요?**
A. `OPENAI_API_KEY`가 없으면 코너 색상 단색 배경으로 대체됩니다. 별도 조치 없이 자동으로 폴백됩니다.

**Q. Blogger 외 다른 플랫폼을 사용할 수 있나요?**
A. `publisher_bot.py`의 `publish_to_blogger()` 함수를 교체하면 WordPress REST API, 티스토리 등으로 변경 가능합니다.

**Q. Windows가 아닌 환경에서 사용하려면?**
A. `setup.bat` 대신 수동으로 venv 생성 후 패키지 설치, `scheduler.py`는 크로스 플랫폼 동작합니다. Windows 작업 스케줄러 등록 부분만 Linux cron 또는 macOS launchd로 대체하세요.

**Q. 수집봇이 글감을 못 가져와요.**
A. `config/sources.json`의 RSS URL 유효성을 확인하세요. Google Trends는 요청 제한이 걸릴 수 있습니다 — `logs/collector.log`에서 상세 오류를 확인하세요.

---

## 기여 가이드

PR과 이슈를 환영합니다.

### 로컬 개발 환경

```bash
git clone https://github.com/sinmb79/blog-writer.git
cd blog-writer
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # 값 채우기
python scripts/download_fonts.py
```

### 브랜치 규칙

```
master      — 안정 버전
feature/*   — 새 기능
fix/*       — 버그 수정
```

### 코드 스타일

- Python 3.10+, 타입 힌트 권장
- 모듈별 `logger = logging.getLogger(__name__)` 사용
- 환경 변수는 반드시 `.env`에서만 (`python-dotenv`)
- **비밀값 하드코딩 절대 금지**

### 보안 주의사항

- `.env`, `token.json`, `credentials.json`은 `.gitignore`에 포함 — 절대 커밋하지 마세요
- PR 전 `git diff --staged`로 비밀값이 포함되지 않았는지 반드시 확인하세요

---

## 라이선스

MIT License — 자유롭게 사용·수정·배포 가능합니다.
상업적 이용 시 브랜드명 "The 4th Path"와 "22B Labs"는 제거해 주세요.

---

<p align="center">
  <strong>The 4th Path</strong> · Independent Tech Media<br>
  by <a href="https://github.com/sinmb79">22B Labs</a>
</p>
