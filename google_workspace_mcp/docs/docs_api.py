"""Google Docs API wrapper (create, read, edit, format, layout, headers/footers)."""
from __future__ import annotations
import google_auth_core as core

PAGE_PRESETS = {
    "LETTER": (612, 792),
    "A4": (595.28, 841.89),
    "LEGAL": (612, 1008),
    "TABLOID": (792, 1224),
}


class DocsAPI:
    def __init__(self, account=None):
        self.account = account
        self.service = core.get_service("docs", "v1", account=account)

    def _batch(self, document_id, requests):
        return self.service.documents().batchUpdate(
            documentId=document_id, body={"requests": requests}
        ).execute()

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
        hex_str = hex_str.lstrip("#")
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
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
                               space_above_pt=None, space_below_pt=None, segment_id=None):
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

    def insert_table(self, document_id, rows, columns, index=1, segment_id=None):
        location = {"index": index}
        if segment_id:
            location["segmentId"] = segment_id
        return self._batch(document_id, [{"insertTable": {
            "rows": rows,
            "columns": columns,
            "location": location,
        }}])

    def insert_page_break(self, document_id, index=1):
        return self._batch(document_id, [{"insertPageBreak": {"location": {"index": index}}}])

    def insert_bullets(self, document_id, start_index, end_index, bullet_preset="BULLET_DISC_CIRCLE_SQUARE"):
        return self._batch(document_id, [{"createParagraphBullets": {
            "range": {"startIndex": start_index, "endIndex": end_index},
            "bulletPreset": bullet_preset,
        }}])

    def delete_range(self, document_id, start_index, end_index, segment_id=None):
        text_range = {"startIndex": start_index, "endIndex": end_index}
        if segment_id:
            text_range["segmentId"] = segment_id
        return self._batch(document_id, [{"deleteContentRange": {"range": text_range}}])
