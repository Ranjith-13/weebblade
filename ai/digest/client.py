from __future__ import annotations

import os

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq's model lineup rotates - llama-3.3-70b-versatile (the obvious pick from
# training-era knowledge) has since been retired; verified live against
# /openai/v1/models that this one is actually available as of 2026-09.
DEFAULT_MODEL = "openai/gpt-oss-120b"


class GroqClient:
    """Minimal client for Groq's OpenAI-compatible chat completions endpoint.

    Free-tier signup at console.groq.com - the user has to do that themselves and
    put the resulting key in GROQ_API_KEY (see .env.example). This client never
    creates the account or handles the credential beyond reading it from env.
    """

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self.model = model

    def complete(self, prompt: str) -> str:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
