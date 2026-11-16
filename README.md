# Aegis AI
A local-first document evidence API built with FastAPI. Upload a text PDF, select the documents a question may use, and retrieve quotations with one-based PDF page numbers. Optionally, ask a local Ollama model to select the quotations that answer the question.

## Try it with Docker
Install Docker with Compose and Python 3.12. From the repository root run:

```sh
python scripts/setup_env.py
docker compose up --build -d --wait
docker compose exec api python -m aegis.demo
```

The demo generates a two-page handbook, uploads it to the running API and asks about archive retention. The response should include page 2 and the quotation “The archive retention period is 45 days.” Repeating the demo with the same PDF bytes and key reuses its document ID. The API listens on 127.0.0.1:8000. PostgreSQL uses a named volume and has no published port. Stop the services with `docker compose down`.

## Use an installed Ollama model on Windows
This native profile uses SQLite FTS5 and your existing Ollama instance. Use it with PDFs you trust. The Docker profile supplies Linux parser restrictions for handling untrusted input.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts/setup_env.py
ollama list
$env:AEGIS_MODEL = "qwen3.5:9b"
.\.venv\Scripts\python -m uvicorn aegis.api:create_app --factory --host 127.0.0.1 --env-file .env --no-access-log --no-proxy-headers
```

Use an installed tag from `ollama list`. In a second PowerShell session run `.\.venv\Scripts\python -m aegis.demo`. To use passage search alone, omit the model environment variable. Both profiles use port 8000, so stop one before starting the other.

### Use Ollama with the Linux container
Add an installed or downloadable model tag to your local `.env` as `AEGIS_MODEL=qwen3.5:9b`. The optional service has its own model volume. It shares the API container's network namespace and binds to loopback. It runs on CPU by default.

```sh
docker compose -f compose.yaml -f compose.ollama.yaml up -d --build
docker compose -f compose.yaml -f compose.ollama.yaml exec ollama ollama pull qwen3.5:9b
docker compose exec api python -m aegis.demo
```

## API
Application routes require `Authorization: Bearer <key>`. The setup script writes the local account key to the ignored `.env` file. Map additional stable owner names to independently generated keys in `AEGIS_KEYS`. Key rotation preserves documents when the owner name is unchanged. Restart the service after editing configuration.

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/v1/health/live` | Public process check |
| POST | `/api/v1/documents` | Multipart `file` field, MIME type `application/pdf`. Returns 201 after indexing or 200 for an owner’s duplicate |
| GET | `/api/v1/documents/{id}` | Filename, page count and indexing status |
| GET | `/api/v1/documents/{id}/file` | Download the original PDF as an attachment |
| DELETE | `/api/v1/documents/{id}` | Remove the original and its searchable passages in one transaction |
| POST | `/api/v1/chat/query` | Accepts `{"question":"What is the retention period?","document_ids":["<id>"]}` |

`matching_passages` returns retrieved text. `quoted_answer` means the model selected exact text present in a retrieved passage. The server supplies citation IDs and page numbers. `insufficient_evidence` means no passages matched, no quotes were selected, or citation validation failed. A quotation can be genuine and still be irrelevant to the question. A model outage returns HTTP 503.

## Engineering and security
The request gateway authenticates before reading uploads and caps the whole multipart body, including chunked transfers. The file limit is 4 MiB, the document limit is 100 pages, and extraction stops at 320,000 normalized characters. One server process admits four concurrent requests and enforces a body-read deadline. PDF indexing completes in the request, with a separate parser process and a 15-second wall-clock timeout. There is no background queue to recover in this milestone.

On Linux the parser preloads its dependencies, clears the inherited environment, sets CPU and address-space limits, and applies a seccomp allowlist before reading the PDF. The filter denies opening files, creating network sockets and spawning processes. A failure to install the filter disables ingestion. The container runs as an unprivileged user with a read-only root filesystem and dropped capabilities. The PostgreSQL application role can manage its tables in the application schema and has no superuser privileges.

The store commits the PDF, metadata and index entries together. Queries verify ownership of the entire requested scope before passage selection. The server constructs full-text queries from bounded word tokens and binds SQL parameters. It sends only selected passages to the fixed loopback Ollama endpoint, disables HTTP proxy discovery and supplies no tools. Generated text enters the answer only after an exact substring check against its referenced passage.

This release targets a local workstation. Original PDFs and extracted text are stored in plaintext. Deletion removes live rows and index entries; database backups and storage-level copies have separate lifetimes. There are no public sign-up, TLS termination, account quotas, OCR, or guarantees of semantic entailment. Image-only documents require OCR; mixed PDFs index their extractable text. Quotes refer to whitespace-normalized text and physical PDF page order.

## Tests
```sh
python -m unittest discover -v
```

Run from an environment with `requirements.txt` installed. Native Linux also needs `libseccomp2`. Tests use temporary SQLite databases by default. Setting `TEST_DATABASE` to a disposable PostgreSQL DSN runs the same tests against PostgreSQL with `requirements-postgres.txt` installed. The suite uses real PDFs and a controlled Ollama HTTP transport to exercise quote selection, abstention and outages. The GitHub Actions workflow builds the container, runs both database profiles and checks a live HTTP request.

## Next milestone
Build a labeled retrieval benchmark, then add pgvector embeddings alongside the existing full-text baseline. Measure evidence recall at five passages and citation relevance before introducing reranking or claim-level contradiction detection. The initial release exposes an API and a runnable demo.
