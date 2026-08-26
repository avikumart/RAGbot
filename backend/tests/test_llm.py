import asyncio
import json

import httpx

from app.config import Settings
from app.llm import (
    AnthropicProvider,
    CerebrasProvider,
    GeminiProvider,
    LLMService,
    OpenAICompatibleProvider,
    create_llm_provider,
    ensure_bracketed_citations,
    format_source_context,
    generate_with_cerebras,
    generate_with_cerebras_stream,
)

SOURCES = [
    {
        "index": 1,
        "filename": "people-notes.txt",
        "page": None,
        "excerpt": "Jordan Lee owns the rollout plan.",
    }
]


def test_format_source_context():
    sources = [
        {"index": 1, "filename": "doc1.txt", "page": 2, "excerpt": "Excerpt 1"},
        {"index": 2, "filename": "doc2.txt", "page": None, "excerpt": "Excerpt 2"},
    ]
    formatted = format_source_context(sources)
    assert "[1] doc1.txt, page 2\nExcerpt 1" in formatted
    assert "[2] doc2.txt\nExcerpt 2" in formatted


def test_ensure_bracketed_citations():
    assert ensure_bracketed_citations("Jordan owns the plan [1].", SOURCES) == "Jordan owns the plan [1]."
    assert ensure_bracketed_citations("Jordan owns the plan.", SOURCES) == "Jordan owns the plan.\n\n[1]"
    assert ensure_bracketed_citations("Jordan owns the plan.", []) == "Jordan owns the plan."


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
            provider = CerebrasProvider(
                api_key="test-api-key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
            )
            return await provider.generate_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Jordan owns it [1]."


def test_openai_compatible_provider_matches_contract():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://api.openai.com/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer openai-test-key"
            payload = json.loads(request.content)
            assert payload["model"] == "gpt-4o-mini"
            assert payload["messages"][0]["role"] == "system"
            assert payload["messages"][1]["role"] == "user"
            assert "Jordan Lee owns the rollout plan." in payload["messages"][1]["content"]
            assert payload["max_tokens"] == 1024
            assert payload["temperature"] == 0.1
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Jordan manages the rollout [1]."}}
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                api_key="openai-test-key",
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
                provider_label="openai",
            )
            assert provider.mode_label == "openai:gpt-4o-mini"
            return await provider.generate_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Jordan manages the rollout [1]."


def test_ollama_local_provider_without_api_key():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "http://localhost:11434/v1/chat/completions"
            assert "authorization" not in request.headers
            payload = json.loads(request.content)
            assert payload["model"] == "llama3.2"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Offline local response [1]."}}
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                api_key="",
                base_url="http://localhost:11434/v1",
                model="llama3.2",
                provider_label="ollama",
            )
            assert provider.is_configured() is True
            assert provider.mode_label == "ollama:llama3.2"
            return await provider.generate_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Offline local response [1]."


def test_gemini_provider_matches_contract():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
            assert request.headers["x-goog-api-key"] == "gemini-test-key"
            payload = json.loads(request.content)
            assert "systemInstruction" in payload
            assert payload["contents"][0]["role"] == "user"
            assert "Jordan Lee owns the rollout plan." in payload["contents"][0]["parts"][0]["text"]
            assert payload["generationConfig"]["temperature"] == 0.1
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "Gemini response [1]."}]
                            }
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GeminiProvider(
                api_key="gemini-test-key",
                base_url="https://generativelanguage.googleapis.com/v1beta",
                model="gemini-1.5-flash",
            )
            assert provider.mode_label == "gemini:gemini-1.5-flash"
            return await provider.generate_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Gemini response [1]."


def test_anthropic_provider_matches_contract():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://api.anthropic.com/v1/messages"
            assert request.headers["x-api-key"] == "anthropic-test-key"
            assert request.headers["anthropic-version"] == "2023-06-01"
            payload = json.loads(request.content)
            assert payload["model"] == "claude-3-5-haiku-latest"
            assert payload["max_tokens"] == 1024
            assert "untrusted reference text" in payload["system"]
            assert payload["messages"][0]["role"] == "user"
            assert "Jordan Lee owns the rollout plan." in payload["messages"][0]["content"]
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "Claude response [1]."}
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(
                api_key="anthropic-test-key",
                base_url="https://api.anthropic.com/v1",
                model="claude-3-5-haiku-latest",
            )
            assert provider.mode_label == "anthropic:claude-3-5-haiku-latest"
            return await provider.generate_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )

    assert asyncio.run(run_test()) == "Claude response [1]."


def test_create_llm_provider_factory(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    settings = Settings.from_env(tmp_path)
    provider = create_llm_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == "openai"
    assert provider.model_name == "gpt-4o"

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    settings = Settings.from_env(tmp_path)
    provider = create_llm_provider(settings)
    assert isinstance(provider, GeminiProvider)
    assert provider.provider_name == "gemini"

    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    settings = Settings.from_env(tmp_path)
    provider = create_llm_provider(settings)
    assert isinstance(provider, AnthropicProvider)
    assert provider.provider_name == "anthropic"

    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    settings = Settings.from_env(tmp_path)
    provider = create_llm_provider(settings)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.provider_name == "ollama"

    monkeypatch.setenv("LLM_PROVIDER", "none")
    settings = Settings.from_env(tmp_path)
    assert create_llm_provider(settings) is None


def test_llm_service_generate():
    async def run_test():
        # Service with no provider
        service_none = LLMService(None)
        assert service_none.is_configured is False
        answer, mode = await service_none.generate(question="test", sources=SOURCES)
        assert answer is None
        assert mode == "local-grounded"

        # Service with provider
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "Answer with citation [1]"}}]},
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            provider = CerebrasProvider(
                api_key="key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
            )
            service = LLMService(provider)
            assert service.is_configured is True
            answer, mode = await service.generate(
                question="test", sources=SOURCES, client=client
            )
            assert answer == "Answer with citation [1]"
            assert mode == "cerebras:gpt-oss-120b"

    asyncio.run(run_test())


def test_cerebras_passes_multi_turn_history():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            messages = payload["messages"]
            assert len(messages) == 4
            assert messages[0]["role"] == "developer"
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == "Who owns the rollout plan?"
            assert messages[2]["role"] == "assistant"
            assert messages[2]["content"] == "Jordan Lee owns the rollout plan [1]."
            assert messages[3]["role"] == "user"
            assert "When did they join?" in messages[3]["content"]
            assert "Sources:\n" in messages[3]["content"]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Jordan joined in 2023 [1]."}}
                    ]
                },
            )

        history = [
            {"role": "user", "content": "Who owns the rollout plan?"},
            {"role": "assistant", "content": "Jordan Lee owns the rollout plan [1]."},
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = CerebrasProvider(
                api_key="test-api-key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
            )
            return await provider.generate_response(
                question="When did they join?",
                sources=SOURCES,
                history=history,
                client=client,
            )

    assert asyncio.run(run_test()) == "Jordan joined in 2023 [1]."


def test_openai_compatible_passes_multi_turn_history():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            messages = payload["messages"]
            assert len(messages) == 4
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert messages[2]["role"] == "assistant"
            assert messages[3]["role"] == "user"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "OpenAI history answer [1]."}}
                    ]
                },
            )

        history = [
            {"role": "user", "content": "Who owns the rollout plan?"},
            {"role": "assistant", "content": "Jordan Lee owns the rollout plan [1]."},
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                api_key="sk-test",
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
            )
            return await provider.generate_response(
                question="When did they join?",
                sources=SOURCES,
                history=history,
                client=client,
            )

    assert asyncio.run(run_test()) == "OpenAI history answer [1]."


def test_gemini_passes_multi_turn_history():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            contents = payload["contents"]
            assert len(contents) == 3
            assert contents[0]["role"] == "user"
            assert contents[0]["parts"][0]["text"] == "Who owns the rollout plan?"
            assert contents[1]["role"] == "model"
            assert contents[1]["parts"][0]["text"] == "Jordan Lee owns the rollout plan [1]."
            assert contents[2]["role"] == "user"
            assert "When did they join?" in contents[2]["parts"][0]["text"]
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": "Gemini history answer [1]."}]}}
                    ]
                },
            )

        history = [
            {"role": "user", "content": "Who owns the rollout plan?"},
            {"role": "assistant", "content": "Jordan Lee owns the rollout plan [1]."},
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GeminiProvider(
                api_key="gemini-key",
                base_url="https://generativelanguage.googleapis.com/v1beta",
                model="gemini-1.5-flash",
            )
            return await provider.generate_response(
                question="When did they join?",
                sources=SOURCES,
                history=history,
                client=client,
            )

    assert asyncio.run(run_test()) == "Gemini history answer [1]."


def test_anthropic_passes_multi_turn_history():
    async def run_test() -> str | None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            messages = payload["messages"]
            assert len(messages) == 3
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "Who owns the rollout plan?"
            assert messages[1]["role"] == "assistant"
            assert messages[1]["content"] == "Jordan Lee owns the rollout plan [1]."
            assert messages[2]["role"] == "user"
            assert "When did they join?" in messages[2]["content"]
            return httpx.Response(
                200,
                json={
                    "content": [
                        {"type": "text", "text": "Claude history answer [1]."}
                    ]
                },
            )

        history = [
            {"role": "user", "content": "Who owns the rollout plan?"},
            {"role": "assistant", "content": "Jordan Lee owns the rollout plan [1]."},
        ]
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(
                api_key="anthropic-key",
                base_url="https://api.anthropic.com/v1",
                model="claude-3-5-haiku-latest",
            )
            return await provider.generate_response(
                question="When did they join?",
                sources=SOURCES,
                history=history,
                client=client,
            )

    assert asyncio.run(run_test()) == "Claude history answer [1]."


def test_cerebras_backward_compatible_helper():
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


def test_cerebras_stream_response():
    async def run_test() -> list[str]:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["stream"] is True
            sse_content = (
                "data: " + json.dumps({"choices": [{"delta": {"content": "Jordan "}}]}) + "\n\n"
                "data: " + json.dumps({"choices": [{"delta": {"content": "owns "}}]}) + "\n\n"
                "data: " + json.dumps({"choices": [{"delta": {"content": "the rollout."}}]}) + "\n\n"
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=sse_content)

        tokens = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = CerebrasProvider(
                api_key="test-api-key",
                base_url="https://api.cerebras.ai/v1",
                model="gpt-oss-120b",
            )
            async for token in provider.stream_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            ):
                tokens.append(token)
        return tokens

    assert asyncio.run(run_test()) == ["Jordan ", "owns ", "the rollout."]


def test_openai_stream_response():
    async def run_test() -> list[str]:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["stream"] is True
            sse_content = (
                "data: " + json.dumps({"choices": [{"delta": {"content": "Streaming "}}]}) + "\n\n"
                "data: " + json.dumps({"choices": [{"delta": {"content": "OpenAI "}}]}) + "\n\n"
                "data: " + json.dumps({"choices": [{"delta": {"content": "response."}}]}) + "\n\n"
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=sse_content)

        tokens = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(
                api_key="openai-key",
                base_url="https://api.openai.com/v1",
                model="gpt-4o-mini",
            )
            async for token in provider.stream_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            ):
                tokens.append(token)
        return tokens

    assert asyncio.run(run_test()) == ["Streaming ", "OpenAI ", "response."]


def test_gemini_stream_response():
    async def run_test() -> list[str]:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "streamGenerateContent?alt=sse" in str(request.url)
            sse_content = (
                "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "Gemini "}]}}]}) + "\n\n"
                "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "token "}]}}]}) + "\n\n"
                "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "stream."}]}}]}) + "\n\n"
            )
            return httpx.Response(200, text=sse_content)

        tokens = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = GeminiProvider(
                api_key="gemini-key",
                base_url="https://generativelanguage.googleapis.com/v1beta",
                model="gemini-1.5-flash",
            )
            async for token in provider.stream_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            ):
                tokens.append(token)
        return tokens

    assert asyncio.run(run_test()) == ["Gemini ", "token ", "stream."]


def test_anthropic_stream_response():
    async def run_test() -> list[str]:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload["stream"] is True
            sse_content = (
                "event: content_block_delta\n"
                "data: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Claude "}}) + "\n\n"
                "event: content_block_delta\n"
                "data: " + json.dumps({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "stream."}}) + "\n\n"
            )
            return httpx.Response(200, text=sse_content)

        tokens = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(
                api_key="anthropic-key",
                base_url="https://api.anthropic.com/v1",
                model="claude-3-5-haiku-latest",
            )
            async for token in provider.stream_response(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            ):
                tokens.append(token)
        return tokens

    assert asyncio.run(run_test()) == ["Claude ", "stream."]


def test_llm_service_generate_stream():
    async def run_test():
        async def handler(_: httpx.Request) -> httpx.Response:
            sse_content = (
                "data: " + json.dumps({"choices": [{"delta": {"content": "Service stream [1]. "}}]}) + "\n\n"
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=sse_content)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = CerebrasProvider(
                api_key="key",
                base_url="https://api.cerebras.ai/v1",
                model="model",
            )
            service = LLMService(provider)
            stream_gen, mode = await service.generate_stream(
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            )
            assert mode == "cerebras:model"
            assert stream_gen is not None
            tokens = [t async for t in stream_gen]
            return tokens

    assert asyncio.run(run_test()) == ["Service stream [1]. "]


def test_cerebras_backward_compatible_stream_helper():
    async def run_test():
        async def handler(_: httpx.Request) -> httpx.Response:
            sse_content = (
                "data: " + json.dumps({"choices": [{"delta": {"content": "Streamed helper"}}]}) + "\n\n"
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, text=sse_content)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tokens = []
            async for token in generate_with_cerebras_stream(
                api_key="key",
                base_url="https://api.cerebras.ai/v1",
                model="model",
                question="What does Jordan own?",
                sources=SOURCES,
                client=client,
            ):
                tokens.append(token)
            return tokens

    assert asyncio.run(run_test()) == ["Streamed helper"]



