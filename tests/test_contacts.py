"""Tests for contact lookup: the PeopleAPI wrapper and the shared search_contacts tool."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import google_auth_core as core
import httplib2
import pytest
from googleapiclient.errors import HttpError

from google_workspace_mcp.calendar import server as calendar_server
from google_workspace_mcp.contacts import tools
from google_workspace_mcp.contacts.people_api import (
    CONTACTS_SCOPE,
    DIRECTORY_SCOPE,
    OTHER_CONTACTS_SCOPE,
    READ_MASK,
    PeopleAPI,
)
from google_workspace_mcp.core import cached_keys
from google_workspace_mcp.gmail import server as gmail_server


def _person(name, *emails, phone=None):
    p = {"names": [{"displayName": name}], "emailAddresses": [{"value": e} for e in emails]}
    if phone:
        p["phoneNumbers"] = [{"value": phone}]
    return p


def _http_error(status, body):
    return HttpError(httplib2.Response({"status": status}), json.dumps(body).encode())


SCOPE_ERROR = {
    "error": {
        "code": 403,
        "message": "Request had insufficient authentication scopes.",
        "status": "PERMISSION_DENIED",
        "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}],
    }
}
NOT_WORKSPACE = {
    "error": {"code": 400, "message": "Must be a G Suite domain user.", "status": "FAILED_PRECONDITION"}
}
API_DISABLED = {
    "error": {
        "code": 403,
        "message": "People API has not been used in project 123 before or it is disabled.",
        "details": [{"reason": "SERVICE_DISABLED"}],
    }
}


@pytest.fixture
def people():
    svc = MagicMock()
    with patch("google_auth_core.get_service", return_value=svc):
        yield PeopleAPI("me@x.com"), svc


def _set(svc, contacts=(), other=(), directory=()):
    def results(items):
        if isinstance(items, Exception):
            return MagicMock(side_effect=items)
        return MagicMock(return_value={"results": [{"person": p} for p in items]})

    svc.people().searchContacts.return_value.execute = results(contacts)
    svc.otherContacts().search.return_value.execute = results(other)
    if isinstance(directory, Exception):
        svc.people().searchDirectoryPeople.return_value.execute.side_effect = directory
    else:
        svc.people().searchDirectoryPeople.return_value.execute.return_value = {"people": list(directory)}


class TestPeopleAPI:
    def test_merges_sources_and_shapes_results(self, people):
        api, svc = people
        _set(
            svc,
            contacts=[_person("Dana Cohen", "dana@x.com", phone="+972 50 000 0000")],
            other=[_person("Dana Levi", "dana.levi@y.com")],
            directory=[_person("Dana Ben", "dben@corp.com")],
        )

        out = api.search("Dana")

        assert out == {
            "results": [
                {"name": "Dana Cohen", "emails": ["dana@x.com"], "phone": "+972 50 000 0000", "source": "contact"},
                {"name": "Dana Levi", "emails": ["dana.levi@y.com"], "phone": None, "source": "other"},
                {"name": "Dana Ben", "emails": ["dben@corp.com"], "phone": None, "source": "directory"},
            ],
            "skipped": [],
        }
        svc.people().searchDirectoryPeople.assert_called_with(
            query="Dana",
            readMask=READ_MASK,
            sources=["DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE", "DIRECTORY_SOURCE_TYPE_DOMAIN_CONTACT"],
            pageSize=10,
        )

    def test_warmup_runs_once_per_source(self, people):
        api, svc = people
        _set(svc)

        api.search("Dana")
        api.search("Noa")

        contact_calls = svc.people().searchContacts.call_args_list
        other_calls = svc.otherContacts().search.call_args_list
        assert [c.kwargs["query"] for c in contact_calls] == ["", "Dana", "Noa"]
        assert [c.kwargs["query"] for c in other_calls] == ["", "Dana", "Noa"]
        assert contact_calls[1].kwargs == {"query": "Dana", "readMask": READ_MASK, "pageSize": 10}

    def test_dedupes_by_email_case_insensitive(self, people):
        api, svc = people
        _set(
            svc,
            contacts=[_person("Dana", "Dana@x.com")],
            other=[_person("dana", "dana@x.com")],
        )

        out = api.search("Dana")

        assert [r["source"] for r in out["results"]] == ["contact"]

    def test_max_results_caps_total_and_page_size(self, people):
        api, svc = people
        _set(svc, contacts=[_person(f"P{i}", f"p{i}@x.com") for i in range(3)])

        out = api.search("p", max_results=2)

        assert len(out["results"]) == 2
        svc.otherContacts().search.assert_not_called()
        api.search("p", max_results=1000)
        assert svc.people().searchContacts.call_args.kwargs["pageSize"] == 30
        assert svc.otherContacts().search.call_args.kwargs["pageSize"] == 30
        assert svc.people().searchDirectoryPeople.call_args.kwargs["pageSize"] == 500

    def test_drops_entries_without_email(self, people):
        api, svc = people
        _set(svc, contacts=[_person("Dana phone only"), _person("Dana", "dana@x.com")])

        out = api.search("Dana")

        assert [r["emails"] for r in out["results"]] == [["dana@x.com"]]

    def test_other_errors_propagate(self, people):
        api, svc = people
        _set(svc, contacts=_http_error(500, {"error": {"code": 500, "message": "boom"}}))

        with pytest.raises(HttpError):
            api.search("Dana")

    def test_personal_account_skips_directory(self, people):
        api, svc = people
        _set(svc, other=[_person("Dana", "dana@y.com")], directory=_http_error(400, NOT_WORKSPACE))

        out = api.search("Dana")

        assert out["results"][0]["emails"] == ["dana@y.com"]
        assert out["skipped"][0]["source"] == "directory"
        assert "G Suite domain user" in out["skipped"][0]["reason"]

    def test_partial_scope_reports_skipped_source(self, people):
        api, svc = people
        _set(
            svc,
            contacts=_http_error(403, SCOPE_ERROR),
            other=[_person("Dana", "dana@y.com")],
            directory=_http_error(403, SCOPE_ERROR),
        )

        out = api.search("Dana")

        assert len(out["results"]) == 1
        assert {s["source"] for s in out["skipped"]} == {"contact", "directory"}

    def test_all_scopes_missing_raises_actionable_auth_error(self, people):
        api, svc = people
        err = _http_error(403, SCOPE_ERROR)
        _set(svc, contacts=err, other=err, directory=err)

        with pytest.raises(core.AuthError) as exc:
            api.search("Dana")

        msg = str(exc.value)
        for scope in (CONTACTS_SCOPE, OTHER_CONTACTS_SCOPE, DIRECTORY_SCOPE):
            assert scope in msg
        assert "google-auth login me@x.com" in msg

    def test_people_api_disabled_raises_enable_hint(self, people):
        api, svc = people
        _set(svc, contacts=_http_error(403, API_DISABLED))

        with pytest.raises(core.AuthError, match="people.googleapis.com"):
            api.search("Dana")


# ---------------------------------------------------------------------------
# The tool, on both servers that register it
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_api(monkeypatch):
    fake = MagicMock(spec=PeopleAPI)
    monkeypatch.setattr(tools, "_api", lambda account=None, service_name=None: (fake, "test@x.com"))
    return fake


def _parse(result) -> dict:
    assert isinstance(result, list) and len(result) == 1
    return json.loads(result[0].text)


@pytest.mark.anyio
@pytest.mark.parametrize("srv", [gmail_server, calendar_server])
async def test_search_contacts_tool(srv, fake_api):
    fake_api.search.return_value = {"results": [{"name": "Dana"}], "skipped": []}

    data = _parse(await srv.mcp.call_tool("search_contacts", {"query": "Dana", "max_results": 5}))

    assert data == {"ok": True, "account": "test@x.com", "data": {"results": [{"name": "Dana"}], "skipped": []}}
    fake_api.search.assert_called_once_with("Dana", max_results=5)


@pytest.mark.anyio
async def test_search_contacts_rejects_blank_query(fake_api):
    with pytest.raises(Exception, match="query is required"):
        await gmail_server.mcp.call_tool("search_contacts", {"query": "  "})
    fake_api.search.assert_not_called()


@pytest.mark.anyio
async def test_search_contacts_rejects_nonpositive_max_results(fake_api):
    with pytest.raises(Exception, match="max_results must be at least 1"):
        await calendar_server.mcp.call_tool("search_contacts", {"query": "Dana", "max_results": 0})
    fake_api.search.assert_not_called()


@pytest.mark.parametrize(
    "service_name,env_var", [("gmail", "GMAIL_ACCOUNT"), ("calendar", "GOOGLE_CALENDAR_ACCOUNT")]
)
def test_api_resolves_host_server_default_but_caches_as_people(
    store_env, write_token, monkeypatch, service_name, env_var
):
    write_token(store_env, "env@x.com")
    write_token(store_env, "store-default@x.com")  # last write becomes the store default
    monkeypatch.setenv(env_var, "env@x.com")

    with patch("google_auth_core.get_service", return_value=MagicMock()):
        _api, resolved = tools._api(None, service_name)

    assert resolved == "env@x.com"
    assert ("people", "env@x.com") in cached_keys()
