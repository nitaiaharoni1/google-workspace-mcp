"""Gmail history-based change feed (subclass of upstream GmailAPI)."""
from __future__ import annotations

import base64
import re
from html import unescape

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


def _decode_body_data(data):
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", "replace")


def _html_to_text(html_body):
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", html_body)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _header_value(headers, name):
    target = name.lower()
    for header in headers or []:
        if (header.get("name") or "").lower() == target:
            return header.get("value") or ""
    return ""


_TEXT_MIMES = frozenset({"text/plain", "text/html"})


def _walk_parts(part, plains, htmls, attachments):
    if not part:
        return
    body = part.get("body") or {}
    mime = (part.get("mimeType") or "").split(";", 1)[0].strip().lower()
    filename = part.get("filename") or ""
    attachment_id = body.get("attachmentId")
    if attachment_id or (filename and mime not in _TEXT_MIMES):
        attachments.append(
            {
                "filename": filename,
                "mimeType": part.get("mimeType") or "",
                "size": body.get("size", 0),
                "attachmentId": attachment_id or "",
            }
        )
        return
    data = body.get("data")
    if data:
        if mime == "text/plain":
            plains.append(_decode_body_data(data))
        elif mime == "text/html":
            htmls.append(_decode_body_data(data))
    for child in part.get("parts") or []:
        _walk_parts(child, plains, htmls, attachments)


def project_message_text(message):
    payload = message.get("payload") or {}
    headers = payload.get("headers")
    plains, htmls, attachments = [], [], []
    _walk_parts(payload, plains, htmls, attachments)
    if plains:
        body_text = plains[0]
    elif htmls:
        body_text = _html_to_text(htmls[0])
    else:
        body_text = ""
    return {
        "id": message.get("id"),
        "threadId": message.get("threadId"),
        "labelIds": message.get("labelIds") or [],
        "subject": _header_value(headers, "Subject"),
        "from": _header_value(headers, "From"),
        "to": _header_value(headers, "To"),
        "cc": _header_value(headers, "Cc"),
        "date": _header_value(headers, "Date"),
        "snippet": message.get("snippet") or "",
        "body_text": body_text,
        "attachments": attachments,
    }


class GmailChangesAPI(GmailAPI):
    """GmailAPI plus the history-based change feed."""

    def _fetch_attachment_data(self, message_id, attachment_id):
        result = self.service.users().messages().attachments().get(
            userId=self.user_id, messageId=message_id, id=attachment_id
        ).execute()
        return result.get("data") or ""

    def _fill_hosted_text_body(self, message_id, projected):
        if projected.get("body_text"):
            return projected
        kept = []
        for att in projected.get("attachments") or []:
            mime = (att.get("mimeType") or "").split(";", 1)[0].strip().lower()
            attachment_id = att.get("attachmentId")
            if not projected.get("body_text") and mime in _TEXT_MIMES and attachment_id and not att.get("filename"):
                data = self._fetch_attachment_data(message_id, attachment_id)
                if mime == "text/plain":
                    projected["body_text"] = _decode_body_data(data)
                else:
                    projected["body_text"] = _html_to_text(_decode_body_data(data))
                continue
            kept.append(att)
        projected["attachments"] = kept
        return projected

    def get_message_text(self, message_id):
        return self._fill_hosted_text_body(
            message_id, project_message_text(self.get_message(message_id, format="full"))
        )

    def get_thread_text(self, thread_id):
        thread = self.get_thread(thread_id, format="full")
        return {
            "id": thread.get("id"),
            "historyId": thread.get("historyId"),
            "messages": [
                self._fill_hosted_text_body(m.get("id"), project_message_text(m))
                for m in thread.get("messages") or []
            ],
        }

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
