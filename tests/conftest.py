"""Shared fixtures: anyio backend and a temp ~/.google store."""

import datetime

import pytest
from google.oauth2.credentials import Credentials

import google_auth_core as core
from google_auth_core import service as service_mod
from google_auth_core import store
from google_workspace_mcp.core import runtime


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    """Point the store at a temp ~/.google and clear all caches."""
    base = tmp_path / ".google"
    tokens = base / "tokens"
    tokens.mkdir(parents=True)
    monkeypatch.setattr(store, "GOOGLE_CONFIG_DIR", base)
    monkeypatch.setattr(store, "GOOGLE_CONFIG_FILE", base / "config.json")
    monkeypatch.setattr(store, "GOOGLE_CREDENTIALS_FILE", base / "credentials.json")
    monkeypatch.setattr(store, "GOOGLE_TOKENS_DIR", tokens)
    service_mod.invalidate()
    runtime.reset_api_cache()
    yield base
    service_mod.invalidate()
    runtime.reset_api_cache()


@pytest.fixture
def write_token():
    """Return a helper that writes a unified token file and registers the account."""

    def _write(base, account, *, token="t", expiry="future", refresh_token="r"):
        creds = Credentials(
            token=token,
            refresh_token=refresh_token,
            client_id="cid",
            client_secret="secret",
            scopes=list(core.ALL_SCOPES),
            token_uri="https://oauth2.googleapis.com/token",
        )
        if expiry == "future":
            creds.expiry = datetime.datetime.now(datetime.timezone.utc).replace(
                tzinfo=None
            ) + datetime.timedelta(hours=1)
        elif expiry is not None:
            creds.expiry = expiry
        path = base / "tokens" / f"google_{account}.json"
        path.write_text(creds.to_json())
        store.set_default_account(account)
        return path

    return _write
