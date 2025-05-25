import json
import os
from dataclasses import dataclass

import psycopg2
from pydantic_ai import Agent


@dataclass
class PostGISResult:
    query: str


def get_postgis_connection():
    """Get a connection to the PostGIS database."""
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST") or "database",
        database=os.getenv("POSTGRES_DB") or "geodini",
        user="postgres",
        port=os.getenv("POSTGRES_PORT") or 5432,
        password=os.getenv("POSTGRES_PASSWORD"),
    )


geometry_table_schema = """
CREATE TABLE IF NOT EXISTS geometries (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    geom GEOMETRY(Geometry, 4326),
    geometry GEOMETRY(Geometry, 4326)
);
"""


def create_geometries_table():
    """Create a table for storing places with name and geometry columns."""
    conn = get_postgis_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(geometry_table_schema)
        conn.commit()
    finally:
        conn.close()


def insert_place(name: str, geometry: str):
    """Insert a place into the database."""
    conn = get_postgis_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO geometries (name, geom, geometry) VALUES (%s, %s, %s)",
                (name, geometry, geometry),
            )
        conn.commit()
    finally:
        conn.close()


def run_postgis_query(query: str):
    """Run a PostGIS query on the database."""
    conn = get_postgis_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            results = cur.fetchone()
            return json.loads(results[0])
    finally:
        conn.close()


def clear_geometries_table():
    """Clear the geometries table."""
    conn = get_postgis_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM geometries")
        conn.commit()
    finally:
        conn.close()


def delete_geometries_table():
    """Delete the geometries table."""
    conn = get_postgis_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS geometries")
        conn.commit()
    finally:
        conn.close()


postgis_agent = Agent(
    "openai:gpt-4o",
    output_type=PostGISResult,
    system_prompt="""
    You are a helpful assistant that can help with PostGIS queries.
    The database has a table called geometries with the following schema:
    {geometry_table_schema}

    The geometries table has the following columns:
    - id: integer
    - name: string
    - geom: geometry

    For the user query, you need to return the SQL query to execute to construct
    the geojson geometry of the AOI related to the user query as a single geojson geometry.
    The SQL query should return the result in geojson format.
    You need to return the SQL query only, no other text.

    Use ::geography type for the buffer calculation using ST_Buffer. And then convert the result to ::geometry.

    Think step by step and write the SQL query. Some examples:
    - 100km within Mumbai: 100kms buffer around Mumbai
    - India north of Mumbai: India area with latitude more than Mumbai's highest latitude
        - Use ST_MakeBox2D to get full longitude width of India (from ST_XMin(india.geom) to ST_XMax(india.geom)) and latitude from ST_YMax of Mumbai to 90 (North Pole: highest latitude north of Mumbai)
        - Use ST_SetSRID around ST_MakeBox2D to set the SRID to 4326
        - Use ST_Intersection to get the area of India north of Mumbai's highest latitude
    - India east of Delhi: India area with longitude more than Delhi's highest longitude
        - Use ST_MakeBox2D to get full latitude height of India (from ST_YMin(india.geom) to ST_YMax(india.geom)) and longitude from ST_XMax of Delhi to 180 (Highest longitude east of Mumbai)
        - Use ST_SetSRID around ST_MakeBox2D to set the SRID to 4326
        - Use ST_Intersection to get the area of India east of Delhi
    - Area within 100kms to 200kms of Delhi - not nearer than 100kms but not further than 200kms:
        - 100kms buffer around Delhi
        - 200kms buffer around Delhi
        - Intersection of the two buffers
    - Area within 100kms of USA and Canada borders
        - Border is the intersection of USA and Canada geometries
        - 100kms buffer around the border
    """,
)


postgis_query_judgement_agent = Agent(
    "openai:gpt-4o",
    output_type=PostGISResult,
    system_prompt="""
    You are a helpful assistant that can help with PostGIS queries.

    The database has a table called geometries with the following schema:
    {geometry_table_schema}

    The geometries table has the following columns:
    - id: integer
    - name: string
    - geom: geometry

    We have to construct the geojson geometry of the AOI related to the user query as a single geojson geometry.

    Given the user query and the SQL query, you need to judge if the SQL query is correctly calculating the AOI.
    If the SQL query is correct, return the SQL query as is.
    If the SQL query is incorrect, you need to return the correct SQL query.
    You need to return the SQL query only, no other text.
    """,
)

if __name__ == "__main__":
    delete_geometries_table()
    create_geometries_table()
