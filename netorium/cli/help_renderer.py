from __future__ import annotations

from collections import defaultdict
from typing import Any

import click
from rich.align import Align
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from typer.core import TyperGroup
from typer.models import DefaultPlaceholder

from netorium.cli.branding import (
    MUTED_STYLE,
    PANEL_BORDER,
    PANEL_BORDER_MUTED,
    PROMPT_STYLE,
    SECTION_STYLE,
    render_logo_panel,
)

_ORIGINAL_FORMAT_HELP = TyperGroup.format_help
_INSTALLED = False


def install_help_renderer() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    TyperGroup.format_help = _netorium_format_help  # type: ignore[method-assign]
    _INSTALLED = True


def _netorium_format_help(
    self: TyperGroup,
    ctx: click.Context,
    formatter: click.HelpFormatter,
) -> None:
    console = Console()
    console.print(_render_help(self, ctx))
    console.print()


def _panel_name(command: click.Command) -> str | None:
    panel = getattr(command, "rich_help_panel", None)
    if panel is None or isinstance(panel, DefaultPlaceholder):
        return None
    return str(panel)


def _first_help_line(command: click.Command) -> str:
    help_text = command.help or command.short_help or ""
    return help_text.split("\n", 1)[0].strip()


def _visible_commands(group: TyperGroup) -> list[tuple[str, click.Command]]:
    return [
        (name, command)
        for name, command in group.commands.items()
        if not getattr(command, "hidden", False)
    ]


def _render_help(command: click.Command, ctx: click.Context) -> Group:
    parts: list[Any] = []
    is_root = ctx.parent is None

    if is_root and isinstance(command, TyperGroup):
        parts.append(render_logo_panel(compact=True, border_style=PANEL_BORDER))
        parts.append(Text(""))
        description = _first_help_line(command)
        if description:
            parts.append(
                Panel(
                    Text(description, style="bright_black"),
                    box=ROUNDED,
                    border_style=PANEL_BORDER_MUTED,
                    padding=(0, 2),
                )
            )
            parts.append(Text(""))
    else:
        parts.append(_render_command_header(command, ctx.command_path))

    if isinstance(command, TyperGroup) and command.commands:
        parts.append(_render_group_commands(command))
    elif command.params:
        parts.append(_render_options_table(command))

    if is_root:
        parts.append(Text(""))
        parts.append(
            Align.center(
                Text.assemble(
                    ("Run ", MUTED_STYLE),
                    (f"{ctx.command_path} <command> --help", PROMPT_STYLE),
                    (" for command details", MUTED_STYLE),
                )
            )
        )

    return Group(*parts)


def _render_command_header(command: click.Command, command_path: str) -> Panel:
    title = command_path or command.name or "netorium"
    body = Table.grid(padding=(0, 1))
    body.add_row(Text(_first_help_line(command) or "No description.", style="bright_black"))
    return Panel(
        body,
        title=f"[bold bright_cyan]{escape(title)}[/]",
        border_style=PANEL_BORDER,
        padding=(0, 1),
    )


def _render_group_commands(group: TyperGroup) -> Panel:
    commands = _visible_commands(group)
    grouped: dict[str, list[tuple[str, click.Command]]] = defaultdict(list)
    for name, command in commands:
        grouped[_panel_name(command) or "Commands"].append((name, command))

    table = Table(
        box=None,
        show_header=False,
        pad_edge=False,
        padding=(0, 2),
        expand=True,
        show_edge=False,
    )
    table.add_column("", style="bold bright_cyan", no_wrap=True, ratio=2)
    table.add_column("", style="bright_black", ratio=5)

    panel_order = sorted(grouped.keys(), key=lambda name: (name == "Commands", name.lower()))
    for panel_index, panel_name in enumerate(panel_order):
        if panel_index:
            table.add_row("", "", end_section=True)
        table.add_row(Text(panel_name, style=SECTION_STYLE), Text(""))
        entries = sorted(grouped[panel_name], key=lambda item: item[0])
        for name, command in entries:
            table.add_row(f"  {name}", _first_help_line(command))

    return Panel(
        table,
        title="[bold]Commands[/]",
        border_style=PANEL_BORDER_MUTED,
        padding=(0, 1),
    )


def _render_options_table(command: click.Command) -> Panel:
    table = Table(
        box=None,
        show_header=True,
        header_style="bold bright_cyan",
        pad_edge=False,
        padding=(0, 2),
        expand=True,
    )
    table.add_column("Option", style="bold cyan", no_wrap=True, ratio=2)
    table.add_column("Description", style="bright_black", ratio=5)

    for param in command.params:
        if isinstance(param, click.Argument):
            signature = param.name
            if param.nargs != 1:
                signature = f"{signature} ..."
        else:
            opts = [opt for opt in param.opts if opt.startswith("-")]
            signature = ", ".join(opts) if opts else param.name
            if param.is_flag:
                signature = signature or param.name
            elif param.metavar:
                signature = f"{signature} {param.metavar}"

        required = " [bold red]required[/]" if param.required else ""
        default = ""
        if not param.required and param.default is not None and param.default != ():
            default_value = param.default if not callable(param.default) else "..."
            default = f" [bright_black](default: {default_value})[/]"

        table.add_row(signature, Text.from_markup(f"{param.help or ''}{required}{default}"))

    return Panel(
        table,
        title="[bold]Options[/]",
        border_style=PANEL_BORDER_MUTED,
        padding=(0, 1),
    )
