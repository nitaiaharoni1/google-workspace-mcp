"""Tests for core runtime helpers."""
from __future__ import annotations

from google_workspace_mcp.core.runtime import ok


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
