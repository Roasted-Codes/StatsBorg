#!/usr/bin/env python3
"""
Halo 2 Stats Reader - Cross-platform post-game stats via XBDM/QMP

Reads Halo 2 post-game statistics from Xbox/Xemu via XBDM (port 731)
or QMP (QEMU Machine Protocol).

Usage:
    # Read post-game stats (default: tries PGCR Display first, falls back to PCR)
    python halo2_stats.py --host 172.20.0.51

    # Watch for game completions and auto-save history
    python halo2_stats.py --host 172.20.0.51 --watch

    # JSON output
    python halo2_stats.py --host 172.20.0.51 --json

    # QMP mode (reads same PGCR data via QEMU Machine Protocol)
    python halo2_stats.py --host 172.20.0.10 --qmp 4444
"""

import argparse
import hashlib
import json
import os
import re
import select
import signal
import struct
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from xbdm_client import XBDMClient, XBDMNotificationListener
from halo2_structs import (
    PCRPlayerStats,
    GameType,
    GameTeam,
    GAMETYPE_NAMES,
    TeamStats,
    calculate_pcr_address,
    calculate_pgcr_display_address,
    calculate_team_data_address,
    calculate_pgcr_display_team_address,
    get_address,
    decode_medals,
    PCR_PLAYER_SIZE,
    PGCR_DISPLAY_SIZE,
    TEAM_DATA_STRIDE,
    MAX_TEAMS,
    PGCR_BREAKPOINT_ADDR,
    PGCR_DISPLAY_HEADER,
    PGCR_DISPLAY_HEADER_SIZE,
    PGCR_DISPLAY_GAMETYPE_ADDR,
)
from addresses import DISCOVERED_ADDRESSES


def _is_valid_player_name(name_bytes: bytes) -> bool:
    """
    Check if raw UTF-16LE name bytes represent a valid Xbox gamertag.

    Rejects garbage/uninitialized memory by checking:
    - At least 1 character
    - All characters are printable ASCII or common Unicode (0x20-0x7E range)
    - First null terminator within reasonable range
    """
    try:
        name = name_bytes.decode("utf-16-le").rstrip("\x00")
    except (UnicodeDecodeError, ValueError):
        return False

    if not name or len(name) < 1:
        return False

    return all(0x20 <= ord(c) <= 0x7E for c in name)


class Halo2StatsReader:
    """Reads Halo 2 statistics from Xbox memory via XBDM or QMP."""

    MAX_PLAYERS = 16

    # .data section VA start — used for linear physical reads that bypass
    # stale page table entries (see _read_via_data_section_offset)
    _DATA_SECTION_VA = 0x46D6E0

    # variant_info: XBE-relative offset expressed as pseudo-VA
    # OffVariantInfo = 0x35AD0EC, confirmed working across xemu sessions
    _XBE_BASE_VA = 0x10000
    VARIANT_INFO_VA = _XBE_BASE_VA + 0x35AD0EC  # 0x35BD0EC
    VARIANT_INFO_SIZE = 0x230  # enough to reach +0x130 + 256 bytes

    # Fixed live map metadata block (validated across controlled RAM snapshots)
    MAP_DISPLAY_NAME_ADDR = 0x01917000
    MAP_DESCRIPTION_ADDR = 0x01917008

    MAP_NAMES = {
        "ascension": "Ascension",
        "backwash": "Backwash",
        "beavercreek": "Beaver Creek",
        "burial_mounds": "Burial Mounds",
        "coagulation": "Coagulation",
        "colossus": "Colossus",
        "containment": "Containment",
        "cyclotron": "Ivory Tower",
        "deltatap": "Sanctuary",
        "derelict": "Desolation",
        "dune": "Relic",
        "elongation": "Elongation",
        "foundation": "Foundation",
        "gemini": "Gemini",
        "headlong": "Headlong",
        "highplains": "Tombstone",
        "highplains2": "Tombstone",
        "lockout": "Lockout",
        "midship": "Midship",
        "needle": "Uplift",
        "street_sweeper": "District",
        "triplicate": "Terminal",
        "turf": "Turf",
        "warlock": "Warlock",
        "waterworks": "Waterworks",
        "zanzibar": "Zanzibar",
    }

    DISPLAY_TO_INTERNAL = {
        "Ascension": "ascension",
        "Backwash": "backwash",
        "Beaver Creek": "beavercreek",
        "Burial Mounds": "burial_mounds",
        "Coagulation": "coagulation",
        "Colossus": "colossus",
        "Containment": "containment",
        "Desolation": "derelict",
        "District": "street_sweeper",
        "Elongation": "elongation",
        "Foundation": "foundation",
        "Gemini": "gemini",
        "Headlong": "headlong",
        "Ivory Tower": "cyclotron",
        "Lockout": "lockout",
        "Midship": "midship",
        "Relic": "dune",
        "Sanctuary": "deltatap",
        "Terminal": "triplicate",
        "Tombstone": "highplains2",
        "Turf": "turf",
        "Uplift": "needle",
        "Warlock": "warlock",
        "Waterworks": "waterworks",
        "Zanzibar": "zanzibar",
    }

    KNOWN_DISPLAY_NAMES = set(DISPLAY_TO_INTERNAL.keys())

    def __init__(self, client: XBDMClient, verbose: bool = False):
        self.client = client
        self.verbose = verbose
        self._last_error: Optional[str] = None
        self._variant_info = None  # Reserved for future use

    def log(self, message: str):
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(f"[DEBUG] {message}")

    def _merge_variant_info(
        self,
        primary: Optional[Dict[str, str]],
        fallback: Optional[Dict[str, str]],
    ) -> Optional[Dict[str, str]]:
        if not primary and not fallback:
            return None

        result = dict(primary or {})
        for key in ("map", "variant", "scenario", "description"):
            if not result.get(key) and fallback and fallback.get(key):
                result[key] = fallback[key]
        return result

    def _scan_bytes_for_map(self, data: bytes) -> Optional[Dict[str, str]]:
        """
        Look for known map internal names or display names in a raw memory block.
        Searches both ASCII-ish and UTF-16LE-ish views.
        """
        if not data:
            return None

        ascii_view = "".join(chr(b) if 0x20 <= b <= 0x7E else " " for b in data).lower()
        try:
            utf16_view = data.decode("utf-16-le", errors="ignore").lower()
        except Exception:
            utf16_view = ""

        hits = []
        for internal, display in self.MAP_NAMES.items():
            disp = display.lower()
            score = 0
            if internal in ascii_view:
                score += 3
            if internal in utf16_view:
                score += 3
            if disp in ascii_view:
                score += 1
            if disp in utf16_view:
                score += 1
            if score > 0:
                hits.append((score, internal, display))

        if not hits:
            return None

        hits.sort(reverse=True)
        _, internal, display = hits[0]

        if self.verbose:
            print(f'[DEBUG] dump-scan map hit: internal="{internal}" display="{display}"')

        return {
            "map": display,
            "scenario": internal,
        }

    def infer_map_from_dump_regions(self) -> Optional[Dict[str, str]]:
        """
        Fallback: scan the same PGCR regions we already dump to text files.
        This will not always work, but when a map string is present here,
        it gives us something usable instead of nothing.
        """
        regions = []

        # PGCR header
        regions.append((PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE))

        # PGCR display players
        for i in range(self.MAX_PLAYERS):
            regions.append((calculate_pgcr_display_address(i), PCR_PLAYER_SIZE))

        # PGCR display teams
        for i in range(MAX_TEAMS):
            regions.append((calculate_pgcr_display_team_address(i), TEAM_DATA_STRIDE))

        # PCR players fallback
        for i in range(self.MAX_PLAYERS):
            regions.append((calculate_pcr_address(i), PCR_PLAYER_SIZE))

        # PCR teams fallback
        for i in range(MAX_TEAMS):
            regions.append((calculate_team_data_address(i), TEAM_DATA_STRIDE))

        best = None
        for addr, size in regions:
            try:
                data = self.client.read_memory(addr, size)
            except Exception:
                data = None

            if not data:
                continue

            found = self._scan_bytes_for_map(data)
            if found:
                best = found
                break

        return best

    def _read_ascii_z(self, addr: int, max_len: int = 256, physical: bool = False) -> str:
        try:
            if physical and hasattr(self.client, "_read_physical"):
                data = self.client._read_physical(addr, max_len)
            else:
                data = self.client.read_memory(addr, max_len)
        except Exception:
            return ""

        if not data:
            return ""

        return data.split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()

    def read_map_name_from_metadata(self) -> Optional[Dict[str, str]]:
        """
        Primary map-name source. Controlled RAM snapshots show:
          0x01917000 = current map display name
          0x01917008 = current map description

        These are physical offsets in the RAM image, so in QMP mode we read
        them via _read_physical(). As a fallback, try direct read_memory().
        """
        display_name = self._read_ascii_z(self.MAP_DISPLAY_NAME_ADDR, 64, physical=True)
        if self.verbose:
            print(display_name + " < map1")

        description = self._read_ascii_z(self.MAP_DESCRIPTION_ADDR, 192, physical=True)

        # Fallback for bridges/modes where direct read_memory happens to work
        if not display_name:
            display_name = self._read_ascii_z(self.MAP_DISPLAY_NAME_ADDR, 64, physical=False)
            if self.verbose:
                print(display_name + " < map2")

        if not description:
            description = self._read_ascii_z(self.MAP_DESCRIPTION_ADDR, 192, physical=False)

        if self.verbose:
            print(f'[DEBUG] metadata map="{display_name}" desc="{description[:80]}"')

        if display_name not in self.KNOWN_DISPLAY_NAMES:
            return None

        # Basic sanity check: real metadata block has a non-trivial description
        if not description or len(description) < 12:
            return None

        internal = self.DISPLAY_TO_INTERNAL.get(display_name, "")
        return {
            "map": display_name,
            "scenario": internal,
            "description": description,
        }

    def _friendly_map_name(self, scenario: str) -> str:
        if not scenario:
            return ""
        internal = scenario.replace("\\", "/").split("/")[-1].strip().lower()
        return self.MAP_NAMES.get(internal, internal[:1].upper() + internal[1:])

    def _looks_reasonable_variant(self, s: str) -> bool:
        return bool(s) and len(s) <= 32 and all(0x20 <= ord(c) <= 0x7E for c in s)

    def _looks_reasonable_scenario(self, s: str) -> bool:
        if not s:
            return False
        if "\\" in s or "/" in s:
            return True
        return s.lower() in self.MAP_NAMES

    def _parse_variant_block(self, data: bytes) -> Optional[Dict[str, str]]:
        """
        Parse the C# struct layout:
          +0x00 wchar[16] variant name
          +0x40 byte gametype
          +0x130 char[256] scenario/content path
        """
        if not data or len(data) < self.VARIANT_INFO_SIZE:
            return None

        try:
            variant_name = data[0x00:0x20].decode("utf-16-le", errors="ignore").rstrip("\x00").strip()
        except Exception:
            variant_name = ""

        try:
            raw_scenario = (
                data[0x130:0x230]
                .split(b"\x00", 1)[0]
                .decode("ascii", errors="ignore")
                .strip()
            )
        except Exception:
            raw_scenario = ""

        map_name = self._friendly_map_name(raw_scenario)

        if self.verbose:
            print(f'[DEBUG] variant="{variant_name}" scenario="{raw_scenario}" map="{map_name}"')

        # Reject obvious garbage
        if variant_name and not self._looks_reasonable_variant(variant_name):
            variant_name = ""

        if raw_scenario and not self._looks_reasonable_scenario(raw_scenario):
            raw_scenario = ""
            map_name = ""

        if variant_name or raw_scenario or map_name:
            result = {
                "variant": variant_name,
                "scenario": raw_scenario,
            }
            if map_name:
                result["map"] = map_name
            return result

        return None

    def _read_via_data_section_offset(self, va: int, length: int = 4) -> Optional[bytes]:
        """
        Read a .data section address via linear physical offset.

        Xbox page table entries for individual pages within .data can be stale/wrong
        between games, but the section is physically contiguous.

        Translates the .data section START VA to physical, then adds the fixed offset
        to reach the target address.

        Only works for QMP clients that expose translate_va and _read_physical.
        """
        if not hasattr(self.client, "translate_va") or not hasattr(self.client, "_read_physical"):
            return None

        phys_start = self.client.translate_va(self._DATA_SECTION_VA)
        if phys_start is None:
            return None

        offset = va - self._DATA_SECTION_VA
        if offset < 0:
            return None

        target_physical = phys_start + offset
        if target_physical + length > 0x4000000:  # 64MB Xbox RAM boundary
            self.log(f"_read_via_data_section_offset: 0x{target_physical:X} exceeds 64MB")
            return None

        return self.client._read_physical(target_physical, length)

    def read_variant_info_qmp(self) -> Optional[Dict[str, str]]:
        """
        Read variant/map using the pseudo-VA + .data linear-offset approach.
        This is the primary path for QMP mode.
        """
        data = self._read_via_data_section_offset(self.VARIANT_INFO_VA, self.VARIANT_INFO_SIZE)
        if not data or len(data) < self.VARIANT_INFO_SIZE:
            self.log(f"variant_info QMP read failed (got {len(data) if data else 0} bytes)")
            return None
        return self._parse_variant_block(data)

    def read_variant_info_direct(self) -> Optional[Dict[str, str]]:
        """
        Fallback direct read. This may work in some bridges, but QMP should stay
        primary for variant/map extraction.
        """
        try:
            data = self.client.read_memory(self.VARIANT_INFO_VA, self.VARIANT_INFO_SIZE)
        except Exception:
            return None
        return self._parse_variant_block(data)

    def get_variant_info_any(self) -> Optional[Dict[str, str]]:
        """
        Priority:
          1. fixed live map metadata block
          2. variant-info QMP reader
          3. variant-info direct reader
        """
        vinfo = self.read_map_name_from_metadata()
        if vinfo:
            return vinfo

        vinfo = self.read_variant_info_qmp()
        if vinfo:
            return vinfo

        return self.read_variant_info_direct()

    def read_player(self, player_index: int) -> Optional[PCRPlayerStats]:
        """Read stats for a single player using PCR structure."""
        addr = calculate_pcr_address(player_index)
        self.log(f"Reading player {player_index} from 0x{addr:08X}")

        data = self.client.read_memory(addr, PCR_PLAYER_SIZE)
        if not data:
            self._last_error = f"Failed to read player {player_index} at 0x{addr:08X}"
            return None

        try:
            stats = PCRPlayerStats.from_bytes(data)
            if stats.player_name:
                self.log(f" Found: {stats.player_name} - K:{stats.kills} D:{stats.deaths}")
            return stats
        except Exception as e:
            self._last_error = f"Failed to parse player {player_index}: {e}"
            return None

    def read_all_players(self) -> List[PCRPlayerStats]:
        """Read stats for all 16 player slots."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_player(i)
            if player:
                players.append(player)
        return players

    def read_active_players(self) -> List[PCRPlayerStats]:
        """Read stats only for players with valid (printable ASCII) names."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_player(i)
            if player and player.player_name.strip():
                if all(0x20 <= ord(c) <= 0x7E for c in player.player_name):
                    players.append(player)
        return players

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get a complete snapshot of current game state.
        Returns a dictionary ready for JSON serialization.
        """
        players = self.read_active_players()
        vinfo = self.get_variant_info_any()
        dump_vinfo = self.read_map_name_from_metadata()
        vinfo = self._merge_variant_info(vinfo, dump_vinfo)

        result = {
            "timestamp": datetime.now().isoformat(),
            "player_count": len(players),
            "players": [p.to_dict() for p in players],
        }

        if vinfo:
            if vinfo.get("map"):
                result["map"] = vinfo["map"]
            if vinfo.get("variant"):
                result["variant"] = vinfo["variant"]
            if vinfo.get("scenario"):
                result["scenario"] = vinfo["scenario"]
            if vinfo.get("description"):
                result["map_description"] = vinfo["description"]

        return result

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # =========================================================================
    # PCR Probing and PGCR Display Methods
    # =========================================================================

    def probe_pcr_populated(self) -> bool:
        """
        Lightweight check: is the PCR populated with game data?
        Reads only the first player's name field (32 bytes at 0x55CAF0).
        """
        addr = calculate_pcr_address(0)
        data = self.client.read_memory(addr, 32)
        if not data:
            return False
        return _is_valid_player_name(data)

    def read_all_players_indexed(self) -> List[Optional[PCRPlayerStats]]:
        """Read all 16 player slots, preserving slot indices (None for empty)."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_player(i)
            if player and player.player_name.strip() and all(0x20 <= ord(c) <= 0x7E for c in player.player_name):
                players.append(player)
            else:
                players.append(None)
        return players

    def read_pgcr_display_player(self, player_index: int) -> Optional[PCRPlayerStats]:
        """
        Read PGCR display stats for a single player.
        """
        addr = calculate_pgcr_display_address(player_index)
        self.log(f"Reading PGCR display player {player_index} from 0x{addr:08X}")

        data = self.client.read_memory(addr, PCR_PLAYER_SIZE)
        if not data:
            return None

        try:
            stats = PCRPlayerStats.from_bytes(data)
            if stats.player_name:
                return stats
            return None
        except Exception as e:
            self.log(f"Failed to parse PGCR display {player_index}: {e}")
            return None

    def read_active_pgcr_display(self) -> List[PCRPlayerStats]:
        """Read PGCR display stats for all players with valid (printable) names."""
        players = []
        for i in range(self.MAX_PLAYERS):
            player = self.read_pgcr_display_player(i)
            if player and player.player_name.strip():
                if all(0x20 <= ord(c) <= 0x7E for c in player.player_name):
                    players.append(player)
        return players

    def probe_pgcr_display_populated(self) -> bool:
        """
        Lightweight check: is the PGCR display populated with real data?
        """
        addr = calculate_pgcr_display_address(0)
        data = self.client.read_memory(addr, 32)
        if not data:
            return False
        return _is_valid_player_name(data)

    # =========================================================================
    # Gametype and Team Methods
    # =========================================================================

    def read_pgcr_header(self) -> Optional[bytes]:
        """Read the full PGCR Display header."""
        addr = PGCR_DISPLAY_HEADER
        self.log(f"Reading PGCR header from 0x{addr:08X} ({PGCR_DISPLAY_HEADER_SIZE} bytes)")

        data = self.client.read_memory(addr, PGCR_DISPLAY_HEADER_SIZE)
        if not data or len(data) < PGCR_DISPLAY_HEADER_SIZE:
            return None
        return data

    def read_gametype(self) -> Optional[GameType]:
        """
        Read gametype enum from PGCR Display header at 0x56B984.
        WARNING: This address can be stale on docker-bridged-xemu.
        """
        addr = PGCR_DISPLAY_GAMETYPE_ADDR
        self.log(f"Reading gametype from 0x{addr:08X}")

        data = self.client.read_memory(addr, 4)
        if not data or len(data) < 4:
            return None

        value = struct.unpack("<I", data)[0]
        try:
            gt = GameType(value)
            return gt if gt != GameType.NONE else None
        except ValueError:
            self.log(f"Unknown gametype value: {value}")
            return None

    def read_gametype_discovered(self) -> Optional[GameType]:
        """
        Read gametype from discovered address 0x52ED24.
        Uses linear physical offset from .data start first, then falls back to direct VA read.
        """
        addr = DISCOVERED_ADDRESSES.get("gametype_confirmed", 0)
        if not addr:
            return None

        data = self._read_via_data_section_offset(addr)
        if not data or len(data) < 4:
            try:
                data = self.client.read_memory(addr, 4)
            except Exception:
                data = None

        if not data or len(data) < 4:
            return None

        value = struct.unpack("<I", data)[0]
        try:
            gt = GameType(value)
            if gt != GameType.NONE:
                self.log(f"Gametype from 0x{addr:08X}: {value} -> {gt.name}")
                return gt
        except ValueError:
            self.log(f"Unknown gametype value at 0x{addr:08X}: {value}")

        return None

    def read_teams(self) -> List[TeamStats]:
        """Read team data, trying PGCR Display location first then PCR fallback."""
        teams = self._read_teams_from(calculate_pgcr_display_team_address)
        if teams:
            return teams
        return self._read_teams_from(calculate_team_data_address)

    def _read_teams_from(self, addr_func) -> List[TeamStats]:
        """Read team data from a given address calculator."""
        teams = []
        for i in range(MAX_TEAMS):
            addr = addr_func(i)
            data = self.client.read_memory(addr, TEAM_DATA_STRIDE)
            if not data:
                continue

            try:
                team = TeamStats.from_bytes(data, index=i)
                if team.name.strip() and all(0x20 <= ord(c) <= 0x7E for c in team.name):
                    teams.append(team)
            except Exception as e:
                self.log(f"Failed to parse team {i}: {e}")

        return teams


def format_player_summary(player: PCRPlayerStats) -> str:
    """Format a single player's stats as a readable line."""
    name = player.player_name[:16].ljust(16)
    k = player.kills
    d = player.deaths
    a = player.assists
    kd = k / max(d, 1)
    return f"{name} K:{k:3d} D:{d:3d} A:{a:3d} K/D:{kd:.2f}"


def print_scoreboard(players: List[PCRPlayerStats]):
    """Print a formatted scoreboard to console."""
    if not players:
        print("No players found in game.")
        return

    print("\n" + "=" * 60)
    print(" HALO 2 STATS")
    print("=" * 60)

    sorted_players = sorted(players, key=lambda p: p.kills, reverse=True)
    for i, player in enumerate(sorted_players, 1):
        print(f" {i:2d}. {format_player_summary(player)}")

    print("=" * 60)
    print()


def print_scoreboard_rich(
    players: List[PCRPlayerStats],
    gametype: Optional[str] = None,
    all_players: Optional[List[Optional[PCRPlayerStats]]] = None,
    teams: Optional[List[TeamStats]] = None,
):
    """Print rich scoreboard with all available fields."""
    if not players:
        print("No players found in game.")
        return

    print("\n" + "=" * 90)
    title = " HALO 2 POST-GAME CARNAGE REPORT "
    if gametype:
        title += f"({gametype.upper()})"
    print(title)
    print("=" * 90)

    if teams:
        print("Teams:")
        for t in sorted(teams, key=lambda x: (x.place, x.index)):
            score_disp = t.score_string or str(t.score)
            place_disp = t.place_string or str(t.place + 1)
            print(f" {t.name:<16} score:{score_disp:<6} place:{place_disp}")
        print("-" * 90)

    header = ["Name", "Score", "K", "D", "A", "KD", "Rank", "Medals", "Acc%"]
    if gametype:
        header.extend(["GT0", "GT1"])

    print(
        f"{header[0]:<16} {header[1]:>6} {header[2]:>4} {header[3]:>4} {header[4]:>4} "
        f"{header[5]:>6} {header[6]:>5} {header[7]:>7} {header[8]:>6}"
        + (f" {header[9]:>6} {header[10]:>6}" if gametype else "")
    )
    print("-" * 90)

    sorted_players = sorted(players, key=lambda p: (p.place, -p.kills, p.player_name))
    for p in sorted_players:
        acc = round((p.shots_hit / p.total_shots * 100), 1) if p.total_shots > 0 else 0.0
        line = (
            f"{p.player_name[:16]:<16} {p.score_string[:6]:>6} {p.kills:>4} {p.deaths:>4} {p.assists:>4} "
            f"{(p.kills / max(p.deaths, 1)):>6.2f} {p.rank:>5} {p.medals_earned:>7} {acc:>6.1f}"
        )
        if gametype:
            line += f" {p.gametype_value0:>6} {p.gametype_value1:>6}"
        print(line)

    print("=" * 90)
    print()


def print_pgcr_report(
    players: List[PCRPlayerStats],
    teams: Optional[List[TeamStats]] = None,
    gametype: Optional[str] = None,
):
    """Print a PGCR-like report that mirrors the in-game layout more closely."""
    if not players:
        print("No players found in game.")
        return

    print("\nPGCR")
    print("=" * 90)

    if teams:
        print("TEAMS")
        for t in sorted(teams, key=lambda x: (x.place, x.index)):
            score_disp = t.score_string or str(t.score)
            place_disp = t.place_string or str(t.place + 1)
            print(f" {t.name:<16} {score_disp:<8} {place_disp}")
        print()

    sorted_players = sorted(players, key=lambda p: (p.place, -p.kills, p.player_name))
    for p in sorted_players:
        print(
            f"{p.place_string or str(p.place + 1):>4} "
            f"{p.player_name:<16} "
            f"Score:{p.score_string:<6} "
            f"K:{p.kills:<3} D:{p.deaths:<3} A:{p.assists:<3} "
            f"Shots:{p.shots_hit}/{p.total_shots:<5} "
            f"HS:{p.headshots:<3} "
            f"Medals:{p.medals_earned:<3}"
        )
        if gametype:
            stats = p.get_gametype_stats(gametype)
            if stats:
                print(" " + ", ".join(f"{k}: {v}" for k, v in stats.items()))

    print("=" * 90)
    print()


def compute_game_fingerprint(players) -> str:
    """Compute a fingerprint string for deduplication."""
    parts = []
    for p in sorted(players, key=lambda x: x.player_name):
        fields = f"{p.player_name}:{p.kills}:{p.deaths}:{p.assists}:{p.suicides}"
        if hasattr(p, "score_string"):
            fields += f":{p.score_string}"
        if hasattr(p, "total_shots"):
            fields += f":{p.total_shots}:{p.shots_hit}:{p.headshots}"
        if hasattr(p, "gametype_value0"):
            fields += f":{p.gametype_value0}:{p.gametype_value1}"
        parts.append(fields)
    content = "|".join(parts)
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def build_snapshot(
    players,
    source: str = "pcr",
    gametype_id: Optional[int] = None,
    teams: Optional[List[TeamStats]] = None,
    map_name: Optional[str] = None,
    variant_name: Optional[str] = None,
    scenario: Optional[str] = None,
    map_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a complete game snapshot dictionary."""
    fingerprint = compute_game_fingerprint(players)

    gametype = None
    if gametype_id is not None and gametype_id > 0:
        try:
            gametype = GAMETYPE_NAMES.get(GameType(gametype_id), f"Unknown({gametype_id})").lower()
        except ValueError:
            pass

    timestamp = datetime.now().isoformat()
    unique_fingerprint = hashlib.md5((fingerprint + ":" + timestamp).encode("utf-8")).hexdigest()

    snapshot = {
        "schema_version": 3,
        "timestamp": timestamp,
        "fingerprint": unique_fingerprint,
        "source": source,
        "gametype": gametype,
        "gametype_id": gametype_id,
        "player_count": len(players),
        "players": [p.to_dict() for p in players],
    }

    if map_name:
        snapshot["map"] = map_name
    if variant_name:
        snapshot["variant"] = variant_name
    if scenario:
        snapshot["scenario"] = scenario
    if map_description:
        snapshot["map_description"] = map_description

    if gametype:
        for i, p in enumerate(players):
            snapshot["players"][i]["gametype_stats"] = p.get_gametype_stats(gametype)

    if teams:
        snapshot["teams"] = [t.to_dict() for t in teams]

    return snapshot


def save_game_history(snapshot: Dict[str, Any], history_dir: str) -> str:
    """Save a game snapshot to the history directory."""
    os.makedirs(history_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fingerprint = snapshot.get("fingerprint", "00000000")[:8]
    filename = f"{timestamp}_{fingerprint}.json"
    filepath = os.path.join(history_dir, filename)

    with open(filepath, "w") as f:
        json.dump(snapshot, f, indent=2)

    return filepath


def dump_pgcr_raw(client, history_dir: str, fingerprint: str) -> Optional[str]:
    """Dump raw hex of PGCR header, player records, and team structs to a file."""
    regions = [("PGCR Header", PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE)]

    for i in range(16):
        addr = calculate_pgcr_display_address(i)
        regions.append((f"Player {i}", addr, PCR_PLAYER_SIZE))

    for i in range(MAX_TEAMS):
        addr = calculate_pgcr_display_team_address(i)
        regions.append((f"Team {i}", addr, TEAM_DATA_STRIDE))

    lines = []
    for label, addr, length in regions:
        try:
            data = client.read_memory(addr, length)
            if not data:
                lines.append(f"=== {label} (0x{addr:08X}, 0x{length:X} bytes) === NO DATA")
                continue

            lines.append(f"=== {label} (0x{addr:08X}, 0x{length:X} bytes) ===")
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
                lines.append(f" {addr + i:08X} {hex_part:<48} {ascii_part}")
            lines.append("")
        except Exception as e:
            lines.append(f"=== {label} (0x{addr:08X}) === ERROR: {e}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fp_short = fingerprint[:8] if fingerprint else "unknown"
    filepath = os.path.join(history_dir, f"{timestamp}_{fp_short}_memdump.txt")

    with open(filepath, "w") as f:
        f.write("\n".join(lines))

    return filepath


def dump_pgcr_annotated(client, history_dir: str, fingerprint: str) -> Optional[str]:
    """Dump PGCR-related memory regions to a readable text file."""
    os.makedirs(history_dir, exist_ok=True)

    regions = [("PGCR Header", PGCR_DISPLAY_HEADER, PGCR_DISPLAY_HEADER_SIZE)]

    for i in range(16):
        addr = calculate_pgcr_display_address(i)
        regions.append((f"PGCR Display Player {i}", addr, PCR_PLAYER_SIZE))

    for i in range(8):
        addr = calculate_pgcr_display_team_address(i)
        regions.append((f"PGCR Display Team {i}", addr, TEAM_DATA_STRIDE))

    for i in range(16):
        addr = calculate_pcr_address(i)
        regions.append((f"PCR Player {i}", addr, PCR_PLAYER_SIZE))

    for i in range(8):
        addr = calculate_team_data_address(i)
        regions.append((f"PCR Team {i}", addr, TEAM_DATA_STRIDE))

    output_path = os.path.join(history_dir, f"{fingerprint}_pgcr_annotated.txt")

    try:
        with open(output_path, "w") as f:
            for region_name, region_addr, region_size in regions:
                try:
                    data = client.read_memory(region_addr, region_size)
                    if data is None or len(data) < region_size:
                        f.write(f"\n=== {region_name} (0x{region_addr:08X}, 0x{region_size:X} bytes) ===\n")
                        f.write("[Read failed or incomplete]\n")
                        continue
                except Exception as e:
                    f.write(f"\n=== {region_name} (0x{region_addr:08X}, 0x{region_size:X} bytes) ===\n")
                    f.write(f"[Error: {e}]\n")
                    continue

                f.write(f"\n=== {region_name} (0x{region_addr:08X}, 0x{region_size:X} bytes) ===\n")
                for i in range(0, len(data), 16):
                    chunk = data[i:i + 16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    ascii_str = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
                    f.write(f" {region_addr + i:08X} {hex_str:<48} {ascii_str}\n")
        return output_path
    except Exception as e:
        print(f"ERROR: Failed to dump PGCR annotated: {e}", file=sys.stderr)
        return None


def run_watch_mode(reader: "Halo2StatsReader", args) -> None:
    """Watch mode: continuously monitor for game completions."""
    history_dir = args.history_dir
    os.makedirs(history_dir, exist_ok=True)

    last_fingerprint = None

    try:
        if reader.probe_pgcr_display_populated():
            seed_players = reader.read_active_pgcr_display()
            if seed_players:
                last_fingerprint = compute_game_fingerprint(seed_players)
                print(f"[Watch] Seeded fingerprint from current PGCR memory: {last_fingerprint[:8]}")
    except Exception:
        pass

    print(f"Watch mode active. Polling every {args.watch_interval}s.")
    print(f"History will be saved to: {os.path.abspath(history_dir)}/")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            if hasattr(reader.client, "is_connected") and not reader.client.is_connected:
                print("[Watch] Connection lost, reconnecting...")
                reader.client.reconnect()
                print("[Watch] Reconnected!")

            players = None
            source = None

            if reader.probe_pgcr_display_populated():
                display_players = reader.read_active_pgcr_display()
                if display_players:
                    players = display_players
                    source = "pgcr_display"

            if not players and reader.probe_pcr_populated():
                all_indexed = reader.read_all_players_indexed()
                pcr_players = [p for p in all_indexed if p is not None]
                if pcr_players:
                    players = pcr_players
                    source = "pcr"

            if players:
                fingerprint = compute_game_fingerprint(players)

                if fingerprint != last_fingerprint:
                    time.sleep(1)

                    recheck_players = None
                    if reader.probe_pgcr_display_populated():
                        recheck_players = reader.read_active_pgcr_display()
                        if recheck_players:
                            recheck_fp = compute_game_fingerprint(recheck_players)
                            if recheck_fp != fingerprint:
                                continue
                            players = recheck_players

                    last_fingerprint = fingerprint

                    if hasattr(reader.client, "clear_va_cache"):
                        reader.client.clear_va_cache()

                    if args.save_ram:
                        if hasattr(reader.client, "save_ram"):
                            ram_filepath = os.path.abspath(os.path.join(history_dir, f"{fingerprint}_ram.bin"))
                            print(f"[Watch] Saving RAM snapshot...")
                            try:
                                if reader.client.save_ram(ram_filepath):
                                    try:
                                        ram_size = os.path.getsize(ram_filepath) / 1024 / 1024
                                        print(f" -> RAM snapshot saved ({ram_size:.1f} MB)")
                                    except Exception:
                                        print(f" -> RAM snapshot saved to {os.path.basename(ram_filepath)}")
                                else:
                                    print(" -> RAM snapshot save failed (not supported on this connection)")
                            except Exception as e:
                                print(f" -> RAM snapshot save error: {e}")
                        else:
                            print("[Watch] --save-ram requires QMP mode")

                    if reader.probe_pgcr_display_populated():
                        fresh_players = reader.read_active_pgcr_display()
                        if fresh_players:
                            players = fresh_players

                    teams = reader.read_teams()

                    gametype_id = None
                    for _gt_attempt in range(3):
                        gametype_id = reader.read_gametype_discovered()
                        if gametype_id:
                            break
                        time.sleep(0.5)
                    if not gametype_id:
                        gametype_id = reader.read_gametype()

                    gt_label = GAMETYPE_NAMES.get(gametype_id, "Unknown") if gametype_id else "Unknown"
                    print(f"[Gametype] {gt_label} ({gametype_id.value if gametype_id else '?'})")

                    vinfo = reader.get_variant_info_any()
                    dump_vinfo = reader.infer_map_from_dump_regions()
                    vinfo = reader._merge_variant_info(vinfo, dump_vinfo)

                    map_name = vinfo.get("map") if vinfo else None
                    variant_name = vinfo.get("variant") if vinfo else None
                    scenario = vinfo.get("scenario") if vinfo else None
                    map_description = vinfo.get("description") if vinfo else None

                    snapshot = build_snapshot(
                        players,
                        source=source,
                        gametype_id=gametype_id.value if gametype_id else None,
                        teams=teams,
                        map_name=map_name,
                        variant_name=variant_name,
                        scenario=scenario,
                        map_description=map_description,
                    )

                    map_str = f", map: {map_name}" if map_name else ""
                    scenario_str = f", scenario: {scenario}" if scenario else ""
                    desc_str = f", desc: {map_description[:40]}..." if map_description else ""

                    print(
                        f"[Watch] Game detected! "
                        f"({len(players)} players, source: {source}, gametype: {gt_label}{map_str}{scenario_str}{desc_str})"
                    )

                    gametype_for_display = args.gametype
                    if not gametype_for_display and gametype_id and gametype_id.value > 0:
                        gametype_for_display = GAMETYPE_NAMES.get(gametype_id, str(gametype_id)).lower()

                    if args.json:
                        print(json.dumps(snapshot, indent=2))
                    elif args.pgcr:
                        print_pgcr_report(players, teams, gametype_for_display)
                    else:
                        print_scoreboard_rich(players, gametype=gametype_for_display, teams=teams)

                    filepath = save_game_history(snapshot, history_dir)
                    print(f" -> Saved to {filepath}")

                    fp8 = fingerprint[:8] if len(fingerprint) >= 8 else fingerprint

                    try:
                        annotated_path = dump_pgcr_annotated(reader.client, history_dir, fp8)
                        if annotated_path:
                            print(f" -> Annotated hex dump saved to {os.path.basename(annotated_path)}")
                    except Exception as e:
                        print(f" -> Annotated hex dump failed: {e}")

                    try:
                        dump_path = dump_pgcr_raw(reader.client, history_dir, fingerprint)
                        if dump_path:
                            print(f" -> Raw memory dump saved to {os.path.basename(dump_path)}\n")
                    except Exception as e:
                        print(f" -> Raw memory dump failed: {e}\n")

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[Watch] Error: {e}")

        time.sleep(args.watch_interval)


def _parse_thread_id(notification: str) -> Optional[int]:
    """Extract thread ID from breakpoint notification."""
    m = re.search(r"thread=(\d+)", notification)
    return int(m.group(1)) if m else None


def run_watch_mode_breakpoint(reader: "Halo2StatsReader", client: XBDMClient, args) -> None:
    """
    Watch mode using XBDM breakpoint at 0x23975C for instant game-end detection.
    """
    history_dir = args.history_dir
    os.makedirs(history_dir, exist_ok=True)

    last_fingerprint = None
    bp_addr_hex = f"0x{PGCR_BREAKPOINT_ADDR:08X}"

    client.clear_all_breakpoints()
    try:
        client.continue_execution()
    except Exception:
        pass

    time.sleep(0.2)

    print(f"Setting breakpoint at {bp_addr_hex}...")
    if not client.set_breakpoint(PGCR_BREAKPOINT_ADDR):
        print("ERROR: Failed to set breakpoint. Falling back to polling mode.")
        run_watch_mode(reader, args)
        return

    print("Opening notification listener...")
    listener = XBDMNotificationListener(client.host, client.port, timeout=10.0)
    if not listener.connect():
        print("ERROR: Failed to connect notification listener. Falling back to polling mode.")
        try:
            client.clear_breakpoint(PGCR_BREAKPOINT_ADDR)
        except Exception:
            pass
        run_watch_mode(reader, args)
        return

    print(f"Breakpoint watch mode active at {bp_addr_hex}.")
    print(f"History will be saved to: {os.path.abspath(history_dir)}/")
    print("Waiting for game end (breakpoint trigger)...")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            sock = listener._socket
            if sock is None or not listener._connected:
                print("[Breakpoint] Notification connection lost, exiting.")
                break

            try:
                readable, _, _ = select.select([sock], [], [], 30.0)
            except (OSError, ValueError):
                print("[Breakpoint] Socket error, exiting.")
                break

            if not readable:
                continue

            notification = listener.wait_for_notification(timeout=2)
            if not notification:
                print("[Breakpoint] Connection appears dead, exiting.")
                break

            notification_stripped = notification.strip()
            ts = time.strftime("%H:%M:%S")

            if "break" not in notification.lower():
                continue
            if f"addr={bp_addr_hex.lower()}" not in notification.lower():
                continue

            print(f"[{ts}] Breakpoint hit: {notification_stripped}")

            thread_id = _parse_thread_id(notification)
            if thread_id is None:
                print("[Breakpoint] WARNING: Could not parse thread id, skipping")
                continue

            try:
                ok1 = client.continue_thread(thread_id)
                ok2 = client.continue_execution()
                if not ok1:
                    print(f"[Breakpoint] WARNING: continue_thread {thread_id} failed")
                if not ok2:
                    print("[Breakpoint] WARNING: continue_execution failed")
            except Exception as e:
                print(f"[Breakpoint] WARNING: failed to resume execution: {e}")

            print("[Breakpoint] Waiting for PGCR Display to populate...")

            players = None
            for _ in range(20):
                time.sleep(0.25)
                if reader.probe_pgcr_display_populated():
                    players = reader.read_active_pgcr_display()
                    if players:
                        break

            if not players:
                print("[Breakpoint] PGCR Display not populated after 5s, skipping")
                continue

            fingerprint = compute_game_fingerprint(players)
            if fingerprint == last_fingerprint:
                print("[Breakpoint] Duplicate fingerprint, ignoring")
                continue

            last_fingerprint = fingerprint
            fp8 = fingerprint[:8] if fingerprint else "unknown"

            if hasattr(reader.client, "clear_va_cache"):
                reader.client.clear_va_cache()

            teams = reader.read_teams()

            gametype_id = None
            for _gt_attempt in range(3):
                gametype_id = reader.read_gametype_discovered()
                if gametype_id:
                    break
                time.sleep(0.5)

            if args.save_ram:
                if hasattr(reader.client, "save_ram"):
                    ram_filepath = os.path.abspath(os.path.join(history_dir, f"{fp8}_ram.bin"))
                    print(f"[{ts}] Saving RAM snapshot...")
                    try:
                        if reader.client.save_ram(ram_filepath):
                            try:
                                ram_size = os.path.getsize(ram_filepath) / 1024 / 1024
                                print(f" -> RAM snapshot saved ({ram_size:.1f} MB)")
                            except Exception:
                                print(f" -> RAM snapshot saved to {os.path.basename(ram_filepath)}")
                        else:
                            print(" -> RAM snapshot save failed (not supported on this connection)")
                    except Exception as e:
                        print(f" -> RAM snapshot save error: {e}")

            try:
                if not gametype_id:
                    gametype_id = reader.read_gametype()

                gt_label = GAMETYPE_NAMES.get(gametype_id, "Unknown") if gametype_id else "Unknown"
                print(f"[Gametype] {gt_label} ({gametype_id.value if gametype_id else '?'})")

                vinfo = reader.get_variant_info_any()
                dump_vinfo = reader.infer_map_from_dump_regions()
                vinfo = reader._merge_variant_info(vinfo, dump_vinfo)

                map_name = vinfo.get("map") if vinfo else None
                variant_name = vinfo.get("variant") if vinfo else None
                scenario = vinfo.get("scenario") if vinfo else None
                map_description = vinfo.get("description") if vinfo else None

                snapshot = build_snapshot(
                    players,
                    source="pgcr_display",
                    gametype_id=gametype_id.value if gametype_id else None,
                    teams=teams,
                    map_name=map_name,
                    variant_name=variant_name,
                    scenario=scenario,
                    map_description=map_description,
                )

                map_str = f", map: {map_name}" if map_name else ""
                scenario_str = f", scenario: {scenario}" if scenario else ""
                desc_str = f", desc: {map_description[:40]}..." if map_description else ""

                print(f"[{ts}] Game captured! ({len(players)} players{map_str}{scenario_str}{desc_str})")

                gametype_for_display = args.gametype
                if not gametype_for_display and gametype_id and gametype_id.value > 0:
                    gametype_for_display = GAMETYPE_NAMES.get(gametype_id, str(gametype_id)).lower()

                if args.json:
                    print(json.dumps(snapshot, indent=2))
                elif args.pgcr:
                    print_pgcr_report(players, teams, gametype_for_display)
                else:
                    print_scoreboard_rich(players, gametype=gametype_for_display, teams=teams)

                filepath = save_game_history(snapshot, history_dir)
                print(f" -> Saved to {filepath}")

                try:
                    annotated_path = dump_pgcr_annotated(reader.client, history_dir, fp8)
                    if annotated_path:
                        print(f" -> Annotated hex dump saved to {os.path.basename(annotated_path)}\n")
                except Exception as e:
                    print(f" -> Annotated hex dump failed: {e}\n")

                print("Waiting for next game...\n")

            except Exception as e:
                print(f"[{ts}] Error reading stats: {e}")

    except KeyboardInterrupt:
        print("\nStopping breakpoint watch mode...")
    finally:
        print(f"Clearing breakpoint at {bp_addr_hex}...")
        try:
            client.clear_all_breakpoints()
        except Exception:
            pass
        try:
            client.continue_execution()
        except Exception:
            pass
        try:
            listener.close()
        except Exception:
            pass
        print("Breakpoint cleared, listener closed.")


def main():
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))

    parser = argparse.ArgumentParser(
        description="Read Halo 2 post-game statistics via XBDM/QMP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host 192.168.1.100                 # Read stats once (rich output)
  %(prog)s --host 127.0.0.1 --watch            # Watch for game completions
  %(prog)s --host 127.0.0.1 --poll 5           # Poll every 5 seconds
  %(prog)s --host 127.0.0.1 --json --save      # JSON output + save to history
  %(prog)s --host 127.0.0.1 --pgcr-display     # Include killed-by info
  %(prog)s --host 127.0.0.1 -g slayer          # Label gametype-specific stats
""",
    )

    parser.add_argument("--host", "-H", default="127.0.0.1", help="Xbox/Xemu IP address (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=731, help="XBDM port (default: 731)")
    parser.add_argument("--poll", "-P", type=float, default=0, help="Poll interval in seconds (0 = single read)")
    parser.add_argument("--output", "-o", help="Output file path for JSON data")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON instead of formatted text")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug output")
    parser.add_argument("--timeout", "-t", type=float, default=5.0, help="Connection timeout in seconds (default: 5.0)")
    parser.add_argument("--slow", "-s", action="store_true", help="Use slower, safer read delays (200ms instead of 50ms)")
    parser.add_argument("--watch", "-w", action="store_true", help="Watch for game completions and auto-capture PCR stats")
    parser.add_argument("--watch-interval", type=float, default=3.0, help="Seconds between watch-mode probes (default: 3.0)")
    parser.add_argument("--history-dir", default="data/history", help="Directory for auto-saved game history (default: data/history/)")
    parser.add_argument("--save", action="store_true", help="Save results to history directory")
    parser.add_argument("--pgcr-display", action="store_true", help="Also read PGCR display data (killed-by info, only on post-game screen)")
    parser.add_argument("--gametype", "-g", choices=["slayer", "ctf", "oddball", "koth", "juggernaut", "territories", "assault"], help="Gametype for interpreting gametype-specific stat fields")
    parser.add_argument("--simple", action="store_true", help="Use simple K/D/A output instead of detailed scoreboard")
    parser.add_argument("--breakpoint", "-b", action="store_true", help="Use XBDM breakpoint for instant game-end detection (instead of polling)")
    parser.add_argument("--dump-header", action="store_true", help="Hex dump the PGCR Display header (0x90 bytes) for research")
    parser.add_argument("--qmp", type=int, metavar="PORT", help="Use QMP protocol on PORT for live stats (requires Xemu -qmp flag)")
    parser.add_argument("--pgcr", action="store_true", help="Print output in PGCR-display format (tabular, matching in-game screenshots)")
    parser.add_argument("--save-ram", action="store_true", help="Save full 64MB RAM snapshot at each game end (QMP only, creates large files)")

    args = parser.parse_args()

    if args.qmp:
        from qmp_client import QMPClient

        print(f"Connecting to QMP at {args.host}:{args.qmp}...")
        client = QMPClient(args.host, args.qmp, timeout=args.timeout)

        if not client.connect_with_retry():
            print("ERROR: Failed to connect to QMP", file=sys.stderr)
            print("Make sure Xemu is running with:", file=sys.stderr)
            print(f" -qmp tcp:0.0.0.0:{args.qmp},server,nowait", file=sys.stderr)
            sys.exit(1)

        print("Connected to QMP!")
    else:
        print(f"Connecting to XBDM at {args.host}:{args.port}...")
        read_delay = 0.2 if args.slow else 0.05
        client = XBDMClient(args.host, args.port, timeout=args.timeout, read_delay=read_delay)

        if args.slow:
            print("Using slow mode (200ms between reads)")

        if not client.connect():
            print("ERROR: Failed to connect to XBDM", file=sys.stderr)
            print("Make sure:", file=sys.stderr)
            print(" - For Xemu: xbdm_gdb_bridge is running", file=sys.stderr)
            print(" - For Xbox: Console is on with XBDM enabled", file=sys.stderr)
            print(f" - Port {args.port} is accessible", file=sys.stderr)
            sys.exit(1)

        print("Connected!")

    reader = Halo2StatsReader(client, verbose=args.verbose)

    try:
        if args.dump_header:
            header = reader.read_pgcr_header()
            if header:
                print(f"\nPGCR Display Header (0x{PGCR_DISPLAY_HEADER:08X}, {len(header)} bytes):")
                print("=" * 72)
                for offset in range(0, len(header), 16):
                    chunk = header[offset:offset + 16]
                    hex_str = " ".join(f"{b:02X}" for b in chunk)
                    ascii_str = "".join(chr(b) if 0x20 <= b <= 0x7E else "." for b in chunk)
                    print(f" +0x{offset:02X}: {hex_str:<48s} {ascii_str}")

                gametype_val = struct.unpack("<I", header[0x84:0x88])[0]
                print("\nKnown fields:")
                print(f" +0x84: Gametype enum = {gametype_val}", end="")
                try:
                    print(f" ({GameType(gametype_val).name})")
                except ValueError:
                    print(" (unknown)")

                for label, start, end in [
                    ("Offset 0x00", 0x00, 0x20),
                    ("Offset 0x20", 0x20, 0x40),
                    ("Offset 0x40", 0x40, 0x60),
                    ("Offset 0x60", 0x60, 0x80),
                ]:
                    try:
                        text = header[start:end].decode("utf-16-le").rstrip("\x00")
                        if text and all(0x20 <= ord(c) <= 0x7E for c in text):
                            print(f' {label}: "{text}" (UTF-16LE)')
                    except Exception:
                        pass
            else:
                print("Failed to read PGCR header")
            return

        if args.watch:
            if args.breakpoint:
                run_watch_mode_breakpoint(reader, client, args)
            else:
                run_watch_mode(reader, args)
            return

        while True:
            all_indexed = None
            source = "pcr"

            if reader.probe_pgcr_display_populated():
                players = reader.read_active_pgcr_display()
                source = "pgcr_display"
                if players:
                    print("[Note] Using PGCR Display data")
                else:
                    players = []
            else:
                players = []

            if not players:
                all_indexed = reader.read_all_players_indexed()
                players = [p for p in all_indexed if p is not None]
                source = "pcr"

            gametype_enum = reader.read_gametype_discovered() or reader.read_gametype()
            teams = reader.read_teams()
            gametype_id_val = gametype_enum.value if gametype_enum else None

            vinfo = reader.get_variant_info_any()
            dump_vinfo = reader.infer_map_from_dump_regions()
            vinfo = reader._merge_variant_info(vinfo, dump_vinfo)

            _map = vinfo.get("map") if vinfo else None
            _variant = vinfo.get("variant") if vinfo else None
            _scenario = vinfo.get("scenario") if vinfo else None
            _map_description = vinfo.get("description") if vinfo else None

            if args.json or args.output:
                snapshot = build_snapshot(
                    players,
                    source=source,
                    gametype_id=gametype_id_val,
                    teams=teams,
                    map_name=_map,
                    variant_name=_variant,
                    scenario=_scenario,
                    map_description=_map_description,
                )

                if args.output:
                    with open(args.output, "w") as f:
                        json.dump(snapshot, f, indent=2)
                    print(f"Stats saved to {args.output}")

                if args.json:
                    print(json.dumps(snapshot, indent=2))
            else:
                gametype_for_display = args.gametype
                if not gametype_for_display and gametype_enum and gametype_enum.value > 0:
                    gametype_for_display = GAMETYPE_NAMES.get(gametype_enum, str(gametype_enum)).lower()

                if args.simple:
                    print_scoreboard(players)
                elif args.pgcr:
                    print_pgcr_report(players, teams, gametype_for_display)
                else:
                    print_scoreboard_rich(
                        players,
                        gametype=gametype_for_display,
                        all_players=all_indexed,
                        teams=teams,
                    )

                if _variant or _map or _scenario:
                    print(f"[Variant] {(_variant or '')}")
                    print(f"[Map] {(_map or '')}")
                    print(f"[Scenario] {(_scenario or '')}")
                    print(f"[Map Description] {(_map_description or '')}")

            if args.save and players:
                snapshot = build_snapshot(
                    players,
                    source=source,
                    gametype_id=gametype_id_val,
                    teams=teams,
                    map_name=_map,
                    variant_name=_variant,
                    scenario=_scenario,
                    map_description=_map_description,
                )
                filepath = save_game_history(snapshot, args.history_dir)
                print(f"Saved to {filepath}")

            if args.poll <= 0:
                break

            time.sleep(args.poll)

    except (KeyboardInterrupt, SystemExit):
        print("\nStopped.")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
