#!/usr/bin/env python3
"""Compare RAM dumps for unique Halo 2 variant-name markers.

This is an offline research tool. It does not talk to xemu/QMP directly; feed it
64MB RAM dumps captured while a known custom variant is selected.
"""
import argparse
import json
import os
from collections import defaultdict
from typing import Dict, Iterable, List


DEFAULT_MARKERS = ["SBORG A1", "SBORG A2"]
CONTEXT_BYTES = 96


def _find_all(data: bytes, needle: bytes) -> List[int]:
    hits = []
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx < 0:
            return hits
        hits.append(idx)
        start = idx + 1


def _ascii_preview(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def _utf16_preview(data: bytes) -> str:
    return data.decode("utf-16-le", errors="ignore").replace("\x00", "").strip()


def _state_from_name(path: str) -> str:
    name = os.path.basename(path).lower()
    if "lobby" in name:
        return "lobby"
    if "pgcr" in name or "post" in name:
        return "pgcr"
    return "unknown"


def scan_dump(path: str, markers: Iterable[str]) -> Dict:
    with open(path, "rb") as handle:
        data = handle.read()

    other_encoded = []
    for marker in markers:
        other_encoded.extend([
            (marker, "ascii", marker.encode("ascii")),
            (marker, "utf16le", marker.encode("utf-16-le")),
        ])

    hits = []
    for marker in markers:
        patterns = {
            "ascii": marker.encode("ascii"),
            "utf16le": marker.encode("utf-16-le"),
        }
        for encoding, needle in patterns.items():
            for offset in _find_all(data, needle):
                start = max(0, offset - CONTEXT_BYTES)
                end = min(len(data), offset + len(needle) + CONTEXT_BYTES)
                context = data[start:end]
                other_markers = sorted({
                    other_marker
                    for other_marker, _other_encoding, other_needle in other_encoded
                    if other_marker != marker and context.find(other_needle) >= 0
                })
                hits.append({
                    "path": path,
                    "state": _state_from_name(path),
                    "marker": marker,
                    "encoding": encoding,
                    "offset": offset,
                    "offset_hex": f"0x{offset:08X}",
                    "context_start": start,
                    "context_ascii": _ascii_preview(context),
                    "context_utf16": _utf16_preview(context),
                    "contains_other_markers": other_markers,
                })

    return {
        "path": path,
        "state": _state_from_name(path),
        "size": len(data),
        "hits": hits,
    }


def summarize(results: List[Dict], markers: List[str]) -> Dict:
    offset_index = defaultdict(list)
    counts = defaultdict(int)
    for result in results:
        for hit in result["hits"]:
            key = (hit["state"], hit["encoding"], hit["offset"])
            offset_index[key].append(hit)
            counts[(result["path"], hit["marker"], hit["encoding"])] += 1

    same_offset_candidates = []
    marker_set = set(markers)
    for (state, encoding, offset), hits in sorted(offset_index.items()):
        present = {hit["marker"] for hit in hits}
        paths = sorted({hit["path"] for hit in hits})
        if present == marker_set:
            same_offset_candidates.append({
                "state": state,
                "encoding": encoding,
                "offset": offset,
                "offset_hex": f"0x{offset:08X}",
                "paths": paths,
                "dirty_context": any(hit["contains_other_markers"] for hit in hits),
                "contexts": [
                    {
                        "marker": hit["marker"],
                        "path": hit["path"],
                        "context_ascii": hit["context_ascii"],
                        "context_utf16": hit["context_utf16"],
                    }
                    for hit in hits
                ],
            })

    return {
        "counts": {
            f"{path}|{marker}|{encoding}": count
            for (path, marker, encoding), count in sorted(counts.items())
        },
        "same_offset_candidates": same_offset_candidates,
    }


def print_report(results: List[Dict], summary: Dict) -> None:
    print("RAM dump marker scan")
    print("=" * 72)
    for result in results:
        print(f"\n{result['path']} ({result['state']}, {result['size']} bytes)")
        grouped = defaultdict(list)
        for hit in result["hits"]:
            grouped[(hit["marker"], hit["encoding"])].append(hit)
        if not grouped:
            print("  no marker hits")
            continue
        for (marker, encoding), hits in sorted(grouped.items()):
            offsets = ", ".join(hit["offset_hex"] for hit in hits[:20])
            more = f" (+{len(hits) - 20} more)" if len(hits) > 20 else ""
            print(f"  {marker!r} {encoding}: {len(hits)} hit(s): {offsets}{more}")

    print("\nSame-offset candidates")
    print("=" * 72)
    candidates = summary["same_offset_candidates"]
    if not candidates:
        print("  none yet")
        return
    for candidate in candidates:
        dirty = " dirty-context" if candidate["dirty_context"] else ""
        print(
            f"  {candidate['state']} {candidate['encoding']} "
            f"{candidate['offset_hex']}{dirty}"
        )
        for context in candidate["contexts"][:4]:
            print(
                f"    {context['marker']}: "
                f"{context['context_ascii'][:160]!r}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan RAM dumps for unique variant-name markers."
    )
    parser.add_argument("dumps", nargs="+", help="RAM dump .bin files")
    parser.add_argument(
        "--marker",
        action="append",
        dest="markers",
        help="Marker to search for. Repeat for multiple markers.",
    )
    parser.add_argument("--json", dest="json_path", help="Write full JSON report")
    args = parser.parse_args()

    markers = args.markers or DEFAULT_MARKERS
    results = [scan_dump(path, markers) for path in args.dumps]
    summary = summarize(results, markers)
    print_report(results, summary)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump({"markers": markers, "results": results, "summary": summary}, handle, indent=2)
        print(f"\nWrote {args.json_path}")


if __name__ == "__main__":
    main()
