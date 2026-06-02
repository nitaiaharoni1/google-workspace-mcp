"""Opt-in live smoke tests against real Google accounts.

Skipped unless GOOGLE_MCP_LIVE=1 and a default account is authenticated
(run `google-auth login` first). These hit the real APIs, so they are never
run in CI.

Env:
  GOOGLE_MCP_LIVE=1                 enable these tests
  GOOGLE_MCP_TEST_ACCOUNT=<email>  account/alias to use (else default)
  GOOGLE_MCP_TEST_SHEET_ID=<id>    an existing scratch spreadsheet for the
                                   Sheets round-trip (avoids leaving litter)
  GOOGLE_MCP_TEST_ACCOUNT_2=<email> second account, for the isolation check
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("GOOGLE_MCP_LIVE"),
    reason="set GOOGLE_MCP_LIVE=1 (and authenticate) to run live tests",
)

ACCOUNT = os.getenv("GOOGLE_MCP_TEST_ACCOUNT")


def test_gmail_profile_live():
    from google_workspace_mcp.gmail import server

    api, resolved = server._api(ACCOUNT)
    profile = api.get_profile()
    assert profile.get("emailAddress")


def test_calendar_list_live():
    from google_workspace_mcp.calendar import server

    api, _ = server._api(ACCOUNT)
    calendars = api.list_calendars()
    assert isinstance(calendars, (list, dict))


def test_sheets_roundtrip_live():
    sheet_id = os.getenv("GOOGLE_MCP_TEST_SHEET_ID")
    if not sheet_id:
        pytest.skip("set GOOGLE_MCP_TEST_SHEET_ID to a scratch spreadsheet")
    from google_workspace_mcp.sheets import server

    api, _ = server._api(ACCOUNT)
    api.update_range(sheet_id, "A1", [["mcp-live"]])
    got = api.read_range(sheet_id, "A1")
    assert got.get("values") == [["mcp-live"]]
    api.clear_range(sheet_id, "A1")


def test_multi_account_isolation_live():
    account_2 = os.getenv("GOOGLE_MCP_TEST_ACCOUNT_2")
    if not (ACCOUNT and account_2):
        pytest.skip("set GOOGLE_MCP_TEST_ACCOUNT and GOOGLE_MCP_TEST_ACCOUNT_2")
    from google_workspace_mcp.gmail import server

    api1, r1 = server._api(ACCOUNT)
    api2, r2 = server._api(account_2)
    assert r1 != r2
    assert api1.get_profile()["emailAddress"] != api2.get_profile()["emailAddress"]
