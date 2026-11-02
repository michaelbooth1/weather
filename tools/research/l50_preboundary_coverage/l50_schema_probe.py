"""L50: print parquet column names only (metadata; no values read)."""
import sys, pyarrow.parquet as pq
for p in sys.argv[1:]:
    s = pq.read_schema(p)
    md = pq.read_metadata(p)
    print(p.split("artifact_family=")[-1], "rows=", md.num_rows)
    print("  ", [f"{f.name}:{f.type}" for f in s][:200])
