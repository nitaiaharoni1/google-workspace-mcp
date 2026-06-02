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
