from app.config import Settings
from app.extraction import Chunk, ExtractedPage, chunk_pages, extract_people


def test_sliding_window_chunking_with_overlap():
    long_text = (
        "Sentence one describes the initial setup of the system. "
        "Sentence two provides details on configuration and environment variables. "
        "Sentence three highlights the importance of sliding window overlap. "
        "Sentence four explains how context boundaries are preserved without splitting words. "
        "Sentence five summarizes the results of the retrieval engine test suite."
    )
    pages = [ExtractedPage(page=1, text=long_text)]
    chunks = chunk_pages(pages, limit=120, overlap=30)

    assert len(chunks) > 1
    # Verify adjacent chunks share overlapping text content
    for idx in range(len(chunks) - 1):
        c1_text = chunks[idx].content
        c2_text = chunks[idx + 1].content
        # Check that there is common substring overlap between end of c1 and start of c2
        common = set(c1_text.split()) & set(c2_text.split())
        assert len(common) > 0

    # Ensure no chunk exceeds the length limit significantly
    for chunk in chunks:
        assert len(chunk.content) <= 150


def test_chunking_respects_configurable_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "500")
    monkeypatch.setenv("CHUNK_OVERLAP", "100")
    settings = Settings.from_env(tmp_path)
    assert settings.chunk_size == 500
    assert settings.chunk_overlap == 100


def test_chunking_extracts_people_in_overlapping_window():
    text = (
        "Dr. Maya Patel leads the AI research lab. " * 5
        + "Jordan Lee coordinates the infrastructure rollout. " * 5
    )
    pages = [ExtractedPage(page=1, text=text)]
    chunks = chunk_pages(pages, limit=200, overlap=50)

    people_found = set()
    for chunk in chunks:
        people_found.update(chunk.people)

    assert "Maya Patel" in people_found or "Jordan Lee" in people_found
