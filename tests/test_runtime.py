"""Tests for core runtime helpers."""
from __future__ import annotations

import google_auth_core as core
import pytest

from google_workspace_mcp.core.runtime import cap_items, cap_text, ok, run_tool


def test_ok_without_meta():
    assert ok("a@x.com", [{"id": 1}]) == {
        "ok": True,
        "account": "a@x.com",
        "data": [{"id": 1}],
    }


def test_ok_with_next_page_token():
    assert ok("a@x.com", [], next_page_token="tok") == {
        "ok": True,
        "account": "a@x.com",
        "data": [],
        "next_page_token": "tok",
    }


def test_ok_drops_none_meta():
    assert ok("a@x.com", "x", next_page_token=None) == {
        "ok": True,
        "account": "a@x.com",
        "data": "x",
    }


def test_run_tool_maps_value_error():
    def boom():
        raise ValueError("bad range")

    with pytest.raises(core.InvalidArgumentError) as exc:
        run_tool(boom)
    assert str(exc.value) == "bad range"


def test_run_tool_reraises_google_core_error():
    err = core.AuthError("login first")

    def boom():
        raise err

    with pytest.raises(core.AuthError) as exc:
        run_tool(boom)
    assert exc.value is err


def test_cap_text_fits_returns_no_meta():
    assert cap_text("hello", 10) == ("hello", {})


def test_cap_text_truncates_and_pages():
    chunk, meta = cap_text("abcdefghij", 4, hint="more")
    assert chunk == "abcd"
    assert meta == {"truncated": True, "total_chars": 10, "offset": 0, "next_offset": 4, "hint": "more"}
    chunk, meta = cap_text("abcdefghij", 4, offset=8)
    assert chunk == "ij"
    assert meta == {"truncated": False, "total_chars": 10, "offset": 8}


def test_cap_text_default_limit():
    chunk, meta = cap_text("x" * 100_001)
    assert len(chunk) == 100_000 and meta["next_offset"] == 100_000


@pytest.mark.parametrize("kwargs", [{"max_chars": 0}, {"offset": -1}])
def test_cap_text_rejects_bad_args(kwargs):
    with pytest.raises(core.InvalidArgumentError):
        cap_text("abc", **kwargs)


def test_cap_items_keeps_whole_items_and_pages():
    items = ["aaaa", "bbbb", "cccc"]  # each serializes to 6 chars
    kept, meta = cap_items(items, 13, hint="next")
    assert kept == ["aaaa", "bbbb"]
    assert meta == {"truncated": True, "total_items": 3, "offset": 0, "next_offset": 2, "hint": "next"}
    kept, meta = cap_items(items, 13, offset=2)
    assert kept == ["cccc"] and meta["truncated"] is False


def test_cap_items_always_returns_one_item():
    kept, meta = cap_items(["x" * 50, "y"], 10)
    assert kept == ["x" * 50] and meta["next_offset"] == 1
