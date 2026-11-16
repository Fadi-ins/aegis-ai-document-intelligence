import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import UUID

import httpx
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .answers import answer, keywords
from .gateway import Gateway, MAX_PDF
from .store import Store


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1000)
    document_ids: list[UUID] = Field(min_length=1, max_length=8)


def parse_pdf(data):
    worker = Path(__file__).with_name("pdf_worker.py").resolve()
    command = [sys.executable, "-I", str(worker)]
    environment = {}
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        command = [sys.executable, "--pdf-worker"]
        # Reuse the one-file bootloader's extraction directory. Pass no user credentials.
        environment = {k: v for k, v in os.environ.items()
                       if k.startswith("_PYI_") or k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    with tempfile.TemporaryDirectory() as directory:
        try:
            result = subprocess.run(command, input=data,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    env=environment, cwd=directory, timeout=15, check=False)
        except subprocess.TimeoutExpired:
            raise HTTPException(422, "PDF processing limit exceeded") from None
    if result.returncode == 5:
        raise HTTPException(503, "PDF parser isolation unavailable")
    if result.returncode:
        reasons = {2: "Encrypted PDF", 3: "PDF exceeds extraction limits", 4: "OCR required"}
        raise HTTPException(422, reasons.get(result.returncode, "PDF could not be processed"))
    return json.loads(result.stdout)


def make_app(store, keys, model=None, transport=None):
    app = FastAPI(title="Aegis AI", version="0.1.0", docs_url=None, redoc_url=None)
    app.add_middleware(Gateway, keys=keys)
    store.initialize()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "Invalid request fields"}, 422)

    @app.get("/api/v1/health/live")
    def health():
        return {"status": "ok"}

    ui = Path(__file__).with_name("ui")

    @app.get("/", include_in_schema=False)
    def workspace():
        return FileResponse(ui / "index.html", headers={"Content-Security-Policy":
            "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})

    @app.get("/workspace.css", include_in_schema=False)
    def stylesheet():
        return FileResponse(ui / "workspace.css")

    @app.get("/workspace.js", include_in_schema=False)
    def javascript():
        return FileResponse(ui / "workspace.js", media_type="text/javascript")

    @app.get("/api/v1/documents")
    def list_documents(request: Request):
        return store.list_documents(request.state.owner)

    @app.post("/api/v1/documents", status_code=201)
    def upload(request: Request, response: Response, file: UploadFile = File()):
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        name = re.sub(r"[^\w. -]", "_", name)[:160]
        if not name.lower().endswith(".pdf") or file.content_type != "application/pdf":
            raise HTTPException(415, "Expected a PDF file")
        data = file.file.read(MAX_PDF + 1)
        if len(data) > MAX_PDF:
            raise HTTPException(413, "PDF too large")
        if not data.startswith(b"%PDF-"):
            raise HTTPException(422, "Invalid PDF signature")
        meta, created = store.save(request.state.owner, name, data, parse_pdf(data))
        response.status_code = 201 if created else 200
        return {**meta, "status": "ready"}

    @app.get("/api/v1/documents/{doc_id}")
    def metadata(doc_id: UUID, request: Request):
        row = store.get(request.state.owner, str(doc_id))
        if not row:
            raise HTTPException(404, "Document unavailable")
        return {**row, "status": "ready"}

    @app.get("/api/v1/documents/{doc_id}/file")
    def original(doc_id: UUID, request: Request):
        row = store.get(request.state.owner, str(doc_id), file=True)
        if not row:
            raise HTTPException(404, "Document unavailable")
        return Response(bytes(row["original"]), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="source.pdf"',
                                 "Content-Security-Policy": "sandbox; default-src 'none'"})

    @app.delete("/api/v1/documents/{doc_id}", status_code=204)
    def remove(doc_id: UUID, request: Request):
        if not store.delete(request.state.owner, str(doc_id)):
            raise HTTPException(404, "Document unavailable")
        return Response(status_code=204)

    @app.post("/api/v1/chat/query")
    def query(body: Query, request: Request):
        ids = list(dict.fromkeys(map(str, body.document_ids)))
        try:
            passages = store.search(request.state.owner, ids, keywords(body.question))
        except LookupError:
            raise HTTPException(404, "Document unavailable") from None
        try:
            return answer(body.question, passages, model, transport)
        except httpx.HTTPError:
            raise HTTPException(503, "Local model unavailable") from None
    return app


def create_app():
    keys = json.loads(os.environ["AEGIS_KEYS"])
    return make_app(Store(os.getenv("AEGIS_DATABASE", ".aegis/documents.sqlite3")),
                    keys, os.getenv("AEGIS_MODEL"))
