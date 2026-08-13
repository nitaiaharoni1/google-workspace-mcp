"""Tests for core runtime helpers."""
from __future__ import annotations

import google_auth_core as core
import pytest

from google_workspace_mcp.core.runtime import ok, run_tool


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
