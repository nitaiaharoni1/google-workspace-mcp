"""Outgoing Gmail bodies: right-to-left layout and the account's signature.

A plain-text part has no direction, so a Hebrew email sent as text shows from
the left in Gmail and Outlook, and mail created through the API never gets the
signature Gmail's own composer adds. ``compose_body`` and
``GmailChangesAPI.compose`` fix both for every send, reply and draft.
"""
from __future__ import annotations

import base64
import email
from email import policy

import pytest
from googleapiclient.errors import HttpError

from google_workspace_mcp.gmail import changes_api
from google_workspace_mcp.gmail.changes_api import GmailChangesAPI, compose_body, is_rtl

HEBREW = "היי אפרת,\n\nמתחילים ב-HTTP עד שהתעודה תהיה מוכנה.\nתודה"
SIGNATURE = '<div><b>Nitai Aharoni</b><br>VP R&amp;D | Vistral</div>'


@pytest.mark.parametrize(
    "text,expected",
    [
        ("היי אפרת", True),
        ("שלום, the API address is https://api.example.com and the key stays the same", True),
        ("Hi Efrat, the button says שלח לינק", False),
        ("مرحبا", True),
        ("Hi David", False),
        ("", False),
        ("12345 :-)", False),
    ],
)
def test_direction_follows_the_opening_letter_then_the_majority(text, expected):
    assert is_rtl(text) is expected


def test_plain_english_without_a_signature_is_left_untouched():
    assert compose_body("Hi David,\n\nThanks", False, "") == ("Hi David,\n\nThanks", False)


def test_plain_hebrew_becomes_right_to_left_html():
    body, html = compose_body(HEBREW, False, "")

    assert html is True
    assert 'dir="rtl"' in body and "text-align:right" in body
    # A blank line is a paragraph, a single newline a line break.
    assert body.count("<p ") == 2
    assert "מוכנה.<br>תודה" in body
    # Named, or Outlook falls back to Times New Roman.
    assert "font-family:Arial" in body


def test_plain_text_is_escaped_and_links_stay_clickable():
    body, _ = compose_body("שלום <script> & https://api.vistralai.com/x?a=1", False, "")

    assert "&lt;script&gt;" in body and "<script>" not in body
    assert '<a href="https://api.vistralai.com/x?a=1">https://api.vistralai.com/x?a=1</a>' in body


def test_hebrew_html_without_a_direction_is_wrapped_and_one_with_it_is_trusted():
    bare, _ = compose_body("<p>היי אפרת</p>", True, "")
    own = '<div dir="rtl"><p>היי אפרת</p></div>'
    kept, _ = compose_body(own, True, "")

    assert bare.startswith("<table") and 'dir="rtl"' in bare
    assert kept == own


def test_the_signature_follows_the_body_in_its_own_left_to_right_block():
    body, html = compose_body("Hi David", False, SIGNATURE)

    assert html is True
    assert body.index("Hi David") < body.index("--&nbsp;") < body.index(SIGNATURE)
    assert '<div dir="ltr" class="gmail_signature"' in body
    assert 'dir="rtl"' not in body


def test_a_hebrew_body_keeps_the_signature_outside_the_right_to_left_block():
    body, _ = compose_body(HEBREW, False, SIGNATURE)

    assert body.index("</table>") < body.index(SIGNATURE)


# ── the API wrapper ──────────────────────────────────────────────────────────


class _Call:
    def __init__(self, result=None, error=None):
        self._result, self._error = result, error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class _Service:
    """The slice of the Gmail client the wrapper touches, recording what is sent."""

    def __init__(self, send_as=None, original=None, send_as_error=None):
        self.send_as = send_as if send_as is not None else []
        self.send_as_error = send_as_error
        self.original = original or {}
        self.send_as_reads = 0
        self.sent: list[dict] = []
        self.created_drafts: list[dict] = []

    def users(self):
        return self

    def settings(self):
        return self

    def sendAs(self):  # noqa: N802 (Gmail's name)
        return self

    def messages(self):
        return self

    def drafts(self):
        return _Drafts(self)

    def getProfile(self, userId):  # noqa: N802, N803 (Gmail's names)
        return _Call({"emailAddress": "Me@Example.com"})

    def list(self, userId):  # noqa: N803
        self.send_as_reads += 1
        return _Call({"sendAs": self.send_as}, self.send_as_error)

    def get(self, userId, id, format=None):  # noqa: N803, A002
        return _Call(self.original)

    def send(self, userId, body):  # noqa: N803
        self.sent.append(body)
        return _Call({"id": "sent1", "threadId": body.get("threadId")})


class _Drafts:
    def __init__(self, service):
        self._service = service

    def create(self, userId, body):  # noqa: N803
        self._service.created_drafts.append(body)
        return _Call({"id": "draft1", "message": {"id": "m1"}})


def _api(service) -> GmailChangesAPI:
    api = GmailChangesAPI.__new__(GmailChangesAPI)
    api.service = service
    api.user_id = "me"
    return api


def _original(**headers):
    base = {"From": "Efrat <efrat@example.co.il>", "Subject": "RE: FW: Integrations", "Message-ID": "<m1@x>"}
    base.update(headers)
    return {
        "threadId": "thread1",
        "payload": {"headers": [{"name": k, "value": v} for k, v in base.items()]},
    }


def _parsed(raw_message: dict):
    return email.message_from_bytes(
        base64.urlsafe_b64decode(raw_message["raw"]), policy=policy.default
    )


def _html_of(message) -> str:
    part = message.get_body(preferencelist=("html",))
    return part.get_content() if part else ""


def _http_error(status=403):
    class _Resp:
        def __init__(self):
            self.status, self.reason = status, "Forbidden"

    return HttpError(_Resp(), b'{"error": {"message": "insufficient scope"}}')


def test_the_default_address_signature_is_read_once_per_client():
    service = _Service(
        send_as=[
            {"sendAsEmail": "old@example.com", "signature": "<i>old</i>"},
            {"sendAsEmail": "me@example.com", "isDefault": True, "signature": SIGNATURE},
        ]
    )
    api = _api(service)

    assert api.default_signature() == SIGNATURE
    assert api.default_signature() == SIGNATURE
    assert service.send_as_reads == 1


def test_an_account_with_no_signature_sends_plain_english_as_before():
    api = _api(_Service(send_as=[{"sendAsEmail": "me@example.com", "isDefault": True}]))

    assert api.compose("Hi David") == ("Hi David", False, changes_api.SIGNATURE_NONE)


def test_signature_off_never_reads_the_settings():
    service = _Service(send_as_error=_http_error())
    api = _api(service)

    assert api.compose("Hi David", signature=False) == ("Hi David", False, changes_api.SIGNATURE_OFF)
    assert service.send_as_reads == 0


def test_a_body_that_already_carries_a_signature_gets_no_second_one():
    api = _api(_Service(send_as=[{"isDefault": True, "signature": SIGNATURE}]))
    body = '<p>Hi</p><div class="gmail_signature">mine</div>'

    out, html, status = api.compose(body, html=True)

    assert (out, html, status) == (body, True, changes_api.SIGNATURE_PRESENT)


def test_a_signature_that_cannot_be_read_fails_the_send_and_says_how_to_go_on():
    api = _api(_Service(send_as_error=_http_error()))

    with pytest.raises(Exception, match="signature=False"):
        api.compose("Hi David")


def test_a_hebrew_reply_goes_out_right_to_left_with_the_signature_in_its_thread():
    service = _Service(
        send_as=[{"isDefault": True, "signature": SIGNATURE}],
        original=_original(References="<m0@x>", Cc="Eli <eli@example.co.il>"),
    )
    api = _api(service)

    result = api.reply_to_message("orig1", HEBREW, additional_cc="yoni@example.com")

    (sent,) = service.sent
    message = _parsed(sent)
    html = _html_of(message)
    assert result["signature"] == changes_api.SIGNATURE_ADDED
    assert sent["threadId"] == "thread1"
    assert message["to"] == "Efrat <efrat@example.co.il>"
    # reply_all is off: the original's Cc is not copied, the extra one is.
    assert message["cc"] == "yoni@example.com"
    assert message["subject"] == "RE: FW: Integrations"
    assert message["In-Reply-To"] == "<m1@x>"
    assert message["References"] == "<m0@x> <m1@x>"
    assert 'dir="rtl"' in html and "היי אפרת" in html and SIGNATURE in html
    # Clients that show text only still get the words.
    assert "היי אפרת" in message.get_body(preferencelist=("plain",)).get_content()


def test_an_english_reply_without_a_signature_stays_a_plain_text_message():
    service = _Service(send_as=[{"isDefault": True}], original=_original(Subject="Hello"))
    api = _api(service)

    api.reply_to_message("orig1", "Thanks David")

    message = _parsed(service.sent[0])
    assert message.get_content_type() == "text/plain"
    assert message["subject"] == "Re: Hello"


def test_a_reply_with_an_attachment_keeps_the_html_and_the_file(tmp_path):
    spec = tmp_path / "spec.pdf"
    spec.write_bytes(b"%PDF-1.4 test")
    service = _Service(send_as=[{"isDefault": True, "signature": SIGNATURE}], original=_original())
    api = _api(service)

    api.reply_to_message("orig1", HEBREW, attachments=[str(spec)])

    message = _parsed(service.sent[0])
    assert message.get_content_type() == "multipart/mixed"
    assert 'dir="rtl"' in _html_of(message)
    assert [part.get_filename() for part in message.iter_attachments()] == ["spec.pdf"]


def test_a_hebrew_draft_reply_is_stored_right_to_left_with_the_signature():
    service = _Service(send_as=[{"isDefault": True, "signature": SIGNATURE}], original=_original())
    api = _api(service)

    result = api.draft_reply("orig1", HEBREW)

    (draft,) = service.created_drafts
    html = _html_of(_parsed(draft["message"]))
    assert result["signature"] == changes_api.SIGNATURE_ADDED
    assert draft["message"]["threadId"] == "thread1"
    assert 'dir="rtl"' in html and SIGNATURE in html
    assert service.sent == []


def test_reply_all_reaches_the_other_to_recipients_and_never_this_account():
    service = _Service(
        send_as=[{"isDefault": True}],
        original=_original(
            From="Efrat <efrat@example.co.il>",
            To="Me <me@example.com>, Eli <eli@example.co.il>",
            Cc="Vladimir <vlad@example.co.il>, eli@example.co.il, EFRAT@example.co.il",
        ),
    )
    api = _api(service)

    api.reply_to_message("orig1", "Thanks", reply_all=True, additional_cc="yoni@example.com")

    message = _parsed(service.sent[0])
    assert message["to"] == "Efrat <efrat@example.co.il>"
    assert [a.addr_spec for a in message["cc"].addresses] == [
        "eli@example.co.il",
        "vlad@example.co.il",
        "yoni@example.com",
    ]


def test_a_reply_goes_to_the_reply_to_address_when_the_sender_set_one():
    service = _Service(
        send_as=[{"isDefault": True}],
        original=_original(**{"Reply-To": "Support <support@example.co.il>"}),
    )
    api = _api(service)

    api.reply_to_message("orig1", "Thanks")

    assert _parsed(service.sent[0])["to"] == "Support <support@example.co.il>"
