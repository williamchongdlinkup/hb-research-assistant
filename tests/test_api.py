"""End-to-end + unit tests for the HB Research Assistant.

Focus: the trustworthiness fixes from the June 2026 review — bilingual retrieval,
the empty-context guard, honest grounding counts, searchable venues, input
guardrails — plus export/citation smoke tests. Gemini is always stubbed.
"""
import main


class FakeResp:
    def __init__(self, text):
        self.text = text


# ── Unit: term extraction (locks T1 — bilingual coverage) ────────────────────

def test_extract_terms_keeps_cjk_and_diacritics():
    terms = main._extract_terms("人間佛教 compassion Karuṇā the of")
    assert "人間佛教" in terms          # CJK run kept
    assert "compassion" in terms
    assert "Karuṇā" in terms            # accented Latin kept
    assert "the" not in terms and "of" not in terms  # stopwords dropped


# ── Health / stats ───────────────────────────────────────────────────────────

def test_health(client):
    d = client.get("/api/health").json()
    assert d["status"] == "ok"
    assert d["db_entries"] == 5
    assert d["model"] == main.GEMINI_MODEL


def test_stats(client):
    d = client.get("/api/stats").json()
    assert d["total"] == 5
    assert d["year_min"] == 2017 and d["year_max"] == 2021


# ── Search: keyword, venue (S1), bilingual, bounds ───────────────────────────

def test_search_by_title_word(client):
    d = client.get("/api/search", params={"q": "compassion"}).json()
    titles = {r["title"] for r in d["results"]}
    assert "Compassion in Modern Buddhism" in titles


def test_search_by_journal_name(client):
    # S1: journal text is now indexed — this returned nothing before the fix.
    d = client.get("/api/search", params={"q": "Journal of Buddhist Ethics"}).json()
    assert d["total"] == 1
    assert d["results"][0]["serial_no"] == "1"


def test_search_by_publisher(client):
    d = client.get("/api/search", params={"q": "Routledge"}).json()
    assert d["total"] == 1
    assert d["results"][0]["serial_no"] == "2"


def test_search_cjk_title(client):
    d = client.get("/api/search", params={"q": "人間佛教"}).json()
    assert d["total"] == 1
    assert d["results"][0]["serial_no"] == "3"


def test_search_param_bounds(client):
    assert client.get("/api/search", params={"per_page": 500}).status_code == 422
    assert client.get("/api/search", params={"page": 0}).status_code == 422


def test_year_filter(client):
    d = client.get("/api/search", params={"q": "suffering", "year_from": 2020}).json()
    years = [r["year"] for r in d["results"]]
    assert years and all(y >= 2020 for y in years)
    assert d["results"][0]["serial_no"] == "4"


# ── Chat: empty-context guard (T2), grounding counts (T3), guardrails ─────────

def test_chat_empty_context_skips_llm(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM must not be called when nothing was retrieved")
    monkeypatch.setattr(main, "_chat_with_rotation", boom)
    d = client.post("/api/chat", json={"message": "zzzznonexistentterm", "history": []}).json()
    assert d["answer"] == main._INSUFFICIENT_INFO
    assert d["sources_count"] == 0 and d["cited_count"] == 0


def test_chat_grounded_counts_and_citation_bounds(client, monkeypatch):
    # Model cites [1] (valid) and [99] (out of range — must be dropped).
    monkeypatch.setattr(main, "_chat_with_rotation",
                        lambda sp, h, m: FakeResp("Compassion is central [1]. Bogus [99]."))
    d = client.post("/api/chat", json={"message": "compassion", "history": []}).json()
    assert d["cited_count"] == 1
    assert [c["number"] for c in d["citations"]] == [1]
    assert d["sources_count"] >= 1
    assert d["sources_count"] >= d["cited_count"]  # honest: never overstates


def test_chat_turn_limit_enforced_server_side(client, monkeypatch):
    monkeypatch.setattr(main, "_chat_with_rotation",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("blocked")))
    history = [{"role": "user", "content": "q"}, {"role": "model", "content": "a"}] * 5
    r = client.post("/api/chat", json={"message": "compassion", "history": history})
    assert r.status_code == 429


def test_chat_rejects_empty_and_overlong(client):
    assert client.post("/api/chat", json={"message": "   ", "history": []}).status_code == 400
    big = "x" * (main._MAX_CHAT_MESSAGE + 1)
    assert client.post("/api/chat", json={"message": big, "history": []}).status_code == 400


def test_chat_503_when_ai_unconfigured(client, monkeypatch):
    monkeypatch.setattr(main, "_clients", [])
    assert client.post("/api/chat", json={"message": "compassion", "history": []}).status_code == 503


# ── Audit guardrails ─────────────────────────────────────────────────────────

def test_audit_empty_returns_empty(client):
    d = client.post("/api/audit", json={"bibliography": ""}).json()
    assert d == {"verified": [], "not_in_corpus": [], "missing": [], "suggested": [], "pool_size": 0}


def test_audit_rejects_overlong(client):
    big = "x" * (main._MAX_AUDIT_BIB + 1)
    assert client.post("/api/audit", json={"bibliography": big}).status_code == 400


# ── Citations & exports (incl. CJK preservation) ─────────────────────────────

def test_cite_includes_venue_and_pages(client):
    d = client.get("/api/cite", params={"id": "1"}).json()
    assert "Journal of Buddhist Ethics" in d["chicago"]
    assert "1" in d["chicago"]  # page range present
    for fmt in ("chicago", "apa", "mla", "ris", "bibtex"):
        assert d[fmt].strip()


def test_cite_unknown_id_404(client):
    assert client.get("/api/cite", params={"id": "9999"}).status_code == 404


def test_export_csv_preserves_cjk_and_venue(client):
    r = client.post("/api/export", json={"ids": ["1", "3"], "format": "csv"})
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "Journal of Buddhist Ethics" in text
    assert "人間佛教" in text  # CJK round-trips through CSV


def test_export_ris_and_bibtex(client):
    ris = client.post("/api/export", json={"ids": ["1"], "format": "ris"}).content.decode("utf-8")
    assert "TY  - JOUR" in ris and "Journal of Buddhist Ethics" in ris
    bib = client.post("/api/export", json={"ids": ["1"], "format": "bibtex"}).content.decode("utf-8")
    assert bib.startswith("@article") and "Buddhist Ethics" in bib


def test_export_rtf_encodes_cjk_as_unicode(client):
    r = client.post("/api/export", json={"ids": ["3"], "format": "rtf"})
    assert r.status_code == 200
    # RTF body is ASCII, with CJK emitted as \uNNNN? escapes (not lost to '?').
    assert b"\\u" in r.content


def test_export_no_ids_400(client):
    assert client.post("/api/export", json={"ids": [], "format": "csv"}).status_code == 400
