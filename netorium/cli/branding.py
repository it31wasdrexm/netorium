from __future__ import annotations

from rich.align import Align
from rich.box import ROUNDED, SIMPLE
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

LOGO_LINES: tuple[str, ...] = (
    " _   _      _             _",
    r"| \ | | ___| |_ ___ _ __ (_) ___  _ __",
    r"|  \| |/ _ \ __/ _ \ '_ \| |/ _ \| '_ \\",
    r"|  \| |  __/ ||  __/ | | | | (_) | | | |",
    r"|_| \_|\___|\__\___|_| |_|_|\___/|_| |_|",
)

TAGLINE = "Building-level network access control"
ACCENT_STYLE = Style(color="bright_cyan", bold=True)
MUTED_STYLE = Style(color="bright_black")
TAGLINE_STYLE = Style(color="cyan")
PROMPT_STYLE = Style(color="bright_cyan", bold=True)

COMMAND_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Essentials",
        ("help", "version", "doctor", "uninstall"),
    ),
    (
        "Controller",
        ("controller init", "controller start", "controller status", "policy site all youtube.com"),
    ),
    (
        "Monitoring",
        ("report traffic", "report anomalies", "telegram start"),
    ),
    (
        "Inventory",
        ("zone list", "device list", "firewall status"),
    ),
)


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
    border_style: str = "bright_cyan",
    expand: bool = False,
) -> Panel:
    body = Table.grid(padding=(0, 1))
    body.add_row(Align.center(logo_text()))
    body.add_row(Align.center(Text(TAGLINE, style=TAGLINE_STYLE)))
    if subtitle:
        body.add_row(Align.center(Text(subtitle, style=MUTED_STYLE)))
    return Panel(
        body,
        box=ROUNDED,
        border_style=border_style,
        expand=expand,
        padding=(1, 3),
    )


def render_info_panel(
    title: str,
    rows: tuple[tuple[str, str], ...],
    *,
    border_style: str = "bright_cyan",
    key_style: str = "cyan",
    expand: bool = False,
) -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=key_style, justify="right", no_wrap=True)
    table.add_column(ratio=1)
    for key, value in rows:
        table.add_row(key, value)
    return Panel(
        table,
        title=f"[bold]{title}[/]",
        box=ROUNDED,
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
        title=f"[bold]{title}[/]",
        box=ROUNDED,
        border_style=border_style,
        expand=expand,
        padding=(0, 1),
    )


def render_quickstart_panel() -> Panel:
    table = Table(box=SIMPLE, show_header=True, header_style="bold cyan", pad_edge=False)
    table.add_column("Group", style="bright_black", no_wrap=True)
    table.add_column("Example command")
    for group_name, examples in COMMAND_GROUPS:
        for index, example in enumerate(examples):
            table.add_row(group_name if index == 0 else "", Text(example, style="white"))
    return Panel(
        table,
        title="[bold]Quick commands[/]",
        box=ROUNDED,
        border_style="bright_black",
        padding=(0, 1),
    )


def render_status_line(
    *,
    version: str,
    platform_name: str,
    config_path: str,
) -> Text:
    return Text.assemble(
        (" netorium ", "bold white on bright_cyan"),
        (" v", "bright_black"),
        (version, "bold"),
        ("  ", ""),
        (platform_name, "cyan"),
        ("  ", ""),
        (config_path, "bright_black"),
    )


def print_logo(console: Console, *, subtitle: str | None = None) -> None:
    console.print(render_logo_panel(subtitle=subtitle))
