"""
One-time migration: add vec_paragraphs virtual table to foguangpedia.db.

Run once locally, then push the updated DB to Railway:
    python migrate_vec.py

The existing `embeddings` table (para_id PK, passage_id, vector BLOB) is
left intact — it is still used for per-article paragraph scoring.
"""
import struct
import sys
from pathlib import Path

try:
    import sqlite_vec
    from sqlite_vec import serialize_float32
except ImportError:
    print("ERROR: sqlite-vec not installed.  Run:  pip install sqlite-vec")
    sys.exit(1)

import sqlite3

DB_PATH = Path(__file__).parent / "data" / "foguangpedia.db"
if not DB_PATH.exists():
    print(f"ERROR: {DB_PATH} not found")
    sys.exit(1)

print(f"Opening {DB_PATH} ({DB_PATH.stat().st_size / 1e6:.1f} MB) ...")
conn = sqlite3.connect(str(DB_PATH))
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)

# Drop and recreate (idempotent)
try:
    conn.execute("DROP TABLE IF EXISTS vec_paragraphs")
    conn.commit()
    print("Dropped existing vec_paragraphs (if any).")
except Exception as e:
    print(f"Warning during drop: {e}")

print("Creating vec_paragraphs virtual table ...")
conn.execute("CREATE VIRTUAL TABLE vec_paragraphs USING vec0(embedding float[1024])")

print("Loading paragraph blobs from embeddings table ...")
rows = conn.execute(
    "SELECT para_id, vector FROM embeddings ORDER BY para_id"
).fetchall()
print(f"Found {len(rows):,} paragraphs. Inserting ...")

BATCH = 500
batch: list = []
for i, (para_id, blob) in enumerate(rows):
    floats = struct.unpack(f"{len(blob) // 4}f", blob)
    batch.append((para_id, serialize_float32(floats)))
    if len(batch) == BATCH:
        conn.executemany(
            "INSERT INTO vec_paragraphs(rowid, embedding) VALUES (?, ?)", batch
        )
        batch = []
        print(f"  {i + 1:,} / {len(rows):,}", end="\r")

if batch:
    conn.executemany(
        "INSERT INTO vec_paragraphs(rowid, embedding) VALUES (?, ?)", batch
    )

conn.commit()

final = conn.execute("SELECT COUNT(*) FROM vec_paragraphs").fetchone()[0]
print(f"\nDone. vec_paragraphs: {final:,} rows.")

conn.close()
new_size = DB_PATH.stat().st_size / 1e6
print(f"foguangpedia.db now {new_size:.1f} MB.")
