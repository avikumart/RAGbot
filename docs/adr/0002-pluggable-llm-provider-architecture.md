# 0002: Pluggable LLM provider architecture for retrieval summarization

- Status: Accepted
- Date: 2026-08-21
- Deciders: project maintainers
- Supersedes: none
- Superseded by: none

## Context

Originally, Personagraph answer generation was coupled exclusively to Cerebras Cloud via direct HTTP chat completion calls. Users desiring local offline inference (via Ollama or vLLM) or alternative hosted models (OpenAI, Google Gemini, Anthropic Claude, Groq) could not switch backends without altering backend source code. Furthermore, coupling response generation to a specific provider vendor limited deployment flexibility in privacy-sensitive or offline environments.

## Decision

We introduce an object-oriented, provider-agnostic LLM interface centered around an abstract base class `LLMProvider` and an orchestration service `LLMService` in `backend/app/llm.py`.

The system provides concrete provider implementations:
1. `CerebrasProvider`: Cloud ultra-fast inference with developer-role formatting.
2. `OpenAICompatibleProvider`: Standard `/chat/completions` protocol supporting OpenAI, Groq, local offline Ollama, vLLM, and DeepSeek.
3. `GeminiProvider`: Google Gemini REST API (`generateContent`) with system instructions and JSON candidate parsing.
4. `AnthropicProvider`: Anthropic Messages API (`/v1/messages`) with role-based structure and version headers.
5. Zero-configuration local fallback: Deterministic grounded synthesis when no API key or provider is available.

Key design principles:
- **Object-Oriented & Pluggable**: Each provider implements `provider_name`, `model_name`, `mode_label`, `is_configured()`, and `generate_response()`.
- **Strict Citation Guarantee**: All provider adapters enforce bracketed source citations (`[1]`, `[2]`), automatically appending citation markers if omitted by the LLM.
- **Unified Configuration**: Configurable via `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` with provider-specific automatic fallbacks and backward compatibility for legacy `CEREBRAS_*` settings.
- **Fail-Safe Fallback**: Any HTTP error, timeout, or malformed provider response safely degrades to deterministic local grounded synthesis without failing user requests.

## Alternatives considered

### Keep provider-specific custom endpoints

Creating disparate functions per provider would lead to code duplication, inconsistent prompt engineering, and tighter coupling across route handlers.

### Use heavy external orchestration frameworks (e.g. LangChain / LlamaIndex)

Adding bulky external dependencies introduces significant dependency bloat, runtime overhead, and supply-chain vulnerabilities for straightforward retrieval summarization.

## Consequences

- Switching LLM backends requires only environment variable changes.
- Offline and air-gapped deployments can run completely locally with Ollama/vLLM without external network dependencies.
- Frontend transparently displays the active provider and model in chat response metadata badges.
- Contract tests verify request serialization, authentication header transmission, and response parsing for each provider.

## Validation

Contract unit tests in `backend/tests/test_llm.py` and API integration tests in `backend/tests/test_api.py` verify all supported providers, factory initialization, citation normalization, and fallback mechanisms.
