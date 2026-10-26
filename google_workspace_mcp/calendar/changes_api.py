"""Calendar syncToken-based change feed (subclass of upstream CalendarAPI)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google_calendar_cli.api import CalendarAPI
from google_calendar_cli.utils import parse_datetime
from googleapiclient.errors import HttpError

_SYNC_EXPIRED = (
    "sync_token expired; call list_event_changes without sync_token to re-baseline"
)

_EVENT_FIELDS = (
    "nextPageToken,nextSyncToken,"
    "items(id,status,summary,start,end,updated,organizer,recurringEventId)"
)

_STATUS_EVENT_TYPES = {
    "outOfOffice": {
        "summary": "Out of office",
        "properties_key": "outOfOfficeProperties",
        "decline_message": "Declining because I am out of office.",
        "extra": {},
    },
    "focusTime": {
        "summary": "Focus time",
        "properties_key": "focusTimeProperties",
        "decline_message": "Declining because I am in focus time.",
        "extra": {"chatStatus": "doNotDisturb"},
    },
}


def _event_time(value, timezone, field):
    parsed = parse_datetime(value)
    if not parsed:
        raise ValueError(f"{field} is not a parseable datetime: {value!r}")
    return {"dateTime": parsed.isoformat(), "timeZone": timezone}


def _meet_request():
    return {
        "createRequest": {
            "requestId": str(uuid.uuid4()),
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }
    }


def trim_event(event):
    """Return a compact event dict for change-feed responses."""
    return {
        "id": event.get("id"),
        "status": event.get("status"),
        "summary": event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
        "updated": event.get("updated"),
        "organizer": event.get("organizer"),
        "recurringEventId": event.get("recurringEventId"),
    }


class CalendarChangesAPI(CalendarAPI):
    """CalendarAPI plus syncToken-based incremental event listing."""

    def create_event(
        self,
        summary,
        start_time=None,
        end_time=None,
        description=None,
        location=None,
        calendar_id="primary",
        attendees=None,
        recurrence=None,
        timezone="UTC",
        color_id=None,
        add_meet=False,
        send_updates="all",
    ):
        # Upstream never passes sendUpdates on event writes, so Google applies the
        # change but never emails the attendees. create/update/delete/quick-add/
        # move are overridden here for that reason alone.
        start = (
            _event_time(start_time, timezone, "start_time")
            if start_time
            else {"dateTime": datetime.now(ZoneInfo(timezone)).isoformat(), "timeZone": timezone}
        )
        if end_time:
            end = _event_time(end_time, timezone, "end_time")
        else:
            end_dt = datetime.fromisoformat(start["dateTime"]) + timedelta(hours=1)
            end = {"dateTime": end_dt.isoformat(), "timeZone": timezone}

        event = {"summary": summary, "start": start, "end": end}
        if description:
            event["description"] = description
        if location:
            event["location"] = location
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]
        if recurrence:
            event["recurrence"] = recurrence if isinstance(recurrence, list) else [recurrence]
        if color_id:
            event["colorId"] = color_id

        params = {"calendarId": calendar_id, "body": event, "sendUpdates": send_updates}
        if add_meet:
            event["conferenceData"] = _meet_request()
            params["conferenceDataVersion"] = 1
        return self.service.events().insert(**params).execute()

    def update_event(
        self,
        event_id,
        summary=None,
        start_time=None,
        end_time=None,
        description=None,
        location=None,
        calendar_id="primary",
        attendees=None,
        recurrence=None,
        timezone=None,
        color_id=None,
        add_meet=False,
        remove_meet=False,
        send_updates="all",
    ):
        event = self.get_event(event_id, calendar_id)
        timezone = timezone or event.get("start", {}).get("timeZone", "UTC")
        if summary:
            event["summary"] = summary
        if start_time:
            event["start"] = _event_time(start_time, timezone, "start_time")
        if end_time:
            event["end"] = _event_time(end_time, timezone, "end_time")
        if description is not None:
            event["description"] = description
        if location is not None:
            event["location"] = location
        if attendees is not None:
            event["attendees"] = [{"email": email} for email in attendees]
        if recurrence is not None:
            event["recurrence"] = recurrence if isinstance(recurrence, list) else [recurrence]
        if color_id == "":
            event.pop("colorId", None)
        elif color_id is not None:
            event["colorId"] = color_id

        params = {"calendarId": calendar_id, "eventId": event_id, "body": event, "sendUpdates": send_updates}
        if remove_meet:
            event.pop("conferenceData", None)
        elif add_meet:
            event["conferenceData"] = _meet_request()
        if add_meet or remove_meet:
            params["conferenceDataVersion"] = 1
        return self.service.events().update(**params).execute()

    def delete_event(self, event_id, calendar_id="primary", send_updates="all"):
        self.service.events().delete(
            calendarId=calendar_id, eventId=event_id, sendUpdates=send_updates
        ).execute()
        return True

    def quick_add_event(self, text, calendar_id="primary", send_updates="all"):
        return self.service.events().quickAdd(
            calendarId=calendar_id, text=text, sendUpdates=send_updates
        ).execute()

    def move_event(self, event_id, destination_calendar_id, calendar_id="primary", send_updates="all"):
        return self.service.events().move(
            calendarId=calendar_id,
            eventId=event_id,
            destination=destination_calendar_id,
            sendUpdates=send_updates,
        ).execute()

    def list_event_changes(
        self,
        calendar_id="primary",
        sync_token=None,
        page_token=None,
        max_results=250,
        single_events=False,
    ):
        params = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "showDeleted": True,
            "singleEvents": single_events,
            "fields": _EVENT_FIELDS,
        }
        if sync_token:
            params["syncToken"] = sync_token
        if page_token:
            params["pageToken"] = page_token
        try:
            result = self.service.events().list(**params).execute()
        except HttpError as error:
            if error.resp.status == 410:
                raise ValueError(_SYNC_EXPIRED) from error
            raise
        return {
            "events": [trim_event(e) for e in result.get("items", [])],
            "next_page_token": result.get("nextPageToken"),
            "new_sync_token": result.get("nextSyncToken"),
        }

    def create_status_event(
        self,
        event_type,
        start_time,
        end_time,
        timezone="UTC",
        calendar_id="primary",
        summary=None,
        decline_message=None,
        auto_decline=True,
    ):
        spec = _STATUS_EVENT_TYPES.get(event_type)
        if spec is None:
            raise ValueError('event_type must be "outOfOffice" or "focusTime"')
        if calendar_id not in (None, "", "primary"):
            raise ValueError("out-of-office and focus time only work on the primary calendar")
        calendar_id = "primary"
        if not start_time or not end_time:
            raise ValueError("start_time and end_time are required")
        start_dt = parse_datetime(start_time)
        end_dt = parse_datetime(end_time)
        if not start_dt or not end_dt:
            raise ValueError("start_time and end_time must be parseable datetimes")
        properties = {
            "autoDeclineMode": (
                "declineOnlyNewConflictingInvitations" if auto_decline else "declineNone"
            ),
            "declineMessage": decline_message or spec["decline_message"],
            **spec["extra"],
        }
        event = {
            "eventType": event_type,
            "summary": summary or spec["summary"],
            "transparency": "opaque",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone},
            spec["properties_key"]: properties,
        }
        return self.service.events().insert(calendarId=calendar_id, body=event).execute()
