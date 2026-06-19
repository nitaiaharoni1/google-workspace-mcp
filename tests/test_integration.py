"""Cross-cutting guarantees that span the whole system:

* multi-account isolation through the shared ``get_api`` cache (the headline
  requirement: parallel accounts must never interfere),
* persistence (credentials load from disk on "restart"; no interactive flow),
* the read-only gate (mutating tools disappear from every server),
* all five servers expose the aligned common tools.
"""

import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import google_auth_core as core
from google_workspace_mcp.core import runtime


# --- multi-account isolation -------------------------------------------------

def test_get_api_isolation(store_env, write_token):
    write_token(store_env, "a@x.com")
    write_token(store_env, "b@y.com")

    created = []

    def factory(account):
        created.append(account)
        return SimpleNamespace(account=account)

    api_a, ra = runtime.get_api("gmail", factory, "a@x.com")
    api_a2, _ = runtime.get_api("gmail", factory, "a@x.com")
    api_b, rb = runtime.get_api("gmail", factory, "b@y.com")

    assert ra == "a@x.com" and rb == "b@y.com"
    assert api_a is api_a2  # cached per account
    assert api_a is not api_b
    assert api_a.account == "a@x.com" and api_b.account == "b@y.com"
    assert created == ["a@x.com", "b@y.com"]  # one construction per account
    assert runtime.cached_keys() == [("gmail", "a@x.com"), ("gmail", "b@y.com")]


def test_get_api_alias_resolves(store_env, write_token):
    write_token(store_env, "real@x.com")
    core.set_account_alias("work", "real@x.com")
    _api, resolved = runtime.get_api("gmail", lambda a: SimpleNamespace(account=a), "work")
    assert resolved == "real@x.com"


@pytest.mark.anyio
async def test_parallel_accounts_do_not_interfere(store_env, write_token):
    write_token(store_env, "a@x.com", token="tok-A")
    write_token(store_env, "b@y.com", token="tok-B")

    def factory(account):
        # capture which account's credentials were loaded for this build
        creds, resolved = core.get_credentials(account)
        return SimpleNamespace(account=resolved, token=creds.token)

    async def call(acct):
        return await asyncio.to_thread(runtime.get_api, "gmail", factory, acct)

    (api_a, _), (api_b, _) = await asyncio.gather(call("a@x.com"), call("b@y.com"))
    assert api_a.token == "tok-A"
    assert api_b.token == "tok-B"  # no cross-contamination under concurrency


# --- persistence -------------------------------------------------------------

def test_credentials_persist_across_restart(store_env, write_token, monkeypatch):
    write_token(store_env, "a@x.com")
    runtime.get_api("gmail", lambda a: SimpleNamespace(account=a), "a@x.com")

    # Simulate a server restart: drop the in-process cache.
    runtime.reset_api_cache()

    # Any interactive auth attempt should be considered a failure.
    def boom(*args, **kwargs):
        raise AssertionError("interactive auth must not run in the server")

    monkeypatch.setattr(core, "authenticate", boom)

    _api, resolved = runtime.get_api("gmail", lambda a: SimpleNamespace(account=a), "a@x.com")
    assert resolved == "a@x.com"  # loaded from disk, no re-consent


def test_missing_credentials_raise_actionable_error(store_env):
    with pytest.raises(core.AuthError) as exc:
        runtime.get_api("gmail", lambda a: SimpleNamespace(account=a), "ghost@x.com")
    assert "google-auth login ghost@x.com" in str(exc.value)


# --- read-only gate ----------------------------------------------------------

def test_readonly_gate_hides_mutating_tools():
    """With GOOGLE_MCP_READONLY set, mutating tools must not be registered."""
    code = (
        "import asyncio\n"
        "from google_workspace_mcp.gmail import server\n"
        "names = [t.name for t in asyncio.run(server.mcp.list_tools())]\n"
        "print(('send_message' in names, 'delete_message' in names, 'list_messages' in names))\n"
    )
    env = {**os.environ, "GOOGLE_MCP_READONLY": "1"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "(False, False, True)"


def test_mutating_tools_present_by_default():
    code = (
        "import asyncio\n"
        "from google_workspace_mcp.gmail import server\n"
        "names = [t.name for t in asyncio.run(server.mcp.list_tools())]\n"
        "print(('send_message' in names, 'list_messages' in names))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_MCP_READONLY"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "(True, True)"


@pytest.mark.parametrize(
    "pkg,read_tool,write_tool",
    [
        ("docs", "read_document", "create_document"),
        ("drive", "list_files", "upload_file"),
    ],
)
def test_readonly_gate_hides_mutating_tools_docs_drive(pkg, read_tool, write_tool):
    code = (
        f"import asyncio\n"
        f"from google_workspace_mcp.{pkg} import server\n"
        f"names = [t.name for t in asyncio.run(server.mcp.list_tools())]\n"
        f"print(({write_tool!r} in names, {read_tool!r} in names))\n"
    )
    env = {**os.environ, "GOOGLE_MCP_READONLY": "1"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "(False, True)"


# --- alignment: every server exposes the common tools ------------------------

@pytest.mark.anyio
async def test_all_servers_expose_common_tools():
    from google_workspace_mcp.gmail import server as g
    from google_workspace_mcp.calendar import server as c
    from google_workspace_mcp.sheets import server as s
    from google_workspace_mcp.docs import server as d
    from google_workspace_mcp.drive import server as dr

    for mod in (g, c, s, d, dr):
        names = {t.name for t in await mod.mcp.list_tools()}
        assert {"list_accounts", "whoami", "auth_status"}.issubset(names)
