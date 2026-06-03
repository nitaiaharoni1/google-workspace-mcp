"""Minimal Google Sheets API wrapper (values + structure operations)."""
from __future__ import annotations
import google_auth_core as core


class SheetsAPI:
    def __init__(self, account=None):
        self.account = account
        self.service = core.get_service("sheets", "v4", account=account)

    # --- values ---
    def read_range(self, spreadsheet_id, range, value_render_option="FORMATTED_VALUE"):
        return self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range, valueRenderOption=value_render_option
        ).execute()

    def batch_read(self, spreadsheet_id, ranges, value_render_option="FORMATTED_VALUE"):
        return self.service.spreadsheets().values().batchGet(
            spreadsheetId=spreadsheet_id, ranges=ranges, valueRenderOption=value_render_option
        ).execute()

    def update_range(self, spreadsheet_id, range, values, value_input_option="USER_ENTERED"):
        return self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=range, valueInputOption=value_input_option,
            body={"values": values},
        ).execute()

    def batch_update_values(self, spreadsheet_id, data, value_input_option="USER_ENTERED"):
        # data: list of {"range": "A1:B2", "values": [[...],[...]]}
        return self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": value_input_option, "data": data},
        ).execute()

    def append_rows(self, spreadsheet_id, range, values, value_input_option="USER_ENTERED"):
        return self.service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id, range=range, valueInputOption=value_input_option,
            insertDataOption="INSERT_ROWS", body={"values": values},
        ).execute()

    def clear_range(self, spreadsheet_id, range):
        return self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id, range=range, body={}
        ).execute()

    # --- spreadsheet / structure ---
    def create_spreadsheet(self, title):
        return self.service.spreadsheets().create(body={"properties": {"title": title}}).execute()

    def get_spreadsheet(self, spreadsheet_id, include_grid_data=False):
        return self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id, includeGridData=include_grid_data
        ).execute()

    def add_sheet(self, spreadsheet_id, title):
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()

    def rename_sheet(self, spreadsheet_id, sheet_id, new_title):
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"updateSheetProperties": {"properties": {"sheetId": sheet_id, "title": new_title}, "fields": "title"}}]},
        ).execute()

    def delete_sheet(self, spreadsheet_id, sheet_id):
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        ).execute()

    # --- formatting / structure helpers ---
    def _hex_to_color(self, hex_str):
        h = hex_str.lstrip("#")
        return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

    def _a1_to_grid_range(self, spreadsheet_id, a1):
        # rpartition already puts the cell part last and the (optional) sheet
        # name first, for both "Sheet1!A1:C10" and a bare "A1:C10".
        sheet_name, _, cell_part = a1.rpartition("!")
        meta = self.get_spreadsheet(spreadsheet_id)
        sheets = meta.get("sheets", [])
        if sheet_name:
            sheet_name = sheet_name.strip("'\"")
            sheet_id = next(s["properties"]["sheetId"] for s in sheets if s["properties"]["title"] == sheet_name)
        else:
            sheet_id = sheets[0]["properties"]["sheetId"]
        grid = {"sheetId": sheet_id}
        start, _, end = cell_part.partition(":")
        end = end or start

        def col_to_index(letters):
            idx = 0
            for ch in letters:
                idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
            return idx - 1

        def split_cell(cell):
            letters = "".join(c for c in cell if c.isalpha())
            digits = "".join(c for c in cell if c.isdigit())
            return letters, digits

        start_letters, start_digits = split_cell(start)
        end_letters, end_digits = split_cell(end)
        if start_letters:
            grid["startColumnIndex"] = col_to_index(start_letters)
        if end_letters:
            grid["endColumnIndex"] = col_to_index(end_letters) + 1
        if start_digits:
            grid["startRowIndex"] = int(start_digits) - 1
        if end_digits:
            grid["endRowIndex"] = int(end_digits)
        return grid

    def format_cells(self, spreadsheet_id, range, bold=None, italic=None, font_size=None, text_color=None,
                     background_color=None, number_format=None, horizontal_alignment=None, wrap=None):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        fmt = {}
        text_format = {}
        fields = []
        if bold is not None:
            text_format["bold"] = bold
            fields.append("userEnteredFormat.textFormat.bold")
        if italic is not None:
            text_format["italic"] = italic
            fields.append("userEnteredFormat.textFormat.italic")
        if font_size is not None:
            text_format["fontSize"] = font_size
            fields.append("userEnteredFormat.textFormat.fontSize")
        if text_color is not None:
            text_format["foregroundColor"] = self._hex_to_color(text_color)
            fields.append("userEnteredFormat.textFormat.foregroundColor")
        if text_format:
            fmt["textFormat"] = text_format
        if background_color is not None:
            fmt["backgroundColor"] = self._hex_to_color(background_color)
            fields.append("userEnteredFormat.backgroundColor")
        if number_format is not None:
            if number_format in {"NUMBER", "CURRENCY", "PERCENT", "DATE", "TIME", "DATE_TIME", "SCIENTIFIC"}:
                fmt["numberFormat"] = {"type": number_format}
            else:
                fmt["numberFormat"] = {"type": "NUMBER", "pattern": number_format}
            fields.append("userEnteredFormat.numberFormat")
        if horizontal_alignment is not None:
            fmt["horizontalAlignment"] = horizontal_alignment
            fields.append("userEnteredFormat.horizontalAlignment")
        if wrap is not None:
            fmt["wrapStrategy"] = "WRAP" if wrap else "OVERFLOW_CELL"
            fields.append("userEnteredFormat.wrapStrategy")
        if not fields:
            raise ValueError("format_cells requires at least one formatting parameter")
        req = {"repeatCell": {"range": grid, "cell": {"userEnteredFormat": fmt}, "fields": ",".join(fields)}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def sort_range(self, spreadsheet_id, range, column, ascending=True):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = {"sortRange": {"range": grid, "sortSpecs": [{"dimensionIndex": column, "sortOrder": "ASCENDING" if ascending else "DESCENDING"}]}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def set_basic_filter(self, spreadsheet_id, range):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = {"setBasicFilter": {"filter": {"range": grid}}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def clear_basic_filter(self, spreadsheet_id, range):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = {"clearBasicFilter": {"sheetId": grid["sheetId"]}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def merge_cells(self, spreadsheet_id, range, merge_type="MERGE_ALL"):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = {"mergeCells": {"range": grid, "mergeType": merge_type}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def unmerge_cells(self, spreadsheet_id, range):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = {"unmergeCells": {"range": grid}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()
