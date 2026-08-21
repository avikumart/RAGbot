from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
HONORIFIC_PATTERN = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof|Professor)\.?\s+"
    r"([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?){1,2})"
)
NAME_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
    r"(?:\s+(?:[A-Z]\.?(?:\s+|$)|[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?)){1,3})\b"
)

GENERIC_TERMS = {
    "about", "appendix", "board", "chapter", "company", "confidential", "contact",
    "department", "document", "education", "experience", "friday", "group", "inc",
    "introduction", "labs", "monday", "notes", "overview", "project", "references",
    "report", "saturday", "section", "services", "summary", "sunday", "team", "thursday",
    "tuesday", "wednesday",
}
ROLE_TERMS = {
    "analyst", "architect", "assistant", "consultant", "coordinator", "designer", "director",
    "engineer", "lead", "manager", "officer", "owner", "president", "specialist", "supervisor",
}


class ExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedPage:
    page: int | None
    text: str


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page: int | None
    content: str
    people: tuple[str, ...]


def normalize_space(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pages(filename: str, payload: bytes) -> list[ExtractedPage]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ExtractionError("Supported formats are PDF, DOCX, TXT, and Markdown.")

    try:
        if suffix in {".txt", ".md"}:
            text = payload.decode("utf-8-sig")
            pages = [ExtractedPage(page=None, text=normalize_space(text))]
        elif suffix == ".pdf":
            reader = PdfReader(io.BytesIO(payload))
            pages = [
                ExtractedPage(page=index + 1, text=normalize_space(page.extract_text() or ""))
                for index, page in enumerate(reader.pages)
            ]
        else:
            document = Document(io.BytesIO(payload))
            text = "\n\n".join(paragraph.text for paragraph in document.paragraphs)
            pages = [ExtractedPage(page=None, text=normalize_space(text))]
    except Exception as exc:  # parser errors are intentionally normalized for the API
        raise ExtractionError(f"Could not read {suffix.removeprefix('.').upper()} content.") from exc

    pages = [page for page in pages if page.text]
    if not pages:
        raise ExtractionError(
            "No selectable text was found. Scanned PDFs need OCR before upload."
        )
    return pages


def _clean_person(candidate: str) -> str | None:
    candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;()[]")
    tokens = candidate.split()
    if not 2 <= len(tokens) <= 4:
        return None
    lowered = {token.lower().strip(".") for token in tokens}
    if lowered & GENERIC_TERMS or tokens[-1].lower().strip(".") in ROLE_TERMS:
        return None
    if any(len(token.strip(".")) < 2 for token in tokens if not token.endswith(".")):
        return None
    return candidate


def extract_people(text: str) -> list[str]:
    """Extract likely personal names with a dependency-free, deterministic heuristic."""
    honorific_names = {
        person for match in HONORIFIC_PATTERN.finditer(text)
        if (person := _clean_person(match.group(1)))
    }
    general_names = {
        person for match in NAME_PATTERN.finditer(text)
        if (person := _clean_person(match.group(1)))
    }
    names = honorific_names | general_names
    # Prefer the longest form when the same name appears as both "Maya Patel" and "Maya" aliases.
    return sorted(names, key=lambda name: (name.lower(), -len(name)))


def _split_long_paragraph(paragraph: str, limit: int) -> list[str]:
    words = paragraph.split()
    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        if current and len(" ".join(current + [word])) > limit:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_pages(
    pages: list[ExtractedPage], limit: int = 800, overlap: int = 150
) -> list[Chunk]:
    if limit <= 0:
        limit = 800
    overlap = max(0, min(overlap, limit // 2))

    chunks: list[Chunk] = []
    ordinal = 0
    for page in pages:
        text = page.text.strip()
        if not text:
            continue

        start = 0
        text_len = len(text)
        while start < text_len:
            end = min(start + limit, text_len)
            if end < text_len:
                space_idx = text.rfind(" ", start, end)
                if space_idx > start:
                    end = space_idx

            content = text[start:end].strip()
            if content:
                chunks.append(
                    Chunk(ordinal, page.page, content, tuple(extract_people(content)))
                )
                ordinal += 1

            if end >= text_len:
                break

            next_start = max(start + 1, end - overlap)
            if next_start < text_len:
                space_idx = text.find(" ", next_start, end)
                if space_idx != -1:
                    next_start = space_idx + 1
            start = next_start

    return chunks


def count_people(chunks: list[Chunk]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for chunk in chunks:
        counts.update(chunk.people)
    return counts


