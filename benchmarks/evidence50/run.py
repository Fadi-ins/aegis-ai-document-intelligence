"""Evaluate the real PDF ingestion and query routes on an isolated SQLite database."""
import argparse
import hashlib
import io
import itertools
import json
from pathlib import Path
import platform
import secrets
import sqlite3
import tempfile
import textwrap
from contextlib import ExitStack
from importlib.metadata import version
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from aegis.api import make_app
from aegis.store import Store

HERE = Path(__file__).resolve().parent


def pdf_bytes(document):
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for number, paragraph in enumerate(document["pages"], 1):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
        })
        lines = [document["title"], f"Page {number}", "", *textwrap.wrap(paragraph, 78)]
        commands = ["BT /F1 11 Tf 16 TL 46 740 Td"]
        for line in lines:
            literal = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            commands.append(f"({literal}) Tj T*")
        stream = DecodedStreamObject()
        stream.set_data(("\n".join(commands) + "\nET").encode("ascii"))
        page.replace_contents(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def load_suite():
    sources = json.loads((HERE / "corpus.json").read_text())
    cases = [json.loads(line) for line in (HERE / "questions.jsonl").read_text().splitlines()]
    if len(sources) != 10 or len(cases) != 50 or len({c["id"] for c in cases}) != 50:
        raise ValueError("Expected ten sources and fifty distinct case IDs")
    if sum(c["gold"] is None for c in cases) != 10:
        raise ValueError("Expected ten unanswerable cases")
    for case in cases:
        scope, gold = case["scope"], case["gold"]
        if not 1 <= len(set(scope)) == len(scope) <= 8 or not set(scope) <= sources.keys():
            raise ValueError(f"Invalid document scope for {case['id']}")
        if gold:
            pages = sources[gold["document"]]["pages"]
            if (gold["document"] not in scope or not 1 <= gold["page"] <= len(pages)
                    or not gold["span"] or gold["span"] not in pages[gold["page"] - 1]):
                raise ValueError(f"Invalid answer key for {case['id']}")
    return sources, cases


def query(client, question, ids):
    response = client.post("/api/v1/chat/query", json={"question": question, "document_ids": ids})
    response.raise_for_status()
    result = response.json()
    citations = [{"document": Path(c["filename"]).stem, "page": c["page"], "quote": c["quote"]}
                 for c in result["citations"]]
    return result["status"], citations


def summarize(rows, with_model):
    positives = [row for row in rows if row["answerable"]]
    negatives = [row for row in rows if not row["answerable"]]

    def count(items, key):
        return [sum(bool(item[key]) for item in items), len(items)]

    metrics = {
        "gold_page_at_1": [sum(r["rank"] == 1 for r in positives), len(positives)],
        "gold_page_at_5": count(positives, "rank"),
        "retrieval_no_match_on_unanswerable": [sum(not r["retrieved"] for r in negatives), len(negatives)],
    }
    if with_model:
        quotes = [q for r in rows for q in r["selected"]]
        metrics.update({
            "supported_answer_on_answerable": count(positives, "supported"),
            "relevant_selected_quotes": count(quotes, "relevant"),
            "abstention_on_unanswerable": [sum(r["status"] == "insufficient_evidence" for r in negatives), len(negatives)],
            "abstention_on_answerable": [sum(r["status"] == "insufficient_evidence" for r in positives), len(positives)],
        })
    return metrics


def model_info(tag):
    with httpx.Client(base_url="http://127.0.0.1:11434", trust_env=False, timeout=10) as client:
        tags = client.get("/api/tags").raise_for_status().json()["models"]
        for item in tags:
            if item["name"] == tag:
                engine = client.get("/api/version").raise_for_status().json()["version"]
                return {"tag": tag, "digest": item["digest"], "ollama": engine}
    raise ValueError(f"Install the exact model tag first: ollama pull {tag}")


def run(args):
    sources, cases = load_suite()
    metadata = {
        "model": model_info(args.model) if args.model else None,
        "backend": "SQLite FTS5", "sqlite": sqlite3.sqlite_version,
        "python": platform.python_version(), "pypdf": version("pypdf"),
        "input_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                         for name in ("corpus.json", "questions.jsonl")},
    }
    rows = []
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        store = Store(str(Path(directory) / "bench.sqlite3"))
        key = secrets.token_urlsafe(32)

        def app_client(model=None):
            client = stack.enter_context(TestClient(make_app(store, {"benchmark": key}, model)))
            client.headers["Authorization"] = f"Bearer {key}"
            return client

        retrieval = app_client()
        selector = app_client(args.model) if args.model else None
        ids = {}
        # Production breaks equal FTS ranks by passage UUID. Fix only fixture IDs
        # so independent runs resolve those ties in the same order.
        fixture_ids = (uuid5(NAMESPACE_URL, f"aegis:evidence50:{n}") for n in itertools.count())
        with patch("aegis.store.uuid4", side_effect=fixture_ids):
            for name, source in sources.items():
                data = pdf_bytes(source)
                if args.pdf_dir:
                    args.pdf_dir.mkdir(parents=True, exist_ok=True)
                    (args.pdf_dir / f"{name}.pdf").write_bytes(data)
                file = (f"{name}.pdf", data, "application/pdf")
                result = retrieval.post("/api/v1/documents", files={"file": file}).raise_for_status().json()
                if result["pages"] != len(source["pages"]):
                    raise ValueError(f"Page count mismatch for {name}")
                ids[name] = result["id"]

        for case in cases:
            scope = [ids[name] for name in case["scope"]]
            _, hits = query(retrieval, case["question"], scope)
            gold = case["gold"]
            rank = next((i for i, hit in enumerate(hits, 1) if gold and
                         (hit["document"], hit["page"]) == (gold["document"], gold["page"])), None)
            row = {"id": case["id"], "answerable": bool(gold), "rank": rank,
                   "retrieved": [[hit["document"], hit["page"]] for hit in hits]}
            if selector:
                status, quotes = query(selector, case["question"], scope)
                for quote in quotes:
                    quote["relevant"] = bool(gold and quote["document"] == gold["document"]
                                             and quote["page"] == gold["page"] and gold["span"] in quote["quote"])
                row.update(status=status, selected=quotes,
                           supported=bool(quotes) and all(q["relevant"] for q in quotes))
            rows.append(row)
    return {"metadata": metadata, "metrics": summarize(rows, bool(args.model)), "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Exact Ollama tag for scoring quote selection and abstention")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, help="Also save the generated PDFs here")
    args = parser.parse_args()
    report = run(args)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))


if __name__ == "__main__":
    main()
