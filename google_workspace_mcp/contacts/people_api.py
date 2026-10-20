"""Google People API wrapper: resolve a name to email addresses.

Searches three sources in order: saved contacts, "other contacts" (people the
account has emailed or been emailed by), and, for Workspace accounts, the
company directory.
"""
from __future__ import annotations

import google_auth_core as core

READ_MASK = "names,emailAddresses,phoneNumbers"
# searchContacts and otherContacts.search cap pageSize at 30.
_SEARCH_PAGE_MAX = 30
_DIRECTORY_PAGE_MAX = 500
_DIRECTORY_SOURCES = [
    "DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE",
    "DIRECTORY_SOURCE_TYPE_DOMAIN_CONTACT",
]

CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
OTHER_CONTACTS_SCOPE = "https://www.googleapis.com/auth/contacts.other.readonly"
DIRECTORY_SCOPE = "https://www.googleapis.com/auth/directory.readonly"

SOURCE_SCOPES = {
    "contact": CONTACTS_SCOPE,
    "other": OTHER_CONTACTS_SCOPE,
    "directory": DIRECTORY_SCOPE,
}


def _http_status(exc: Exception) -> int | None:
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _error_text(exc: Exception) -> str:
    content = getattr(exc, "content", b"") or b""
    if isinstance(content, bytes):
        content = content.decode(errors="replace")
    return f"{exc} {content}"


def _is_scope_error(exc: Exception) -> bool:
    text = _error_text(exc)
    return _http_status(exc) == 403 and (
        "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in text
        or "insufficient authentication scopes" in text.lower()
    )


def _is_api_disabled(exc: Exception) -> bool:
    text = _error_text(exc)
    return _http_status(exc) == 403 and (
        "SERVICE_DISABLED" in text or "accessNotConfigured" in text
    )


def _scope_error(account: str | None, scopes: list[str]) -> core.AuthError:
    return core.AuthError(
        "Contact search needs Google scopes this account's token does not have: "
        + ", ".join(scopes)
        + ". Update google-auth-core to a version that requests them, then re-run: "
        f"google-auth login {account or '<account>'}"
    )


def _api_disabled_error(exc: Exception) -> core.AuthError:
    return core.AuthError(
        "The Google People API is not enabled for your OAuth client's Cloud project. "
        "Enable it at https://console.cloud.google.com/apis/library/people.googleapis.com "
        f"and retry. ({core.map_exception(exc)})"
    )


def _shape(person: dict, source: str) -> dict:
    names = person.get("names") or []
    phones = person.get("phoneNumbers") or []
    return {
        "name": names[0].get("displayName") if names else None,
        "emails": [e["value"] for e in person.get("emailAddresses") or [] if e.get("value")],
        "phone": phones[0].get("value") if phones else None,
        "source": source,
    }


class PeopleAPI:
    def __init__(self, account=None):
        self.account = account
        self.service = core.get_service("people", "v1", account=account)
        self._warmed: set[str] = set()

    def _search_contacts(self, query: str, page_size: int) -> list[dict]:
        people = self.service.people()
        if "contact" not in self._warmed:
            # Google's search cache is only populated after an empty-query request.
            people.searchContacts(query="", readMask=READ_MASK).execute()
            self._warmed.add("contact")
        resp = people.searchContacts(
            query=query, readMask=READ_MASK, pageSize=min(page_size, _SEARCH_PAGE_MAX)
        ).execute()
        return [r["person"] for r in resp.get("results") or [] if r.get("person")]

    def _search_other(self, query: str, page_size: int) -> list[dict]:
        other = self.service.otherContacts()
        if "other" not in self._warmed:
            other.search(query="", readMask=READ_MASK).execute()
            self._warmed.add("other")
        resp = other.search(
            query=query, readMask=READ_MASK, pageSize=min(page_size, _SEARCH_PAGE_MAX)
        ).execute()
        return [r["person"] for r in resp.get("results") or [] if r.get("person")]

    def _search_directory(self, query: str, page_size: int) -> list[dict]:
        resp = self.service.people().searchDirectoryPeople(
            query=query,
            readMask=READ_MASK,
            sources=_DIRECTORY_SOURCES,
            pageSize=min(page_size, _DIRECTORY_PAGE_MAX),
        ).execute()
        return resp.get("people") or []

    def search(self, query: str, max_results: int = 10) -> dict:
        """Search all sources, dedupe by email, and report sources that were skipped.

        Raises AuthError when no source could be searched because of missing
        scopes, so the agent gets one actionable message instead of empty results.
        """
        searches = (
            ("contact", self._search_contacts),
            ("other", self._search_other),
            ("directory", self._search_directory),
        )
        results: list[dict] = []
        seen: set[str] = set()
        skipped: list[dict] = []
        missing_scopes: list[str] = []
        for source, fn in searches:
            if len(results) >= max_results:
                break
            try:
                people = fn(query, max_results)
            except Exception as e:  # noqa: BLE001 - classify per source below
                if _is_api_disabled(e):
                    raise _api_disabled_error(e) from e
                if _is_scope_error(e):
                    missing_scopes.append(SOURCE_SCOPES[source])
                    skipped.append({"source": source, "reason": f"token lacks {SOURCE_SCOPES[source]}"})
                    continue
                if source == "directory" and _http_status(e) in (400, 403):
                    # Personal Gmail accounts have no directory to search.
                    skipped.append({"source": source, "reason": str(core.map_exception(e))})
                    continue
                raise
            for person in people:
                item = _shape(person, source)
                keys = {e.lower() for e in item["emails"]}
                # Phone-only entries can't be emailed or invited; don't let them crowd out ones that can.
                if not keys or keys & seen:
                    continue
                seen |= keys
                results.append(item)
                if len(results) >= max_results:
                    break
        if missing_scopes and not results and len(skipped) == len(searches):
            raise _scope_error(self.account, missing_scopes)
        return {"results": results, "skipped": skipped}
