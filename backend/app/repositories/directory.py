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
        self.__institution_index = [(row, self.__text(row)) for row in self.__institutions]
        self.__program_index = [(row, self.__text(row)) for row in self.__programs]

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
        candidates = []
        if kind in ("all", "institution"):
            candidates.extend(("institution", row, hay) for row, hay in self.__institution_index)
        if kind in ("all", "program"):
            candidates.extend(("program", row, hay) for row, hay in self.__program_index)
        found = []
        for item_type, row, hay in candidates:
            if not strategy.matches(query, hay) or not self.__passes(row, filters): continue
            found.append((item_type, row))
        found.sort(key=lambda item: (
            str(item[1].get("name") or "").casefold(),
            str(item[1].get("campus") or item[1].get("city") or "").casefold(),
            str(item[1].get("id") or "")
        ))
        total = len(found)
        items = []
        for item_type, row in found[offset:offset+limit]:
            item = {"type": item_type, "id": row.get("id"), "name": row.get("name"), "data": row}
            if item_type == "program":
                item.update({"institution_name": row.get("campus"), "level": row.get("level"), "field": row.get("field")})
            items.append(item)
        return items, total
