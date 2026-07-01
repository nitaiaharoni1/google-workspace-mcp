# MCP-native tool annotations + structured output in `@register`: design

**Date:** 2026-07-01
**Status:** Draft, pending review
**Author:** nitai (+ Claude)

## Problem

`@register` already knows which tools are read-only, mutating, and destructive,
but it only expresses that knowledge two ways: by *not registering* mutating
tools under `GOOGLE_MCP_READONLY`, and by appending a `[DESTRUCTIVE]` string to
the docstring. Neither is machine-readable. MCP has first-class
`ToolAnnotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
`openWorldHint`) that clients can use for policy: a client can auto-allow
read-only tools, or require explicit confirmation for destructive ones. Today a
client looking at `list_tools` from these servers sees no annotations at all,
so it must treat `read_range` and `batch_delete_messages` with the same level
of caution, or parse a docstring string, which no client does.

## Goals

1. Every one of the ~163 tools (plus the 3 common tools) advertises accurate
   `readOnlyHint` / `destructiveHint` annotations in `list_tools`, derived from
   the flags `@register` already takes. Zero per-tool changes in the five
   `server.py` files for this baseline.
2. Clients that consume annotations (permission gating, auto-allow of
   read-only tools) work correctly against these servers with no client-side
   configuration.
3. The change is invisible to clients that ignore annotations: same tool
   names, same descriptions (still including `[DESTRUCTIVE]`), same envelope.

## Non-goals

- **Not replacing the `GOOGLE_MCP_READONLY` gate.** Annotations are hints;
  the spec explicitly says clients must not rely on them for security. The
  gate (mutating tools never registered) stays as the enforcement layer;
  annotations are defense in depth for well-behaved clients.
- **No per-tool permission configuration** (e.g. an env var to hide only
  deletes). Out of scope; the read-only gate plus client-side policy covers
  the known use cases.
- **No per-tool `data` payload schemas in this pass.** See Structured output
  below; full schemas for 163 heterogeneous payloads is its own project and
  most of the value is in the annotations.

## Verified SDK facts (mcp 1.26.0 installed; pyproject pins `mcp>=1.12`)

Verified against the installed SDK, not from memory:

- `FastMCP.tool()` signature accepts `annotations: ToolAnnotations | None`,
  plus `title`, `structured_output: bool | None`, `icons`, `meta`.
- `mcp.types.ToolAnnotations` fields, all optional: `title`, `readOnlyHint`,
  `destructiveHint`, `idempotentHint`, `openWorldHint`.
- **Bare `-> dict` returns (all 163 current tools) produce
  `outputSchema: None`**: auto-detection treats unparameterized `dict` as
  unstructured, and `call_tool` returns text content only. So annotations can
  ship with no output-schema side effects.
- `structured_output=True` with a bare `-> dict` annotation raises
  `InvalidSignature` at registration time ("return type dict is not
  serializable for structured output").
- `-> dict[str, Any]` auto-generates a permissive object schema
  (`{"type": "object", "additionalProperties": true}`) and `call_tool` then
  returns `(content, structuredContent)`: the JSON payload is serialized
  **twice** on the wire (once as text content, once as `structuredContent`).
- A `TypedDict` return annotation generates a real schema (e.g. required
  `ok` / `account` / `data`) and the SDK validates every result against it at
  call time. Same double-serialization on the wire.

## Design

### `register()` changes (`core/runtime.py`)

Map the existing flags to native annotations; add one new optional flag,
`idempotent`, for tools where repeat-safety is meaningful:

```python
from mcp.types import ToolAnnotations

def register(mcp, *, mutating: bool = False, destructive: bool = False,
             idempotent: bool | None = None):
    """Decorator that registers a tool, honoring the read-only gate and
    attaching MCP ToolAnnotations derived from the same flags."""

    def deco(fn):
        if mutating and READONLY:
            return fn  # skip registration entirely (unchanged)
        if destructive and fn.__doc__:
            fn.__doc__ = fn.__doc__.rstrip() + (
                "\n\n[DESTRUCTIVE] Permanently changes or deletes data; cannot be undone."
            )
        annotations = ToolAnnotations(
            readOnlyHint=not mutating,
            # Per the MCP spec, destructiveHint defaults to TRUE when absent,
            # so mutating non-destructive tools must set it False explicitly.
            destructiveHint=destructive if mutating else None,
            idempotentHint=idempotent,
        )
        return mcp.tool(annotations=annotations)(fn)

    return deco
```

Semantics:

| Registration | readOnlyHint | destructiveHint | notes |
|---|---|---|---|
| `@register(mcp)` | `True` | unset | reads |
| `@register(mcp, mutating=True)` | `False` | `False` | writes; explicit False matters (spec default is True) |
| `@register(mcp, mutating=True, destructive=True)` | `False` | `True` | deletes, clears |
| `idempotent=True` added | unchanged | unchanged | `idempotentHint=True` |

`openWorldHint` is deliberately left unset in this pass: whether `send_message`
(reaches arbitrary external recipients) versus `format_cells` (closed domain of
one spreadsheet) warrants different values is real, but low-stakes; revisit if
a client is shown to use it. The `[DESTRUCTIVE]` docstring append stays for
humans and for clients that ignore annotations. The read-only gate is
unchanged.

### Common tools (`core/common_tools.py`)

`list_accounts`, `auth_status`, and `whoami` currently use bare `@mcp.tool()`.
Switch them to `@register(mcp)` so they advertise `readOnlyHint=True` like
every other read. No behavior change otherwise.

### `idempotent` rollout table (P1, per-tool follow-up)

The flag exists at P0 but nothing sets it yet. Candidate assignments, to be
applied one server at a time:

| Server | `idempotent=True` candidates |
|---|---|
| Gmail | `mark_read`, `star_message`, `unstar_message`, `archive_message`, `modify_labels` (add/remove same labels), `trash_message`, `untrash_message` |
| Calendar | `respond_to_event`, `move_event` (same target) |
| Sheets | `update_range`, `format_cells`, `freeze_panes`, `resize_columns`, `resize_rows`, `hide_columns`, `hide_rows`, `merge_cells`, `unmerge_cells`, `clear_range` |
| Docs | `replace_all_text`, `set_page_layout`, `set_paragraph_style` |
| Drive | `rename_file` (same name), `move_file` (same parent), `trash_file`, `share_file` (same role) |

Non-candidates (never idempotent): `send_message`, `append_rows`,
`append_text`, `create_*`, `copy_*`, `insert_*`, `delete_rows` /
`delete_columns` (index-shifting), `quick_add_event`.

### Structured output: scoped to P1/P2 after an explicit finding

The tempting move is to annotate every tool `-> Envelope` (a `TypedDict` with
`ok` / `account` / `data`) and get `outputSchema` plus validated
`structuredContent` for free. Two verified findings argue for deferring:

1. **Wire cost.** With an output schema present, every `call_tool` result
   carries the payload twice (text content + `structuredContent`). For the
   heavy readers (`get_document`, `get_thread`, `read_range` on big ranges)
   that can double an already large response. This directly conflicts with
   the envelope-v2 context-efficiency work (see the pagination + field
   selection spec of the same date).
2. **Envelope drift.** The common tools do not all emit `account`
   (`list_accounts` and `auth_status` omit it; `whoami` can return
   `ok: False` inside a success result). A required-field schema would make
   the SDK reject those results at call time, so a shared schema forces an
   envelope cleanup first.

Decision: **P0 ships annotations only** (bare `-> dict` keeps
`outputSchema: None`, verified). **P1** may add a minimal shared schema
(`ok` required, `account` optional, `data` open) once (a) the common-tool
envelopes are normalized and (b) it is confirmed that target clients do not
resend both representations to the model. **P2** is real per-tool `data`
schemas, most valuable for machine consumers of Sheets/Drive list shapes.

## Client impact (verified vs assumed)

- **Verified (SDK level):** annotations pass through FastMCP and appear in
  `list_tools` responses; this repo's in-memory protocol tests can assert
  them (see Testing).
- **Assumed, to confirm during rollout:** Claude Code consults
  `readOnlyHint` / annotations when deciding whether an MCP tool call needs a
  permission prompt, and Claude Desktop surfaces destructive hints in its
  tool-approval UI. These behaviors are documented client features but have
  not been exercised against this codebase; the P0 acceptance pass includes a
  manual check with Claude Code (`claude mcp add` a dev build, observe
  prompting behavior for `read_range` vs `delete_message`).

## Requirements

**P0 (this spec):**

- [ ] `@register` attaches `ToolAnnotations` per the table above; signature
      gains `idempotent: bool | None = None`.
- [ ] Common tools registered via `@register(mcp)`.
- [ ] `pyproject.toml` dependency floor raised to a version verified to
      support both `annotations` and `structured_output` in `FastMCP.tool()`
      (installed 1.26.0 verified; see Open questions for the exact floor).
- [ ] All existing tests pass unchanged; new tests below added.
- [ ] README gains three lines documenting that annotations are advertised
      and that `GOOGLE_MCP_READONLY` remains the enforcement mechanism.

**P1 (fast follow):**

- [ ] `idempotent=True` applied per the rollout table, one server per PR.
- [ ] Envelope normalization for common tools, then the minimal shared
      output schema, gated on the wire-cost check.

**P2 (future):**

- [ ] Per-tool `data` schemas for the highest-value list/read tools.

## Testing

Match the in-memory protocol style already used in `tests/test_integration.py`
(`await mod.mcp.list_tools()` across all five imported server modules):

- `test_annotations_read_vs_destructive`: for each of the five servers, fetch
  `list_tools`; assert a known read tool (`get_profile`, `read_range`,
  `search_files`, `read_document`, `list_events`) has
  `annotations.readOnlyHint is True`, and a known destructive tool
  (`delete_message`, `delete_event`, `delete_sheet`, `delete_range`,
  `delete_file`) has `readOnlyHint is False` and `destructiveHint is True`.
- `test_annotations_mutating_not_destructive`: a known write tool per server
  (`send_message`, `create_event`, `update_range`, `append_text`,
  `upload_file`) has `readOnlyHint is False` and `destructiveHint is False`.
- `test_common_tools_readonly_hint`: `list_accounts` / `whoami` /
  `auth_status` advertise `readOnlyHint is True` on every server.
- `test_no_output_schema_regression`: every tool's `outputSchema` is `None`
  (locks in the P0 decision; deleted deliberately when P1 lands).
- Existing read-only gate tests must pass untouched (the gate path returns
  before annotations are built).

## Out of scope

- Replacing or weakening `GOOGLE_MCP_READONLY`.
- Per-tool permission env vars.
- `openWorldHint` assignments.
- Full per-tool output schemas (P2 placeholder only).

## Open questions

1. **Exact minimum `mcp` version.** `annotations` and `structured_output` are
   verified in 1.26.0; the current floor is `>=1.12`. Before release, either
   verify 1.12 supports both kwargs or bump the floor (engineering,
   non-blocking: bumping to the verified version is the safe default).
2. **Does Claude Code currently auto-allow `readOnlyHint=True` MCP tools, or
   only its built-in read tools?** Determines how much friction P0 actually
   removes (engineering, non-blocking; answer via the manual rollout check).
3. **Do any target clients feed both text content and `structuredContent`
   back to the model?** Blocks P1 schemas if yes (engineering, blocking for
   P1 only).
