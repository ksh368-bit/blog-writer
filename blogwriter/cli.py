"""
blogwriter/cli.py
Blog Writer MVP CLI - 8 commands

Usage:
    bw                      # Interactive menu
    bw write [TOPIC]        # Write a blog post
    bw shorts               # Create a shorts video
    bw publish              # Publish pending articles
    bw distribute           # Distribute to SNS platforms
    bw status               # Show system status
    bw doctor               # Check API keys and dependencies
    bw config show          # Show resolved configuration
    bw init                 # Setup wizard (implemented in PR 10)
"""
import json
import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

BASE_DIR = Path(__file__).parent.parent
console = Console()
logger = logging.getLogger(__name__)


def _load_resolved_config() -> dict:
    """Load resolved config from ConfigResolver."""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from bots.config_resolver import ConfigResolver
        return ConfigResolver().resolve()
    except Exception as e:
        return {'error': str(e), 'budget': 'free', 'level': 'beginner'}


@click.group(invoke_without_command=True)
@click.pass_context
def app(ctx):
    """Blog Writer - AI 콘텐츠 자동화 도구 (v3.0)"""
    if ctx.invoked_subcommand is None:
        _interactive_menu()


def _interactive_menu():
    """Display interactive menu when no subcommand given."""
    console.print("\n[bold cyan]Blog Writer v3.0[/bold cyan] - AI 콘텐츠 자동화\n")
    console.print("사용 가능한 명령어:")
    commands = [
        ("  bw init",       "설정 마법사 - 처음 설정 시 실행"),
        ("  bw write",      "블로그 글 작성"),
        ("  bw shorts",     "쇼츠 영상 생성"),
        ("  bw publish",    "대기 중인 글 발행"),
        ("  bw distribute", "SNS 플랫폼에 배포"),
        ("  bw status",     "시스템 상태 확인"),
        ("  bw doctor",     "API 키 및 의존성 점검"),
        ("  bw config show","현재 설정 보기"),
    ]
    for cmd, desc in commands:
        console.print(f"[green]{cmd:<20}[/green] {desc}")
    console.print()


@app.command()
@click.argument('topic', required=False)
@click.option('--publish', '-p', is_flag=True, help='작성 후 즉시 발행')
@click.option('--shorts', '-s', is_flag=True, help='쇼츠 영상도 생성')
@click.option('--dry-run', is_flag=True, help='실제 API 호출 없이 테스트')
def write(topic, publish, shorts, dry_run):
    """블로그 글 작성."""
    cfg = _load_resolved_config()

    if dry_run:
        console.print("[yellow]Dry run 모드[/yellow] - API 호출 없이 실행")

    if not topic:
        topic = click.prompt('주제를 입력하세요')

    console.print(f"\n[bold]블로그 글 작성 시작[/bold]")
    console.print(f"주제: {topic}")
    console.print(f"글쓰기 엔진: [cyan]{cfg.get('writing', 'auto')}[/cyan]")

    if dry_run:
        console.print("[yellow]Dry run 완료 (실제 작성 없음)[/yellow]")
        return

    try:
        sys.path.insert(0, str(BASE_DIR))
        from bots.writer_bot import WriterBot
        bot = WriterBot()
        result = bot.write(topic)
        if result:
            console.print(f"[green]✓ 작성 완료[/green]: {result.get('title', topic)}")
            if publish:
                ctx = click.get_current_context()
                ctx.invoke(publish_cmd)
            if shorts:
                ctx = click.get_current_context()
                ctx.invoke(shorts_cmd)
        else:
            console.print("[red]✗ 작성 실패[/red]")
    except ImportError:
        console.print("[red]writer_bot 로드 실패 - bots/ 경로 확인[/red]")
    except Exception as e:
        console.print(f"[red]오류: {e}[/red]")


@app.command()
@click.option('--slug', help='특정 글 slug 지정')
@click.option('--text', '-t', help='직접 텍스트 입력 (글 없이 쇼츠 생성)')
@click.option('--dry-run', is_flag=True, help='실제 렌더링 없이 테스트')
def shorts(slug, text, dry_run):
    """쇼츠 영상 생성."""
    cfg = _load_resolved_config()

    console.print(f"\n[bold]쇼츠 영상 생성[/bold]")
    console.print(f"비디오 엔진: [cyan]{cfg.get('video', 'ffmpeg_slides')}[/cyan]")
    console.print(f"TTS 엔진: [cyan]{cfg.get('tts', 'edge_tts')}[/cyan]")

    if dry_run:
        console.print("[yellow]Dry run 모드 - 렌더링 없이 설정 확인 완료[/yellow]")
        return

    try:
        sys.path.insert(0, str(BASE_DIR))
        from bots.shorts_bot import ShortsBot
        bot = ShortsBot()
        if text:
            result = bot.create_from_text(text)
        elif slug:
            result = bot.create_from_slug(slug)
        else:
            result = bot.create_latest()

        if result:
            console.print(f"[green]✓ 쇼츠 생성 완료[/green]: {result}")
        else:
            console.print("[red]✗ 쇼츠 생성 실패[/red]")
    except ImportError:
        console.print("[red]shorts_bot 로드 실패 - bots/ 경로 확인[/red]")
    except Exception as e:
        console.print(f"[red]오류: {e}[/red]")


@app.command('publish')
def publish_cmd():
    """대기 중인 글 발행."""
    console.print("\n[bold]발행 시작[/bold]")
    try:
        sys.path.insert(0, str(BASE_DIR))
        from bots.publisher_bot import PublisherBot
        bot = PublisherBot()
        result = bot.publish_pending()
        console.print(f"[green]✓ 발행 완료[/green]: {result} 건")
    except ImportError:
        console.print("[red]publisher_bot 로드 실패[/red]")
    except Exception as e:
        console.print(f"[red]오류: {e}[/red]")


@app.command()
@click.option('--to', help='특정 플랫폼으로만 배포 (예: youtube,tiktok)')
def distribute(to):
    """SNS 플랫폼에 콘텐츠 배포."""
    platforms = to.split(',') if to else None
    console.print(f"\n[bold]배포 시작[/bold]")
    if platforms:
        console.print(f"대상: {', '.join(platforms)}")

    try:
        sys.path.insert(0, str(BASE_DIR))
        # Use scheduler or direct bot calls
        console.print("[yellow]배포 기능은 현재 개발 중입니다[/yellow]")
    except Exception as e:
        console.print(f"[red]오류: {e}[/red]")


@app.command()
def status():
    """시스템 상태 확인 (대시보드 서버 없이 동작)."""
    console.print("\n[bold]시스템 상태[/bold]\n")

    cfg = _load_resolved_config()

    # Config table
    table = Table(title="설정 현황", show_header=True)
    table.add_column("항목", style="cyan")
    table.add_column("값", style="green")

    table.add_row("예산", cfg.get('budget', 'N/A'))
    table.add_row("레벨", cfg.get('level', 'N/A'))
    table.add_row("글쓰기 엔진", str(cfg.get('writing', 'N/A')))
    table.add_row("TTS 엔진", str(cfg.get('tts', 'N/A')))
    table.add_row("비디오 엔진", str(cfg.get('video', 'N/A')))
    table.add_row("플랫폼", ', '.join(cfg.get('platforms', [])))
    console.print(table)

    # Check data dirs
    data_dirs = ['data/shorts', 'data/outputs', 'logs']
    console.print("\n[bold]데이터 디렉터리[/bold]")
    for d in data_dirs:
        path = BASE_DIR / d
        exists = "✓" if path.exists() else "✗"
        count = len(list(path.glob('*'))) if path.exists() else 0
        console.print(f"  {exists} {d}: {count}개 파일")

    # Prompt tracker stats
    try:
        from bots.prompt_layer.prompt_tracker import PromptTracker
        tracker = PromptTracker()
        stats = tracker.get_stats()
        if stats.get('total', 0) > 0:
            console.print(f"\n[bold]프롬프트 로그[/bold]: {stats['total']}건 기록됨")
    except Exception:
        pass


@app.command()
def doctor():
    """API 키 및 의존성 점검."""
    console.print("\n[bold]시스템 점검[/bold]\n")

    # Check API keys
    api_keys = {
        'OPENAI_API_KEY': 'OpenAI (GPT + TTS)',
        'ANTHROPIC_API_KEY': 'Anthropic (Claude)',
        'GEMINI_API_KEY': 'Google Gemini / Veo',
        'ELEVENLABS_API_KEY': 'ElevenLabs TTS',
        'KLING_API_KEY': 'Kling AI 영상',
        'FAL_API_KEY': 'Seedance 2.0 영상',
        'RUNWAY_API_KEY': 'Runway 영상',
        'YOUTUBE_CHANNEL_ID': 'YouTube 채널',
    }

    table = Table(title="API 키 상태", show_header=True)
    table.add_column("서비스", style="cyan")
    table.add_column("상태", style="bold")
    table.add_column("설명")

    for key, desc in api_keys.items():
        value = os.environ.get(key, '')
        if value:
            status_str = "[green]✓ 설정됨[/green]"
        else:
            status_str = "[red]✗ 미설정[/red]"
        table.add_row(desc, status_str, key)

    console.print(table)

    # Check Python dependencies
    console.print("\n[bold]의존성 점검[/bold]")
    deps = ['click', 'rich', 'edge_tts', 'requests', 'Pillow', 'dotenv']
    for dep in deps:
        try:
            import importlib
            importlib.import_module(dep.replace('-', '_').lower().replace('pillow', 'PIL'))
            console.print(f"  [green]✓[/green] {dep}")
        except ImportError:
            console.print(f"  [red]✗[/red] {dep} - pip install {dep}")

    # Check FFmpeg
    import subprocess
    try:
        r = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
        if r.returncode == 0:
            console.print(f"  [green]✓[/green] FFmpeg")
        else:
            console.print(f"  [red]✗[/red] FFmpeg - PATH 확인 필요")
    except Exception:
        console.print(f"  [red]✗[/red] FFmpeg - 설치 필요")


@app.group()
def config():
    """설정 관리."""
    pass


@config.command('show')
def config_show():
    """현재 해석된 설정 출력."""
    cfg = _load_resolved_config()

    if 'error' in cfg:
        console.print(f"[red]설정 로드 오류: {cfg['error']}[/red]")
        return

    console.print("\n[bold]현재 설정 (ConfigResolver 기준)[/bold]\n")

    table = Table(show_header=True)
    table.add_column("항목", style="cyan")
    table.add_column("값", style="green")

    for key, value in cfg.items():
        if isinstance(value, list):
            value = ', '.join(str(v) for v in value)
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        table.add_row(key, str(value))

    console.print(table)


@app.command()
def init():
    """설정 마법사 - 처음 설치 시 실행."""
    console.print("\n[bold cyan]Blog Writer 설정 마법사[/bold cyan]")
    console.print("PR 10에서 구현 예정입니다.\n")
    console.print("현재는 config/user_profile.json을 직접 편집하세요.")
    console.print(f"위치: {BASE_DIR / 'config' / 'user_profile.json'}")


# Entry point
def main():
    """Main entry point."""
    app()


if __name__ == '__main__':
    main()
