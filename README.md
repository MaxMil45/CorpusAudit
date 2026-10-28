# CorpusAudit

CorpusAudit helps you find statistics, trace them to sources, and screen research papers. It runs its language model locally with Ollama and can search your own PDF library.

## What it can do

- **Check a claim** against public search results or reports in your local PDF library.
- **Find statistics** about a topic, with an answer separated from the exact source-backed findings.
- **Find papers** by research question or follow citation links from a seed paper. Save local project profiles, assess abstracts against your goals, and pass a shortlist to Study Explainer.
- **Explore and index PDFs** locally, then ask questions about their contents.
- **Compare studies** using selected passages, with source filenames and page references.

Paper indexes and public search providers may receive your search queries. PDFs and saved project profiles are stored locally. CorpusAudit does not require an OpenAI API key; Ollama handles the model requests on your computer.

## Run it on Windows

Install [Ollama](https://ollama.com/download), then open PowerShell at the repository folder and run:

```powershell
ollama pull qwen3:4b-instruct
cd CorpusAudit
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Keep Ollama running while you use the app. The first model download is about 2.5 GB. A `.env` file is optional; use one only if you want to change the local Ollama model or address.

## Project files

The application source and detailed setup notes are in [`CorpusAudit/`](CorpusAudit/). Start with its [full README](CorpusAudit/README.md) for architecture, usage details, and current limitations.

```text
CorpusAudit/
  app.py
  corpus_audit_core/   Search, PDF processing, retrieval, and local model prompts
  ui/                  Streamlit pages, including Literature Scout
  tests/               Existing focused tests
  README.md            Detailed project documentation
```
