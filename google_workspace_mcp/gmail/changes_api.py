"""Gmail history-based change feed (subclass of upstream GmailAPI)."""
from __future__ import annotations

import base64
import re
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, getaddresses
from html import escape, unescape

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


def address_header(value):
    """Render To/Cc so only display names get RFC 2047 encoded.

    Upstream sets raw strings on compat32 MIME objects, which encode the whole
    header (address included) once any character is non-ASCII, e.g. a Hebrew
    display name. Gmail then rejects it with "Invalid To header".
    """
    if not value:
        return value
    values = [value] if isinstance(value, str) else list(value)
    return ", ".join(formataddr(pair) for pair in getaddresses(values) if pair[1])


# Hebrew, Arabic, Syriac, Thaana and their presentation forms.
_RTL_LETTER = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFC]")
_LTR_LETTER = re.compile(r"[A-Za-z\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF]")
_TAG = re.compile(r"(?s)<[^>]+>")
_HAS_DIR = re.compile(r"(?i)<[a-z][^>]*\sdir\s*=")
_URL = re.compile(r"https?://[^\s<>\"']+")

_TEXT_STYLE = "font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5"

SIGNATURE_ADDED = "added"
SIGNATURE_NONE = "none_configured"
SIGNATURE_OFF = "off"
SIGNATURE_PRESENT = "already_in_body"
_SIGNATURE_MARK = "gmail_signature"


def is_rtl(text):
    """Whether ``text`` reads right to left: it opens with a right-to-left
    letter, or has more of them than left-to-right ones. A Hebrew email full of
    English product names still opens in Hebrew, so the opening letter decides
    first."""
    text = text or ""
    first_rtl = _RTL_LETTER.search(text)
    if not first_rtl:
        return False
    first_ltr = _LTR_LETTER.search(text)
    if not first_ltr or first_rtl.start() < first_ltr.start():
        return True
    return len(_RTL_LETTER.findall(text)) > len(_LTR_LETTER.findall(text))


def _linked(escaped_line):
    return _URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped_line)


def text_to_html(text):
    """Plain text as HTML paragraphs: a blank line starts a paragraph, a single
    newline is a line break, and bare links stay clickable."""
    paragraphs = re.split(r"\n[ \t]*\n", (text or "").replace("\r\n", "\n").strip("\n"))
    out = []
    for paragraph in paragraphs:
        lines = [_linked(escape(line, quote=False)) for line in paragraph.split("\n")]
        out.append(f'<p style="margin:0 0 14px">{"<br>".join(lines)}</p>')
    # Outlook shows HTML that names no font in Times New Roman.
    return f'<div style="{_TEXT_STYLE}">{"".join(out)}</div>'


def rtl_block(inner_html):
    """``inner_html`` laid out right to left in every mail client. Direction
    and alignment sit on the content cell: Outlook ignores an outer ``dir``."""
    return (
        '<table role="presentation" width="100%" dir="rtl" style="direction:rtl" '
        'cellpadding="0" cellspacing="0" border="0"><tr>'
        '<td dir="rtl" align="right" style="direction:rtl;text-align:right">'
        f"{inner_html}</td></tr></table>"
    )


def signature_block(signature_html):
    """The signature the way Gmail's own composer appends it: after a ``--``
    line, in its own left-to-right block."""
    return (
        "<div><br></div><div>--&nbsp;</div>"
        f'<div dir="ltr" class="{_SIGNATURE_MARK}" data-smartmail="{_SIGNATURE_MARK}">'
        f"{signature_html}</div>"
    )


def compose_body(body, html=False, signature_html=""):
    """``(body, html)`` ready to send.

    Plain left-to-right text with no signature goes out untouched. Anything
    else becomes HTML: right-to-left text (Hebrew, Arabic) is wrapped so it
    reads from the right, since a plain-text part has no direction and mail
    clients show it from the left; and a signature is HTML to begin with.
    HTML that already sets a ``dir`` is trusted as written.
    """
    body = body or ""
    rtl = is_rtl(_TAG.sub(" ", unescape(body)) if html else body)
    if not html and not rtl and not signature_html:
        return body, False
    inner = body if html else text_to_html(body)
    if rtl and not (html and _HAS_DIR.search(body)):
        inner = rtl_block(inner)
    if signature_html:
        inner += signature_block(signature_html)
    return inner, True


def _with_signature_status(result, status):
    """Gmail's answer plus what happened to the signature, so the caller can
    say so instead of assuming."""
    if isinstance(result, dict):
        return {**result, "signature": status}
    return result


class GmailChangesAPI(GmailAPI):
    """GmailAPI plus the history-based change feed."""

    _signature_cache = None

    def default_signature(self):
        """The HTML signature of the address this account sends from by
        default, as set in Gmail's settings; ``""`` when it has none. Read once
        per client. A read that fails raises: a caller who asked for the
        signature must not get mail without it and never hear why."""
        if self._signature_cache is None:
            try:
                result = self.service.users().settings().sendAs().list(userId=self.user_id).execute()
            except HttpError as error:
                raise Exception(
                    f"Failed to read the Gmail signature: {error}. Pass signature=False to send "
                    "without it."
                )
            aliases = result.get("sendAs") or []
            chosen = next((a for a in aliases if a.get("isDefault")), None) or next(
                (a for a in aliases if a.get("isPrimary")), {}
            )
            self._signature_cache = (chosen.get("signature") or "").strip()
        return self._signature_cache

    def compose(self, body, html=False, signature=True):
        """``(body, html, signature_status)`` for an outgoing message: the
        account's Gmail signature appended (unless ``signature`` is False, it
        has none, or the body already carries one) and right-to-left text laid
        out from the right. See ``compose_body``."""
        if not signature:
            status, signature_html = SIGNATURE_OFF, ""
        elif _SIGNATURE_MARK in (body or ""):
            status, signature_html = SIGNATURE_PRESENT, ""
        else:
            signature_html = self.default_signature()
            status = SIGNATURE_ADDED if signature_html else SIGNATURE_NONE
        body, html = compose_body(body, html, signature_html)
        return body, html, status

    def send_message(self, to, subject, body, attachments=None, cc=None, html=False, signature=True):
        body, html, status = self.compose(body, html, signature)
        sent = super().send_message(
            address_header(to), subject, body, attachments=attachments, cc=address_header(cc), html=html
        )
        return _with_signature_status(sent, status)

    def create_draft(self, to, subject, body, attachments=None, cc=None, html=False, signature=True):
        body, html, status = self.compose(body, html, signature)
        draft = super().create_draft(
            address_header(to), subject, body, attachments=attachments, cc=address_header(cc), html=html
        )
        return _with_signature_status(draft, status)

    def update_draft(
        self, draft_id, to=None, subject=None, body=None, attachments=None, cc=None, html=False,
        signature=True,
    ):
        status = None
        if body is not None:
            body, html, status = self.compose(body, html, signature)
        draft = super().update_draft(
            draft_id, to=address_header(to), subject=subject, body=body,
            attachments=attachments, cc=address_header(cc), html=html,
        )
        return _with_signature_status(draft, status) if status else draft

    def forward_message(self, message_id, to, body=None, attachments=None):
        return super().forward_message(message_id, address_header(to), body=body, attachments=attachments)

    _own_address_cache = None

    def _own_address(self):
        if self._own_address_cache is None:
            self._own_address_cache = (self.get_profile().get("emailAddress") or "").lower()
        return self._own_address_cache

    def _other_recipients(self, headers, reply_to):
        """Everyone else on the original for a reply-all: its To and Cc, minus
        this account and whoever the reply already goes to, each address once.
        The original's To counts: a message sent to two people and answered
        with reply-all must reach the second one too."""
        skip = {address.lower() for _, address in getaddresses([reply_to])}
        skip.add(self._own_address())
        others = []
        named = [_header_value(headers, "To"), _header_value(headers, "Cc")]
        for name, address in getaddresses([value for value in named if value]):
            if address and address.lower() not in skip:
                skip.add(address.lower())
                others.append(formataddr((name, address)))
        return others

    def _build_reply(self, message_id, body, reply_all, additional_cc, attachments, html, signature):
        # Mirrors upstream reply_to_message/draft_reply, but the recipients are
        # read from the original's headers, so they go through address_header.
        original = self.get_message(message_id, format="full")
        headers = original.get("payload", {}).get("headers", [])
        subject = _header_value(headers, "Subject")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body, html, status = self.compose(body, html, signature)
        content = self._body_part(body, html)
        if attachments:
            reply = MIMEMultipart()
            reply.attach(content)
            self._attach_files(reply, attachments)
        else:
            reply = content
        # A Reply-To is where the sender asked answers to go.
        reply_to = _header_value(headers, "Reply-To") or _header_value(headers, "From")
        reply["to"] = address_header(reply_to)
        reply["subject"] = subject

        cc_list = []
        if reply_all:
            cc_list.extend(self._other_recipients(headers, reply_to))
        if additional_cc:
            cc_list.append(additional_cc)
        if cc_list:
            reply["cc"] = address_header(cc_list)

        message_id_header = _header_value(headers, "Message-ID")
        if message_id_header:
            earlier = _header_value(headers, "References")
            reply["In-Reply-To"] = message_id_header
            reply["References"] = f"{earlier} {message_id_header}".strip()

        message = {
            "raw": base64.urlsafe_b64encode(reply.as_bytes()).decode(),
            "threadId": original.get("threadId"),
        }
        return message, status

    def reply_to_message(
        self, message_id, body, reply_all=False, additional_cc=None, attachments=None, html=False,
        signature=True,
    ):
        message, status = self._build_reply(
            message_id, body, reply_all, additional_cc, attachments, html, signature
        )
        try:
            sent = self.service.users().messages().send(userId=self.user_id, body=message).execute()
        except HttpError as error:
            raise Exception(f"Failed to reply to message: {error}")
        return _with_signature_status(sent, status)

    def draft_reply(
        self, message_id, body, reply_all=False, additional_cc=None, attachments=None, html=False,
        signature=True,
    ):
        message, status = self._build_reply(
            message_id, body, reply_all, additional_cc, attachments, html, signature
        )
        try:
            draft = self.service.users().drafts().create(
                userId=self.user_id, body={"message": message}
            ).execute()
        except HttpError as error:
            raise Exception(f"Failed to create draft reply: {error}")
        return _with_signature_status(draft, status)

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
