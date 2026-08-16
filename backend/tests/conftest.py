import pytest


@pytest.fixture(autouse=True)
def disable_live_cerebras_calls(monkeypatch):
    """Tests must never spend API credits or depend on external network access."""
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "false")
