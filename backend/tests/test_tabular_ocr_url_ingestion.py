from __future__ import annotations

import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.extraction import ExtractionError, extract_pages, extract_people
from app.html_scraper import clean_html, fetch_and_clean_url, is_safe_url
from app.ocr import extract_page_ocr_text, ocr_image_bytes, set_ocr_handler


def create_sample_xlsx(headers: list[str], rows: list[list[str]]) -> bytes:
    """Build a minimal valid XLSX in memory."""
    buf = io.BytesIO()
    all_strings: list[str] = []
    string_map: dict[str, int] = {}

    def get_str_idx(val: str) -> int:
        if val not in string_map:
            string_map[val] = len(all_strings)
            all_strings.append(val)
        return string_map[val]

    header_indices = [get_str_idx(h) for h in headers]
    row_indices = [[get_str_idx(cell) for cell in row] for row in rows]

    with zipfile.ZipFile(buf, "w") as zf:
        # xl/sharedStrings.xml
        sst_xml = ['<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
        for s in all_strings:
            sst_xml.append(f"<si><t>{s}</t></si>")
        sst_xml.append("</sst>")
        zf.writestr("xl/sharedStrings.xml", "".join(sst_xml))

        # xl/worksheets/sheet1.xml
        sheet_xml = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        # header row
        sheet_xml.append('<row r="1">')
        for col_idx, s_idx in enumerate(header_indices):
            col_letter = chr(ord('A') + col_idx)
            sheet_xml.append(f'<c r="{col_letter}1" t="s"><v>{s_idx}</v></c>')
        sheet_xml.append('</row>')
        # data rows
        for r_num, row_cells in enumerate(row_indices, start=2):
            sheet_xml.append(f'<row r="{r_num}">')
            for col_idx, s_idx in enumerate(row_cells):
                col_letter = chr(ord('A') + col_idx)
                sheet_xml.append(f'<c r="{col_letter}{r_num}" t="s"><v>{s_idx}</v></c>')
            sheet_xml.append('</row>')
        sheet_xml.append('</sheetData></worksheet>')
        zf.writestr("xl/worksheets/sheet1.xml", "".join(sheet_xml))

    return buf.getvalue()


def test_csv_extraction_with_headers():
    csv_content = "Name,Department,Role\nAlice Walker,Research,Lead Scientist\nBob Martinez,Operations,Manager\n"
    pages = extract_pages("team.csv", csv_content.encode("utf-8"))
    assert len(pages) == 1
    assert "Row 1: Name: Alice Walker | Department: Research | Role: Lead Scientist" in pages[0].text
    assert "Row 2: Name: Bob Martinez | Department: Operations | Role: Manager" in pages[0].text

    people = extract_people(pages[0].text)
    assert "Alice Walker" in people
    assert "Bob Martinez" in people


def test_xlsx_extraction_with_headers():
    xlsx_bytes = create_sample_xlsx(
        headers=["Full Name", "Project", "Location"],
        rows=[
            ["Elena Rostova", "Project Titan", "Zurich"],
            ["Marcus Vance", "Project Apollo", "Boston"],
        ],
    )
    pages = extract_pages("roster.xlsx", xlsx_bytes)
    assert len(pages) == 1
    assert "Row 1: Full Name: Elena Rostova | Project: Project Titan | Location: Zurich" in pages[0].text
    assert "Row 2: Full Name: Marcus Vance | Project: Project Apollo | Location: Boston" in pages[0].text

    people = extract_people(pages[0].text)
    assert "Elena Rostova" in people
    assert "Marcus Vance" in people


def test_ocr_handler_fallback():
    try:
        set_ocr_handler(lambda b: "Extracted text via Custom OCR for Dr. David Clark")
        assert ocr_image_bytes(b"dummy_bytes") == "Extracted text via Custom OCR for Dr. David Clark"

        # Mock PDF page with an image
        mock_image = MagicMock()
        mock_image.data = b"image_data"
        mock_page = MagicMock()
        mock_page.images = [mock_image]

        text = extract_page_ocr_text(mock_page)
        assert "Dr. David Clark" in text
    finally:
        set_ocr_handler(None)


def test_url_safety_validation():
    # Blocked hosts and internal/loopback IPs
    assert not is_safe_url("http://localhost:8000/data")
    assert not is_safe_url("http://127.0.0.1/doc")
    assert not is_safe_url("http://0.0.0.0/")
    assert not is_safe_url("http://169.254.169.254/latest/meta-data")
    assert not is_safe_url("http://[::1]/")
    assert not is_safe_url("http://10.0.0.1/internal")
    assert not is_safe_url("http://192.168.1.1/secret")
    assert not is_safe_url("ftp://example.com/file")
    assert not is_safe_url("file:///etc/passwd")

    # Allowed public URLs
    assert is_safe_url("https://example.com/article")
    assert is_safe_url("http://github.com/avikumart/RAGbot")


def test_clean_html_extraction():
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Leadership Team | Acme Corp</title>
        <script>console.log("ignore me");</script>
        <style>body { color: red; }</style>
      </head>
      <body>
        <nav><a href="/">Home</a></nav>
        <article>
          <h1>Executive Leadership</h1>
          <p>Sarah Connor serves as Chief Executive Officer.</p>
          <p>John Doe leads Product Development across Europe.</p>
        </article>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    title, cleaned = clean_html(sample_html)
    assert title == "Leadership Team | Acme Corp"
    assert "ignore me" not in cleaned
    assert "color: red" not in cleaned
    assert "Sarah Connor serves as Chief Executive Officer." in cleaned
    assert "John Doe leads Product Development across Europe." in cleaned


def test_fetch_and_clean_url_mocked():
    import asyncio

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><head><title>Test Page</title></head><body><p>Dr. Alan Grant studies paleontology.</p></body></html>"
        mock_resp.content = mock_resp.text.encode("utf-8")
        mock_get.return_value = mock_resp

        title, cleaned, raw_bytes = asyncio.run(fetch_and_clean_url("https://example.com/bio"))
        assert title == "Test Page"
        assert "Dr. Alan Grant studies paleontology." in cleaned
        assert len(raw_bytes) > 0


def test_post_documents_url_endpoint(tmp_path):
    from app.main import create_app

    app = create_app(tmp_path)
    with TestClient(app) as client:
        with patch("app.main.fetch_and_clean_url", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (
                "Engineering Directors",
                "Rachel Green heads the platform engineering group at Central Perk.",
                b"<html><body>Rachel Green heads the platform engineering group at Central Perk.</body></html>",
            )

            response = client.post(
                "/api/documents/url",
                json={"url": "https://example.com/team/rachel"},
            )
            assert response.status_code == 201, response.text
            data = response.json()
            assert data["filename"] == "Engineering-Directors.html"
            assert "Rachel Green" in data["people"]


def test_post_documents_url_ssrf_rejected(tmp_path):
    from app.main import create_app

    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/url",
            json={"url": "http://127.0.0.1:8000/admin"},
        )
        assert response.status_code == 400
        assert "invalid or points to a restricted address" in response.json()["detail"]
