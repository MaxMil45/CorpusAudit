# CorpusAudit

CorpusAudit helps trace a statistic back to a report or dataset. Paste a claim for a web search, or add PDFs and search your own library.

## What you need

- Python 3.10 or newer
- [Ollama](https://ollama.com/download) to run the language model on your computer
- About 2.5 GB for the default `qwen3:4b-instruct` model download

CorpusAudit does not need an OpenAI API key. Model prompts and PDF passages are processed by Ollama locally. The `openai` Python package is used only as a compatible client pointed at Ollama on `localhost`; it does not send requests to OpenAI. Web search sends the claim text to public search providers through `ddgs`; those providers may log queries, change availability, or rate-limit requests.

## Run it on Windows

Install Ollama, then open PowerShell and download the model once:

```powershell
ollama pull qwen3:4b-instruct
```

In the project folder, install the Python dependencies and start the app:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Ollama should be running while you use CorpusAudit. To use a different model or local Ollama address, copy `.env.example` to `.env` and edit `OLLAMA_MODEL` or `OLLAMA_BASE_URL`. You do not need a `.env` file for the defaults.

## Use the app

- **Statistic Checker:** Paste the statistic and choose Web search or My PDF library. Web search works without uploading a document.
- **Find statistics:** Discover figures about a topic, optionally narrowed by place, population, or year. It searches with several research-focused queries, looks through retrieved pages for number-bearing passages, and links each finding to its source. If the local model misses a passage, the app can show the source sentence directly.
- **Research Explorer:** Add reports in the sidebar and ask about a metric, year, country, or population.
- **Evidence Library:** See what is indexed or clear the local index. Clearing the index does not delete your original PDFs.
- **Study Explainer:** Search your indexed PDFs for a question, choose up to three matching papers, and get a paper-by-paper screening summary plus a comparison. It shows the passages and page numbers used; reading-priority labels are suggestions, not decisions to discard a paper.

## Project layout

```text
app.py                    Streamlit entry point
ui/                       Page sections and shared display helpers
corpus_audit_core/
  analysis.py              Research answers and claim checks
  documents.py             PDF extraction, indexing, retrieval, and source ranking
  llm.py                   Local Ollama client
  prompts.py               Model instructions
  settings.py              Local Chroma storage
tests/                     Focused tests for text chunking
```

`corpus_audit.py` is a small compatibility module for older imports; new code should import from `corpus_audit_core` or `ui`.

## How it works

PyMuPDF extracts selectable PDF text page by page. Chroma stores overlapping passages with their filename and page number. The local model summarizes or compares retrieved passages.

For web checks, `ddgs` searches public search engines and returns titles, links, and snippets. The local model compares those snippets with the claim. Topic search tries several query phrasings, extracts short number-bearing passages from a few results, and checks that any model-selected statistic is copied from its quote. If the model returns no verifiable result, the app can show the exact passage instead. A site may block page retrieval, in which case a result is labelled as a search snippet. Open the links before relying on a result: a quote is traceability, not proof of source quality.

## Current limits

- Public search can be unreliable or rate-limited. It may miss the original source.
- Search results and snippets are sent to the local model, but the claim itself is sent to the search provider.
- Scanned PDFs and complex tables are not parsed yet.
- A model verdict is not proof. Check the source’s definitions, dates, and methods.
- Re-uploading a PDF replaces the indexed version with the same filename. Rename different reports that share a filename.
- A lack of evidence is not evidence that a claim is false.
