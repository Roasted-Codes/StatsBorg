import pathlib
target = pathlib.Path("c:/Users/james/code/StatsBorg/_search_maps.py")
lines = []
def a(s): lines.append(s)

a("#!/usr/bin/env python3")
a("import os, struct")
a("")
a("SNAPSHOTS_DIR = "c:/Users/james/code/StatsBorg/_archive/research/snapshots"")
a("DATA_SECTION_VA = 0x46D6E0")
a("PGCR_DISPLAY_BASE = 0x56B900")

target.write_text(chr(10).join(lines), encoding="utf-8")
print("done")