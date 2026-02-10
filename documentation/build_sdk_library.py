#!/usr/bin/env python3
"""
Build a clean, organized library from an extracted Xbox SDK CHM file.

Parses the HHC table of contents, strips boilerplate from HTML files,
converts encoding to UTF-8, organizes into directories, and generates
a navigable index.

Usage:
    python build_sdk_library.py
"""

import os
import re
import shutil
import html
from html.parser import HTMLParser

SRC_DIR = os.path.join(os.path.dirname(__file__), "XboxSDK_extracted")
OUT_DIR = os.path.join(os.path.dirname(__file__), "XboxSDK")
HHC_FILE = os.path.join(SRC_DIR, "XBox_sdk.hhc")

# ---------------------------------------------------------------------------
# Step 1: Parse the HHC table of contents into a tree
# ---------------------------------------------------------------------------

def parse_hhc(path):
    """Parse HHC file into a list of TOC nodes: [{name, file, children}, ...]"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Tokenize: extract meaningful tags/params in order of appearance
    # HHC structure: <UL> = descend into last node's children, </UL> = ascend
    # <OBJECT>...<param name="Name" value="X"/><param name="Local" value="Y"/>...</OBJECT> = node
    token_pattern = re.compile(
        r'<UL>|</UL>|'
        r'<param\s+name="Name"\s+value="([^"]*)"\s*/?>|'
        r'<param\s+name="Local"\s+value="([^"]*)"\s*/?>|'
        r'</OBJECT>',
        re.IGNORECASE
    )

    root = []
    stack = [root]  # stack of children-lists; stack[-1] is where new nodes go
    current_name = None
    current_file = None
    # Track whether we've seen the initial site-properties OBJECT (skip it)
    skip_first_object = True

    for m in token_pattern.finditer(content):
        token = m.group(0).strip()
        token_upper = token.upper()

        if token_upper == '<UL>':
            # Descend: new children list for the most recently added node
            parent_list = stack[-1]
            if parent_list:
                stack.append(parent_list[-1]["children"])
            else:
                # No parent node yet (e.g., the outermost <UL>)
                stack.append(root)

        elif token_upper == '</UL>':
            if len(stack) > 1:
                stack.pop()

        elif m.group(1) is not None:
            # Name param
            current_name = html.unescape(m.group(1)).strip()

        elif m.group(2) is not None:
            # Local param
            current_file = m.group(2).strip()

        elif token_upper == '</OBJECT>':
            if skip_first_object:
                skip_first_object = False
                current_name = None
                current_file = None
                continue

            if current_name is not None:
                node = {
                    "name": current_name,
                    "file": current_file,
                    "children": []
                }
                stack[-1].append(node)
            current_name = None
            current_file = None

    return root


def flatten_toc(nodes, path_prefix="", depth=0):
    """Flatten TOC tree into list of (file, dir_path, depth, name)."""
    result = []
    for node in nodes:
        result.append({
            "file": node.get("file"),
            "dir": path_prefix,
            "depth": depth,
            "name": node["name"],
        })
        if node.get("children"):
            # Build subdirectory name from node name
            subdir = sanitize_dirname(node["name"])
            child_path = os.path.join(path_prefix, subdir) if path_prefix else subdir
            # Only create subdirs for the first 2 levels to avoid crazy nesting
            if depth < 2:
                result.extend(flatten_toc(node["children"], child_path, depth + 1))
            else:
                # Deeper nodes go in the same directory
                result.extend(flatten_toc(node["children"], path_prefix, depth + 1))
    return result


def sanitize_dirname(name):
    """Convert a TOC section name to a valid directory name."""
    # Remove/replace problematic chars
    s = re.sub(r'[<>:"/\\|?*]', '', name)
    s = re.sub(r'\s+', '_', s.strip())
    s = s[:80]  # limit length
    return s


# ---------------------------------------------------------------------------
# Step 2: Clean HTML files — strip boilerplate, convert to UTF-8
# ---------------------------------------------------------------------------

# Patterns to strip from HTML
STRIP_PATTERNS = [
    # MSHelp XML blocks
    (r'<xml>.*?</xml>', re.DOTALL | re.IGNORECASE),
    # Script tags
    (r'<SCRIPT[^>]*>.*?</SCRIPT>', re.DOTALL | re.IGNORECASE),
    (r'<script[^>]*>.*?</script>', re.DOTALL | re.IGNORECASE),
    # Style blocks
    (r'<style[^>]*>.*?</style>', re.DOTALL | re.IGNORECASE),
    # DOCTYPE
    (r'<!DOCTYPE[^>]*>', re.IGNORECASE),
    # MSHelp namespace on html tag — simplify to just <html>
    (r'<html[^>]*>', re.IGNORECASE),
    # Meta charset tags (we'll add our own)
    (r'<META[^>]*charset[^>]*>', re.IGNORECASE),
    # Banner image tables (buttonbarshade + buttonbartable)
    (r'<TABLE\s+CLASS="buttonbarshade"[^>]*>.*?</TABLE>', re.DOTALL | re.IGNORECASE),
    (r'<TABLE\s+CLASS="buttonbartable"[^>]*>.*?</TABLE>', re.DOTALL | re.IGNORECASE),
    (r'<table\s+class="buttonbarshade"[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE),
    (r'<table\s+class="buttonbartable"[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE),
    # Footer div
    (r'<DIV\s+CLASS="footer"[^>]*>.*?</DIV>', re.DOTALL | re.IGNORECASE),
    (r'<div\s+class="footer"[^>]*>.*?</div>', re.DOTALL | re.IGNORECASE),
    # Banner header images (introduction page style with full table layout)
    # The big header table with images/introduction.jpg, header_xdk.jpg, header_xbox.jpg
    (r'<table[^>]*>\s*<tr>\s*<td[^>]*bgcolor="#000000"[^>]*>.*?</table>', re.DOTALL | re.IGNORECASE),
    # Standalone banner image references
    (r'<IMG\s+SRC="XDK_CHM_BANNER\.jpg"[^>]*>', re.IGNORECASE),
    # Comment boilerplate
    (r'<!--\*\*\*\*.*?\*\*\*\*-->', re.DOTALL),
]

# Image references to rewrite (point to images/ subdir relative to output root)
IMG_PATTERN = re.compile(r'(src|SRC)="(images/[^"]*)"', re.IGNORECASE)
IMG_PATTERN_BARE = re.compile(r'(src|SRC)="([^"/]*\.(gif|jpg|png))"', re.IGNORECASE)


def clean_html(content, relative_depth=0):
    """Strip boilerplate from HTML content and return cleaned UTF-8 HTML."""

    # Apply strip patterns
    for pattern, flags in STRIP_PATTERNS:
        content = re.sub(pattern, '', content, flags=flags)

    # Fix image paths: images not in images/ subdir
    # Files at top level reference images as "images/foo.jpg" or just "foo.jpg"
    # We need to adjust relative paths based on output directory depth
    if relative_depth > 0:
        prefix = "../" * relative_depth
        content = IMG_PATTERN.sub(lambda m: f'{m.group(1)}="{prefix}{m.group(2)}"', content)
        content = IMG_PATTERN_BARE.sub(lambda m: f'{m.group(1)}="{prefix}images/{m.group(2)}"', content)

    # Fix .htm links to be relative (they're all flat in the source)
    # We'll leave them as-is for now since we're flattening anyway

    # Add UTF-8 meta if there's a <head>
    if '<head>' in content.lower():
        content = re.sub(
            r'(<head[^>]*>)',
            r'\1\n<meta charset="UTF-8">',
            content,
            flags=re.IGNORECASE
        )

    # Clean up excessive blank lines
    content = re.sub(r'\n{4,}', '\n\n\n', content)

    # Add html tag back (simplified)
    if '<html' not in content.lower():
        content = '<html>\n' + content

    return content.strip() + '\n'


def read_file_any_encoding(path):
    """Read a file trying Windows-1252 first, then UTF-8."""
    for enc in ['windows-1252', 'utf-8', 'latin-1']:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    # Last resort
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


# ---------------------------------------------------------------------------
# Step 3: Build the organized output
# ---------------------------------------------------------------------------

def build_library():
    print(f"Parsing TOC from {HHC_FILE}...")
    toc = parse_hhc(HHC_FILE)

    print(f"  Found {count_nodes(toc)} TOC entries")

    # Build file-to-directory mapping from TOC
    flat = flatten_toc(toc)
    file_to_dir = {}
    file_to_entry = {}
    for entry in flat:
        if entry["file"]:
            fname = entry["file"].replace("/", os.sep)
            if fname not in file_to_dir:
                file_to_dir[fname] = entry["dir"]
                file_to_entry[fname] = entry

    # Collect all HTM/HTML files in source
    all_htm_files = []
    for f in os.listdir(SRC_DIR):
        if f.lower().endswith(('.htm', '.html')):
            all_htm_files.append(f)

    print(f"  {len(all_htm_files)} HTML files in source")
    print(f"  {len(file_to_dir)} mapped via TOC")

    # Create output directory
    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    # Copy images directory
    src_images = os.path.join(SRC_DIR, "images")
    dst_images = os.path.join(OUT_DIR, "images")
    if os.path.isdir(src_images):
        print(f"  Copying images directory...")
        shutil.copytree(src_images, dst_images)

    # Copy any top-level images (banner etc)
    for f in os.listdir(SRC_DIR):
        if f.lower().endswith(('.jpg', '.gif', '.png')):
            src = os.path.join(SRC_DIR, f)
            # Put in images/ for cleanliness
            dst = os.path.join(dst_images, f)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

    # Process each HTML file
    processed = 0
    orphans = 0
    errors = 0
    created_dirs = set()

    for htm_file in sorted(all_htm_files):
        src_path = os.path.join(SRC_DIR, htm_file)

        # Determine output subdirectory
        subdir = file_to_dir.get(htm_file, "_uncategorized")

        # Create output directory
        out_subdir = os.path.join(OUT_DIR, subdir) if subdir else OUT_DIR
        if out_subdir not in created_dirs:
            os.makedirs(out_subdir, exist_ok=True)
            created_dirs.add(out_subdir)

        # Calculate relative depth for image path fixing
        if subdir:
            depth = subdir.count(os.sep) + 1
        else:
            depth = 0

        try:
            content = read_file_any_encoding(src_path)
            cleaned = clean_html(content, depth)

            out_path = os.path.join(out_subdir, htm_file)
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(cleaned)

            processed += 1
            if subdir == "_uncategorized":
                orphans += 1
        except Exception as e:
            print(f"  ERROR processing {htm_file}: {e}")
            errors += 1

    print(f"\n  Processed: {processed} files ({orphans} uncategorized)")
    if errors:
        print(f"  Errors: {errors}")

    # Generate index
    print("  Generating INDEX.md...")
    generate_index(toc)

    print(f"\nDone! Output in {OUT_DIR}")


def count_nodes(nodes):
    count = len(nodes)
    for n in nodes:
        count += count_nodes(n.get("children", []))
    return count


def generate_index(toc):
    """Generate a navigable INDEX.md from the TOC tree."""
    lines = ["# Xbox SDK Documentation\n"]
    lines.append("Extracted and cleaned from XboxSDK.chm\n")
    lines.append("---\n")

    flat = flatten_toc(toc)

    def write_toc(nodes, indent=0, parent_dir=""):
        for node in nodes:
            prefix = "  " * indent
            name = node["name"]
            filename = node.get("file", "")

            if filename:
                # Build the path where we placed this file
                subdir = ""
                # Reconstruct from flatten logic
                entry_dir = _find_dir_for_file(filename, flat)
                if entry_dir:
                    link = f"{entry_dir}/{filename}".replace("\\", "/")
                else:
                    link = filename
                lines.append(f"{prefix}- [{name}]({link})")
            else:
                lines.append(f"{prefix}- **{name}**")

            if node.get("children"):
                write_toc(node["children"], indent + 1, parent_dir)

    write_toc(toc)

    index_path = os.path.join(OUT_DIR, "INDEX.md")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _find_dir_for_file(filename, flat_entries):
    for entry in flat_entries:
        if entry["file"] == filename:
            return entry["dir"]
    return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    build_library()
