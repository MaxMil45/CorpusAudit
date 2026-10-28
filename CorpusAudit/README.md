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
- **Study Explainer:** Search all indexed PDFs for a question, choose up to three matching papers, and optionally describe what you are trying to build. Set priorities such as exact task match, benchmark evidence, robustness, or deployment practicality. For computer-vision research it distinguishes tasks such as object detection, fine-grained recognition, face verification, and face identification, and looks for methods, equations or algorithms, datasets, metrics, results, baselines, and limitations. It explains useful passages in plain language, compares the selected papers with practical guidance about which supported ideas may fit the project, and cites filenames plus PDF pages. If the extracted text names a figure or equation, it points to that too. Equations are shown as extracted from the PDF text for inspection. Recommendations are a shortlist aid, not a paper-quality score or a decision to discard a paper.

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

Study Explainer retrieves a small set of relevant pages from each selected PDF, checks that each summary quote occurs in the retrieved text, and gives the comparison only those checked points. This makes its advice traceable, but it does not mean that the whole paper has been read or independently assessed. The optional project description and review priorities help frame the comparison. Formula text can be distorted by PDF extraction; use the displayed page reference to check the original before copying an equation or algorithm. If the selected passages do not contain enough evidence, the app may leave a point out or decline to rank the papers.

For web checks, `ddgs` searches public search engines and returns titles, links, and snippets. The local model compares those snippets with the claim. Topic search tries several query phrasings, extracts short number-bearing passages from a few results, and checks that any model-selected statistic is copied from its quote. If the model returns no verifiable result, the app can show the exact passage instead. A site may block page retrieval, in which case a result is labelled as a search snippet. Open the links before relying on a result: a quote is traceability, not proof of source quality.

## Current limits

- Public search can be unreliable or rate-limited. It may miss the original source.
- Search results and snippets are sent to the local model, but the claim itself is sent to the search provider.
- Scanned PDFs and complex tables are not parsed yet.
- Study Explainer only reviews a few retrieved passages per paper. Important methods, equations, results, or limitations may be elsewhere in the PDF; verify recommendations in the original paper.
- A model verdict is not proof. Check the source’s definitions, dates, and methods.
- Re-uploading a PDF replaces the indexed version with the same filename. Rename different reports that share a filename.
- A lack of evidence is not evidence that a claim is false.
