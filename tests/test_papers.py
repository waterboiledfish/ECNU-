from __future__ import annotations

import pytest

from app.services import papers


def test_reconstruct_abstract():
    inverted = {"Hello": [0], "world": [1], "again": [2]}
    assert papers._reconstruct_abstract(inverted) == "Hello world again"
    assert papers._reconstruct_abstract(None) == ""


def test_rank_dedupes_and_links():
    ranked = papers._rank(
        [
            {"title": "A Great Paper", "year": 2024, "citations": 100, "doi": "10.1/x", "oa_url": "", "openalex": ""},
            {"title": "A great paper!", "year": 2023, "citations": 50, "doi": "", "oa_url": "https://example.com/pdf", "openalex": ""},
            {"title": "Another Paper", "year": 2025, "citations": 0, "doi": "", "oa_url": "", "openalex": "https://openalex.org/W1"},
        ]
    )
    assert len(ranked) == 2
    assert ranked[0]["link"] == "https://doi.org/10.1/x"
    assert ranked[1]["link"] == "https://openalex.org/W1"


def test_expand_query_mapping():
    assert papers.expand_query("人工智能") == "artificial intelligence"
    assert papers.expand_query("deep learning") == "deep learning"
    assert papers.expand_query("某个冷门方向") == "某个冷门方向"


def test_recommend_caches(client, monkeypatch):
    sample = [
        {
            "title": "LLM Survey",
            "authors": ["Alice"],
            "year": 2024,
            "venue": "Journal",
            "citations": 10,
            "abstract": "An abstract",
            "doi": "10.1000/abc",
            "openalex": "https://openalex.org/W1",
            "oa_url": "",
            "source": "openalex",
        }
    ]
    monkeypatch.setattr(papers, "_openalex", lambda query, per_page=8: list(sample))
    monkeypatch.setattr(papers, "_arxiv", lambda query, max_results=5: [])
    first = papers.recommend("人工智能", refresh=True)
    assert first["cached"] is False
    assert first["papers"][0]["title"] == "LLM Survey"
    assert first["papers"][0]["link"].startswith("https://doi.org/")
    second = papers.recommend("人工智能")
    assert second["cached"] is True


def test_recommend_raises_when_no_sources(client, monkeypatch):
    monkeypatch.setattr(papers, "_openalex", lambda query, per_page=8: [])
    monkeypatch.setattr(papers, "_arxiv", lambda query, max_results=5: [])
    with pytest.raises(papers.PaperError):
        papers.recommend("不存在的方向", refresh=True)
