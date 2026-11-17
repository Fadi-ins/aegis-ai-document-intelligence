# Evidence50

Evidence50 tests a reader's actual task: choose several documents, ask a question, and find a quotation on the right page. It comes with [ten original English document fixtures](corpus.json) and [50 labeled questions](questions.jsonl). The runner builds one four-page text PDF per fixture, uploads it through Aegis, and sends each question to the normal query endpoint.

## Results

[Verified run on November 17, 2026](https://github.com/Fadi-ins/aegis-ai-document-intelligence/actions/runs/44101458331) using SQLite FTS5, Ollama 0.40.16, and Qwen2.5 1.5B on CPU. [Inspect all 50 responses](results/qwen2.5-1.5b.json) or [open the PDFs](pdfs/). The measured benchmark revision is `8fb09a2d14985920b5ef567612eea2641dfd1210`.

| Measure | Observed |
| --- | ---: |
| Correct page ranked first | 26/40 (65%) |
| Correct page in top five | 36/40 (90%) |
| Selected quotes containing the labeled answer on the correct page | 13/28 (46.4%) |
| Answerable questions answered with exclusively relevant quotes | 6/40 (15%) |
| Unanswerable questions correctly declined | 9/10 (90%) |
| Answerable questions declined | 26/40 (65%) |

Retrieval returned at least one passage for every unanswerable question. The model declined all five missing-fact cases and four of five excluded-source cases. Of the 40 answerable cases, 14 received a quoted answer: six contained only relevant quotes, seven mixed relevant and irrelevant quotes, and one selected a quote that omitted the answer.

**Example of a mixed answer.** For `juniper-4`, the user asks how many musicians can rehearse in the Juniper piano room. The model gives the correct eight-performer quote from [Juniper, page 4](pdfs/juniper.pdf), adds the eleven-performer limit from Maple, then cites an unrelated booking deadline. All three quotations are genuine. Only the first answers the question.

**Example of a scope error.** For `elm-5`, the question asks when Cedar reviews digitization requests. Cedar is outside the selected scope. The model returns Elm's Friday review day. The application stayed inside the requested document set, but the selected quotation answered a question about a different archive.

**Example of a retrieval miss.** For `pearl-4`, the question asks where the induction for new helpers takes place. The PDF uses the phrase “volunteer orientation.” The full-text search returned no passages. This case can be used to test whether semantic retrieval improves recall; the mixed answers above can be used to test quote selection separately.

## What the questions test

The corpus contains five pairs of fictional organizations: two libraries, rehearsal studios, markets, archives, and repair cafes. Each pair has similar policies with different names, numbers, days, or locations. Each question searches five or six documents, or 20 to 24 pages. The model sees only the question and retrieved passages.

- **40 answerable questions** each have one labeled source, physical PDF page, and minimum supporting text span. They include literal wording and paraphrases.
- **5 missing facts** are absent from the corpus even though related vocabulary is present.
- **5 excluded-source questions** have an answer in a document the user did not select. A citation from a similar organization is an incorrect answer.

## Scoring

| Metric | Numerator | Denominator |
| --- | --- | --- |
| Correct page at rank 1 or in the top 5 | Questions whose labeled document **and** page appear within that rank | 40 answerable questions |
| Relevant selected quotes | Quotes on the labeled document and page containing the exact labeled answer span | All quotes returned across all 50 questions |
| Supported answers | Responses with at least one selected quote, all of which pass the quote criterion | 40 answerable questions |
| Correct abstentions | Responses with API status `insufficient_evidence` | 10 unanswerable questions |
| Abstentions on answerable questions | Responses with the same status | 40 answerable questions |

The quote metric is an automatic evidence match. A very short quote can pass if it contains the labeled span on the correct page. A useful differently worded span can fail. The report retains the returned quotes for inspection. A request error stops the run, so an unavailable model cannot earn abstention credit.

These are authored, machine-readable PDFs. Scores describe this small collection; they do not establish accuracy on scans, long reports, tables, other languages, or unfamiliar domains. Keep the suite fixed when comparing retrieval changes and evaluate on a fresh collection before claiming generalization.

## Reproduce

From the repository root, install the project dependencies in a Python 3.12 environment. Linux hosts also need `libseccomp2`.

```sh
python -m pip install -r requirements.txt
python -m benchmarks.evidence50.run --output retrieval.json --pdf-dir evidence-pdfs
```

To score quote selection and abstention, start Ollama on its default loopback address. With the service running:

```sh
ollama pull qwen2.5:1.5b
python -m benchmarks.evidence50.run --model qwen2.5:1.5b --output model.json
```

Compare the model digest and input hashes in `metadata` with the published report. The API uses temperature zero. Model output can still vary across runtimes. Retrieval uses SQLite FTS5 in a fresh temporary database. Only fixture UUIDs are fixed to make equal-score ranking ties reproducible; ingestion, parsing, ranking, quote validation, and model inference run normally. Reports omit temporary credentials and random document IDs.

The [benchmark workflow](../../.github/workflows/evidence-benchmark.yml) also runs on pull requests that change the benchmark inputs or runner, and supports manual runs. The `evidence50` artifact includes the ten generated PDFs and the per-question JSON report.
