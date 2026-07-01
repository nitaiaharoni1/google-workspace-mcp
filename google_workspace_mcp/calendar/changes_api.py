"""Calendar syncToken-based change feed (subclass of upstream CalendarAPI)."""
from __future__ import annotations

from google_calendar_cli.api import CalendarAPI
from googleapiclient.errors import HttpError

_SYNC_EXPIRED = (
    "sync_token expired; call list_event_changes without sync_token to re-baseline"
)

_EVENT_FIELDS = (
    "nextPageToken,nextSyncToken,"
    "items(id,status,summary,start,end,updated,organizer,recurringEventId)"
)


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
