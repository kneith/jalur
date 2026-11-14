"""Directory repositories demonstrate abstraction, inheritance and polymorphism."""
from abc import ABC, abstractmethod
from pathlib import Path
import json

class SearchStrategy(ABC):
    """Abstraction: all search strategies expose the same matching contract."""
    @abstractmethod
    def matches(self, query: str, haystack: str) -> bool:
        raise NotImplementedError

class ContainsStrategy(SearchStrategy):
    def matches(self, query: str, haystack: str) -> bool:
        return query.casefold() in haystack.casefold()

class ExactStrategy(SearchStrategy):
    def matches(self, query: str, haystack: str) -> bool:
        return query.casefold() == haystack.casefold()

class DirectoryRepository(ABC):
    """Abstract repository contract consumed by DirectoryService."""
    @abstractmethod
    def search(self, query: str, kind: str, limit: int, offset: int,
               filters: dict, strategy: SearchStrategy) -> tuple[list[dict], int]:
        raise NotImplementedError

class JSONDirectoryRepository(DirectoryRepository):
    """In-memory snapshot repository backed by the original source database.js."""
    def __init__(self, source_path: str):
        self.__source_path = Path(source_path)
        self.__institutions, self.__programs = self.__load()
        self.__search_index = [
            ("institution", row, self.__text(row)) for row in self.__institutions
        ] + [
            ("program", row, self.__text(row)) for row in self.__programs
        ]
        # Sort once during repository startup, not for every keystroke/search request.
        self.__search_index.sort(key=lambda item: (
            str(item[1].get("name") or "").casefold(),
            str(item[1].get("campus") or item[1].get("city") or "").casefold(),
            str(item[1].get("id") or "")
        ))

    @property
    def counts(self) -> dict:
        return {"institutions": len(self.__institutions), "programs": len(self.__programs)}

    def __load(self):
        raw = self.__source_path.read_text(encoding="utf-8")
        marker = "window.JALUR_DB_RAW="
        start = raw.find(marker)
        if start < 0:
            raise ValueError("Format database.js tidak dikenali: JALUR_DB_RAW tidak ditemukan.")
        payload = raw[start + len(marker):].strip().rstrip(";")
        data = json.loads(payload)
        institutions = [dict(zip(data["ik"], row)) for row in data["i"]]
        programs = [dict(zip(data["pk"], row)) for row in data["p"]]
        return institutions, programs

    @staticmethod
    def __text(row: dict) -> str:
        # Search every source field, including metadata added in later workbook revisions.
        return " ".join(str(value) for value in row.values() if value is not None)

    @staticmethod
    def __passes(row: dict, filters: dict) -> bool:
        aliases = {"province": ("province","location"), "level": ("level",),
                   "field": ("field","group"), "accreditation": ("accreditation","programAccreditation"),
                   "status": ("status",), "institution": ("institution","campus","name")}
        for key, value in filters.items():
            if value in (None, ""): continue
            hay = " ".join(str(row.get(k) or "") for k in aliases.get(key, (key,)))
            if str(value).casefold() not in hay.casefold(): return False
        for key in ("capacity_min","capacity_max"):
            value = filters.get(key)
            if value not in (None, ""):
                try: cap = float(row.get("capacity"))
                except (TypeError, ValueError): return False
                if key == "capacity_min" and cap < float(value): return False
                if key == "capacity_max" and cap > float(value): return False
        return True

    def search(self, query, kind, limit, offset, filters, strategy):
        # Iterate in the pre-sorted order and retain only the requested page.
        # This avoids allocating and sorting every matching row on each keystroke.
        items = []
        total = 0
        page_end = offset + limit
        for item_type, row, hay in self.__search_index:
            if kind != "all" and item_type != kind:
                continue
            if not strategy.matches(query, hay) or not self.__passes(row, filters):
                continue
            if offset <= total < page_end:
                item = {"type": item_type, "id": row.get("id"), "name": row.get("name"), "data": row}
                if item_type == "program":
                    item.update({"institution_name": row.get("campus"), "level": row.get("level"), "field": row.get("field")})
                items.append(item)
            total += 1
        return items, total
