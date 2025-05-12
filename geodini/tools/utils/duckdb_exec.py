import duckdb
import json
from typing import Dict, Any

def duckdb_sanbox(geometries: Dict[str, Any], query: str) -> Dict[str, Any]:
    rows = [(name, json.dumps(geom)) for name, geom in geometries.items()]

    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial; LOAD spatial;")
    # Create in-memory table
    con.execute("CREATE TABLE place (name TEXT, geojson TEXT);")
    con.executemany("INSERT INTO place VALUES (?, ?);", rows)
    result = con.execute(query).fetchone()
    print(result)
    con.close()
    return result[0]
