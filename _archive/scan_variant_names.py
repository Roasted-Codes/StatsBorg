#!/usr/bin/env python3
"""Scan .data section snapshots for Halo 2 gametype variant name strings."""
import os, struct, sys
from collections import defaultdict

SNAPSHOTS_DIR = "c:/Users/james/code/StatsBorg/_archive/research/snapshots"
DATA_SECTION_VA = 0x46D6E0

EXPECTED_GAMETYPE = {
    "ctf": 1, "slayer": 2, "oddball": 3, "koth": 4,
    "juggernaut": 7, "territories": 8, "assault": 9,
}

SEARCH_STRINGS = [
    "Team Slayer", "Slayer", "MLG", "Rumble", "FFA",
    "Team BRs", "Snipers", "Team Snipers", "Swat", "SWAT",
    "CTF", "Multi Flag", "One Flag", "Flag", "Capture",
    "Oddball", "Ball",
    "King", "KOTH", "Crazy King", "Team King",
    "Juggernaut",
    "Territories", "Territory",
    "Assault", "One Bomb", "Multi Bomb", "Bomb",
    "Zombies", "Infection",
    "scenarios",
]


def read_utf16le_string(data, offset, max_chars=64):
    result = []
    for i in range(max_chars):
        pos = offset + i * 2
        if pos + 2 > len(data):
            break
        char_val = struct.unpack_from('<H', data, pos)[0]
        if char_val == 0:
            break
        result.append(chr(char_val))
    return ''.join(result)


def read_ascii_string(data, offset, max_len=256):
    result = []
    for i in range(max_len):
        pos = offset + i
        if pos >= len(data):
            break
        byte = data[pos]
        if byte == 0:
            break
        if 0x20 <= byte <= 0x7E:
            result.append(chr(byte))
        else:
            break
    return ''.join(result)


def is_printable_utf16le(data, offset, min_chars=2):
    count = 0
    for i in range(64):
        pos = offset + i * 2
        if pos + 2 > len(data):
            return count >= min_chars
        char_val = struct.unpack_from('<H', data, pos)[0]
        if char_val == 0:
            return count >= min_chars
        if not (0x20 <= char_val <= 0x7E):
            return False
        count += 1
    return count >= min_chars


def search_utf16le(data, search_str):
    encoded = search_str.encode('utf-16-le')
    results = []
    start = 0
    while True:
        idx = data.find(encoded, start)
        if idx == -1:
            break
        results.append(idx)
        start = idx + 2
    return results


def check_variant_info_struct(data, name_offset, expected_gametype_id):
    result = {}
    gt_offset = name_offset + 0x40
    if gt_offset + 4 <= len(data):
        gt_byte = data[gt_offset]
        gt_val = struct.unpack_from('<I', data, gt_offset)[0]
        result['gametype_at_0x40'] = gt_byte
        result['gametype_i32_at_0x40'] = gt_val
        result['gametype_match'] = (gt_byte == expected_gametype_id)
    sc_offset = name_offset + 0x130
    if sc_offset + 20 <= len(data):
        sc_str = read_ascii_string(data, sc_offset)
        result['scenario_at_0x130'] = sc_str
        result['scenario_match'] = sc_str.startswith("scenarios")
    for delta in [0x42, 0x44, 0x48, 0x80, 0xC0, 0x100]:
        check_offset = name_offset + delta
        if check_offset + 1 <= len(data):
            val = data[check_offset]
            if val == expected_gametype_id:
                result['gametype_byte_at_+0x%X' % delta] = val
    for delta in [0x100, 0x120, 0x140, 0x150, 0x180, 0x200]:
        check_offset = name_offset + delta
        if check_offset + 20 <= len(data):
            sc_str = read_ascii_string(data, check_offset)
            if sc_str.startswith("scenarios"):
                result['scenario_at_+0x%X' % delta] = sc_str
    return result
