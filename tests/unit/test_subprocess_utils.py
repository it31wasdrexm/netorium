from netorium.core.subprocess_utils import SUBPROCESS_TEXT_KWARGS


def test_subprocess_text_kwargs_use_utf8_with_replacement() -> None:
    assert SUBPROCESS_TEXT_KWARGS == {
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
