"""Google Docs API wrapper (create, read, edit, format, layout, headers/footers)."""
from __future__ import annotations

import io

import google_auth_core as core
from googleapiclient.http import MediaIoBaseUpload

PAGE_PRESETS = {
    "LETTER": (612, 792),
    "A4": (595.28, 841.89),
    "LEGAL": (612, 1008),
    "TABLOID": (792, 1224),
}

NUMBERED_BULLET_PRESETS = {
    "NUMBERED_DECIMAL_ALPHA_ROMAN",
    "NUMBERED_DECIMAL_ALPHA_ROMAN_PARENS",
    "NUMBERED_DECIMAL_NESTED",
    "NUMBERED_UPPERALPHA_ALPHA_ROMAN",
    "NUMBERED_UPPERROMAN_UPPERALPHA_DECIMAL",
    "NUMBERED_ZERODECIMAL_ALPHA_ROMAN",
}


class DocsAPI:
    def __init__(self, account=None):
        self.account = account
        self.service = core.get_service("docs", "v1", account=account)

    def _batch(self, document_id, requests):
        return self.service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

    def batch_update(self, document_id, requests):
        """Pass raw batchUpdate request dicts through to the Docs API."""
        if not isinstance(requests, list) or not requests:
            raise ValueError("requests must be a non-empty list")
        return self._batch(document_id, requests)

    @staticmethod
    def _pt(points):
        return {"magnitude": points, "unit": "PT"}

    def _size_pt(self, width, height):
        return {"width": self._pt(width), "height": self._pt(height)}

    def create_document(self, title):
        return self.service.documents().create(body={"title": title}).execute()

    def get_document(self, document_id):
        return self.service.documents().get(documentId=document_id).execute()

    def get_document_text(self, document_id):
        """Extract the plain text of a document (paragraphs + table cells)."""
        doc = self.get_document(document_id)

        def walk(elements):
            parts = []
            for el in elements:
                para = el.get("paragraph")
                if para:
                    for e in para.get("elements", []):
                        tr = e.get("textRun")
                        if tr and tr.get("content"):
                            parts.append(tr["content"])
                table = el.get("table")
                if table:
                    for row in table.get("tableRows", []):
                        for cell in row.get("tableCells", []):
                            parts.append(walk(cell.get("content", [])))
            return "".join(parts)

        text = walk(doc.get("body", {}).get("content", []))
        return {"documentId": document_id, "title": doc.get("title"), "text": text}

    def insert_text(self, document_id, text, index=1, segment_id=None):
        location = {"index": index}
        if segment_id:
            location["segmentId"] = segment_id
        return self._batch(document_id, [{"insertText": {"location": location, "text": text}}])

    def append_text(self, document_id, text):
        doc = self.get_document(document_id)
        content = doc.get("body", {}).get("content", [])
        end = content[-1].get("endIndex", 2) - 1 if content else 1
        if end < 1:
            end = 1
        return self.insert_text(document_id, text, index=end)

    def replace_all_text(self, document_id, find, replace, match_case=False):
        return self._batch(document_id, [{"replaceAllText": {
            "containsText": {"text": find, "matchCase": match_case},
            "replaceText": replace,
        }}])

    def _hex_to_rgb_color(self, hex_str):
        h = hex_str.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            raise ValueError(f"invalid hex color: {hex_str!r}")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return {"red": r / 255, "green": g / 255, "blue": b / 255}

    def format_text(self, document_id, start_index, end_index, bold=None, italic=None, underline=None,
                    strikethrough=None, font_size=None, font_family=None, link_url=None,
                    foreground_color=None, background_color=None, segment_id=None):
        text_style = {}
        fields = []
        if bold is not None:
            text_style["bold"] = bold
            fields.append("bold")
        if italic is not None:
            text_style["italic"] = italic
            fields.append("italic")
        if underline is not None:
            text_style["underline"] = underline
            fields.append("underline")
        if strikethrough is not None:
            text_style["strikethrough"] = strikethrough
            fields.append("strikethrough")
        if font_size is not None:
            text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
            fields.append("fontSize")
        if font_family is not None:
            text_style["weightedFontFamily"] = {"fontFamily": font_family}
            fields.append("weightedFontFamily")
        if link_url is not None:
            text_style["link"] = {"url": link_url}
            fields.append("link")
        if foreground_color is not None:
            text_style["foregroundColor"] = {"color": {"rgbColor": self._hex_to_rgb_color(foreground_color)}}
            fields.append("foregroundColor")
        if background_color is not None:
            text_style["backgroundColor"] = {"color": {"rgbColor": self._hex_to_rgb_color(background_color)}}
            fields.append("backgroundColor")
        if not fields:
            raise ValueError("format_text requires at least one style attribute")
        text_range = {"startIndex": start_index, "endIndex": end_index}
        if segment_id:
            text_range["segmentId"] = segment_id
        return self._batch(document_id, [{"updateTextStyle": {
            "range": text_range,
            "textStyle": text_style,
            "fields": ",".join(fields),
        }}])

    def set_paragraph_style(self, document_id, start_index, end_index, named_style):
        valid = {"NORMAL_TEXT", "TITLE", "SUBTITLE", "HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4", "HEADING_5", "HEADING_6"}
        if named_style not in valid:
            raise ValueError(f"named_style must be one of {sorted(valid)}")
        return self.update_paragraph_style(document_id, start_index, end_index, named_style_type=named_style)

    def update_paragraph_style(self, document_id, start_index, end_index, named_style_type=None,
                               alignment=None, indent_start_pt=None, indent_end_pt=None,
                               space_above_pt=None, space_below_pt=None, line_spacing=None,
                               line_spacing_mode=None, segment_id=None):
        paragraph_style = {}
        fields = []
        if named_style_type is not None:
            paragraph_style["namedStyleType"] = named_style_type
            fields.append("namedStyleType")
        if alignment is not None:
            valid_align = {"START", "END", "CENTER", "JUSTIFIED"}
            if alignment not in valid_align:
                raise ValueError(f"alignment must be one of {sorted(valid_align)}")
            paragraph_style["alignment"] = alignment
            fields.append("alignment")
        if indent_start_pt is not None:
            paragraph_style["indentStart"] = self._pt(indent_start_pt)
            fields.append("indentStart")
        if indent_end_pt is not None:
            paragraph_style["indentEnd"] = self._pt(indent_end_pt)
            fields.append("indentEnd")
        if space_above_pt is not None:
            paragraph_style["spaceAbove"] = self._pt(space_above_pt)
            fields.append("spaceAbove")
        if space_below_pt is not None:
            paragraph_style["spaceBelow"] = self._pt(space_below_pt)
            fields.append("spaceBelow")
        if line_spacing is not None:
            paragraph_style["lineSpacing"] = line_spacing
            fields.append("lineSpacing")
        if line_spacing_mode is not None:
            valid_modes = {"AT_LEAST", "EXACTLY", "MULTIPLE"}
            if line_spacing_mode not in valid_modes:
                raise ValueError(f"line_spacing_mode must be one of {sorted(valid_modes)}")
            paragraph_style["spacingMode"] = line_spacing_mode
            fields.append("spacingMode")
        if not fields:
            raise ValueError("update_paragraph_style requires at least one style attribute")
        text_range = {"startIndex": start_index, "endIndex": end_index}
        if segment_id:
            text_range["segmentId"] = segment_id
        return self._batch(document_id, [{"updateParagraphStyle": {
            "range": text_range,
            "paragraphStyle": paragraph_style,
            "fields": ",".join(fields),
        }}])

    def set_page_layout(self, document_id, page_preset=None, width_pt=None, height_pt=None,
                        margin_top_pt=None, margin_bottom_pt=None, margin_left_pt=None, margin_right_pt=None,
                        margin_header_pt=None, margin_footer_pt=None, flip_page_orientation=None):
        document_style = {}
        fields = []
        if page_preset is not None:
            if page_preset not in PAGE_PRESETS:
                raise ValueError(f"page_preset must be one of {sorted(PAGE_PRESETS)}")
            width_pt, height_pt = PAGE_PRESETS[page_preset]
        if width_pt is not None or height_pt is not None:
            if width_pt is None or height_pt is None:
                raise ValueError("width_pt and height_pt must both be set (or use page_preset)")
            document_style["pageSize"] = self._size_pt(width_pt, height_pt)
            fields.append("pageSize")
        for attr, value in (
            ("marginTop", margin_top_pt),
            ("marginBottom", margin_bottom_pt),
            ("marginLeft", margin_left_pt),
            ("marginRight", margin_right_pt),
            ("marginHeader", margin_header_pt),
            ("marginFooter", margin_footer_pt),
        ):
            if value is not None:
                document_style[attr] = self._pt(value)
                fields.append(attr)
        if flip_page_orientation is not None:
            document_style["flipPageOrientation"] = flip_page_orientation
            fields.append("flipPageOrientation")
        if not fields:
            raise ValueError("set_page_layout requires at least one layout attribute")
        return self._batch(document_id, [{"updateDocumentStyle": {
            "documentStyle": document_style,
            "fields": ",".join(fields),
        }}])

    def flip_page_orientation(self, document_id, flip=True):
        """Toggle between portrait and landscape (swaps page width/height)."""
        return self.set_page_layout(document_id, flip_page_orientation=flip)

    def create_header(self, document_id, header_type="DEFAULT"):
        if header_type not in {"DEFAULT"}:
            raise ValueError("header_type must be DEFAULT")
        return self._batch(document_id, [{"createHeader": {"type": header_type}}])

    def create_footer(self, document_id, footer_type="DEFAULT"):
        if footer_type not in {"DEFAULT"}:
            raise ValueError("footer_type must be DEFAULT")
        return self._batch(document_id, [{"createFooter": {"type": footer_type}}])

    def delete_header(self, document_id, header_id):
        return self._batch(document_id, [{"deleteHeader": {"headerId": header_id}}])

    def delete_footer(self, document_id, footer_id):
        return self._batch(document_id, [{"deleteFooter": {"footerId": footer_id}}])

    def setup_header(self, document_id, text, header_type="DEFAULT", index=0):
        resp = self.create_header(document_id, header_type)
        header_id = resp["replies"][0]["createHeader"]["headerId"]
        insert_resp = self.insert_text(document_id, text, index=index, segment_id=header_id)
        return {"headerId": header_id, "createHeader": resp, "insertText": insert_resp}

    def setup_footer(self, document_id, text, footer_type="DEFAULT", index=0):
        resp = self.create_footer(document_id, footer_type)
        footer_id = resp["replies"][0]["createFooter"]["footerId"]
        insert_resp = self.insert_text(document_id, text, index=index, segment_id=footer_id)
        return {"footerId": footer_id, "createFooter": resp, "insertText": insert_resp}

    def insert_inline_image(self, document_id, uri, index=1, width_pt=None, height_pt=None, segment_id=None):
        location = {"index": index}
        if segment_id:
            location["segmentId"] = segment_id
        req = {"insertInlineImage": {"location": location, "uri": uri}}
        if width_pt is not None or height_pt is not None:
            size = {}
            if width_pt is not None:
                size["width"] = self._pt(width_pt)
            if height_pt is not None:
                size["height"] = self._pt(height_pt)
            req["insertInlineImage"]["objectSize"] = size
        return self._batch(document_id, [req])

    def insert_chart_image(self, document_id, uri, index=1, width_pt=468, height_pt=280, segment_id=None):
        """Insert a chart as an inline image (Google Docs has no native chart API).

        Render the chart elsewhere (Sheets export, matplotlib, etc.) and pass a public image URL.
        """
        return self.insert_inline_image(
            document_id, uri, index=index, width_pt=width_pt, height_pt=height_pt, segment_id=segment_id
        )

    def insert_table(self, document_id, rows, columns, index=1, segment_id=None):
        location = {"index": index}
        if segment_id:
            location["segmentId"] = segment_id
        return self._batch(document_id, [{"insertTable": {
            "rows": rows,
            "columns": columns,
            "location": location,
        }}])

    def insert_page_break(self, document_id, index=1, segment_id=None):
        location = {"index": index}
        if segment_id:
            location["segmentId"] = segment_id
        return self._batch(document_id, [{"insertPageBreak": {"location": location}}])

    def insert_bullets(self, document_id, start_index, end_index, bullet_preset="BULLET_DISC_CIRCLE_SQUARE", segment_id=None):
        text_range = {"startIndex": start_index, "endIndex": end_index}
        if segment_id:
            text_range["segmentId"] = segment_id
        return self._batch(document_id, [{"createParagraphBullets": {
            "range": text_range,
            "bulletPreset": bullet_preset,
        }}])

    def insert_numbered_list(self, document_id, start_index, end_index,
                             preset="NUMBERED_DECIMAL_ALPHA_ROMAN", segment_id=None):
        """Apply numbered list formatting to paragraphs in a range.

        Valid presets: NUMBERED_DECIMAL_ALPHA_ROMAN, NUMBERED_DECIMAL_ALPHA_ROMAN_PARENS,
        NUMBERED_DECIMAL_NESTED, NUMBERED_UPPERALPHA_ALPHA_ROMAN,
        NUMBERED_UPPERROMAN_UPPERALPHA_DECIMAL, NUMBERED_ZERODECIMAL_ALPHA_ROMAN.
        """
        if preset not in NUMBERED_BULLET_PRESETS:
            raise ValueError(f"preset must be one of {sorted(NUMBERED_BULLET_PRESETS)}")
        return self.insert_bullets(document_id, start_index, end_index, preset, segment_id)

    def remove_bullets(self, document_id, start_index, end_index, segment_id=None):
        text_range = {"startIndex": start_index, "endIndex": end_index}
        if segment_id:
            text_range["segmentId"] = segment_id
        return self._batch(document_id, [{"deleteParagraphBullets": {"range": text_range}}])

    def delete_range(self, document_id, start_index, end_index, segment_id=None):
        text_range = {"startIndex": start_index, "endIndex": end_index}
        if segment_id:
            text_range["segmentId"] = segment_id
        return self._batch(document_id, [{"deleteContentRange": {"range": text_range}}])

    # --- content map / table helpers ---

    @staticmethod
    def _paragraph_text(paragraph):
        parts = []
        for elem in paragraph.get("elements", []):
            tr = elem.get("textRun")
            if tr and tr.get("content"):
                parts.append(tr["content"])
            if elem.get("autoText"):
                parts.append(f"[{elem['autoText'].get('type', 'AUTO')}]")
        return "".join(parts)

    @classmethod
    def _text_preview(cls, elements, max_len=80):
        parts = []
        for el in elements:
            para = el.get("paragraph")
            if para:
                parts.append(cls._paragraph_text(para))
            table = el.get("table")
            if table:
                for row in table.get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        parts.append(cls._text_preview(cell.get("content", [])))
        text = "".join(parts).replace("\n", " ").strip()
        if len(text) > max_len:
            return text[: max_len - 3] + "..."
        return text

    @classmethod
    def _map_table_cells(cls, table):
        cells = []
        for row_idx, row in enumerate(table.get("tableRows", [])):
            for col_idx, cell in enumerate(row.get("tableCells", [])):
                content = cell.get("content", [])
                entry = {"row": row_idx, "column": col_idx}
                if content:
                    entry["startIndex"] = content[0].get("startIndex")
                    entry["endIndex"] = content[-1].get("endIndex")
                    entry["textPreview"] = cls._text_preview(content)
                cells.append(entry)
        return cells

    @classmethod
    def _walk_content(cls, content, segment_id=None, segment_type="body", elements=None):
        if elements is None:
            elements = []
        for el in content:
            entry = {
                "type": "unknown",
                "startIndex": el.get("startIndex"),
                "endIndex": el.get("endIndex"),
                "segmentId": segment_id,
                "segmentType": segment_type,
            }
            if el.get("paragraph"):
                para = el["paragraph"]
                entry["type"] = "paragraph"
                entry["textPreview"] = cls._paragraph_text(para).replace("\n", " ").strip()
                style = para.get("paragraphStyle", {})
                if style.get("namedStyleType"):
                    entry["namedStyleType"] = style["namedStyleType"]
            elif el.get("table"):
                table = el["table"]
                entry["type"] = "table"
                entry["rows"] = table.get("rows")
                entry["columns"] = table.get("columns")
                entry["cells"] = cls._map_table_cells(table)
            elif el.get("sectionBreak"):
                entry["type"] = "sectionBreak"
            elif el.get("tableOfContents"):
                entry["type"] = "tableOfContents"
            elif el.get("pageBreak"):
                entry["type"] = "pageBreak"
            elements.append(entry)
        return elements

    def get_content_map(self, document_id, include_headers_footers=True):
        """Walk document structure and return indexed elements for agent-friendly editing."""
        doc = self.get_document(document_id)
        elements = self._walk_content(doc.get("body", {}).get("content", []), segment_type="body")
        if include_headers_footers:
            for header_id, header in (doc.get("headers") or {}).items():
                self._walk_content(
                    header.get("content", []),
                    segment_id=header_id,
                    segment_type="header",
                    elements=elements,
                )
            for footer_id, footer in (doc.get("footers") or {}).items():
                self._walk_content(
                    footer.get("content", []),
                    segment_id=footer_id,
                    segment_type="footer",
                    elements=elements,
                )
        return {
            "documentId": document_id,
            "title": doc.get("title"),
            "elements": elements,
        }

    def _table_start_location(self, table_start_index, segment_id=None):
        loc = {"index": table_start_index}
        if segment_id:
            loc["segmentId"] = segment_id
        return loc

    def _table_range(self, table_start_index, row, column, row_span=1, column_span=1, segment_id=None):
        return {
            "tableCellLocation": {
                "tableStartLocation": self._table_start_location(table_start_index, segment_id),
                "rowIndex": row,
                "columnIndex": column,
            },
            "rowSpan": row_span,
            "columnSpan": column_span,
        }

    def _find_table(self, content, table_start_index):
        for el in content:
            if el.get("startIndex") == table_start_index and el.get("table"):
                return el["table"]
        return None

    def populate_table(self, document_id, table_start_index, rows, segment_id=None):
        """Fill table cells with text. Rows is a list of row lists of strings."""
        if not rows or not isinstance(rows, list):
            raise ValueError("rows must be a non-empty list of row lists")
        doc = self.get_document(document_id)
        content = doc.get("body", {}).get("content", [])
        if segment_id:
            segment = (doc.get("headers") or {}).get(segment_id) or (doc.get("footers") or {}).get(segment_id)
            if not segment:
                raise ValueError(f"segment_id {segment_id!r} not found in document headers/footers")
            content = segment.get("content", [])
        table = self._find_table(content, table_start_index)
        if table is None:
            raise ValueError(f"no table found at startIndex {table_start_index}")
        table_rows = table.get("tableRows", [])
        if len(rows) != len(table_rows):
            raise ValueError(
                f"rows has {len(rows)} row(s) but table has {len(table_rows)} row(s)"
            )
        inserts = []
        for row_idx, row_values in enumerate(rows):
            table_cells = table_rows[row_idx].get("tableCells", [])
            if len(row_values) != len(table_cells):
                raise ValueError(
                    f"row {row_idx} has {len(row_values)} value(s) but table has {len(table_cells)} column(s)"
                )
            for col_idx, text in enumerate(row_values):
                cell_content = table_cells[col_idx].get("content", [])
                if not cell_content:
                    raise ValueError(f"cell ({row_idx}, {col_idx}) has no content to insert into")
                index = cell_content[0].get("startIndex")
                if index is None:
                    raise ValueError(f"cell ({row_idx}, {col_idx}) missing startIndex")
                location = {"index": index}
                if segment_id:
                    location["segmentId"] = segment_id
                inserts.append((index, str(text)))
        requests = [
            {"insertText": {"location": {"index": idx, **({"segmentId": segment_id} if segment_id else {})}, "text": text}}
            for idx, text in sorted(inserts, key=lambda item: item[0], reverse=True)
        ]
        return self._batch(document_id, requests)

    def merge_table_cells(self, document_id, table_start_index, row, column, row_span, column_span,
                          segment_id=None):
        return self._batch(document_id, [{
            "mergeTableCells": {
                "tableRange": self._table_range(
                    table_start_index, row, column, row_span, column_span, segment_id,
                ),
            },
        }])

    def format_table_cells(self, document_id, table_start_index, row, column, row_span=1, column_span=1,
                           background_color=None, border_color=None, border_width_pt=None, segment_id=None):
        table_cell_style = {}
        fields = []
        if background_color is not None:
            table_cell_style["backgroundColor"] = {
                "color": {"rgbColor": self._hex_to_rgb_color(background_color)},
            }
            fields.append("backgroundColor")
        if border_color is not None or border_width_pt is not None:
            border = {"dashStyle": "SOLID"}
            if border_color is not None:
                border["color"] = {"color": {"rgbColor": self._hex_to_rgb_color(border_color)}}
            if border_width_pt is not None:
                border["width"] = self._pt(border_width_pt)
            for side in ("borderTop", "borderBottom", "borderLeft", "borderRight"):
                table_cell_style[side] = border
                fields.append(side)
        if not fields:
            raise ValueError("format_table_cells requires at least one style attribute")
        return self._batch(document_id, [{
            "updateTableCellStyle": {
                "tableRange": self._table_range(
                    table_start_index, row, column, row_span, column_span, segment_id,
                ),
                "tableCellStyle": table_cell_style,
                "fields": ",".join(fields),
            },
        }])

    def insert_page_number(self, document_id, footer_id, index=0):
        """Insert a dynamic page number field into a footer segment.

        Note: the public Google Docs API currently rejects ``insertPageNumber``
        (400 Unknown name). Kept for forward compatibility; use the Docs UI or
        a template with page numbers pre-configured until Google exposes this request.
        """
        location = {"segmentId": footer_id, "index": index}
        return self._batch(document_id, [{"insertPageNumber": {"location": location}}])

    def _upload_public_image_uri(self, image_bytes, name="chart.png", account=None):
        drive = core.get_service("drive", "v3", account=account or self.account)
        media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/png", resumable=True)
        created = drive.files().create(
            body={"name": name},
            media_body=media,
            fields="id",
        ).execute()
        file_id = created["id"]
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            sendNotificationEmail=False,
        ).execute()
        return f"https://drive.google.com/uc?export=view&id={file_id}"

    def insert_sheets_chart(self, document_id, spreadsheet_id, chart_id, index=1,
                            width_pt=468, height_pt=280, account=None):
        """Export a Sheets chart as PNG and insert it into the document."""
        from ..sheets.sheets_api import SheetsAPI

        resolved_account = account or self.account
        sheets = SheetsAPI(resolved_account)
        image_bytes = sheets.fetch_chart_image_bytes(spreadsheet_id, chart_id)
        uri = self._upload_public_image_uri(
            image_bytes,
            name=f"chart-{chart_id}.png",
            account=resolved_account,
        )
        result = self.insert_chart_image(
            document_id, uri, index=index, width_pt=width_pt, height_pt=height_pt,
        )
        return {"imageUri": uri, "insertInlineImage": result}
