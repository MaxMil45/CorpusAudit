# CorpusAudit

CorpusAudit helps trace a statistic back to the report or dataset behind it. Paste a claim for a web search, or add PDFs and search your own library.

## Run it

You’ll need Python 3.10 or newer. The web search and AI summaries use the OpenAI API and may incur charges. The app can still extract PDFs and search its local index without an API key.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
streamlit run app.py
```

Put your API key in `.env` if you want to use web search or AI summaries. Keep that file private; it is excluded from Git.

On macOS or Linux, use `python3 -m venv .venv`, `source .venv/bin/activate`, and `cp .env.example .env` in place of the Windows commands.

## Using CorpusAudit

- **Statistic Checker:** Paste the claim as you saw it. Web search is the default, and citations link to the pages used.
- **Research Explorer:** Add a few reports in the sidebar, then ask about a metric, year, country, or population.
- **Evidence Library:** Review what is indexed or clear the local index.

When using your own PDFs, the files and Chroma index stay in the project’s `data` folder. Text passages selected for an AI summary or audit are sent to the OpenAI API. Don’t use confidential reports unless that’s acceptable for your use case.

## How it works

PyMuPDF extracts selectable text page by page. CorpusAudit splits it into overlapping passages and stores the passages with their source filename and page number. Chroma retrieves passages for a question; the model then summarizes or compares them with a claim.

For a web check, the Responses API searches the web and returns cited sources. The model’s verdict is a useful lead, not proof. Open the source and check that its population, dates, units, and definitions match the claim.

## Current limits

- Scanned PDFs and complex tables are not parsed yet.
- A search can miss the best source or retrieve evidence that only looks relevant.
- The app does not independently verify that a web source is authoritative or that no newer dataset exists.
- Re-uploading a PDF replaces the indexed version with the same filename. Rename different reports that share a filename.
- A lack of evidence is not evidence that a claim is false.

## A good first demo

Try a claim with a number, place, and year. Then open the cited source and check its definition and methods. For the local workflow, add two reports about the same topic and ask what each one measures. The differences in scope are often more useful than a single verdict.
