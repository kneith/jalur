"""Application services. SearchStrategy is injected and dispatched polymorphically."""
from app.repositories.directory import ContainsStrategy, ExactStrategy, JSONDirectoryRepository

class DirectoryService:
    def __init__(self, repository):
        self._repository = repository
    def search(self, query, kind="all", limit=25, offset=0, filters=None, exact=False):
        strategy = ExactStrategy() if exact else ContainsStrategy()
        return self._repository.search(query, kind, limit, offset, filters or {}, strategy)

class InstitutionDirectoryService(DirectoryService):
    """Inheritance: specialization fixes the resource type to institutions."""
    def search(self, query, kind="institution", limit=25, offset=0, filters=None, exact=False):
        return super().search(query, "institution", limit, offset, filters, exact)

class ProgramDirectoryService(DirectoryService):
    """Inheritance: specialization fixes the resource type to study programs."""
    def search(self, query, kind="program", limit=25, offset=0, filters=None, exact=False):
        return super().search(query, "program", limit, offset, filters, exact)
