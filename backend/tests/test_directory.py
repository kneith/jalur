from pathlib import Path
from app.repositories.directory import (
    JSONDirectoryRepository, ContainsStrategy, ExactStrategy,
)
from app.services import DirectoryService

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "database.js"

def make_service():
    repo = JSONDirectoryRepository(str(DATA))
    return repo, DirectoryService(repo)

def test_original_dataset_counts_are_preserved():
    repo, _ = make_service()
    assert repo.counts == {"institutions": 4303, "programs": 34709}

def test_institution_search_returns_original_detail_fields():
    _, service = make_service()
    items, total = service.search("Universitas Gadjah Mada", "institution", 10, 0)
    assert total >= 1
    row = items[0]["data"]
    assert row["name"] == "Universitas Gadjah Mada"
    assert row["province"] == "Prov. D.I. Yogyakarta"
    assert row["accreditation"] == "Unggul"
    assert items[0]["type"] == "institution"

def test_program_search_includes_institution_level_and_field():
    _, service = make_service()
    items, total = service.search("Peternakan", "program", 10, 0, {"institution":"Universitas Muara Bungo"})
    assert total > 0
    assert any(item["data"]["campus"] == "Universitas Muara Bungo" for item in items)
    assert all(item["data"]["level"] for item in items)

def test_filters_and_pagination():
    _, service = make_service()
    first, total = service.search("Peternakan", "program", 1, 0, {"level":"S1"})
    second, _ = service.search("Peternakan", "program", 1, 1, {"level":"S1"})
    assert total >= 2
    assert len(first) == len(second) == 1
    assert first[0]["id"] != second[0]["id"]

def test_search_strategy_polymorphism():
    contains = ContainsStrategy()
    exact = ExactStrategy()
    assert contains.matches("Gadjah", "Universitas Gadjah Mada")
    assert not exact.matches("Gadjah", "Universitas Gadjah Mada")
    assert exact.matches("UGM", "UGM")
