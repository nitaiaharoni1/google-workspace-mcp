"""Minimal Google Sheets API wrapper (values + structure operations)."""
from __future__ import annotations

import google_auth_core as core
from google.auth.transport.requests import Request as GoogleAuthRequest


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
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise ValueError(f"invalid hex color: {hex_str!r}")
        return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}

    def _hex_to_color_style(self, hex_str):
        return {"rgbColor": self._hex_to_color(hex_str)}

    def _batch(self, spreadsheet_id, requests):
        if not requests:
            return {"replies": []}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    def _cell_part_to_grid(self, sheet_id, cell_part):
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

    def _resolve_a1(self, spreadsheet_id, a1, meta=None):
        sheet_name, _, cell_part = a1.rpartition("!")
        if meta is None:
            meta = self.get_spreadsheet(spreadsheet_id)
        sheets = meta.get("sheets", [])
        if sheet_name:
            sheet_name = sheet_name.strip("'\"")
            sheet_id = next(s["properties"]["sheetId"] for s in sheets if s["properties"]["title"] == sheet_name)
        else:
            sheet_id = sheets[0]["properties"]["sheetId"]
            sheet_name = sheets[0]["properties"]["title"]
        grid = self._cell_part_to_grid(sheet_id, cell_part)
        start, _, end = cell_part.partition(":")
        end = end or start
        start_row = int("".join(c for c in start if c.isdigit()) or "1")
        end_row = int("".join(c for c in end if c.isdigit()) or str(start_row))
        start_col = "".join(c for c in start if c.isalpha())
        end_col = "".join(c for c in end if c.isalpha())
        return sheet_name, sheet_id, grid, start_row, end_row, start_col, end_col

    def _quoted_sheet_range(self, sheet_name, cell_range):
        escaped = sheet_name.replace("'", "''")
        return f"'{escaped}'!{cell_range}"

    def _a1_to_grid_range(self, spreadsheet_id, a1, meta=None):
        _, _, grid, _, _, _, _ = self._resolve_a1(spreadsheet_id, a1, meta)
        return grid

    def _format_cells_request(self, grid, bold=None, italic=None, strikethrough=None, underline=None,
                              font_size=None, text_color=None, background_color=None, number_format=None,
                              horizontal_alignment=None, vertical_alignment=None, wrap=None):
        fmt = {}
        text_format = {}
        fields = []
        if bold is not None:
            text_format["bold"] = bold
            fields.append("userEnteredFormat.textFormat.bold")
        if italic is not None:
            text_format["italic"] = italic
            fields.append("userEnteredFormat.textFormat.italic")
        if strikethrough is not None:
            text_format["strikethrough"] = strikethrough
            fields.append("userEnteredFormat.textFormat.strikethrough")
        if underline is not None:
            text_format["underline"] = underline
            fields.append("userEnteredFormat.textFormat.underline")
        if font_size is not None:
            text_format["fontSize"] = font_size
            fields.append("userEnteredFormat.textFormat.fontSize")
        if text_color is not None:
            text_format["foregroundColorStyle"] = self._hex_to_color_style(text_color)
            fields.append("userEnteredFormat.textFormat.foregroundColorStyle")
        if text_format:
            fmt["textFormat"] = text_format
        if background_color is not None:
            fmt["backgroundColorStyle"] = self._hex_to_color_style(background_color)
            fields.append("userEnteredFormat.backgroundColorStyle")
        if number_format is not None:
            if number_format in {"NUMBER", "CURRENCY", "PERCENT", "DATE", "TIME", "DATE_TIME", "SCIENTIFIC"}:
                fmt["numberFormat"] = {"type": number_format}
            else:
                fmt["numberFormat"] = {"type": "NUMBER", "pattern": number_format}
            fields.append("userEnteredFormat.numberFormat")
        if horizontal_alignment is not None:
            fmt["horizontalAlignment"] = horizontal_alignment
            fields.append("userEnteredFormat.horizontalAlignment")
        if vertical_alignment is not None:
            fmt["verticalAlignment"] = vertical_alignment
            fields.append("userEnteredFormat.verticalAlignment")
        if wrap is not None:
            fmt["wrapStrategy"] = "WRAP" if wrap else "OVERFLOW_CELL"
            fields.append("userEnteredFormat.wrapStrategy")
        if not fields:
            raise ValueError("format_cells requires at least one formatting parameter")
        return {"repeatCell": {"range": grid, "cell": {"userEnteredFormat": fmt}, "fields": ",".join(fields)}}

    def format_cells(self, spreadsheet_id, range, bold=None, italic=None, strikethrough=None, underline=None,
                     font_size=None, text_color=None, background_color=None, number_format=None,
                     horizontal_alignment=None, vertical_alignment=None, wrap=None):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = self._format_cells_request(
            grid, bold, italic, strikethrough, underline, font_size, text_color, background_color,
            number_format, horizontal_alignment, vertical_alignment, wrap,
        )
        return self._batch(spreadsheet_id, [req])

    def _banding_properties(self, header_color=None, first_band_color=None, second_band_color=None, footer_color=None):
        props = {}
        if header_color is not None:
            props["headerColorStyle"] = self._hex_to_color_style(header_color)
        if first_band_color is not None:
            props["firstBandColorStyle"] = self._hex_to_color_style(first_band_color)
        if second_band_color is not None:
            props["secondBandColorStyle"] = self._hex_to_color_style(second_band_color)
        if footer_color is not None:
            props["footerColorStyle"] = self._hex_to_color_style(footer_color)
        if not props:
            raise ValueError("banding requires at least one color")
        return props

    def _banding_request(self, grid, header_color=None, first_band_color="#FFFFFF",
                         second_band_color="#F3F3F3", footer_color=None, band_rows=True):
        props = self._banding_properties(header_color, first_band_color, second_band_color, footer_color)
        banded = {"range": grid}
        if band_rows:
            banded["rowProperties"] = props
        else:
            banded["columnProperties"] = props
        return {"addBanding": {"bandedRange": banded}}

    def add_banding(self, spreadsheet_id, range, header_color=None, first_band_color="#FFFFFF",
                    second_band_color="#F3F3F3", footer_color=None, band_rows=True):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        return self._batch(spreadsheet_id, [self._banding_request(
            grid, header_color, first_band_color, second_band_color, footer_color, band_rows,
        )])

    def update_banding(self, spreadsheet_id, banded_range_id, header_color=None, first_band_color=None,
                       second_band_color=None, footer_color=None):
        props = self._banding_properties(header_color, first_band_color, second_band_color, footer_color)
        banded = {"bandedRangeId": banded_range_id, "rowProperties": props}
        fields = ",".join(f"rowProperties.{k}" for k in props)
        return self._batch(spreadsheet_id, [{"updateBanding": {"bandedRange": banded, "fields": fields}}])

    def delete_banding(self, spreadsheet_id, banded_range_id):
        return self._batch(spreadsheet_id, [{"deleteBanding": {"bandedRangeId": banded_range_id}}])

    def _build_filter_criteria(self, spec):
        criteria = {}
        if spec.get("hidden_values") is not None:
            criteria["hiddenValues"] = spec["hidden_values"]
        condition_type = spec.get("condition_type")
        if condition_type:
            values = spec.get("values", [])
            criteria["condition"] = {
                "type": condition_type,
                "values": [{"userEnteredValue": str(v)} for v in values],
            }
        return criteria

    def _build_filter_specs(self, filter_specs):
        built = []
        for spec in filter_specs:
            criteria = self._build_filter_criteria(spec)
            if not criteria:
                raise ValueError("each filter_spec needs hidden_values and/or condition_type + values")
            built.append({"columnIndex": spec["column"], "filterCriteria": criteria})
        return built

    def sort_range(self, spreadsheet_id, range, column, ascending=True):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        req = {"sortRange": {"range": grid, "sortSpecs": [{"dimensionIndex": column, "sortOrder": "ASCENDING" if ascending else "DESCENDING"}]}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def set_basic_filter(self, spreadsheet_id, range, filter_specs=None, sort_specs=None):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        filt = {"range": grid}
        if filter_specs:
            filt["filterSpecs"] = self._build_filter_specs(filter_specs)
        if sort_specs:
            filt["sortSpecs"] = [
                {
                    "dimensionIndex": s["column"],
                    "sortOrder": "ASCENDING" if s.get("ascending", True) else "DESCENDING",
                }
                for s in sort_specs
            ]
        return self._batch(spreadsheet_id, [{"setBasicFilter": {"filter": filt}}])

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

    # --- dimensions (columns / rows) ---
    def _dimension_range(self, spreadsheet_id, range, dimension):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        if dimension == "COLUMNS":
            start, end = grid.get("startColumnIndex"), grid.get("endColumnIndex")
            hint = "column letters (e.g. 'Sheet1!A:C')"
        else:
            start, end = grid.get("startRowIndex"), grid.get("endRowIndex")
            hint = "row numbers (e.g. 'Sheet1!2:5')"
        if start is None or end is None:
            raise ValueError(f"range must include {hint}")
        return {"sheetId": grid["sheetId"], "dimension": dimension, "startIndex": start, "endIndex": end}

    def resize_dimension(self, spreadsheet_id, range, dimension, pixel_size=None):
        dim = self._dimension_range(spreadsheet_id, range, dimension)
        if pixel_size is None:
            req = {"autoResizeDimensions": {"dimensions": dim}}
        else:
            req = {"updateDimensionProperties": {"range": dim, "properties": {"pixelSize": pixel_size}, "fields": "pixelSize"}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def insert_dimension(self, spreadsheet_id, range, dimension, inherit_from_before=False):
        dim = self._dimension_range(spreadsheet_id, range, dimension)
        req = {"insertDimension": {"range": dim, "inheritFromBefore": inherit_from_before}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def delete_dimension(self, spreadsheet_id, range, dimension):
        dim = self._dimension_range(spreadsheet_id, range, dimension)
        req = {"deleteDimension": {"range": dim}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    # --- sheet-level helpers ---
    def freeze_panes(self, spreadsheet_id, range, rows=None, cols=None):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        props = {"sheetId": grid["sheetId"], "gridProperties": {}}
        fields = []
        if rows is not None:
            props["gridProperties"]["frozenRowCount"] = rows
            fields.append("gridProperties.frozenRowCount")
        if cols is not None:
            props["gridProperties"]["frozenColumnCount"] = cols
            fields.append("gridProperties.frozenColumnCount")
        if not fields:
            raise ValueError("freeze_panes requires rows and/or cols")
        req = {"updateSheetProperties": {"properties": props, "fields": ",".join(fields)}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()

    def duplicate_sheet(self, spreadsheet_id, sheet_id, new_title=None):
        body = {"sourceSheetId": sheet_id}
        if new_title:
            body["newSheetName"] = new_title
        return self._batch(spreadsheet_id, [{"duplicateSheet": body}])

    def add_table(self, spreadsheet_id, range, name, header_color="#355468", first_band_color="#FFFFFF",
                  second_band_color="#F3F3F3", column_names=None):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        table = {
            "name": name,
            "range": grid,
            "rowsProperties": {
                "headerColorStyle": self._hex_to_color_style(header_color),
                "firstBandColorStyle": self._hex_to_color_style(first_band_color),
                "secondBandColorStyle": self._hex_to_color_style(second_band_color),
            },
        }
        if column_names:
            table["columnProperties"] = [
                {"columnIndex": i, "columnName": col_name} for i, col_name in enumerate(column_names)
            ]
        return self._batch(spreadsheet_id, [{"addTable": {"table": table}}])

    def format_table(self, spreadsheet_id, range, header_color="#355468", header_text_color="#FFFFFF",
                     first_band_color="#FFFFFF", second_band_color="#F3F3F3", wrap=True, auto_resize_columns=True,
                     add_filter=True, add_borders=True, freeze_header=True):
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
            if wrap:
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
        if auto_resize_columns and start_col and end_col:
            col_start = grid.get("startColumnIndex")
            col_end = grid.get("endColumnIndex")
            if col_start is not None and col_end is not None:
                requests.append({"autoResizeDimensions": {
                    "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": col_start, "endIndex": col_end},
                }})
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

    def write_formulas(self, spreadsheet_id, range, formulas, value_input_option="USER_ENTERED"):
        """Write formula strings (e.g. '=SUM(A2:A10)') to a range. Same as update_range with USER_ENTERED."""
        return self.update_range(spreadsheet_id, range, formulas, value_input_option)

    def read_formulas(self, spreadsheet_id, range):
        return self.read_range(spreadsheet_id, range, value_render_option="FORMULA")

    # --- chart export (for Docs insert_sheets_chart) ---

    @staticmethod
    def get_chart_image_url(spreadsheet_id, chart_id):
        """Return the authenticated chart export URL (PNG). Requires sign-in when fetched."""
        return (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
            f"/chart?oid={chart_id}&format=image"
        )

    def fetch_chart_image_bytes(self, spreadsheet_id, chart_id):
        """Download chart PNG bytes using the authenticated account."""
        url = self.get_chart_image_url(spreadsheet_id, chart_id)
        creds, _ = core.get_credentials(self.account, service_name="sheets")
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        import urllib.request

        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {creds.token}"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        if not data:
            raise ValueError(f"empty chart image response for chart_id={chart_id!r}")
        return data

    def set_borders(self, spreadsheet_id, range, style="SOLID", color="#000000",
                    top=True, bottom=True, left=True, right=True, inner=False):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        border = {"style": style, "color": self._hex_to_color(color)}
        body = {"range": grid}
        if top:
            body["top"] = border
        if bottom:
            body["bottom"] = border
        if left:
            body["left"] = border
        if right:
            body["right"] = border
        if inner:
            body["innerHorizontal"] = border
            body["innerVertical"] = border
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [{"updateBorders": body}]}
        ).execute()

    def set_data_validation(self, spreadsheet_id, range, allowed_values=None, show_dropdown=True):
        grid = self._a1_to_grid_range(spreadsheet_id, range)
        if allowed_values:
            rule = {
                "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": str(v)} for v in allowed_values]},
                "showCustomUi": show_dropdown,
                "strict": True,
            }
            req = {"setDataValidation": {"range": grid, "rule": rule}}
        else:
            req = {"setDataValidation": {"range": grid}}
        return self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": [req]}
        ).execute()
