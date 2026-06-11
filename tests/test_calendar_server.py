"""Tests for the Google Calendar MCP server."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from google_workspace_mcp.calendar import server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fake_api(monkeypatch):
    """Monkeypatch _api so no real auth or network calls occur."""
    fake = MagicMock()
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "test@x.com"))
    return fake


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse(result) -> dict:
    """Extract the ok-envelope dict from a FastMCP call_tool result."""
    assert isinstance(result, list) and len(result) == 1
    return json.loads(result[0].text)


# ---------------------------------------------------------------------------
# 1. Tool list
# ---------------------------------------------------------------------------

EXPECTED_TOOLS = {
    # common
    "list_accounts", "auth_status", "whoami",
    # read
    "get_profile", "list_calendars", "get_calendar", "list_events",
    "search_events", "get_event", "get_recurring_event_instances",
    "freebusy_query", "find_available_slots", "get_colors",
    # write
    "create_event", "update_event", "quick_add_event", "move_event",
    "add_attendees", "remove_attendees", "propose_new_time",
    "create_calendar", "update_calendar",
    # destructive
    "delete_event", "delete_calendar", "clear_calendar",
}


@pytest.mark.anyio
async def test_tool_list_includes_expected_names():
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS.issubset(names), f"Missing: {EXPECTED_TOOLS - names}"


@pytest.mark.anyio
async def test_tool_count():
    tools = await server.mcp.list_tools()
    # 3 common + 11 read + 9 write + 3 destructive = 26
    assert len(tools) == 26


# ---------------------------------------------------------------------------
# 2. Read tool: list_events
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_events_returns_envelope(fake_api):
    fake_api.list_events.return_value = [{"id": "ev1", "summary": "Standup"}]

    result = await server.mcp.call_tool(
        "list_events",
        {"calendar_id": "primary", "max_results": 5},
    )
    data = _parse(result)

    assert data["ok"] is True
    assert data["account"] == "test@x.com"
    assert data["data"] == [{"id": "ev1", "summary": "Standup"}]


@pytest.mark.anyio
async def test_list_events_passes_args_to_api(fake_api):
    fake_api.list_events.return_value = []

    await server.mcp.call_tool(
        "list_events",
        {
            "calendar_id": "work@example.com",
            "max_results": 20,
            "time_min": "2025-01-01T00:00:00Z",
            "time_max": "2025-01-31T23:59:59Z",
            "single_events": True,
            "order_by": "startTime",
        },
    )

    fake_api.list_events.assert_called_once_with(
        calendar_id="work@example.com",
        max_results=20,
        time_min="2025-01-01T00:00:00Z",
        time_max="2025-01-31T23:59:59Z",
        single_events=True,
        order_by="startTime",
    )


# ---------------------------------------------------------------------------
# 3. Write tool: create_event
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_create_event_calls_api_with_correct_args(fake_api):
    fake_api.create_event.return_value = {"id": "new_event_123", "summary": "Team lunch"}

    result = await server.mcp.call_tool(
        "create_event",
        {
            "summary": "Team lunch",
            "start_time": "2025-06-10T12:00:00",
            "end_time": "2025-06-10T13:00:00",
            "description": "All-hands lunch",
            "location": "HQ",
            "calendar_id": "primary",
            "attendees": ["alice@x.com", "bob@x.com"],
            "timezone": "UTC",
        },
    )
    data = _parse(result)

    assert data["ok"] is True
    assert data["data"]["id"] == "new_event_123"

    fake_api.create_event.assert_called_once_with(
        summary="Team lunch",
        start_time="2025-06-10T12:00:00",
        end_time="2025-06-10T13:00:00",
        description="All-hands lunch",
        location="HQ",
        calendar_id="primary",
        attendees=["alice@x.com", "bob@x.com"],
        recurrence=None,
        timezone="UTC",
        color_id=None,
        add_meet=False,
    )


# ---------------------------------------------------------------------------
# 4. Destructive tool: delete_event
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_delete_event_calls_api(fake_api):
    fake_api.delete_event.return_value = True

    result = await server.mcp.call_tool(
        "delete_event",
        {"event_id": "abc123", "calendar_id": "primary"},
    )
    data = _parse(result)

    assert data["ok"] is True
    assert data["data"] is True
    fake_api.delete_event.assert_called_once_with("abc123", calendar_id="primary")


@pytest.mark.anyio
async def test_delete_event_docstring_has_destructive_marker():
    tools = await server.mcp.list_tools()
    delete_tool = next(t for t in tools if t.name == "delete_event")
    assert "DESTRUCTIVE" in delete_tool.description


# ---------------------------------------------------------------------------
# 5. Additional read tools
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_search_events(fake_api):
    fake_api.search_events.return_value = [{"id": "s1"}]

    result = await server.mcp.call_tool(
        "search_events",
        {"query": "budget", "calendar_id": "primary", "max_results": 3},
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["data"] == [{"id": "s1"}]
    fake_api.search_events.assert_called_once_with(
        query="budget", calendar_id="primary", max_results=3
    )


@pytest.mark.anyio
async def test_get_event(fake_api):
    fake_api.get_event.return_value = {"id": "ev99", "summary": "Dentist"}

    result = await server.mcp.call_tool(
        "get_event",
        {"event_id": "ev99", "calendar_id": "primary"},
    )
    data = _parse(result)
    assert data["data"]["summary"] == "Dentist"
    fake_api.get_event.assert_called_once_with("ev99", calendar_id="primary")


@pytest.mark.anyio
async def test_list_calendars(fake_api):
    fake_api.list_calendars.return_value = [{"id": "primary"}, {"id": "work"}]

    result = await server.mcp.call_tool("list_calendars", {})
    data = _parse(result)
    assert len(data["data"]) == 2


@pytest.mark.anyio
async def test_freebusy_query(fake_api):
    fake_api.freebusy_query.return_value = {"calendars": {}}

    result = await server.mcp.call_tool(
        "freebusy_query",
        {
            "time_min": "2025-06-10T09:00:00Z",
            "time_max": "2025-06-10T17:00:00Z",
            "calendar_ids": ["primary"],
        },
    )
    data = _parse(result)
    assert data["ok"] is True
    fake_api.freebusy_query.assert_called_once_with(
        time_min="2025-06-10T09:00:00Z",
        time_max="2025-06-10T17:00:00Z",
        calendar_ids=["primary"],
    )


# ---------------------------------------------------------------------------
# 6. Write tools
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_quick_add_event(fake_api):
    fake_api.quick_add_event.return_value = {"id": "qa1", "summary": "Lunch tomorrow"}

    result = await server.mcp.call_tool(
        "quick_add_event",
        {"text": "Lunch tomorrow 12pm", "calendar_id": "primary"},
    )
    data = _parse(result)
    assert data["data"]["id"] == "qa1"
    fake_api.quick_add_event.assert_called_once_with(
        text="Lunch tomorrow 12pm", calendar_id="primary"
    )


@pytest.mark.anyio
async def test_update_event(fake_api):
    fake_api.update_event.return_value = {"id": "ev5", "summary": "Updated"}

    result = await server.mcp.call_tool(
        "update_event",
        {"event_id": "ev5", "summary": "Updated", "calendar_id": "primary"},
    )
    data = _parse(result)
    assert data["data"]["summary"] == "Updated"


@pytest.mark.anyio
async def test_create_calendar(fake_api):
    fake_api.create_calendar.return_value = {"id": "newcal", "summary": "Work"}

    result = await server.mcp.call_tool(
        "create_calendar",
        {"summary": "Work", "timezone": "America/New_York"},
    )
    data = _parse(result)
    assert data["ok"] is True
    fake_api.create_calendar.assert_called_once_with(
        summary="Work",
        description=None,
        timezone="America/New_York",
        color_id=None,
    )


@pytest.mark.anyio
async def test_delete_calendar(fake_api):
    fake_api.delete_calendar.return_value = True

    result = await server.mcp.call_tool(
        "delete_calendar", {"calendar_id": "oldcal@group.calendar.google.com"}
    )
    data = _parse(result)
    assert data["ok"] is True
    assert data["data"] is True
    fake_api.delete_calendar.assert_called_once_with(
        "oldcal@group.calendar.google.com"
    )
