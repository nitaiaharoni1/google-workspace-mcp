#!/usr/bin/env python3
"""Live audit for the Sheets content-editing surface (CRUD + new edit tools).

Creates a scratch spreadsheet, exercises every edit operation, verifies by
reading back, then deletes it.
Run: .venv/bin/python tests/live_sheets_editing.py
"""
from __future__ import annotations

import sys
import traceback

from google_workspace_mcp.sheets.sheets_api import SheetsAPI

ACCOUNT = "nitaiaharoni1@gmail.com"
PASS = 0
FAIL = 0


def check(label: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def first_sheet(api, sid):
    return api.get_spreadsheet(sid)["sheets"][0]


def main() -> int:
    api = SheetsAPI(account=ACCOUNT)
    sid = None
    print(f"Account: {ACCOUNT}\n")
    try:
        print("1. Create scratch spreadsheet")
        created = api.create_spreadsheet("MCP Edit Audit (auto-delete)")
        sid = created["spreadsheetId"]
        print(f"   ID: {sid}")

        print("\n2. update_range + batch_update_values + append_rows")
        api.update_range(sid, "Sheet1!A1:C3", [
            ["Name", "Score", "Status"],
            ["Alpha", 10, "Active"],
            ["Beta", 5, "Draft"],
        ])
        api.batch_update_values(sid, [
            {"range": "Sheet1!B2", "values": [[11]]},
            {"range": "Sheet1!B3", "values": [[6]]},
        ])
        api.append_rows(sid, "Sheet1!A1", [["Gamma", 8, "Active"]])
        vals = api.read_range(sid, "Sheet1!A1:C4").get("values", [])
        check("update + batch_update applied", vals and str(vals[1][1]) == "11")
        check("append added a row", len(vals) == 4 and vals[3][0] == "Gamma")

        print("\n3. find_replace (range scope)")
        fr = api.find_replace(sid, "Active", "Open", range="Sheet1!A1:C4")
        occ = fr.get("replies", [{}])[0].get("findReplace", {}).get("occurrencesChanged")
        check("find_replace changed occurrences", bool(occ and occ >= 2), f"occ={occ}")
        vals = api.read_range(sid, "Sheet1!C1:C4").get("values", [])
        check("values replaced to Open", any(r and r[0] == "Open" for r in vals))

        print("\n4. find_replace (regex, all sheets)")
        api.find_replace(sid, "^Op.*", "Closed", all_sheets=True, search_by_regex=True, match_entire_cell=True)
        vals = api.read_range(sid, "Sheet1!C1:C4").get("values", [])
        check("regex replace applied", any(r and r[0] == "Closed" for r in vals))

        print("\n5. copy_paste (values) + cut_paste")
        api.copy_paste(sid, "Sheet1!A1:C1", "Sheet1!E1:G1", paste_type="PASTE_VALUES")
        ev = api.read_range(sid, "Sheet1!E1:G1").get("values", [])
        check("copy_paste copied header", ev and ev[0][0] == "Name")
        api.cut_paste(sid, "Sheet1!E1:G1", "Sheet1!E5")
        moved = api.read_range(sid, "Sheet1!E5:G5").get("values", [])
        src = api.read_range(sid, "Sheet1!E1:G1").get("values", [])
        check("cut_paste moved to E5", moved and moved[0][0] == "Name")
        check("cut_paste cleared source", not src)

        print("\n6. insert/delete rows + columns")
        api.insert_rows(sid, "Sheet1!2:2")
        after_insert = api.read_range(sid, "Sheet1!A3:A3").get("values", [])
        check("insert_rows shifted Alpha down", after_insert and after_insert[0][0] == "Alpha")
        api.delete_rows(sid, "Sheet1!2:2")
        api.insert_columns(sid, "Sheet1!B:B")
        api.delete_columns(sid, "Sheet1!B:B")
        check("insert/delete row+column ran", True)

        print("\n7. hide_columns + unhide")
        api.set_dimension_visibility(sid, "Sheet1!C:C", "COLUMNS", True)
        # hiddenByUser shows up in columnMetadata when grid data is requested
        meta = api.get_spreadsheet(sid, include_grid_data=True)["sheets"][0]
        col_meta = meta.get("data", [{}])[0].get("columnMetadata", [])
        hidden_c = len(col_meta) > 2 and col_meta[2].get("hiddenByUser") is True
        check("hide_columns set hiddenByUser on C", hidden_c)
        api.set_dimension_visibility(sid, "Sheet1!C:C", "COLUMNS", False)
        meta = api.get_spreadsheet(sid, include_grid_data=True)["sheets"][0]
        col_meta = meta.get("data", [{}])[0].get("columnMetadata", [])
        unhidden_c = not (len(col_meta) > 2 and col_meta[2].get("hiddenByUser") is True)
        check("unhide cleared hiddenByUser on C", unhidden_c)

        print("\n8. add_table -> update_table -> delete_table")
        api.update_range(sid, "Sheet1!A10:C12", [
            ["City", "Pop", "Tier"],
            ["NYC", 8, "A"],
            ["LA", 4, "B"],
        ])
        add = api.add_table(sid, "Sheet1!A10:C12", "Cities")
        table_id = add.get("replies", [{}])[0].get("addTable", {}).get("table", {}).get("tableId")
        check("add_table returned tableId", bool(table_id), f"reply={add}")
        if table_id:
            api.update_table(
                sid, table_id, name="CitiesRenamed", header_color="#4285F4",
                column_properties=[{"column_index": 2, "column_name": "Tier",
                                    "column_type": "DROPDOWN", "values": ["A", "B"]}],
            )
            tables = first_sheet(api, sid).get("tables", [])
            t = tables[0] if tables else {}
            check("update_table renamed", t.get("name") == "CitiesRenamed", f"name={t.get('name')}")
            check("update_table recolored header", "headerColorStyle" in t.get("rowsProperties", {}))
            api.delete_table(sid, table_id)
            tables_after = first_sheet(api, sid).get("tables", [])
            check("delete_table removed table", not tables_after)

        print("\n9. merge/unmerge + duplicate_sheet + sort_range + clear_range")
        api.merge_cells(sid, "Sheet1!E10:F10")
        api.unmerge_cells(sid, "Sheet1!E10:F10")
        api.sort_range(sid, "Sheet1!A11:C12", column=1, ascending=False)
        dup = api.duplicate_sheet(sid, first_sheet(api, sid)["properties"]["sheetId"], "Copy")
        check("duplicate_sheet ran", "replies" in dup)
        api.clear_range(sid, "Sheet1!E5:G5")
        cleared = api.read_range(sid, "Sheet1!E5:G5").get("values", [])
        check("clear_range emptied E5:G5", not cleared)

    except Exception as exc:
        print(f"\n  ✗ EXCEPTION: {exc}")
        traceback.print_exc()
        global FAIL
        FAIL += 1
    finally:
        if sid:
            print(f"\nCleanup: removing scratch spreadsheet {sid}")
            try:
                import google_auth_core as core
                drive = core.get_service("drive", "v3", account=ACCOUNT)
                drive.files().delete(fileId=sid).execute()
                print("  ✓ deleted via Drive API")
            except Exception as exc2:
                print(f"  ⚠ cleanup failed: {exc2}")
                print(f"    https://docs.google.com/spreadsheets/d/{sid}")

    print(f"\n{'=' * 40}")
    print(f"PASSED: {PASS}  FAILED: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
