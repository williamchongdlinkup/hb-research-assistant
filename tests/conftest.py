"""Shared pytest fixtures for the HB Research Assistant.

Tests run against a tiny in-memory fixture corpus (not the real CSV) so they are
fast, hermetic, and exercise the bilingual / venue paths deterministically. The
app lifespan is intentionally NOT entered (we set ``main._db`` by hand), so no
real Gemini startup ping fires during tests.
"""
import csv
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `import main` work
import main  # noqa: E402

# Full CSV header the loader expects (rec.get fills blanks for anything omitted).
FIELDNAMES = [
    "sNo", "Type",
    "LastName_1stAuthor", "FirstName_1stAuthor", "LastName_2ndAuthor", "FirstName_2ndAuthor",
    "LastName_3rdAuthor", "FirstName_3rdAuthor", "LastName_4thAuthor", "FirstName_4thAuthor",
    "LastName_1stEditor", "FirstName_1stEditor", "LastName_2ndEditor", "FirstName_2ndEditor",
    "LastName_3rdEditor", "FirstName_3rdEditor",
    "Title", "City", "Publisher", "Year", "Abstract",
    "WebpageMetadata(PreJun2024)", "WebpageMetadata(UpdatedJun2024)", "WebpageFullText",
    "Title_Book", "Title_Journal", "Vol_Journal", "Issue_Journal", "Page_Start", "Page_End",
]

# A handful of rows covering: English journal article (venue + pages), a book with
# publisher, a Chinese-titled article (CJK), a chapter with diacritics, and a thesis.
ROWS = [
    {
        "sNo": "1", "Type": "Journal Article",
        "LastName_1stAuthor": "Smith", "FirstName_1stAuthor": "John",
        "Title": "Compassion in Modern Buddhism", "Year": "2018",
        "Abstract": "A study of karuna and social action in contemporary practice.",
        "Title_Journal": "Journal of Buddhist Ethics", "Vol_Journal": "25",
        "Issue_Journal": "2", "Page_Start": "1", "Page_End": "20",
        "WebpageMetadata(UpdatedJun2024)": "https://example.org/jbe/1",
    },
    {
        "sNo": "2", "Type": "Book",
        "LastName_1stAuthor": "Travagnin", "FirstName_1stAuthor": "Stefania",
        "Title": "Engaged Buddhism in Taiwan", "Year": "2017",
        "City": "London", "Publisher": "Routledge",
        "Abstract": "Humanistic Buddhism and engaged practice across the island.",
    },
    {
        "sNo": "3", "Type": "Journal Article",
        "LastName_1stAuthor": "Chen", "FirstName_1stAuthor": "Wei",
        # CJK term kept as a delimited token (unicode61 has no word segmentation,
        # so it matches whole runs only — mirrors how the real corpus stores it).
        "Title": "人間佛教 的實踐", "Year": "2019",
        "Abstract": "Renjian Fojiao practice in modern society.",
        "Title_Journal": "Chinese Buddhist Studies",
    },
    {
        "sNo": "4", "Type": "Book Chapter",
        "LastName_1stAuthor": "Müller", "FirstName_1stAuthor": "Hans",
        "LastName_1stEditor": "Jones", "FirstName_1stEditor": "Alice",
        "Title": "Karuṇā and Suffering", "Year": "2020",
        "Abstract": "On compassion as a response to suffering.",
        "Title_Book": "Handbook of Buddhist Ethics", "Page_Start": "100", "Page_End": "115",
    },
    {
        "sNo": "5", "Type": "Thesis",
        "LastName_1stAuthor": "Lee", "FirstName_1stAuthor": "Mary",
        "Title": "Secular Mindfulness Movements", "Year": "2021",
        "Publisher": "Harvard University",
        "Abstract": "Mindfulness adapted outside its religious context.",
    },
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    csv_path = tmp_path / "fixture.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in ROWS:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})

    monkeypatch.setattr(main, "CSV_PATH", csv_path)
    main._db = main._build_db()
    # Pretend AI is configured so endpoints don't 503; tests that need the model
    # stub the rotation helpers directly.
    monkeypatch.setattr(main, "_clients", [object()])
    return TestClient(main.app)  # not a context manager -> lifespan not run
