"""Minimal Google Docs API wrapper (create, read, edit)."""
from __future__ import annotations
import google_auth_core as core


class DocsAPI:
    def __init__(self, account=None):
        self.account = account
        self.service = core.get_service("docs", "v1", account=account)

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

    def insert_text(self, document_id, text, index=1):
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": index}, "text": text}}]},
        ).execute()

    def append_text(self, document_id, text):
        doc = self.get_document(document_id)
        content = doc.get("body", {}).get("content", [])
        end = content[-1].get("endIndex", 2) - 1 if content else 1
        if end < 1:
            end = 1
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": end}, "text": text}}]},
        ).execute()

    def replace_all_text(self, document_id, find, replace, match_case=False):
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"replaceAllText": {
                "containsText": {"text": find, "matchCase": match_case},
                "replaceText": replace,
            }}]},
        ).execute()

    def _hex_to_rgb_color(self, hex_str):
        hex_str = hex_str.lstrip("#")
        r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
        return {"red": r / 255, "green": g / 255, "blue": b / 255}

    def format_text(self, document_id, start_index, end_index, bold=None, italic=None, underline=None, font_size=None, link_url=None, foreground_color=None):
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
        if font_size is not None:
            text_style["fontSize"] = {"magnitude": font_size, "unit": "PT"}
            fields.append("fontSize")
        if link_url is not None:
            text_style["link"] = {"url": link_url}
            fields.append("link")
        if foreground_color is not None:
            text_style["foregroundColor"] = {"color": {"rgbColor": self._hex_to_rgb_color(foreground_color)}}
            fields.append("foregroundColor")
        if not fields:
            raise ValueError("format_text requires at least one style attribute")
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"updateTextStyle": {
                "range": {"startIndex": start_index, "endIndex": end_index},
                "textStyle": text_style,
                "fields": ",".join(fields),
            }}]},
        ).execute()

    def set_paragraph_style(self, document_id, start_index, end_index, named_style):
        valid = {"NORMAL_TEXT", "TITLE", "SUBTITLE", "HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4", "HEADING_5", "HEADING_6"}
        if named_style not in valid:
            raise ValueError(f"named_style must be one of {sorted(valid)}")
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"updateParagraphStyle": {
                "range": {"startIndex": start_index, "endIndex": end_index},
                "paragraphStyle": {"namedStyleType": named_style},
                "fields": "namedStyleType",
            }}]},
        ).execute()

    def insert_bullets(self, document_id, start_index, end_index, bullet_preset="BULLET_DISC_CIRCLE_SQUARE"):
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"createParagraphBullets": {
                "range": {"startIndex": start_index, "endIndex": end_index},
                "bulletPreset": bullet_preset,
            }}]},
        ).execute()

    def delete_range(self, document_id, start_index, end_index):
        return self.service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"deleteContentRange": {
                "range": {"startIndex": start_index, "endIndex": end_index},
            }}]},
        ).execute()
