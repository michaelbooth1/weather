"""L50: NBP-sized blobs in WS CAS; read first 400 bytes for the issue header (input bytes only)."""
import sys, os, re, time
from collections import defaultdict
root = os.path.join(sys.argv[1], "sha256"); t0 = time.time()
rows = []
for sub in os.scandir(root):
    if not sub.is_dir(): continue
    for f in os.scandir(sub.path):
        if f.name.endswith(".blob"):
            st = f.stat()
            if st.st_size > 20_000_000:
                with open(f.path, "rb") as h: head = h.read(400).decode("latin-1", "replace")
                m = re.search(r"NBP\s+GUIDANCE\s+(\d+)/(\d+)/(\d{4})\s+(\d{4})\s+UTC", head)
                rows.append((time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)), st.st_size,
                             f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}T{m.group(4)[:2]}Z" if m else "?" + head[:60].replace("\n", " ")))
print("big blobs", len(rows), "secs", round(time.time() - t0, 1))
by = defaultdict(list)
for mt, sz, cyc in sorted(rows, key=lambda r: r[2]):
    by[cyc[:10]].append(cyc[11:])
for d in sorted(by): print(d, " ".join(sorted(set(by[d]))))
