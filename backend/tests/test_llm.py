import asyncio
import json

import httpx

from app.llm import generate_with_cerebras


SOURCES = [
    {
        "index": 1,
        "filename": "people-notes.txt",
        "page": None,
        "excerpt": "Jordan Lee owns the rollout plan.",
    }
]


def test_cerebras_request_matches_chat_completions_contract():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://api.cerebras.ai/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer test-api-key"
            payload = json.loads(request.content)
            assert payload["model"] == "gpt-oss-120b"
            assert payload["messages"][0]["role"] == "developer"
            assert "untrusted reference text" in payload["messages"][0]["content"]
            assert payload["messages"][1]["role"] == "user"
            assert "Jordan Lee owns the rollout plan." in payload["messages"][1]["content"]
            assert payload["reasoning_effort"] == "low"
            assert payload["max_completion_tokens"] == 1024
            assert payload["stream"] is False
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Jordan owns it [1]."}}
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_with_cerebras(
                api_key="test-api-key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Jordan owns it [1]."


def test_cerebras_adds_source_markers_when_model_omits_them():
    async def run_test() -> str | None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Jordan owns the rollout plan."}}]},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await generate_with_cerebras(
                api_key="test-api-key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Jordan owns the rollout plan.\n\n[1]"


def test_cerebras_is_skipped_without_key_or_sources():
    without_key = generate_with_cerebras(
        api_key="",
        base_url="https://api.cerebras.ai/v1",
        model="gpt-oss-120b",
        question="What does Jordan own?",
        sources=SOURCES,
    )
    without_sources = generate_with_cerebras(
        api_key="test-api-key",
        base_url="https://api.cerebras.ai/v1",
        model="gpt-oss-120b",
        question="What does Jordan own?",
        sources=[],
    )

    assert asyncio.run(without_key) is None
    assert asyncio.run(without_sources) is None


def test_cerebras_failure_falls_back_cleanly():
    async def run_test() -> str | None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(401, json={"message": "invalid API key"})
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await generate_with_cerebras(
                api_key="invalid-key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) is None
