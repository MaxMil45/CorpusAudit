"""Local Ollama client and JSON response helper."""

import json
import os
import re
from typing import Any

from openai import OpenAI

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")


def _client() -> OpenAI:
    """Use the OpenAI-compatible interface exposed by the local Ollama server."""
    # The placeholder key is required by the client library; Ollama receives requests locally.
    return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", timeout=300.0)


def ask_json(
    instructions: str,
    payload: str,
    *,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Ask the local model for JSON, with a safe fallback for malformed output."""
    request_options: dict[str, Any] = {}
    if max_output_tokens is not None:
        # Reserve room for the answer so a small local context window is not overfilled.
        request_options["max_tokens"] = max_output_tokens

    response = _client().chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": payload},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        **request_options,
    )
    # A small local model may wrap JSON in a Markdown fence, so strip it before parsing.
    text = (response.choices[0].message.content or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"summary": text, "verdict": "Insufficient evidence", "caveats": [], "evidence_ids": []}
