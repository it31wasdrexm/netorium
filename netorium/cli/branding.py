from __future__ import annotations

from rich.align import Align
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

LOGO_LINES: tuple[str, ...] = (
    " _   _      _             _",
    r"| \ | | ___| |_ ___ _ __ (_) ___  _ __",
    "|  \\| |/ _ \\ __/ _ \\ '_ \\| |/ _ \\| '_ \\",
    "|  \\| |  __/ ||  __/ | | | | (_) | | | |",
    r"|_| \_|\___|\__\___|_| |_|_|\___/|_| |_|",
)

TAGLINE = "Network access control CLI"
ACCENT_STYLE = Style(color="cyan", bold=True)
MUTED_STYLE = Style(color="bright_black")
TAGLINE_STYLE = Style(color="bright_cyan")


def logo_text(*, style: Style | str = ACCENT_STYLE) -> Text:
    text = Text()
    for index, line in enumerate(LOGO_LINES):
        if index:
            text.append("\n")
        text.append(line, style=style)
    return text


def render_logo_panel(
    *,
    subtitle: str | None = None,
    border_style: str = "cyan",
    expand: bool = False,
) -> Panel:
    body = Table.grid(padding=(0, 0))
    body.add_row(logo_text())
    body.add_row(Text(TAGLINE, style=TAGLINE_STYLE))
    if subtitle:
        body.add_row(Text(subtitle, style=MUTED_STYLE))
    return Panel(
        Align.center(body),
        border_style=border_style,
        expand=expand,
        padding=(1, 2),
    )


def render_info_panel(
    title: str,
    rows: tuple[tuple[str, str], ...],
    *,
    border_style: str = "cyan",
    key_style: str = "bright_cyan",
    expand: bool = False,
) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=key_style, justify="right")
    table.add_column()
    for key, value in rows:
        table.add_row(key, value)
    return Panel(
        table,
        title=title,
        border_style=border_style,
        expand=expand,
        padding=(0, 1),
    )


def render_notice_panel(
    title: str,
    body: RenderableType,
    *,
    border_style: str = "yellow",
    expand: bool = False,
) -> Panel:
    return Panel(
        body,
        title=title,
        border_style=border_style,
        expand=expand,
        padding=(0, 1),
    )


def print_logo(console: Console, *, subtitle: str | None = None) -> None:
    console.print(render_logo_panel(subtitle=subtitle))
