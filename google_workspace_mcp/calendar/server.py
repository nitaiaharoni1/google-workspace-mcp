"""Google Calendar MCP server: events, calendars, availability."""
from __future__ import annotations

from ..core import build_server, register, get_api, run_tool, ok
from google_calendar_cli.api import CalendarAPI

mcp = build_server(
    "gcal-mcp",
    "Google Calendar: list/search events, create/update/delete events, manage calendars, and check availability for one or more accounts.",
)


def _api(account=None):
    return get_api("calendar", CalendarAPI, account)


# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

@register(mcp)
def get_profile(account: str | None = None) -> dict:
    """Get the authenticated user's primary calendar profile."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_profile())
    return ok(resolved, data)


@register(mcp)
def list_calendars(account: str | None = None) -> dict:
    """List all calendars accessible to the account."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.list_calendars())
    return ok(resolved, data)


@register(mcp)
def get_calendar(account: str | None = None, calendar_id: str = "primary") -> dict:
    """Get metadata for a specific calendar."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_calendar(calendar_id))
    return ok(resolved, data)


@register(mcp)
def list_events(
    account: str | None = None,
    calendar_id: str = "primary",
    max_results: int = 10,
    time_min: str | None = None,
    time_max: str | None = None,
    single_events: bool = True,
    order_by: str = "startTime",
) -> dict:
    """List events on a calendar within an optional time window (RFC3339 timestamps)."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.list_events(
            calendar_id=calendar_id,
            max_results=max_results,
            time_min=time_min,
            time_max=time_max,
            single_events=single_events,
            order_by=order_by,
        )
    )
    return ok(resolved, data)


@register(mcp)
def search_events(
    account: str | None = None,
    query: str = "",
    calendar_id: str = "primary",
    max_results: int = 10,
) -> dict:
    """Search events on a calendar by text query."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.search_events(query=query, calendar_id=calendar_id, max_results=max_results)
    )
    return ok(resolved, data)


@register(mcp)
def get_event(
    account: str | None = None,
    event_id: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Get a specific event by its ID."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_event(event_id, calendar_id=calendar_id))
    return ok(resolved, data)


@register(mcp)
def get_recurring_event_instances(
    account: str | None = None,
    event_id: str = "",
    calendar_id: str = "primary",
    max_results: int = 250,
) -> dict:
    """Get all instances of a recurring event."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.get_recurring_event_instances(
            event_id, calendar_id=calendar_id, max_results=max_results
        )
    )
    return ok(resolved, data)


@register(mcp)
def freebusy_query(
    account: str | None = None,
    time_min: str = "",
    time_max: str = "",
    calendar_ids: list[str] | None = None,
) -> dict:
    """Query free/busy information for one or more calendars (RFC3339 timestamps)."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.freebusy_query(
            time_min=time_min, time_max=time_max, calendar_ids=calendar_ids
        )
    )
    return ok(resolved, data)


@register(mcp)
def find_available_slots(
    account: str | None = None,
    attendee_emails: list[str] | None = None,
    duration_minutes: int = 60,
    time_min: str = "",
    time_max: str = "",
    working_hours_start: int = 9,
    working_hours_end: int = 18,
    exclude_weekends: bool = True,
    timezone: str = "UTC",
) -> dict:
    """Find available meeting slots when all attendees are free (RFC3339 time_min/time_max)."""
    from datetime import datetime

    api, resolved = _api(account)
    emails = attendee_emails or []

    def _call():
        # Convert ISO strings to datetime objects as required by the API
        t_min = datetime.fromisoformat(time_min.replace("Z", "+00:00"))
        t_max = datetime.fromisoformat(time_max.replace("Z", "+00:00"))
        slots = api.find_available_slots(
            attendee_emails=emails,
            duration_minutes=duration_minutes,
            time_min=t_min,
            time_max=t_max,
            working_hours_start=working_hours_start,
            working_hours_end=working_hours_end,
            exclude_weekends=exclude_weekends,
            timezone=timezone,
        )
        # Serialize datetime tuples to ISO strings for JSON transport
        return [{"start": s.isoformat(), "end": e.isoformat()} for s, e in slots]

    data = run_tool(_call)
    return ok(resolved, data)


@register(mcp)
def get_colors(account: str | None = None) -> dict:
    """Get available colors for calendars and events."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.get_colors())
    return ok(resolved, data)


# ---------------------------------------------------------------------------
# WRITE tools (mutating)
# ---------------------------------------------------------------------------

@register(mcp, mutating=True)
def create_event(
    account: str | None = None,
    summary: str = "",
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    location: str | None = None,
    calendar_id: str = "primary",
    attendees: list[str] | None = None,
    recurrence: list[str] | None = None,
    timezone: str = "UTC",
    color_id: str | None = None,
    add_meet: bool = False,
) -> dict:
    """Create a new calendar event."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.create_event(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            calendar_id=calendar_id,
            attendees=attendees,
            recurrence=recurrence,
            timezone=timezone,
            color_id=color_id,
            add_meet=add_meet,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_event(
    account: str | None = None,
    event_id: str = "",
    calendar_id: str = "primary",
    summary: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    location: str | None = None,
    attendees: list[str] | None = None,
    recurrence: list[str] | None = None,
    timezone: str | None = None,
    color_id: str | None = None,
    add_meet: bool = False,
    remove_meet: bool = False,
) -> dict:
    """Update fields on an existing calendar event."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.update_event(
            event_id=event_id,
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            calendar_id=calendar_id,
            attendees=attendees,
            recurrence=recurrence,
            timezone=timezone,
            color_id=color_id,
            add_meet=add_meet,
            remove_meet=remove_meet,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def quick_add_event(
    account: str | None = None,
    text: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Create an event from a natural-language description (e.g. 'Meeting tomorrow 3pm')."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.quick_add_event(text=text, calendar_id=calendar_id))
    return ok(resolved, data)


@register(mcp, mutating=True)
def move_event(
    account: str | None = None,
    event_id: str = "",
    destination_calendar_id: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Move an event from one calendar to another."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.move_event(
            event_id=event_id,
            destination_calendar_id=destination_calendar_id,
            calendar_id=calendar_id,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def add_attendees(
    account: str | None = None,
    event_id: str = "",
    attendee_emails: list[str] | None = None,
    calendar_id: str = "primary",
    send_updates: str = "all",
) -> dict:
    """Add attendees to an existing event."""
    api, resolved = _api(account)
    emails = attendee_emails or []
    data = run_tool(
        lambda: api.add_attendees(
            event_id=event_id,
            attendee_emails=emails,
            calendar_id=calendar_id,
            send_updates=send_updates,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def remove_attendees(
    account: str | None = None,
    event_id: str = "",
    attendee_emails: list[str] | None = None,
    calendar_id: str = "primary",
    send_updates: str = "all",
) -> dict:
    """Remove attendees from an existing event."""
    api, resolved = _api(account)
    emails = attendee_emails or []
    data = run_tool(
        lambda: api.remove_attendees(
            event_id=event_id,
            attendee_emails=emails,
            calendar_id=calendar_id,
            send_updates=send_updates,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def respond_to_event(
    account: str | None = None,
    event_id: str = "",
    response: str = "",
    calendar_id: str = "primary",
    send_updates: str = "all",
) -> dict:
    """Respond to a calendar invitation: accept / decline / tentatively accept.

    response: one of "accepted", "declined", "tentative", "needsAction".
    """
    api, resolved = _api(account)
    data = run_tool(lambda: api.respond_to_event(event_id, response, calendar_id=calendar_id, send_updates=send_updates))
    return ok(resolved, data)


@register(mcp, mutating=True)
def propose_new_time(
    account: str | None = None,
    event_id: str = "",
    new_start_time: str = "",
    new_end_time: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Propose a new time for an event as an attendee (RFC3339 timestamps)."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.propose_new_time(
            event_id=event_id,
            new_start_time=new_start_time,
            new_end_time=new_end_time,
            calendar_id=calendar_id,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def create_calendar(
    account: str | None = None,
    summary: str = "",
    description: str | None = None,
    timezone: str | None = None,
    color_id: str | None = None,
) -> dict:
    """Create a new secondary calendar."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.create_calendar(
            summary=summary,
            description=description,
            timezone=timezone,
            color_id=color_id,
        )
    )
    return ok(resolved, data)


@register(mcp, mutating=True)
def update_calendar(
    account: str | None = None,
    calendar_id: str = "",
    summary: str | None = None,
    description: str | None = None,
    timezone: str | None = None,
    color_id: str | None = None,
) -> dict:
    """Update metadata (name, description, timezone, color) for a calendar."""
    api, resolved = _api(account)
    data = run_tool(
        lambda: api.update_calendar(
            calendar_id=calendar_id,
            summary=summary,
            description=description,
            timezone=timezone,
            color_id=color_id,
        )
    )
    return ok(resolved, data)


# ---------------------------------------------------------------------------
# DESTRUCTIVE tools (mutating + destructive)
# ---------------------------------------------------------------------------

@register(mcp, mutating=True, destructive=True)
def delete_event(
    account: str | None = None,
    event_id: str = "",
    calendar_id: str = "primary",
) -> dict:
    """Permanently delete a calendar event."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_event(event_id, calendar_id=calendar_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def delete_calendar(
    account: str | None = None,
    calendar_id: str = "",
) -> dict:
    """Permanently delete a secondary calendar and all its events."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.delete_calendar(calendar_id))
    return ok(resolved, data)


@register(mcp, mutating=True, destructive=True)
def clear_calendar(
    account: str | None = None,
    calendar_id: str = "",
) -> dict:
    """Remove all events from a calendar (primary calendar only)."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.clear_calendar(calendar_id))
    return ok(resolved, data)


def main():
    mcp.run()
