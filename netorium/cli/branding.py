from __future__ import annotations

from dataclasses import dataclass

from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.rule import Rule
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

LOGO_LINE_STYLES: tuple[str, ...] = (
    "bold bright_blue",
    "bold cyan",
    "bold bright_cyan",
    "bold bright_cyan",
    "bold white",
)

TAGLINE = "Building-level network access control"
ACCENT_STYLE = Style(color="bright_cyan", bold=True)
MUTED_STYLE = Style(color="bright_black")
TAGLINE_STYLE = Style(color="cyan", italic=True)
PROMPT_STYLE = Style(color="bright_cyan", bold=True)
PANEL_BORDER = "bright_cyan"
PANEL_BORDER_MUTED = "bright_black"
TABLE_HEADER_STYLE = "bold bright_cyan"
TABLE_BORDER_STYLE = "bright_black"
SECTION_STYLE = "bold white"
DIVIDER_STYLE = "bright_black"


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    name: str
    justify: str = "left"


def logo_text(*, gradient: bool = True) -> Text:
    text = Text()
    for index, line in enumerate(LOGO_LINES):
        if index:
            text.append("\n")
        style = LOGO_LINE_STYLES[index] if gradient else "bright_cyan"
        text.append(line, style=style)
    return text


def render_logo_panel(
    *,
    subtitle: str | None = None,
    border_style: str = PANEL_BORDER,
    expand: bool = False,
    compact: bool = False,
) -> Panel:
    body = Table.grid(padding=(0, 1))
    body.add_row(Align.center(logo_text()))
    body.add_row(Align.center(Text(TAGLINE, style=TAGLINE_STYLE)))
    if subtitle:
        body.add_row(Align.center(Text(subtitle, style=MUTED_STYLE)))
    padding = (0, 2) if compact else (1, 4)
    return Panel(
        body,
        box=ROUNDED,
        border_style=border_style,
        expand=expand,
        padding=padding,
    )


def render_info_panel(
    title: str,
    rows: tuple[tuple[str, str], ...],
    *,
    border_style: str = PANEL_BORDER,
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


def render_status_badges(
    *,
    version: str,
    platform_name: str,
    config_path: str,
) -> Panel:
    badges = Table.grid(expand=True, padding=(0, 4))
    badges.add_column(justify="center", ratio=1)
    badges.add_column(justify="center", ratio=1)
    badges.add_column(justify="center", ratio=1)
    badges.add_row(
        _badge("Version", version, accent="bright_green"),
        _badge("Platform", platform_name, accent="cyan"),
        _badge("Config", config_path, accent="bright_black"),
    )
    return Panel(
        badges,
        box=ROUNDED,
        border_style=PANEL_BORDER_MUTED,
        padding=(0, 2),
    )


def _badge(label: str, value: str, *, accent: str) -> Text:
    return Text.assemble(
        (label.upper(), "dim bright_black"),
        ("\n", ""),
        (value, f"bold {accent}"),
    )


def render_welcome_hint() -> Text:
    return Text.assemble(
        ("Type ", MUTED_STYLE),
        ("help", PROMPT_STYLE),
        (" for commands  ·  ", MUTED_STYLE),
        ("exit", PROMPT_STYLE),
        (" to leave", MUTED_STYLE),
    )


def render_farewell() -> Panel:
    return Panel(
        Align.center(Text("Goodbye — see you next time.", style="cyan italic")),
        box=ROUNDED,
        border_style=PANEL_BORDER_MUTED,
        padding=(0, 2),
    )


def render_version_panel(version: str, *, title: str = "Netorium") -> Panel:
    body = Table.grid(padding=(0, 2))
    body.add_column(style="cyan", justify="right")
    body.add_column()
    body.add_row("Release", Text(version, style="bold bright_green"))
    return Panel(
        body,
        title=f"[bold]{title}[/]",
        box=ROUNDED,
        border_style=PANEL_BORDER,
        padding=(0, 1),
    )


def make_table(
    title: str,
    *,
    columns: tuple[str | ColumnSpec, ...],
    border_style: str = TABLE_BORDER_STYLE,
) -> Table:
    table = Table(
        title=title,
        box=ROUNDED,
        show_header=True,
        header_style=TABLE_HEADER_STYLE,
        border_style=border_style,
        title_style="bold",
        pad_edge=False,
        show_lines=False,
    )
    for column in columns:
        if isinstance(column, ColumnSpec):
            table.add_column(column.name, justify=column.justify)
        else:
            table.add_column(column)
    return table


def make_kv_table(title: str, *, border_style: str = TABLE_BORDER_STYLE) -> Table:
    return make_table(title, columns=("Field", "Value"), border_style=border_style)


def status_icon(ok: bool) -> str:
    return "[bold bright_green]✓[/]" if ok else "[bold yellow]![/]"


def render_divider(*, title: str | None = None) -> Rule:
    return Rule(title=title, style=DIVIDER_STYLE, characters="─")


def read_prompt(console: Console) -> str:
    return console.input("[bold bright_cyan]netorium[/] [bright_black]›[/] ")


def print_logo(console: Console, *, subtitle: str | None = None) -> None:
    console.print(render_logo_panel(subtitle=subtitle))
