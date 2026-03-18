"""LLM module - handles Ollama API calls"""
import httpx
from typing import Generator

OLLAMA_URL = "http://localhost:11434"


def chat(prompt: str, model: str = "qwen2.5-coder:7b") -> str:
    """Send a prompt to Ollama and get a response."""
    response = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120.0
    )
    response.raise_for_status()
    return response.json()["response"]


def chat_stream(prompt: str, model: str = "qwen2.5-coder:7b") -> Generator[str, None, None]:
    """Stream response from Ollama."""
    with httpx.stream(
        "POST",
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": True},
        timeout=120.0
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                import json
                data = json.loads(line)
                if "response" in data:
                    yield data["response"]


if __name__ == "__main__":
    # Quick test
    print("Testing Ollama connection...")
    result = chat("Say 'Hello, I am working!' in exactly 5 words.")
    print(f"Response: {result}")
