# Aegis AI
A local-first document evidence API built with FastAPI. Upload a text PDF, select the documents a question may use, and retrieve quotations with one-based PDF page numbers. Optionally, ask a local Ollama model to select the quotations that answer the question.

## Windows desktop app

Download the **Aegis-Windows-x64** ZIP from a successful **Windows desktop** Actions run. Extract it and double-click **Aegis.exe**. The executable bundles Python, the API and the browser interface. It opens your default browser, then you paste the session access key from the Aegis window. Keep that window open while using the app. Press Ctrl+C there to stop it.

Each Windows profile stores its own documents in `%LOCALAPPDATA%\Aegis\documents.sqlite3`. Documents persist across launches. Each launch generates a fresh access key and binds a port on 127.0.0.1. If the browser does not open, copy the displayed local address. The app uses the existing Windows native PDF profile for trusted PDFs. For unfamiliar or potentially hostile files, use the Docker profile below for Linux parser isolation.

## Try it with Docker
Install Docker with Compose and Python 3.12. From the repository root run:

```sh
python scripts/setup_env.py
docker compose up --build -d --wait
docker compose exec api python -m aegis.demo
```

Open **http://127.0.0.1:8000/** in your browser. Unlock the workspace with the value for `local` inside `AEGIS_KEYS` from your local `.env` file. Upload a PDF, select the sources and enter a question. Locking the workspace clears the access key from the page.

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

`matching_passages` returns retrieved text. `quoted_answer` means the model chose numbered source sentences and kept them in a second verification pass. The server copies the text and page numbers from the selected passages. An `insufficient_evidence` response includes a `reason` field. Its values are `no_matching_passages`, `no_matching_sentences`, `subject_not_matched`, `no_sentence_selected`, `verification_rejected`, `invalid_model_response`, and `invalid_sentence_id`. A quotation can be genuine and still be irrelevant to the question. A model outage returns HTTP 503.

## Engineering and security
The request gateway authenticates before reading uploads and caps the whole multipart body, including chunked transfers. The file limit is 4 MiB, the document limit is 100 pages, and extraction stops at 320,000 normalized characters. One server process admits four concurrent requests and enforces a body-read deadline. PDF indexing completes in the request, with a separate parser process and a 15-second wall-clock timeout. There is no background queue to recover in this milestone.

On Linux the parser preloads its dependencies, clears the inherited environment, sets CPU and address-space limits, and applies a seccomp allowlist before reading the PDF. The filter denies opening files, creating network sockets and spawning processes. A failure to install the filter disables ingestion. The container runs as an unprivileged user with a read-only root filesystem and dropped capabilities. The PostgreSQL application role can manage its tables in the application schema and has no superuser privileges.

The store commits the PDF, metadata and index entries together. Queries verify ownership of the entire requested scope before passage selection. The server constructs full-text queries from bounded word tokens and binds SQL parameters. It sends only selected passages to the fixed loopback Ollama endpoint, disables HTTP proxy discovery and supplies no tools. A sentence must share a search term with the question before it goes to the model. A conservative English capitalization rule checks explicit names and acronyms against sentences and filenames. Aliases, translations, and inconsistent capitalization can affect this check. The local model returns up to three integer IDs. The verification pass can remove candidates. The server checks each ID against the list shown in that pass and builds quotations directly from the indexed text.

This release targets a local workstation. Original PDFs and extracted text are stored in plaintext. Deletion removes live rows and index entries; database backups and storage-level copies have separate lifetimes. There are no public sign-up, TLS termination, account quotas, OCR, or guarantees of semantic entailment. Image-only documents require OCR; mixed PDFs index their extractable text. Quotes refer to whitespace-normalized text and physical PDF page order.

## Tests
```sh
python -m unittest discover -v
```

Run from an environment with `requirements.txt` installed. Native Linux also needs `libseccomp2`. Tests use temporary SQLite databases by default. Setting `TEST_DATABASE` to a disposable PostgreSQL DSN runs the same tests against PostgreSQL with `requirements-postgres.txt` installed. The suite uses real PDFs and a controlled Ollama HTTP transport to exercise quote selection, abstention and outages. The GitHub Actions workflow builds the container, runs both database profiles and checks a live HTTP request.

## Evidence benchmark
[See the measured results and reproduction commands](benchmarks/evidence50/README.md) for a 50-question benchmark across ten four-page PDFs. It measures whether the right page is retrieved, whether the selected quotes contain the labeled answer, and when the model declines questions that the selected documents cannot answer.

## Next milestone
Compare the SQLite full-text baseline with hybrid retrieval on the frozen questions. Use a separate held-out collection before drawing conclusions about unfamiliar real-world PDFs.
