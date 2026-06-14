from __future__ import annotations

from importlib import resources
from typing import Final

DOC_PACKAGE: Final[str] = "netorium.docs"

DOC_PAGES: Final[dict[str, str]] = {
    "index": "index.md",
    "commands": "commands.md",
    "examples": "examples.md",
    "troubleshooting": "troubleshooting.md",
}


class DocumentationError(RuntimeError):
    pass


def load_doc_page(page: str) -> str:
    filename = DOC_PAGES.get(page)
    if filename is None:
        raise DocumentationError(f"Unknown documentation page: {page}")

    try:
        return resources.files(DOC_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DocumentationError(f"Documentation page is missing: {filename}") from exc
