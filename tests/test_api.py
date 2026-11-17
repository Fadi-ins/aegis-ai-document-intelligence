import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from aegis.answers import answer
from aegis.api import make_app
from aegis.demo import sample_pdf
from aegis.gateway import MAX_UPLOAD
from aegis.store import Store


class ApiTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(os.getenv("TEST_DATABASE", str(Path(directory.name) / "test.sqlite3")))
        # Separate identities make these tests repeatable on a persistent PostgreSQL test database.
        self.owner = uuid4().hex
        self.keys = {self.owner: secrets.token_urlsafe(32), "guest": secrets.token_urlsafe(32)}
        self.headers = {"Authorization": "Bearer " + self.keys[self.owner]}
        self.guest = {"Authorization": "Bearer " + self.keys["guest"]}
        self.client = TestClient(make_app(self.store, self.keys))
        self.addCleanup(self.client.close)
        self.pdf = sample_pdf()

    def upload(self, payload=None, name="handbook.pdf", headers=None):
        return self.client.post("/api/v1/documents", headers=headers or self.headers,
                files={"file": (name, self.pdf if payload is None else payload, "application/pdf")})

    def query(self, *ids, question="archive retention", headers=None, client=None):
        return (client or self.client).post("/api/v1/chat/query", headers=headers or self.headers,
                json={"question": question, "document_ids": list(ids)})

    def test_public_health_private_upload(self):
        self.assertEqual(self.client.get("/api/v1/health/live").status_code, 200)
        self.assertEqual(self.client.post("/api/v1/documents", content=b"invalid").status_code, 401)
        self.assertEqual(self.client.get("/openapi.json").status_code, 401)

    def test_round_trip_and_deduplication(self):
        first = self.upload(name="../handbook.pdf")
        self.assertEqual(first.status_code, 201, first.text)
        doc = first.json()
        self.assertEqual(doc["filename"], "handbook.pdf")
        self.assertEqual(doc["pages"], 2)
        second = self.upload()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(doc["id"], second.json()["id"])
        path = "/api/v1/documents/" + doc["id"]
        self.assertEqual(self.client.get(path, headers=self.headers).json(), doc)
        self.assertEqual(self.client.get(path + "/file", headers=self.headers).content, self.pdf)
        result = self.query(doc["id"]).json()
        self.assertEqual(result["status"], "matching_passages")
        self.assertEqual(result["citations"][0]["page"], 2)
        self.assertIn("45 days", result["citations"][0]["quote"])

    def test_ownership_at_every_document_route(self):
        own = self.upload().json()["id"]
        other = self.upload(headers=self.guest).json()["id"]
        self.assertNotEqual(own, other)
        path = "/api/v1/documents/" + own
        for method, suffix in (("GET", ""), ("GET", "/file"), ("DELETE", "")):
            self.assertEqual(self.client.request(method, path + suffix, headers=self.guest).status_code, 404)
        self.assertEqual(self.query(own, other).status_code, 404)
        self.assertEqual(self.query(other, question="the").status_code, 404)

    def test_delete_and_reupload(self):
        doc = self.upload().json()["id"]
        path = "/api/v1/documents/" + doc
        self.assertEqual(self.client.delete(path, headers=self.headers).status_code, 204)
        self.assertEqual(self.query(doc).status_code, 404)
        self.assertNotEqual(self.upload().json()["id"], doc)

    def test_unanswerable_and_empty_scope(self):
        doc = self.upload().json()["id"]
        self.assertEqual(self.query(doc, question="zeppelins").json()["reason"], "no_matching_passages")
        self.assertEqual(self.query().status_code, 422)

    def test_oversize_and_chunked_body(self):
        part = b"x" * (MAX_UPLOAD // 2 + 1)
        for body in (part * 2, iter([part, part])):
            res = self.client.post("/api/v1/documents", headers=self.headers, content=body)
            self.assertEqual(res.status_code, 413)

    def test_invalid_encrypted_and_scanned_pdfs(self):
        self.assertEqual(self.upload(b"plain").status_code, 422)
        self.assertEqual(self.upload(b"%PDF-1.4 broken").status_code, 422)
        self.assertEqual(self.upload(name="test.txt").status_code, 415)
        pdf = PdfWriter()
        pdf.add_blank_page(width=200, height=200)
        for expected in ("OCR required", "Encrypted PDF"):
            if expected == "Encrypted PDF":
                pdf.encrypt("sample")
            buf = io.BytesIO()
            pdf.write(buf)
            self.assertEqual(self.upload(buf.getvalue()).json()["detail"], expected)

    def test_model_contract_and_abstention(self):
        doc = self.upload().json()["id"]
        for replies, reason in [
            ([[1], [1]], None),
            ([[]], "no_sentence_selected"),
            ([[4]], "invalid_sentence_id"),
            ([[1], []], "verification_rejected"),
            ([[1], [4]], "invalid_sentence_id"),
            ([[True]], "invalid_model_response"),
        ]:
            responses = iter(replies)
            def reply(request):
                self.assertEqual(str(request.url), "http://127.0.0.1:11434/api/chat")
                payload = {"ids": next(responses)}
                return httpx.Response(200, json={"message": {"content": json.dumps(payload)}})
            with self.subTest(replies=replies), TestClient(
                    make_app(self.store, self.keys, "test-model", httpx.MockTransport(reply))) as client:
                result = self.query(doc, client=client).json()
                if reason is None:
                    self.assertEqual(result["status"], "quoted_answer")
                    self.assertEqual(result["citations"][0]["page"], 2)
                    self.assertEqual(result["citations"][0]["quote"], "The archive retention period is 45 days.")
                else:
                    self.assertEqual(result["reason"], reason)
                    self.assertEqual(result["status"], "insufficient_evidence")
                    self.assertEqual(result["citations"], [])
                self.assertEqual(list(responses), [])

    def test_verifier_can_only_keep_proposed_source_sentences(self):
        passages = [
            {"document_id": "a", "id": "p1", "page": 2, "filename": "pond.pdf",
             "body": "The hall is blue. The hall seats 14."},
            {"document_id": "b", "id": "p2", "page": 4, "filename": "park.pdf",
             "body": "The park seats 90."},
        ]
        for verified in ([2], [1]):
            calls = []
            def reply(request):
                messages = json.loads(request.content)["messages"]
                sentences = json.loads(messages[-1]["content"])["sentences"]
                calls.append([item["id"] for item in sentences])
                ids = [2, 3] if len(calls) == 1 else verified
                return httpx.Response(200, json={"message": {"content": json.dumps({"ids": ids})}})

            with self.subTest(verified=verified):
                result = answer("How many seats are in the hall?", passages, "test", httpx.MockTransport(reply))
                self.assertEqual(calls, [[1, 2, 3], [2, 3]])
                if verified == [2]:
                    self.assertEqual(result["citations"], [{"document_id": "a", "filename": "pond.pdf",
                                     "page": 2, "passage_id": "p1", "quote": "The hall seats 14."}])
                else:
                    self.assertEqual(result["reason"], "invalid_sentence_id")
                    self.assertEqual(result["citations"], [])

    def test_parallel_upload_returns_one_document(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.upload(), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [200, 201])
        self.assertEqual(results[0].json()["id"], results[1].json()["id"])

    def test_bad_model_response_and_outage(self):
        doc = self.upload().json()["id"]
        for response, expected in [(httpx.Response(200, json={"message": {"content": "invalid"}}), 200),
                                   (httpx.Response(500), 503)]:
            fn = httpx.MockTransport(lambda _: response)
            with TestClient(make_app(self.store, self.keys, "example", fn)) as client:
                result = self.query(doc, client=client)
                self.assertEqual(result.status_code, expected)
                if expected == 200:
                    self.assertEqual(result.json()["status"], "insufficient_evidence")
