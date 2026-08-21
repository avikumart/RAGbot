from app.config import Settings
from app.reranker import RerankerService
from app.retrieval import RankedChunk


def test_reranker_rescores_and_reorders_candidates():
    reranker = RerankerService(enabled=True)
    query = "quantum computing research"
    candidates = [
        (0.015, {"id": 1, "content": "General overview of traditional computer architectures."}),
        (0.012, {"id": 2, "content": "Deep dive into quantum computing research and algorithms."}),
    ]

    rescored = reranker.rerank(query, candidates, top_n=20)
    assert len(rescored) == 2
    # The chunk matching 'quantum computing research' should be rescored higher
    assert rescored[0][1]["id"] == 2


def test_reranker_disabled_preserves_original_order():
    reranker = RerankerService(enabled=False)
    query = "quantum computing research"
    candidates = [
        (0.015, {"id": 1, "content": "General overview of traditional computer architectures."}),
        (0.012, {"id": 2, "content": "Deep dive into quantum computing research and algorithms."}),
    ]

    rescored = reranker.rerank(query, candidates, top_n=20)
    assert rescored == candidates


def test_reranker_graceful_fallback_on_exception(monkeypatch):
    reranker = RerankerService(enabled=True)
    candidates = [(0.015, {"id": 1, "content": "Sample content"})]

    def faulty_score(*args, **kwargs):
        raise RuntimeError("Reranker engine memory overflow")

    monkeypatch.setattr(reranker, "score_candidate", faulty_score)
    result = reranker.rerank("query", candidates)
    assert result == candidates


def test_reranker_configurable_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    monkeypatch.setenv("RERANKER_MODEL", "custom-reranker-v1")
    monkeypatch.setenv("RERANK_TOP_N", "10")

    settings = Settings.from_env(tmp_path)
    assert settings.reranker_enabled is False
    assert settings.reranker_model == "custom-reranker-v1"
    assert settings.rerank_top_n == 10
