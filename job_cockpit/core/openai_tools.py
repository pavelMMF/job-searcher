from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OPENAI_ENV_FILE = ROOT / "config" / "openai.env"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-nano"


class OpenAIRequestUnavailable(RuntimeError):
    pass


def openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    if OPENAI_ENV_FILE.exists():
        for raw_line in OPENAI_ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "OPENAI_API_KEY":
                return value.strip().strip('"').strip("'")
    return ""


def call_openai_json(
    *,
    model: str,
    key: str,
    system_prompt: str,
    context: dict[str, Any],
    timeout: int,
    max_output_tokens: int = 5000,
) -> dict[str, Any]:
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": max_output_tokens,
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        raise OpenAIRequestUnavailable(f"OpenAI API error {exc.code}: {redact_secret(detail)}") from exc
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        raise OpenAIRequestUnavailable(f"OpenAI API request failed: {exc}") from exc

    text = extract_response_text(data)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenAIRequestUnavailable("OpenAI returned non-JSON content.") from exc
    if isinstance(parsed, dict):
        parsed["_usage"] = data.get("usage", {})
        return parsed
    raise OpenAIRequestUnavailable("OpenAI returned JSON that is not an object.")


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks: list[str] = []
    for item in data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if isinstance(content.get("text"), str):
                chunks.append(content["text"])
            elif isinstance(content.get("output_text"), str):
                chunks.append(content["output_text"])
    text = "".join(chunks).strip()
    if text:
        return text
    raise OpenAIRequestUnavailable("OpenAI response did not contain output text.")


def redact_secret(value: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", value)
