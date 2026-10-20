"""Tests for core runtime helpers."""
from __future__ import annotations

import google_auth_core as core
import pytest

from google_workspace_mcp.core.paths import free_path, safe_dir, safe_path
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


def test_safe_path_refuses_token_store_even_via_symlink(store_env, tmp_path):
    secret = store_env / "tokens" / "google_a.json"
    secret.write_text("{}")
    link = tmp_path / "innocent.pdf"
    link.symlink_to(secret)
    for p in (str(secret), str(link)):
        with pytest.raises(core.InvalidArgumentError, match="token store"):
            safe_path(p)
    with pytest.raises(core.InvalidArgumentError, match="token store"):
        safe_path("~/.google/credentials.json")
    with pytest.raises(core.InvalidArgumentError, match="token store"):
        safe_dir(str(store_env))
    # macOS volumes are case-insensitive: ~/.Google is the same directory.
    with pytest.raises(core.InvalidArgumentError, match="token store"):
        safe_path(str(store_env).upper() + "/x.json", write=True)


def test_safe_path_file_root(store_env, tmp_path, monkeypatch):
    root = tmp_path / "work"
    root.mkdir()
    inside = root / "a.txt"
    inside.write_text("x")
    outside = tmp_path / "b.txt"
    outside.write_text("x")
    monkeypatch.setenv("GOOGLE_MCP_FILE_ROOT", str(root))
    assert safe_path(str(inside)) == str(inside)
    with pytest.raises(core.InvalidArgumentError, match="GOOGLE_MCP_FILE_ROOT"):
        safe_path(str(outside))
    with pytest.raises(core.InvalidArgumentError, match="GOOGLE_MCP_FILE_ROOT"):
        safe_path(str(root / ".." / "b.txt"), write=True)


def test_safe_path_write_refuses_existing_unless_overwrite(store_env, tmp_path):
    target = tmp_path / "out.bin"
    assert safe_path(str(target), write=True) == str(target)
    target.write_text("keep me")
    with pytest.raises(core.InvalidArgumentError, match="overwrite=True"):
        safe_path(str(target), write=True)
    assert safe_path(str(target), write=True, overwrite=True) == str(target)


def test_safe_path_returns_named_path_not_link_target(store_env, tmp_path):
    target = tmp_path / "ab12.bin"
    target.write_text("x")
    link = tmp_path / "report.pdf"
    link.symlink_to(target)
    assert safe_path(str(link)) == str(link)


def test_free_path_picks_unused_name(tmp_path):
    p = tmp_path / "a.txt"
    assert free_path(str(p)) == str(p)
    p.write_text("x")
    assert free_path(str(p)) == str(tmp_path / "a (1).txt")
