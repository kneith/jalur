"""PostgreSQL implementation of the DirectoryRepository contract."""
from app.repositories.directory import DirectoryRepository, ExactStrategy

class PostgresDirectoryRepository(DirectoryRepository):
    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def search(self, query, kind, limit, offset, filters, strategy):
        # The injected strategy selects exact or contains semantics in SQL.
        exact = isinstance(strategy, ExactStrategy)
        escaped = query.replace("\\\\", "\\\\\\\\").replace("%", "\\\\%").replace("_", "\\\\_")
        pattern = query if exact else f"%{escaped}%"
        operator = "=" if exact else "ILIKE"
        escape_clause = "" if exact else " ESCAPE '\\\\'"
        params = [pattern]
        conditions = []
        if kind in ("all", "institution"):
            conditions.append(f"""
                SELECT 'institution' AS type, id, name, NULL::text AS institution_name,
                       NULL::text AS level, NULL::text AS field, data,
                       search_text, name AS secondary
                FROM directory_institutions WHERE search_text {operator} %s ESCAPE '\\'
            """)
        if kind in ("all", "program"):
            conditions.append(f"""
                SELECT 'program' AS type, id, name, institution_name, level, field, data,
                       search_text, institution_name AS secondary
                FROM directory_programs WHERE search_text {operator} %s ESCAPE '\\'
            """)
        query_params = [pattern] * len(conditions)
        if not conditions:
            return [], 0
        union_sql = " UNION ALL ".join(conditions)
        where = []
        for key, value in filters.items():
            if value in (None, ""): continue
            if key == "province":
                where.append("(data->>'province' ILIKE %s OR data->>'location' ILIKE %s)")
                query_params.extend([f"%{value}%", f"%{value}%"])
            elif key == "level":
                where.append("level ILIKE %s"); query_params.append(f"%{value}%")
            elif key == "field":
                where.append("(field ILIKE %s OR data->>'group' ILIKE %s)")
                query_params.extend([f"%{value}%", f"%{value}%"])
            elif key == "accreditation":
                where.append("(data->>'accreditation' ILIKE %s OR data->>'programAccreditation' ILIKE %s)")
                query_params.extend([f"%{value}%", f"%{value}%"])
            elif key == "status":
                where.append("data->>'status' ILIKE %s"); query_params.append(f"%{value}%")
            elif key == "institution":
                where.append("(institution_name ILIKE %s OR data->>'name' ILIKE %s OR data->>'campus' ILIKE %s)")
                query_params.extend([f"%{value}%", f"%{value}%", f"%{value}%"])
            elif key in ("capacity_min", "capacity_max"):
                op = ">=" if key == "capacity_min" else "<="
                where.append(f"CASE WHEN data->>'capacity' ~ '^[0-9]+(\\.[0-9]+)?$' THEN (data->>'capacity')::numeric END {op} %s")
                query_params.append(value)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        with self._connection_factory() as conn:
            count = conn.execute(f"SELECT count(*) AS n FROM ({union_sql}) found{where_sql}", query_params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT type,id,name,institution_name,level,field,data FROM ({union_sql}) found{where_sql} "
                "ORDER BY lower(name), lower(coalesce(institution_name,'')), id LIMIT %s OFFSET %s",
                query_params + [limit, offset]
            ).fetchall()
        items = []
        for row in rows:
            data = row["data"]
            item = {"type":row["type"],"id":row["id"],"name":row["name"],"data":data}
            if row["type"] == "program":
                item.update({"institution_name":row["institution_name"],"level":row["level"],"field":row["field"]})
            items.append(item)
        return items, count
