"""Exercise the running API with a generated two-page PDF."""
import io
import json
import os

import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, DecodedStreamObject, NameObject


def sample_pdf():
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    for text in ("Aegis sample handbook.", "The archive retention period is 45 days."):
        page = writer.add_blank_page(width=400, height=200)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 36 100 Td ({text}) Tj ET".encode())
        page.replace_contents(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def main():
    from dotenv import load_dotenv
    load_dotenv(".env")
    key = json.loads(os.environ["AEGIS_KEYS"])["local"]
    with httpx.Client(base_url="http://127.0.0.1:8000/api/v1",
                      headers={"Authorization": f"Bearer {key}"}, timeout=65, trust_env=False) as client:
        upload = client.post("/documents", files={"file": ("handbook.pdf", sample_pdf(), "application/pdf")})
        upload.raise_for_status()
        query = client.post("/chat/query", json={"document_ids": [upload.json()["id"]],
                            "question": "What is the archive retention period?"})
        query.raise_for_status()
        print(json.dumps(query.json(), indent=2))


if __name__ == "__main__":
    main()
