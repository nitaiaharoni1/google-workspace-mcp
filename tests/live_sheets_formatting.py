#!/usr/bin/env python3
"""Live integration test for Sheets formatting, tables, filters, and formulas.

Creates a scratch spreadsheet, exercises new features, verifies, then deletes it.
Run: .venv/bin/python tests/live_sheets_formatting.py
"""
from __future__ import annotations

import sys
import traceback

from google_workspace_mcp.sheets.sheets_api import SheetsAPI

ACCOUNT = "aviv.joels@gmail.com"
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


def main() -> int:
    api = SheetsAPI(account=ACCOUNT)
    sheet_id = None
    print(f"Account: {ACCOUNT}\n")

    try:
        # --- setup ---
        print("1. Create scratch spreadsheet")
        created = api.create_spreadsheet("MCP Format Test (auto-delete)")
        sheet_id = created["spreadsheetId"]
        print(f"   ID: {sheet_id}")

        print("\n2. Write sample data")
        rows = [
            ["Name", "Score", "Status", "Total"],
            ["Alpha", 10, "Active", ""],
            ["Beta", 5, "Draft", ""],
            ["Gamma", 8, "Active", ""],
            ["Delta", 3, "Draft", ""],
        ]
        api.update_range(sheet_id, "Sheet1!A1:D5", rows)
        api.write_formulas(sheet_id, "Sheet1!D2:D5", [
            ["=B2"], ["=B3"], ["=B4"], ["=B5"],
        ])

        print("\n3. format_table (header, banding, wrap, filter, borders, auto-resize, freeze)")
        ft = api.format_table(sheet_id, "Sheet1!A1:D5")
        check("format_table returned requests_sent", ft.get("requests_sent", 0) >= 5)
        check("format_table result has replies", "result" in ft)

        print("\n4. Verify formulas")
        formulas = api.read_formulas(sheet_id, "Sheet1!D2:D3")
        vals = formulas.get("values", [])
        check("read_formulas returns =B2", vals and vals[0][0] == "=B2")
        computed = api.read_range(sheet_id, "Sheet1!D2:D3")
        cv = computed.get("values", [])
        check("computed D2=10", cv and str(cv[0][0]) == "10")
        check("computed D3=5", cv and str(cv[1][0]) == "5")

        print("\n5. Verify filter applied")
        meta = api.get_spreadsheet(sheet_id)
        sheet = meta["sheets"][0]
        bf = sheet.get("basicFilter")
        check("basicFilter exists", bf is not None)
        if bf:
            check("basicFilter covers A1:D5", bf["range"].get("endColumnIndex") == 4)

        print("\n6. Verify banding applied")
        bandings = sheet.get("bandedRanges", [])
        check("bandedRanges present", len(bandings) >= 1)

        print("\n7. Verify frozen header row")
        frozen = sheet["properties"]["gridProperties"].get("frozenRowCount", 0)
        check("frozenRowCount=1", frozen == 1)

        print("\n8. format_cells extras (strikethrough, vertical align)")
        api.format_cells(
            sheet_id, "Sheet1!A4", strikethrough=True, vertical_alignment="MIDDLE",
        )
        check("format_cells strikethrough/vertical ok", True)

        print("\n9. set_basic_filter with criteria (hide Draft)")
        api.set_basic_filter(
            sheet_id, "Sheet1!A1:D5",
            filter_specs=[{"column": 2, "hidden_values": ["Draft"]}],
            sort_specs=[{"column": 1, "ascending": False}],
        )
        check("filter with hidden_values + sort ok", True)

        print("\n10. add_banding on second sheet")
        api.add_sheet(sheet_id, "BandingTest")
        api.update_range(sheet_id, "BandingTest!A1:B4", [["H", "V"], [1, 2], [3, 4], [5, 6]])
        band_result = api.add_banding(
            sheet_id, "BandingTest!A1:B4",
            header_color="#4285F4", first_band_color="#E8F0FE", second_band_color="#FFFFFF",
        )
        replies = band_result.get("replies", [])
        band_id = replies[0].get("addBanding", {}).get("bandedRange", {}).get("bandedRangeId") if replies else None
        check("add_banding returns bandedRangeId", band_id is not None)

        if band_id is not None:
            api.update_banding(sheet_id, band_id, first_band_color="#FFF2CC", second_band_color="#FFFFFF")
            check("update_banding ok", True)
            api.delete_banding(sheet_id, band_id)
            check("delete_banding ok", True)

        print("\n11. resize_columns (fixed width + auto-fit)")
        api.resize_dimension(sheet_id, "Sheet1!A:A", "COLUMNS", 120)
        api.resize_dimension(sheet_id, "Sheet1!B:D", "COLUMNS", None)
        check("column resize ok", True)

        print("\n12. wrap text on wide cell")
        api.update_range(sheet_id, "Sheet1!A6", [["This is a long wrapped cell value for testing text wrap behavior"]])
        api.format_cells(sheet_id, "Sheet1!A6", wrap=True)
        check("text wrap ok", True)

    except Exception as exc:
        print(f"\n  ✗ EXCEPTION: {exc}")
        traceback.print_exc()
        global FAIL
        FAIL += 1
    finally:
        if sheet_id:
            print(f"\nCleanup: removing scratch spreadsheet {sheet_id}")
            try:
                import google_auth_core as core
                drive = core.get_service("drive", "v3", account=ACCOUNT)
                drive.files().delete(fileId=sheet_id).execute()
                print("  ✓ deleted via Drive API")
            except Exception:
                try:
                    api.rename_sheet(sheet_id, 0, "[DELETE ME] MCP Format Test")
                    print(f"  ⚠ Drive delete unavailable (scope); renamed tab. Delete manually:")
                    print(f"    https://docs.google.com/spreadsheets/d/{sheet_id}")
                except Exception as exc2:
                    print(f"  ⚠ cleanup failed: {exc2}")
                    print(f"    https://docs.google.com/spreadsheets/d/{sheet_id}")

    print(f"\n{'=' * 40}")
    print(f"PASSED: {PASS}  FAILED: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
