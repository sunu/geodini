import json
from typing import Any

import duckdb


def duckdb_sanbox(geometries: dict[str, Any], query: str) -> dict[str, Any]:
    rows = [(name, json.dumps(geom)) for name, geom in geometries.items()]

    con = duckdb.connect(":memory:")
    # con = duckdb.connect("/app/data/test.db")
    con.execute("INSTALL spatial; LOAD spatial;")
    # Create in-memory table
    con.execute("CREATE TABLE place (name TEXT, geojson TEXT);")
    con.executemany("INSERT INTO place VALUES (?, ?);", rows)
    result = con.execute(query).fetchone()
    # print(result)
    con.close()
    return json.loads(result[0])
