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
