"""Gmail history-based change feed (subclass of upstream GmailAPI)."""
from __future__ import annotations

from gmail_cli.api import GmailAPI
from googleapiclient.errors import HttpError

_HISTORY_EXPIRED = (
    "start_history_token expired or invalid; call get_changes_start_token for a "
    "fresh baseline, then do a full listing to resynchronize"
)


def normalize_history_records(history_records):
    """Flatten Gmail history[] records into typed change entries."""
    changes = []
    for record in history_records or []:
        for entry in record.get("messagesAdded", []):
            msg = entry.get("message", {})
            changes.append(
                {
                    "type": "message_added",
                    "message_id": msg.get("id"),
                    "thread_id": msg.get("threadId"),
                    "label_ids": msg.get("labelIds", []),
                }
            )
        for entry in record.get("messagesDeleted", []):
            msg = entry.get("message", {})
            changes.append(
                {
                    "type": "message_deleted",
                    "message_id": msg.get("id"),
                    "thread_id": msg.get("threadId"),
                }
            )
        for entry in record.get("labelsAdded", []):
            msg = entry.get("message", {})
            changes.append(
                {
                    "type": "labels_added",
                    "message_id": msg.get("id"),
                    "label_ids": entry.get("labelIds", []),
                }
            )
        for entry in record.get("labelsRemoved", []):
            msg = entry.get("message", {})
            changes.append(
                {
                    "type": "labels_removed",
                    "message_id": msg.get("id"),
                    "label_ids": entry.get("labelIds", []),
                }
            )
    return changes


class GmailChangesAPI(GmailAPI):
    """GmailAPI plus the history-based change feed."""

    def get_changes_start_token(self):
        profile = self.service.users().getProfile(userId=self.user_id).execute()
        return {
            "start_history_token": profile["historyId"],
            "email": profile["emailAddress"],
        }

    def list_changes(
        self,
        start_history_token,
        history_types=None,
        label_id=None,
        max_results=100,
        page_token=None,
    ):
        if not start_history_token:
            raise ValueError("start_history_token is required")
        params = {
            "userId": self.user_id,
            "startHistoryId": start_history_token,
            "maxResults": max_results,
        }
        if history_types:
            params["historyTypes"] = history_types
        if label_id:
            params["labelId"] = label_id
        if page_token:
            params["pageToken"] = page_token
        try:
            result = self.service.users().history().list(**params).execute()
        except HttpError as error:
            if error.resp.status == 404:
                raise ValueError(_HISTORY_EXPIRED) from error
            raise
        return {
            "changes": normalize_history_records(result.get("history")),
            "next_page_token": result.get("nextPageToken"),
            "new_history_token": result.get("historyId"),
        }
