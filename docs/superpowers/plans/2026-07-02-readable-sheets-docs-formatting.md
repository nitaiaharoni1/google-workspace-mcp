# Human-Readable Sheets & Docs Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent-written Sheets and Docs readable by humans without manual cleanup: a markdown pipeline for Docs, content-aware column sizing for Sheets, one-shot table writing, and no more unnecessary frozen panes.

**Architecture:** Docs gains four markdown tools backed by Drive's native markdown↔Doc conversion (`text/markdown` import/export, available since 2024) — the agent writes markdown, Google renders real headings/lists/tables. Sheets gains a pure width-planning heuristic (`plan_column_layout`) shared by a new `optimize_layout` tool, a reworked `format_table` (no more unbounded `autoResizeDimensions`, `freeze_header` off by default), and a new `write_table` one-shot tool (values + native table/banding + layout). All tools follow the existing `@register` / `_api` / `run_tool` / `ok` contract in `core/runtime.py`.

**Tech Stack:** Python 3.10+, google-api-python-client (Sheets v4, Docs v1, Drive v3), FastMCP, pytest with MagicMock service mocks.

**Why these choices (design decisions):**
- *Docs markdown via Drive conversion, not Docs batchUpdate*: Drive `files.create`/`files.update` with `text/markdown` media converts headings, bold, lists, links, and tables into native Docs elements in one call. The Docs API has no markdown support; reproducing it with `insertText`+`updateTextStyle` is exactly the tedium the user wants to avoid.
- *Column width heuristic = "auto-fit with a cap"*: `width = clamp(14 + 7 × longest_line_chars, min, max)` (Arial 10 ≈ 7 px/char + ~14 px padding). Columns whose content exceeds the cap get `WRAP` + `TOP` vertical alignment; all other columns get `OVERFLOW_CELL` (normalizes previously over-wrapped sheets); row heights auto-fit at the end. This directly solves "not too much horizontal scroll, not too many wrapped lines".
- *Google's `autoResizeDimensions` for COLUMNS is the bug, not the fix*: it sizes a column to its longest cell with no cap, producing the huge horizontal scroll the user complains about. It stays only for ROWS (height auto-fit).
- *`freeze_header` defaults to False* and `freeze_panes` docstring steers the model away from freezing unless asked.
- *`.md` uploads were converting as `text/plain`* (`drive_api.py` `CONVERSION_SOURCE_MIMES`), which dumps literal `#`/`**` characters into the Doc. Fixed to `text/markdown`.

**Out of scope:** Slides, release/version bump, live smoke tests (run manually with `GOOGLE_MCP_LIVE=1` after merge if desired), append-at-position markdown in Docs (append is whole-doc round-trip; positional insert stays with the existing index tools).

---

## File Structure

- Modify: `google_workspace_mcp/drive/drive_api.py` — `.md`/`.markdown` conversion source mime → `text/markdown` (Task 1).
- Modify: `google_workspace_mcp/docs/docs_api.py` — `_drive()` helper + 4 markdown methods (Task 2).
- Modify: `google_workspace_mcp/docs/server.py` — 4 markdown tools + server description (Task 3).
- Modify: `google_workspace_mcp/sheets/sheets_api.py` — column helpers, `plan_column_layout`, `_layout_requests`, `optimize_layout`, `format_table` rework, `write_table`, `add_table` optional name (Tasks 4–7).
- Modify: `google_workspace_mcp/sheets/server.py` — `optimize_layout` + `write_table` tools, `format_table` signature, `freeze_panes` docstring, server description (Tasks 5–8).
- Test: `tests/test_drive_server.py`, `tests/test_docs_server.py`, `tests/test_sheets_server.py`.
- Docs: `README.md` (Task 9).

---

### Task 1: Drive — convert `.md` uploads as real markdown

**Files:**
- Modify: `google_workspace_mcp/drive/drive_api.py:21-22`
- Test: `tests/test_drive_server.py`

- [ ] **Step 1: Update the existing conversion test and add a unit test**

In `tests/test_drive_server.py`, find `test_upload_file_converts_to_google_doc` and change its last assertion:

```python
    assert kwargs["media_body"].mimetype() == "text/markdown"
```

Then add below it (add `_resolve_upload_mimes` and `DOCUMENT_MIME` to the existing `from google_workspace_mcp.drive.drive_api import ...` line at the top of the file):

```python
def test_resolve_upload_mimes_markdown():
    target, media = _resolve_upload_mimes("plan.md", DOCUMENT_MIME)
    assert (target, media) == (DOCUMENT_MIME, "text/markdown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_drive_server.py -k "upload_file_converts or resolve_upload_mimes_markdown" -v`
Expected: FAIL — `'text/plain' == 'text/markdown'` assertion errors.

- [ ] **Step 3: Fix the mime map**

In `google_workspace_mcp/drive/drive_api.py`, change the two entries in `CONVERSION_SOURCE_MIMES`:

```python
    ".md": "text/markdown",
    ".markdown": "text/markdown",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_drive_server.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add tests/test_drive_server.py google_workspace_mcp/drive/drive_api.py
git commit -m "fix(drive): import .md uploads as text/markdown so Docs conversion renders formatting"
```

---

### Task 2: DocsAPI markdown methods

**Files:**
- Modify: `google_workspace_mcp/docs/docs_api.py`
- Test: `tests/test_docs_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_docs_server.py` (after the existing DocsAPI unit tests; `_api_with_mock` already exists at the top of the file):

```python
def test_create_document_from_markdown(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().create().execute.return_value = {
        "id": "D9", "name": "Spec",
        "mimeType": "application/vnd.google-apps.document",
        "webViewLink": "https://docs.google.com/document/d/D9",
    }
    out = api.create_document_from_markdown("Spec", "# Title\n\nBody", folder_id="F1")
    assert out["documentId"] == "D9"
    assert out["title"] == "Spec"
    _, kwargs = svc.files().create.call_args
    assert kwargs["body"] == {
        "name": "Spec",
        "mimeType": "application/vnd.google-apps.document",
        "parents": ["F1"],
    }
    assert kwargs["media_body"].mimetype() == "text/markdown"


def test_create_document_from_markdown_no_folder(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().create().execute.return_value = {"id": "D9", "name": "Spec"}
    api.create_document_from_markdown("Spec", "# T")
    _, kwargs = svc.files().create.call_args
    assert "parents" not in kwargs["body"]


def test_replace_document_with_markdown(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().update().execute.return_value = {"id": "D1", "name": "Doc"}
    out = api.replace_document_with_markdown("D1", "# New")
    assert out == {"documentId": "D1", "title": "Doc", "replaced": True}
    _, kwargs = svc.files().update.call_args
    assert kwargs["fileId"] == "D1"
    assert kwargs["media_body"].mimetype() == "text/markdown"


def test_read_document_as_markdown(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().export().execute.return_value = b"# Hi\n"
    out = api.read_document_as_markdown("D1")
    assert out == {"documentId": "D1", "markdown": "# Hi\n"}
    svc.files().export.assert_called_with(fileId="D1", mimeType="text/markdown")


def test_append_markdown_round_trips(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().export().execute.return_value = b"# Existing\n\nBody\n"
    svc.files().update().execute.return_value = {"id": "D1", "name": "Doc"}
    out = api.append_markdown("D1", "## Added")
    assert out == {"documentId": "D1", "title": "Doc", "appended": True}
    _, kwargs = svc.files().update.call_args
    media = kwargs["media_body"]
    assert media.getbytes(0, media.size()) == b"# Existing\n\nBody\n\n## Added"


def test_append_markdown_to_empty_doc(monkeypatch):
    api, svc = _api_with_mock(monkeypatch)
    svc.files().export().execute.return_value = b"\n"
    svc.files().update().execute.return_value = {"id": "D1", "name": "Doc"}
    api.append_markdown("D1", "# First")
    _, kwargs = svc.files().update.call_args
    media = kwargs["media_body"]
    assert media.getbytes(0, media.size()) == b"# First"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_docs_server.py -k markdown -v`
Expected: FAIL — `AttributeError: ... has no attribute 'create_document_from_markdown'` (and siblings).

- [ ] **Step 3: Implement the DocsAPI methods**

In `google_workspace_mcp/docs/docs_api.py`, add a constant near the top (after `NUMBERED_BULLET_PRESETS`):

```python
DOCUMENT_MIME = "application/vnd.google-apps.document"
```

Add these methods to `DocsAPI` (place them right before `_upload_public_image_uri`):

```python
    # --- markdown (via Drive import/export conversion) ---

    def _drive(self, account=None):
        return core.get_service("drive", "v3", account=account or self.account)

    def _markdown_media(self, markdown):
        return MediaIoBaseUpload(
            io.BytesIO(markdown.encode("utf-8")), mimetype="text/markdown", resumable=True
        )

    def create_document_from_markdown(self, title, markdown, folder_id=None):
        """Create a Google Doc by importing markdown (Drive converts it to native formatting)."""
        body = {"name": title, "mimeType": DOCUMENT_MIME}
        if folder_id:
            body["parents"] = [folder_id]
        created = self._drive().files().create(
            body=body,
            media_body=self._markdown_media(markdown),
            fields="id, name, mimeType, webViewLink",
        ).execute()
        return {
            "documentId": created.get("id"),
            "title": created.get("name"),
            "webViewLink": created.get("webViewLink"),
        }

    def replace_document_with_markdown(self, document_id, markdown):
        """Replace a document's entire content by re-importing markdown."""
        updated = self._drive().files().update(
            fileId=document_id,
            media_body=self._markdown_media(markdown),
            fields="id, name, mimeType",
        ).execute()
        return {
            "documentId": updated.get("id"),
            "title": updated.get("name"),
            "replaced": True,
        }

    def read_document_as_markdown(self, document_id):
        """Export a document as markdown text."""
        data = self._drive().files().export(
            fileId=document_id, mimeType="text/markdown"
        ).execute()
        text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else str(data)
        return {"documentId": document_id, "markdown": text}

    def append_markdown(self, document_id, markdown):
        """Append markdown by exporting the doc as markdown, concatenating, and re-importing.

        The whole document round-trips through markdown, so elements markdown
        cannot express (comments, suggestions, positioned images) are lost.
        """
        current = self.read_document_as_markdown(document_id)["markdown"]
        combined = markdown if not current.strip() else current.rstrip("\n") + "\n\n" + markdown
        updated = self.replace_document_with_markdown(document_id, combined)
        return {"documentId": document_id, "title": updated.get("title"), "appended": True}
```

Also refactor `_upload_public_image_uri` to reuse the helper — replace its first line:

```python
        drive = self._drive(account)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_docs_server.py -v`
Expected: PASS (all, including the pre-existing chart tests that exercise `_upload_public_image_uri`).

- [ ] **Step 5: Commit**

```bash
git add tests/test_docs_server.py google_workspace_mcp/docs/docs_api.py
git commit -m "feat(docs): markdown create/replace/append/read via Drive conversion"
```

---

### Task 3: Docs server markdown tools

**Files:**
- Modify: `google_workspace_mcp/docs/server.py`
- Test: `tests/test_docs_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_docs_server.py` (bottom of file):

```python
# --- markdown tools (server level) ---

@pytest.fixture
def patched_docs_server(monkeypatch):
    fake = MagicMock(spec=DocsAPI)
    monkeypatch.setattr(server, "_api", lambda account=None: (fake, "test@x.com"))
    return fake


@pytest.mark.anyio
async def test_markdown_tools_registered():
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    assert {
        "create_document_from_markdown", "replace_document_with_markdown",
        "append_markdown", "read_document_as_markdown",
    } <= names


@pytest.mark.anyio
async def test_create_document_from_markdown_tool(patched_docs_server):
    patched_docs_server.create_document_from_markdown.return_value = {"documentId": "D9"}
    raw = await server.mcp.call_tool("create_document_from_markdown", {
        "title": "Spec", "markdown": "# T",
    })
    payload = envelope(raw)
    assert payload["ok"] is True
    assert payload["account"] == "test@x.com"
    assert payload["data"]["documentId"] == "D9"
    patched_docs_server.create_document_from_markdown.assert_called_once_with("Spec", "# T", None)


@pytest.mark.anyio
async def test_replace_document_with_markdown_tool(patched_docs_server):
    patched_docs_server.replace_document_with_markdown.return_value = {"replaced": True}
    raw = await server.mcp.call_tool("replace_document_with_markdown", {
        "document_id": "D1", "markdown": "# New",
    })
    assert envelope(raw)["ok"] is True
    patched_docs_server.replace_document_with_markdown.assert_called_once_with("D1", "# New")


@pytest.mark.anyio
async def test_append_markdown_tool(patched_docs_server):
    patched_docs_server.append_markdown.return_value = {"appended": True}
    raw = await server.mcp.call_tool("append_markdown", {
        "document_id": "D1", "markdown": "## More",
    })
    assert envelope(raw)["ok"] is True
    patched_docs_server.append_markdown.assert_called_once_with("D1", "## More")


@pytest.mark.anyio
async def test_read_document_as_markdown_tool(patched_docs_server):
    patched_docs_server.read_document_as_markdown.return_value = {"markdown": "# Hi"}
    raw = await server.mcp.call_tool("read_document_as_markdown", {"document_id": "D1"})
    assert envelope(raw)["data"]["markdown"] == "# Hi"
    patched_docs_server.read_document_as_markdown.assert_called_once_with("D1")
```

(The `anyio_backend` fixture already at the top of this file covers these async tests.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_docs_server.py -k "tool or registered" -v`
Expected: FAIL — `Unknown tool: create_document_from_markdown`.

- [ ] **Step 3: Register the tools and update the server description**

In `google_workspace_mcp/docs/server.py`, change the `build_server` call:

```python
mcp = build_server(
    "gdocs-mcp",
    "Google Docs: create, read, and edit documents for one or more Google accounts. "
    "For formatted content (headings, lists, tables, bold), prefer the markdown tools "
    "(create_document_from_markdown, replace_document_with_markdown, append_markdown) "
    "over element-by-element insert/format calls.",
)
```

Add the tools after `read_document` / before `get_content_map` (read tool with the reads, write tools in the write section):

```python
@register(mcp)
def read_document_as_markdown(account: str | None = None, document_id: str = "") -> dict:
    """Read a document as markdown, preserving headings, lists, tables, and links (unlike read_document's plain text)."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.read_document_as_markdown(document_id)))
```

And in the write section (after `create_document`):

```python
@register(mcp, mutating=True)
def create_document_from_markdown(account: str | None = None, title: str = "", markdown: str = "", folder_id: str | None = None) -> dict:
    """Create a Google Doc from markdown text: headings, bold/italic, lists, links, and tables become native Docs formatting. Prefer this over create_document + insert/format calls for formatted content."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.create_document_from_markdown(title, markdown, folder_id)))


@register(mcp, mutating=True, destructive=True)
def replace_document_with_markdown(account: str | None = None, document_id: str = "", markdown: str = "") -> dict:
    """Replace a document's ENTIRE content by re-importing markdown. Comments/suggestions are lost."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.replace_document_with_markdown(document_id, markdown)))


@register(mcp, mutating=True, destructive=True)
def append_markdown(account: str | None = None, document_id: str = "", markdown: str = "") -> dict:
    """Append markdown to the end of a document. Round-trips the whole doc through markdown export/import, so elements markdown cannot express (comments, positioned images) are lost."""
    api, resolved = _api(account)
    return ok(resolved, run_tool(lambda: api.append_markdown(document_id, markdown)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_docs_server.py tests/test_integration.py -v`
Expected: PASS. (`test_integration.py` re-checks the read-only gate: the two destructive + one mutating tool must disappear under `GOOGLE_MCP_READONLY`; `@register(mutating=True)` handles this — no extra work.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_docs_server.py google_workspace_mcp/docs/server.py
git commit -m "feat(docs): expose markdown tools on gdocs-mcp"
```

---

### Task 4: Sheets — pure column-layout heuristic

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_sheets_server.py` (as a new top-level class after `TestSheetsAPIUnit`), and extend the import at the top of the file:

```python
from google_workspace_mcp.sheets.sheets_api import SheetsAPI, plan_column_layout
```

```python
class TestPlanColumnLayout:
    """Pure width/wrap heuristic: clamp(14 + 7*chars, min, max); wrap past the cap."""

    def test_short_columns_get_snug_min_width(self):
        plans = plan_column_layout([["Name", "Age"], ["Ann", "7"], ["Bob", "12"]])
        assert plans == [
            {"index": 0, "width": 48, "wrap": False},
            {"index": 1, "width": 48, "wrap": False},
        ]

    def test_medium_column_fits_content(self):
        # longest cell 20 chars -> 14 + 7*20 = 154
        plans = plan_column_layout([["Header"], ["x" * 20]])
        assert plans == [{"index": 0, "width": 154, "wrap": False}]

    def test_long_text_capped_and_wrapped(self):
        plans = plan_column_layout([["Notes"], ["x" * 100]])
        assert plans == [{"index": 0, "width": 320, "wrap": True}]

    def test_multiline_cell_uses_longest_line(self):
        # longest LINE is 30 chars -> 14 + 210 = 224, no wrap needed
        plans = plan_column_layout([["h"], ["short\n" + "y" * 30]])
        assert plans == [{"index": 0, "width": 224, "wrap": False}]

    def test_empty_column_skipped(self):
        plans = plan_column_layout([["a", ""], ["b", ""]])
        assert [p["index"] for p in plans] == [0]

    def test_numbers_are_stringified(self):
        plans = plan_column_layout([[12345678]])
        assert plans == [{"index": 0, "width": 70, "wrap": False}]

    def test_ragged_rows_use_widest_row(self):
        plans = plan_column_layout([["a"], ["b", "cc"]])
        assert [p["index"] for p in plans] == [0, 1]

    def test_custom_caps(self):
        plans = plan_column_layout([["x" * 100]], min_width=60, max_width=200)
        assert plans == [{"index": 0, "width": 200, "wrap": True}]

    def test_empty_values(self):
        assert plan_column_layout([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_server.py::TestPlanColumnLayout -v`
Expected: FAIL — `ImportError: cannot import name 'plan_column_layout'`.

- [ ] **Step 3: Implement the helper**

In `google_workspace_mcp/sheets/sheets_api.py`, add module-level code after the imports (before `class SheetsAPI`):

```python
# Width heuristic for the default Sheets font (Arial 10):
# ~7 px per character plus ~14 px of cell padding/border.
CHAR_PX = 7
CELL_PADDING_PX = 14


def _col_to_index(letters):
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _index_to_col(idx):
    letters = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def plan_column_layout(values, min_width=48, max_width=320):
    """Pick a pixel width and wrap flag per column from formatted cell values.

    Width fits the longest line in the column ("auto-fit"), clamped to
    [min_width, max_width]; columns whose content exceeds the cap are flagged
    for wrapping instead of growing wider. Empty columns are skipped so their
    existing width is left untouched. Returns [{"index", "width", "wrap"}].
    """
    n_cols = max((len(r) for r in values), default=0)
    plans = []
    for col in range(n_cols):
        max_len = 0
        for row in values:
            cell = row[col] if col < len(row) else ""
            text = cell if isinstance(cell, str) else str(cell)
            for line in text.splitlines():
                max_len = max(max_len, len(line))
        if max_len == 0:
            continue
        needed = CELL_PADDING_PX + CHAR_PX * max_len
        plans.append({
            "index": col,
            "width": max(min_width, min(max_width, needed)),
            "wrap": needed > max_width,
        })
    return plans
```

Also DRY the existing duplicate: in `_cell_part_to_grid`, delete the nested `col_to_index` function and change its two call sites to use the module-level `_col_to_index`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_server.py -v`
Expected: PASS (all, including existing grid-range tests that exercise `_cell_part_to_grid`).

- [ ] **Step 5: Commit**

```bash
git add tests/test_sheets_server.py google_workspace_mcp/sheets/sheets_api.py
git commit -m "feat(sheets): content-aware column layout heuristic"
```

---

### Task 5: Sheets — `optimize_layout` API method + tool

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py`
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API-level tests**

Add inside the class that owns the `api_with_meta` fixture (the fixture returns a mock whose `spreadsheets().get` yields `{"sheets": [{"properties": {"sheetId": 7, "title": "Tab"}}]}`):

```python
    def test_optimize_layout_range(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().get.return_value.execute.return_value = {
            "values": [["Name", "Notes"], ["Ann", "x" * 100]],
        }
        out = api.optimize_layout("sid", "Tab!A1:B2")
        requests = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"]
        # col A: snug width, no wrap (normalized to OVERFLOW_CELL)
        assert requests[0]["updateDimensionProperties"] == {
            "range": {"sheetId": 7, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 48},
            "fields": "pixelSize",
        }
        assert requests[1]["repeatCell"]["cell"]["userEnteredFormat"] == {
            "wrapStrategy": "OVERFLOW_CELL",
        }
        # col B: capped width + wrap, top-aligned
        assert requests[2]["updateDimensionProperties"]["properties"]["pixelSize"] == 320
        assert requests[3]["repeatCell"]["cell"]["userEnteredFormat"] == {
            "wrapStrategy": "WRAP", "verticalAlignment": "TOP",
        }
        assert requests[3]["repeatCell"]["range"] == {
            "sheetId": 7, "startRowIndex": 0, "endRowIndex": 2,
            "startColumnIndex": 1, "endColumnIndex": 2,
        }
        # rows auto-fit last
        assert requests[-1]["autoResizeDimensions"]["dimensions"] == {
            "sheetId": 7, "dimension": "ROWS", "startIndex": 0, "endIndex": 2,
        }
        assert out["columns"] == [
            {"column": "A", "width": 48, "wrap": False},
            {"column": "B", "width": 320, "wrap": True},
        ]
        assert out["requests_sent"] == 5

    def test_optimize_layout_bare_sheet_name(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["hi"]]}
        api.optimize_layout("sid", "Tab")
        svc.spreadsheets().values().get.assert_called_with(
            spreadsheetId="sid", range="'Tab'", valueRenderOption="FORMATTED_VALUE",
        )

    def test_optimize_layout_unknown_sheet(self, api_with_meta):
        api, _svc = api_with_meta
        with pytest.raises(ValueError, match="no sheet named"):
            api.optimize_layout("sid", "Nope")

    def test_optimize_layout_empty_sheet_sends_nothing(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().get.return_value.execute.return_value = {}
        out = api.optimize_layout("sid", "Tab")
        assert out["requests_sent"] == 0

    def test_optimize_layout_no_row_resize(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["hi"]]}
        api.optimize_layout("sid", "Tab", resize_rows=False)
        requests = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"]
        assert not any("autoResizeDimensions" in r for r in requests)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_server.py -k optimize_layout -v`
Expected: FAIL — `AttributeError: 'SheetsAPI' object has no attribute 'optimize_layout'`.

- [ ] **Step 3: Implement `_layout_requests` + `optimize_layout`**

Add to `SheetsAPI` in `google_workspace_mcp/sheets/sheets_api.py` (place after `format_table`):

```python
    def _layout_requests(self, sheet_id, values, col_offset, row_start, row_end,
                         min_width=48, max_width=320, resize_rows=True):
        """Turn plan_column_layout output into batchUpdate requests.

        Per column: set pixel width; set wrapStrategy WRAP + TOP alignment when
        content exceeds the width cap, else OVERFLOW_CELL (normalizes previous
        blanket wrapping). Optionally auto-fit row heights afterwards.
        """
        plans = plan_column_layout(values, min_width, max_width)
        requests = []
        for p in plans:
            col = col_offset + p["index"]
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": col, "endIndex": col + 1},
                "properties": {"pixelSize": p["width"]},
                "fields": "pixelSize",
            }})
            cell_range = {"sheetId": sheet_id, "startRowIndex": row_start, "endRowIndex": row_end,
                          "startColumnIndex": col, "endColumnIndex": col + 1}
            if p["wrap"]:
                requests.append({"repeatCell": {
                    "range": cell_range,
                    "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}},
                    "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment",
                }})
            else:
                requests.append({"repeatCell": {
                    "range": cell_range,
                    "cell": {"userEnteredFormat": {"wrapStrategy": "OVERFLOW_CELL"}},
                    "fields": "userEnteredFormat.wrapStrategy",
                }})
        if resize_rows and values:
            requests.append({"autoResizeDimensions": {"dimensions": {
                "sheetId": sheet_id, "dimension": "ROWS",
                "startIndex": row_start, "endIndex": row_end,
            }}})
        return plans, requests

    def optimize_layout(self, spreadsheet_id, range, max_column_width=320,
                        min_column_width=48, resize_rows=True):
        """Size columns to content (capped), wrap only over-cap columns, auto-fit rows."""
        meta = self.get_spreadsheet(spreadsheet_id)
        if "!" in range:
            sheet_name, sheet_id, grid, *_ = self._resolve_a1(spreadsheet_id, range, meta)
            read_a1 = range
            col_offset = grid.get("startColumnIndex", 0)
            row_start = grid.get("startRowIndex", 0)
            row_end_hint = grid.get("endRowIndex")
        else:
            sheet_name = range.strip("'\"")
            matches = [s["properties"]["sheetId"] for s in meta.get("sheets", [])
                       if s["properties"]["title"] == sheet_name]
            if not matches:
                raise ValueError(f"no sheet named {sheet_name!r}")
            sheet_id = matches[0]
            read_a1 = "'" + sheet_name.replace("'", "''") + "'"
            col_offset = 0
            row_start = 0
            row_end_hint = None
        values = self.read_range(spreadsheet_id, read_a1, "FORMATTED_VALUE").get("values") or []
        row_end = row_end_hint or (row_start + len(values))
        plans, requests = self._layout_requests(
            sheet_id, values, col_offset, row_start, row_end,
            min_column_width, max_column_width, resize_rows,
        )
        if not requests:
            return {"sheet": sheet_name, "columns": [], "requests_sent": 0}
        result = self._batch(spreadsheet_id, requests)
        return {
            "sheet": sheet_name,
            "columns": [
                {"column": _index_to_col(col_offset + p["index"]),
                 "width": p["width"], "wrap": p["wrap"]}
                for p in plans
            ],
            "requests_sent": len(requests),
            "result": result,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_server.py -k optimize_layout -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Write the failing server-tool test**

Add to the server-integration section at the bottom of `tests/test_sheets_server.py`, and add `"optimize_layout"` to the `expected` set inside `test_list_tools_includes_expected`:

```python
@pytest.mark.anyio
async def test_optimize_layout_tool(patched_server):
    patched_server.optimize_layout.return_value = {"sheet": "Tab", "columns": [], "requests_sent": 0}
    raw = await mcp.call_tool("optimize_layout", {"spreadsheet_id": "sid", "range": "Tab"})
    payload = _parse_result(raw)
    assert payload["ok"] is True
    patched_server.optimize_layout.assert_called_once_with("sid", "Tab", 320, 48, True)
```

Run: `pytest tests/test_sheets_server.py -k "optimize_layout_tool or list_tools" -v`
Expected: FAIL — `Unknown tool: optimize_layout`.

- [ ] **Step 6: Register the tool**

Add to `google_workspace_mcp/sheets/server.py` (after `format_table`):

```python
@register(mcp, mutating=True)
def optimize_layout(account: str | None = None, spreadsheet_id: str = "", range: str = "", max_column_width: int = 320, min_column_width: int = 48, resize_rows: bool = True) -> dict:
    """Make a sheet readable in one call: size each column to its content (capped at max_column_width px), wrap only over-cap columns (top-aligned), and auto-fit row heights. Pass an A1 range or a bare tab name for the whole sheet. Use after writing data."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.optimize_layout(spreadsheet_id, range, max_column_width, min_column_width, resize_rows))
    return ok(resolved, data)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_sheets_server.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/test_sheets_server.py google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py
git commit -m "feat(sheets): optimize_layout tool for human-readable column widths"
```

---

### Task 6: `format_table` — capped sizing, freeze off by default

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py:528-584` (`format_table`)
- Modify: `google_workspace_mcp/sheets/server.py:329-334` (`format_table` tool)
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Rewrite the format_table tests to the new contract**

Replace `test_format_table_batches_single_request` in `tests/test_sheets_server.py` with:

```python
    def test_format_table_smart_sizing_no_freeze(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().get.return_value.execute.return_value = {
            "values": [["H1", "H2"], ["v", "x" * 100]],
        }
        result = api.format_table("sid", "Tab!A1:B2")
        requests = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"]
        # header styling + banding still present
        assert requests[0]["repeatCell"]["range"]["endRowIndex"] == 1
        assert any("addBanding" in r for r in requests)
        assert any("setBasicFilter" in r for r in requests)
        # capped per-column widths replace unbounded column auto-resize
        widths = [r["updateDimensionProperties"]["properties"]["pixelSize"]
                  for r in requests if "updateDimensionProperties" in r]
        assert widths == [48, 320]
        assert not any(
            r.get("autoResizeDimensions", {}).get("dimensions", {}).get("dimension") == "COLUMNS"
            for r in requests
        )
        # rows auto-fit; no frozen header by default
        assert any(
            r.get("autoResizeDimensions", {}).get("dimensions", {}).get("dimension") == "ROWS"
            for r in requests
        )
        assert not any("updateSheetProperties" in r for r in requests)
        assert result["requests_sent"] == len(requests)

    def test_format_table_freeze_header_opt_in(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["H"]]}
        api.format_table("sid", "Tab!A1:A1", freeze_header=True)
        requests = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"]
        frozen = [r for r in requests if "updateSheetProperties" in r]
        assert frozen[0]["updateSheetProperties"]["properties"]["gridProperties"] == {"frozenRowCount": 1}

    def test_format_table_no_auto_resize_uses_blanket_wrap(self, api_with_meta):
        api, svc = api_with_meta
        result = api.format_table("sid", "Tab!A1:B3", auto_resize_columns=False)
        requests = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"]
        svc.spreadsheets().values().get.assert_not_called()
        assert not any("updateDimensionProperties" in r for r in requests)
        # data rows get the blanket wrap (legacy behavior)
        wraps = [r for r in requests if "repeatCell" in r
                 and r["repeatCell"]["cell"]["userEnteredFormat"].get("wrapStrategy") == "WRAP"]
        assert wraps
        assert result["requests_sent"] == len(requests)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_server.py -k format_table -v`
Expected: FAIL — old behavior asserts (autoResize COLUMNS present, frozen row present).

- [ ] **Step 3: Rework `format_table`**

In `google_workspace_mcp/sheets/sheets_api.py`, change the signature and body of `format_table`:

```python
    def format_table(self, spreadsheet_id, range, header_color="#355468", header_text_color="#FFFFFF",
                     first_band_color="#FFFFFF", second_band_color="#F3F3F3", wrap=True, auto_resize_columns=True,
                     add_filter=True, add_borders=True, freeze_header=False, max_column_width=320):
        """Apply common table styling in a single batchUpdate: header, bands, wrap, filter, borders, sizing."""
        meta = self.get_spreadsheet(spreadsheet_id)
        sheet_name, sheet_id, grid, start_row, end_row, start_col, end_col = self._resolve_a1(
            spreadsheet_id, range, meta,
        )
        header_grid = {**grid, "startRowIndex": start_row - 1, "endRowIndex": start_row}
        data_start = start_row + 1
        has_data_rows = data_start <= end_row
        data_grid = (
            {**grid, "startRowIndex": start_row, "endRowIndex": end_row}
            if has_data_rows else None
        )

        requests = [
            self._format_cells_request(
                header_grid, bold=True, background_color=header_color,
                text_color=header_text_color, wrap=wrap, horizontal_alignment="CENTER",
            ),
        ]
        if has_data_rows:
            requests.append(self._banding_request(
                grid, header_color=header_color,
                first_band_color=first_band_color, second_band_color=second_band_color,
            ))
            if wrap and not auto_resize_columns:
                requests.append(self._format_cells_request(data_grid, wrap=True))
        if add_filter:
            requests.append({"setBasicFilter": {"filter": {"range": grid}}})
        if add_borders:
            border = {"style": "SOLID", "color": self._hex_to_color("#CCCCCC")}
            requests.append({"updateBorders": {
                "range": grid,
                "top": border, "bottom": border, "left": border, "right": border,
                "innerHorizontal": border, "innerVertical": border,
            }})
        if auto_resize_columns and grid.get("startColumnIndex") is not None:
            values = self.read_range(spreadsheet_id, range, "FORMATTED_VALUE").get("values") or []
            _, layout = self._layout_requests(
                sheet_id, values, grid["startColumnIndex"],
                start_row - 1, end_row, max_width=max_column_width,
            )
            requests.extend(layout)
        if freeze_header:
            requests.append({"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }})
        result = self._batch(spreadsheet_id, requests)
        return {
            "sheet": sheet_name,
            "range": self._quoted_sheet_range(sheet_name, f"{start_col}{start_row}:{end_col}{end_row}"),
            "requests_sent": len(requests),
            "result": result,
        }
```

In `google_workspace_mcp/sheets/server.py`, update the tool signature and docstring:

```python
@register(mcp, mutating=True)
def format_table(account: str | None = None, spreadsheet_id: str = "", range: str = "", header_color: str = "#355468", header_text_color: str = "#FFFFFF", first_band_color: str = "#FFFFFF", second_band_color: str = "#F3F3F3", wrap: bool = True, auto_resize_columns: bool = True, add_filter: bool = True, add_borders: bool = True, freeze_header: bool = False, max_column_width: int = 320) -> dict:
    """One-shot table styling: formatted header, alternating row colors, filter dropdowns, borders, and content-aware column widths (capped at max_column_width px; over-cap columns wrap). Set freeze_header=True only if the user asks for frozen headers."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.format_table(spreadsheet_id, range, header_color, header_text_color, first_band_color, second_band_color, wrap, auto_resize_columns, add_filter, add_borders, freeze_header, max_column_width))
    return ok(resolved, data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sheets_server.py google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py
git commit -m "feat(sheets): format_table capped smart sizing; freeze header opt-in"
```

---

### Task 7: `write_table` one-shot tool

**Files:**
- Modify: `google_workspace_mcp/sheets/sheets_api.py` (`add_table` optional name + new `write_table`)
- Modify: `google_workspace_mcp/sheets/server.py`
- Test: `tests/test_sheets_server.py`

- [ ] **Step 1: Write the failing API-level tests**

Add inside the `api_with_meta` class:

```python
    def test_write_table_native(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().update.return_value.execute.return_value = {"updatedCells": 4}
        svc.spreadsheets().values().get.return_value.execute.return_value = {
            "values": [["Name", "Age"], ["Ann", "7"]],
        }
        svc.spreadsheets().batchUpdate.return_value.execute.return_value = {
            "replies": [{"addTable": {"table": {"tableId": "t1"}}}],
        }
        out = api.write_table("sid", "Tab!B2", [["Name", "Age"], ["Ann", "7"]])
        # values written at the anchor-derived range
        svc.spreadsheets().values().update.assert_called_with(
            spreadsheetId="sid", range="'Tab'!B2:C3", valueInputOption="USER_ENTERED",
            body={"values": [["Name", "Age"], ["Ann", "7"]]},
        )
        assert out["range"] == "'Tab'!B2:C3"
        assert out["rows"] == 2 and out["columns"] == 2
        assert out["tableId"] == "t1"
        assert out["style"] == "native"
        assert out["layout"]["requests_sent"] > 0
        # an addTable request went out
        add_table_calls = [
            c for c in svc.spreadsheets().batchUpdate.call_args_list
            if any("addTable" in r for r in c.kwargs["body"]["requests"])
        ]
        assert len(add_table_calls) == 1

    def test_write_table_plain_skips_styling(self, api_with_meta):
        api, svc = api_with_meta
        svc.spreadsheets().values().update.return_value.execute.return_value = {}
        svc.spreadsheets().values().get.return_value.execute.return_value = {"values": [["a"]]}
        out = api.write_table("sid", "Tab!A1", [["a"]], style="plain")
        assert out["tableId"] is None
        assert not any(
            any("addTable" in r or "addBanding" in r for r in c.kwargs["body"]["requests"])
            for c in svc.spreadsheets().batchUpdate.call_args_list
        )

    def test_write_table_rejects_range_anchor(self, api_with_meta):
        api, _svc = api_with_meta
        with pytest.raises(ValueError, match="single cell"):
            api.write_table("sid", "Tab!A1:B2", [["a"]])

    def test_write_table_rejects_empty_values(self, api_with_meta):
        api, _svc = api_with_meta
        with pytest.raises(ValueError, match="non-empty"):
            api.write_table("sid", "Tab!A1", [])

    def test_write_table_rejects_bad_style(self, api_with_meta):
        api, _svc = api_with_meta
        with pytest.raises(ValueError, match="native/banded/plain"):
            api.write_table("sid", "Tab!A1", [["a"]], style="fancy")

    def test_add_table_omits_empty_name(self, api_with_meta):
        api, svc = api_with_meta
        api.add_table("sid", "Tab!A1:B2", None)
        req = svc.spreadsheets().batchUpdate.call_args.kwargs["body"]["requests"][0]
        assert "name" not in req["addTable"]["table"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_server.py -k "write_table or add_table_omits" -v`
Expected: FAIL — no `write_table` attribute; `name` present in addTable body.

- [ ] **Step 3: Implement**

In `google_workspace_mcp/sheets/sheets_api.py`, make `add_table`'s name optional — replace the `table = {...}` construction:

```python
    def add_table(self, spreadsheet_id, range, name, header_color="#355468", first_band_color="#FFFFFF",
                  second_band_color="#F3F3F3", column_names=None):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        table = {
            "range": grid,
            "rowsProperties": {
                "headerColorStyle": self._hex_to_color_style(header_color),
                "firstBandColorStyle": self._hex_to_color_style(first_band_color),
                "secondBandColorStyle": self._hex_to_color_style(second_band_color),
            },
        }
        if name:
            table["name"] = name
        if column_names:
            table["columnProperties"] = [
                {"columnIndex": i, "columnName": col_name} for i, col_name in enumerate(column_names)
            ]
        return self._batch(spreadsheet_id, [{"addTable": {"table": table}}])
```

Add `write_table` after `optimize_layout`:

```python
    def write_table(self, spreadsheet_id, anchor, values, style="native", name=None,
                    header_color="#355468", first_band_color="#FFFFFF",
                    second_band_color="#F3F3F3", max_column_width=320):
        """Write values (first row = header) at an anchor cell, style them as a
        table, and optimize the layout — one call from data to readable sheet."""
        if not values or not any(row for row in values):
            raise ValueError("write_table requires a non-empty 2D values array (first row = header)")
        sheet_name, start_col, start_row, end_col, end_row = self._parse_a1_local(anchor)
        if not (start_col and start_row and start_col == end_col and start_row == end_row):
            raise ValueError(f"anchor must be a single cell like 'Sheet1!A1', got {anchor!r}")
        n_rows = len(values)
        n_cols = max(len(r) for r in values)
        last_col = _index_to_col(_col_to_index(start_col) + n_cols - 1)
        last_row = int(start_row) + n_rows - 1
        cell_range = f"{start_col}{start_row}:{last_col}{last_row}"
        full_range = self._quoted_sheet_range(sheet_name, cell_range) if sheet_name else cell_range
        self.update_range(spreadsheet_id, full_range, values)
        table_id = None
        if style == "native":
            reply = self.add_table(spreadsheet_id, full_range, name,
                                   header_color, first_band_color, second_band_color)
            replies = reply.get("replies") or []
            if replies and replies[0].get("addTable"):
                table_id = replies[0]["addTable"].get("table", {}).get("tableId")
        elif style == "banded":
            self.format_table(spreadsheet_id, full_range, header_color=header_color,
                              first_band_color=first_band_color, second_band_color=second_band_color,
                              auto_resize_columns=False)
        elif style != "plain":
            raise ValueError("style must be one of native/banded/plain")
        layout = self.optimize_layout(spreadsheet_id, full_range, max_column_width=max_column_width)
        return {"range": full_range, "rows": n_rows, "columns": n_cols,
                "style": style, "tableId": table_id, "layout": layout}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_server.py -k "write_table or add_table" -v`
Expected: PASS.

- [ ] **Step 5: Write the failing server-tool test, then register the tool**

Add `"write_table"` to the `expected` set in `test_list_tools_includes_expected`, and add:

```python
@pytest.mark.anyio
async def test_write_table_tool(patched_server):
    patched_server.write_table.return_value = {"range": "'Tab'!A1:B2", "tableId": "t1"}
    raw = await mcp.call_tool("write_table", {
        "spreadsheet_id": "sid", "anchor": "Tab!A1",
        "values": [["Name", "Age"], ["Ann", "7"]],
    })
    payload = _parse_result(raw)
    assert payload["ok"] is True
    patched_server.write_table.assert_called_once_with(
        "sid", "Tab!A1", [["Name", "Age"], ["Ann", "7"]],
        "native", None, "#355468", "#FFFFFF", "#F3F3F3", 320,
    )
```

Run `pytest tests/test_sheets_server.py -k write_table_tool -v` (expect FAIL: unknown tool), then add to `google_workspace_mcp/sheets/server.py` after `optimize_layout`:

```python
@register(mcp, mutating=True)
def write_table(account: str | None = None, spreadsheet_id: str = "", anchor: str = "", values: list[list] | None = None, style: str = "native", name: str | None = None, header_color: str = "#355468", first_band_color: str = "#FFFFFF", second_band_color: str = "#F3F3F3", max_column_width: int = 320) -> dict:
    """Write a 2D array (first row = headers) at an anchor cell (e.g. 'Sheet1!A1') and make it readable in one shot: native Sheets table (style='native'), alternating-color banding (style='banded'), or values only (style='plain'), plus content-aware column widths and wrapping. Prefer this over update_range for tabular data. Overwrites cells in the target range. If a native table already overlaps the range, use style='banded' or update_table instead."""
    api, resolved = _api(account)
    data = run_tool(lambda: api.write_table(spreadsheet_id, anchor, values or [], style, name, header_color, first_band_color, second_band_color, max_column_width))
    return ok(resolved, data)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_sheets_server.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_sheets_server.py google_workspace_mcp/sheets/sheets_api.py google_workspace_mcp/sheets/server.py
git commit -m "feat(sheets): write_table one-shot data-to-readable-table tool"
```

---

### Task 8: Steering pass — stop the freeze habit, advertise the new flows

**Files:**
- Modify: `google_workspace_mcp/sheets/server.py:7-10, 217-222`

- [ ] **Step 1: Update the server description and freeze_panes docstring**

In `google_workspace_mcp/sheets/server.py`, change the `build_server` call:

```python
mcp = build_server(
    "gsheets-mcp",
    "Google Sheets: read/write values, formulas, filters, and table formatting for one or more accounts. "
    "Ranges use A1 notation. When writing tabular data, prefer write_table (or update_range followed by "
    "format_table / optimize_layout) so the sheet stays human-readable: content-aware column widths, "
    "wrapped long text, alternating row colors. Do not freeze rows/columns unless the user asks.",
)
```

Change the `freeze_panes` docstring:

```python
    """Freeze the first N rows and/or columns of the sheet containing the given range (A1 notation). Pass 0 to unfreeze. Rarely needed: only freeze when the user explicitly asks, or headers genuinely scroll out of view on a very large sheet."""
```

- [ ] **Step 2: Run the full suite**

Run: `pytest && ruff check .`
Expected: all PASS, no lint errors.

- [ ] **Step 3: Commit**

```bash
git add google_workspace_mcp/sheets/server.py
git commit -m "docs(sheets): steer agents toward readable layouts, away from freezing"
```

---

### Task 9: README + final verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the right README sections**

Run: `grep -n "Sheets\|Docs\|gsheets\|gdocs" README.md | head -30`
Locate where the Sheets and Docs servers' capabilities are described (feature bullets or per-server sections).

- [ ] **Step 2: Add the new capabilities**

Under the Docs server's description, add:

```markdown
- **Markdown in/out** — `create_document_from_markdown`, `append_markdown`, and
  `replace_document_with_markdown` let an agent write plain markdown while Google
  converts it to native headings, lists, links, and tables; `read_document_as_markdown`
  round-trips it back.
```

Under the Sheets server's description, add:

```markdown
- **Human-readable layouts** — `write_table` writes data and formats it as a native
  table (or banded range) in one call; `optimize_layout` sizes every column to its
  content with a width cap, wraps only what must wrap, and auto-fits row heights.
  Header freezing is opt-in.
```

Adjust wording/indentation to match the surrounding README style.

- [ ] **Step 3: Full verification**

Run: `pytest && ruff check .`
Expected: full suite PASS, lint clean.

Optionally (maintainer, live account configured): `GOOGLE_MCP_LIVE=1 pytest -k live` to smoke the new tools against real APIs.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document markdown pipeline and readable-layout tools"
```
