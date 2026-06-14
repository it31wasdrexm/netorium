import pytest

from netorium.core import docs as docs_core
from netorium.core.docs import DocumentationError, load_doc_page


def test_load_doc_page_reads_packaged_markdown() -> None:
    text = load_doc_page("index")

    assert "# Netorium CLI" in text
    assert "netorium docs commands" in text
    assert "netorium docs install" in text


def test_load_doc_page_rejects_unknown_page() -> None:
    with pytest.raises(DocumentationError, match="Unknown documentation page"):
        load_doc_page("missing")


def test_load_doc_page_reports_missing_packaged_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(docs_core.DOC_PAGES, "index", "missing.md")

    with pytest.raises(DocumentationError, match="Documentation page is missing"):
        load_doc_page("index")
