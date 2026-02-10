#!/usr/bin/env python3
"""
Halo 2 Stats Reader - Cross-platform live stats collection via XBDM

Connects to XBDM on port 731 to read game statistics.

Requirements:
- For Xemu: xbdm_gdb_bridge must be running (implements XBDM protocol)
- For Real Xbox: Connect directly (native XBDM support)

Usage:
    # PCR stats (post-game only, default)
    python halo2_stats.py --host 127.0.0.1

    # LIVE stats during gameplay (uses HaloCaster addresses)
    python halo2_stats.py --host 127.0.0.1 --live

    # Poll live stats every 2 seconds
    python halo2_stats.py --host 127.0.0.1 --live --poll 2

    # JSON output
    python halo2_stats.py --host 127.0.0.1 --live --json

Stats Modes:
    --live    Read real-time stats during gameplay (HaloCaster addresses)
              Works with Halo 2 v1.5 debug XBE
    (default) Read PCR stats - only populated after game ends
"""

import argparse
import hashlib
import json
import os
import re
import select
import struct
import sys
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

from xbdm_client import XBDMClient, XBDMNotificationListener
from halo2_structs import (
    PCRPlayerStats,
    PGCRDisplayStats,
    GameStats,
    PlayerProperties,
    GameType,
    GameTeam,
    GAMETYPE_NAMES,
    TeamStats,
    calculate_pcr_address,
    calculate_live_stats_address,
    calculate_session_player_address,
    calculate_pgcr_display_address,
    calculate_team_data_address,
    calculate_pgcr_display_team_address,
    get_address,
    get_live_address,
    decode_medals,
    detect_gametype_from_medals,
    PCR_PLAYER_SIZE,
    PGCR_DISPLAY_SIZE,
    TEAM_DATA_STRIDE,
    MAX_TEAMS,
    GAME_STATS_STRUCT,
    SESSION_PLAYER_SIZE,
    PGCR_BREAKPOINT_ADDR,
    PGCR_DISPLAY_GAMETYPE_ADDR,
    LifeCycle,
    LIVE_ADDRESSES,
)


def _is_valid_player_name(name_bytes: bytes) -> bool:
    """
    Check if raw UTF-16LE name bytes represent a valid Xbox gamertag.

    Rejects garbage/uninitialized memory by checking:
    - At least 1 character
    - All characters are printable ASCII or common Unicode (0x20-0x7E range)
    - First null terminator within reasonable range
    """
    try:
        name = name_bytes.decode('utf-16-le').rstrip('\x00')
    except (UnicodeDecodeError, ValueError):
        return False
    if not name or len(name) < 1:
        return False
    # Xbox gamertags are ASCII printable (letters, digits, spaces, some symbols)
    return all(0x20 <= ord(c) <= 0x7E for c in name)


class Halo2StatsReader:
    """
    Reads Halo 2 statistics from Xbox memory via XBDM.

    Uses the PCR (Post-game Carnage Report) structure at address 0x55CAF0.
    This structure contains player stats that work during and after games.
    """

    MAX_PLAYERS = 16

    def __init__(self, client: XBDMClient, verbose: bool = False):
        self.client = client
        self.verbose = verbose
        self._last_error: Optional[str] = None

    def log(self, message: str):
        """Print message if verbose mode enabled."""
        if self.verbose:
            print(f"[DEBUG] {message}")

    def read_player(self, player_index: int) -> Optional[PCRPlayerStats]:
        """
        Read stats for a single player using PCR structure.

        Args:
            player_index: Player slot (0-15)

        Returns:
            PCRPlayerStats if successful, None on error
        """
        addr = calculate_pcr_address(player_index)
        self.log(f"Reading player {player_index} from 0x{addr:08X}")

        data = self.client.read_memory(addr, PCR_PLAYER_SIZE)
        if not data:
            self._last_error = f"Failed to read player {player_index} at 0x{addr:08X}"
            return None

        try:
            stats = PCRPlayerStats.from_bytes(data)
            if stats.player_name:
                self.log(f"  Found: {stats.player_name} - K:{stats.kills} D:{stats.deaths}")
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

        return {
            "timestamp": datetime.now().isoformat(),
            "player_count": len(players),
            "players": [p.to_dict() for p in players],
        }

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
        Validates the name contains printable characters (not garbage memory).
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
            if (player and player.player_name.strip()
                    and all(0x20 <= ord(c) <= 0x7E for c in player.player_name)):
                players.append(player)
            else:
                players.append(None)
        return players

    def read_pgcr_display_player(self, player_index: int) -> Optional[PCRPlayerStats]:
        """
        Read PGCR display stats for a single player.

        The PGCR Display uses the same pcr_stat_player layout as PCR,
        just at a different base address (0x56B990 instead of 0x55CAF0).
        Only populated during the post-game carnage report screen.
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
                # Validate the name is printable ASCII (not garbage memory)
                if all(0x20 <= ord(c) <= 0x7E for c in player.player_name):
                    players.append(player)
        return players

    def probe_pgcr_display_populated(self) -> bool:
        """
        Lightweight check: is the PGCR display populated with real data?

        Reads the first player's name (32 bytes at 0x56B990) and validates
        it contains printable characters (not garbage/uninitialized memory).
        """
        addr = calculate_pgcr_display_address(0)
        # Player name is at offset 0x00 within the player record
        data = self.client.read_memory(addr, 32)
        if not data:
            return False
        return _is_valid_player_name(data)

    # =========================================================================
    # Gametype and Team Methods
    # =========================================================================

    def read_gametype(self) -> Optional[GameType]:
        """Read gametype enum from PGCR Display header at 0x56B984.

        The gametype is stored at offset +0x84 within the PGCR Display header
        (0x56B900). This is populated both during gameplay and on the post-game
        screen. The previously-documented address 0x50224C reads as zero on
        docker-bridged-xemu.
        """
        addr = PGCR_DISPLAY_GAMETYPE_ADDR
        self.log(f"Reading gametype from 0x{addr:08X}")
        data = self.client.read_memory(addr, 4)
        if not data or len(data) < 4:
            return None
        value = struct.unpack('<I', data)[0]
        try:
            gt = GameType(value)
            return gt if gt != GameType.NONE else None
        except ValueError:
            self.log(f"Unknown gametype value: {value}")
            return None

    def read_teams(self) -> List[TeamStats]:
        """Read team data, trying PGCR Display location first then PCR fallback.

        PGCR Display teams: 0x56CAD0 (after 16 PGCR player records)
        PCR teams: 0x55DC30 (after 16 PCR player records) — empty on docker-bridged-xemu
        """
        # Try PGCR Display team data first (primary)
        teams = self._read_teams_from(calculate_pgcr_display_team_address)
        if teams:
            return teams
        # Fallback to PCR team data
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
                # Validate team name is real (not garbage memory)
                if team.name.strip() and all(0x20 <= ord(c) <= 0x7E for c in team.name):
                    teams.append(team)
            except Exception as e:
                self.log(f"Failed to parse team {i}: {e}")
        return teams

    # =========================================================================
    # Live Stats Methods (read during gameplay)
    # =========================================================================

    def read_life_cycle(self) -> Optional[LifeCycle]:
        """
        Read current game life cycle state.

        Returns:
            LifeCycle enum value, or None on error
        """
        addr = get_live_address("life_cycle")
        self.log(f"Reading life_cycle from 0x{addr:08X}")

        data = self.client.read_memory(addr, 4)
        if not data or len(data) < 4:
            self._last_error = f"Failed to read life_cycle at 0x{addr:08X}"
            return None

        value = struct.unpack('<I', data)[0]
        try:
            return LifeCycle(value)
        except ValueError:
            self.log(f"Unknown life_cycle value: {value}")
            return LifeCycle.NONE

    def read_live_player_stats(self, player_index: int) -> Optional[GameStats]:
        """
        Read LIVE stats for a single player during gameplay.

        Args:
            player_index: Player slot (0-15)

        Returns:
            GameStats if successful, None on error
        """
        addr = calculate_live_stats_address(player_index)
        self.log(f"Reading live stats for player {player_index} from 0x{addr:08X}")

        # Read the full game stats structure (54 bytes)
        data = self.client.read_memory(addr, GAME_STATS_STRUCT)
        if not data:
            self._last_error = f"Failed to read live stats for player {player_index} at 0x{addr:08X}"
            return None

        try:
            stats = GameStats.from_bytes(data)
            self.log(f"  Live stats: K:{stats.kills} D:{stats.deaths} A:{stats.assists}")
            return stats
        except Exception as e:
            self._last_error = f"Failed to parse live stats for player {player_index}: {e}"
            return None

    def read_session_player(self, player_index: int) -> Optional[PlayerProperties]:
        """
        Read player session properties (name, team, etc.)

        Args:
            player_index: Player slot (0-15)

        Returns:
            PlayerProperties if successful, None on error
        """
        addr = calculate_session_player_address(player_index)
        self.log(f"Reading session player {player_index} from 0x{addr:08X}")

        data = self.client.read_memory(addr, SESSION_PLAYER_SIZE)
        if not data:
            self._last_error = f"Failed to read session player {player_index} at 0x{addr:08X}"
            return None

        try:
            props = PlayerProperties.from_bytes(data)
            if props.player_name:
                self.log(f"  Found: {props.player_name} on team {props.team.name}")
            return props
        except Exception as e:
            self._last_error = f"Failed to parse session player {player_index}: {e}"
            return None

    def read_all_live_players(self) -> List[Dict[str, Any]]:
        """Read live stats for all players with valid names."""
        players = []
        for i in range(self.MAX_PLAYERS):
            props = self.read_session_player(i)
            if props and props.player_name.strip():
                stats = self.read_live_player_stats(i)
                if stats:
                    players.append({
                        "index": i,
                        "name": props.player_name,
                        "team": props.team.name.lower(),
                        "kills": stats.kills,
                        "deaths": stats.deaths,
                        "assists": stats.assists,
                        "betrayals": stats.betrayals,
                        "suicides": stats.suicides,
                    })
        return players

    def get_live_snapshot(self) -> Dict[str, Any]:
        """
        Get a complete snapshot of current LIVE game state.

        Returns a dictionary ready for JSON serialization.
        """
        life_cycle = self.read_life_cycle()
        players = self.read_all_live_players()

        return {
            "timestamp": datetime.now().isoformat(),
            "life_cycle": life_cycle.name if life_cycle else "UNKNOWN",
            "player_count": len(players),
            "players": players,
        }


def format_live_player_summary(player: Dict[str, Any]) -> str:
    """Format a single player's live stats as a readable line."""
    name = player["name"][:16].ljust(16)
    k = player["kills"]
    d = player["deaths"]
    a = player["assists"]
    kd = k / max(d, 1)

    return f"{name} K:{k:3d} D:{d:3d} A:{a:3d} K/D:{kd:.2f}"


def print_live_scoreboard(players: List[Dict[str, Any]], life_cycle: str):
    """Print a formatted live scoreboard to console."""
    print("\n" + "=" * 60)
    print(f" HALO 2 LIVE STATS - {life_cycle}")
    print("=" * 60)

    if not players:
        print(" No players found in game.")
    else:
        # Sort by kills descending
        sorted_players = sorted(players, key=lambda p: p["kills"], reverse=True)

        for i, player in enumerate(sorted_players, 1):
            print(f" {i:2d}. {format_live_player_summary(player)}")

    print("=" * 60)
    print()


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

    # Sort by kills descending
    sorted_players = sorted(players, key=lambda p: p.kills, reverse=True)

    for i, player in enumerate(sorted_players, 1):
        print(f" {i:2d}. {format_player_summary(player)}")

    print("=" * 60)
    print()


def compute_game_fingerprint(players) -> str:
    """
    Compute a fingerprint string for deduplication.

    Uses player names + all available stats to create a unique identifier.
    Includes score_string, shots, headshots, and gametype values to
    distinguish games with identical K/D/A (e.g. solo 0-0-0 CTF games).

    Works with both PCRPlayerStats and PGCRDisplayStats.
    """
    parts = []
    for p in sorted(players, key=lambda x: x.player_name):
        fields = f"{p.player_name}:{p.kills}:{p.deaths}:{p.assists}:{p.suicides}"
        # Include additional fields to distinguish otherwise-identical games
        if hasattr(p, 'score_string'):
            fields += f":{p.score_string}"
        if hasattr(p, 'total_shots'):
            fields += f":{p.total_shots}:{p.shots_hit}:{p.headshots}"
        if hasattr(p, 'gametype_value0'):
            fields += f":{p.gametype_value0}:{p.gametype_value1}"
        parts.append(fields)
    content = "|".join(parts)
    return hashlib.md5(content.encode('utf-8')).hexdigest()


def build_snapshot(players,
                   pgcr_display: Optional[List[PGCRDisplayStats]] = None,
                   source: str = "pcr",
                   gametype_id: Optional[int] = None,
                   teams: Optional[List[TeamStats]] = None) -> Dict[str, Any]:
    """
    Build a complete game snapshot dictionary.

    Args:
        players: List of active player stats (PCRPlayerStats or PGCRDisplayStats)
        pgcr_display: Optional extra PGCR display stats for killed-by data
        source: Data source identifier ("pcr" or "pgcr_display")
        gametype_id: Gametype enum value from memory (e.g. GameType.SLAYER = 2)
        teams: Optional list of TeamStats from team data area
    """
    fingerprint = compute_game_fingerprint(players)

    # Determine gametype string: enum-based if available, else medal-based fallback
    if gametype_id is not None and gametype_id > 0:
        try:
            gametype = GAMETYPE_NAMES.get(GameType(gametype_id), f"Unknown({gametype_id})").lower()
        except ValueError:
            gametype = detect_gametype_from_medals(players)
    else:
        gametype = detect_gametype_from_medals(players)

    snapshot = {
        "schema_version": 3,
        "timestamp": datetime.now().isoformat(),
        "fingerprint": fingerprint,
        "source": source,
        "gametype": gametype,
        "gametype_id": gametype_id,
        "player_count": len(players),
        "players": [p.to_dict() for p in players],
    }

    # Add labeled gametype stats per player
    if gametype:
        for i, p in enumerate(players):
            snapshot["players"][i]["gametype_stats"] = p.get_gametype_stats(gametype)

    # Add team data if present
    if teams:
        snapshot["teams"] = [t.to_dict() for t in teams]

    if pgcr_display and source != "pgcr_display":
        snapshot["pgcr_display"] = [d.to_dict() for d in pgcr_display]

    return snapshot


def save_game_history(snapshot: Dict[str, Any], history_dir: str) -> str:
    """
    Save a game snapshot to the history directory.

    Args:
        snapshot: Game data dictionary (from build_snapshot)
        history_dir: Directory path for history files

    Returns:
        Path to the saved file
    """
    os.makedirs(history_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    fingerprint = snapshot.get("fingerprint", "00000000")[:8]
    filename = f"{timestamp}_{fingerprint}.json"
    filepath = os.path.join(history_dir, filename)

    with open(filepath, 'w') as f:
        json.dump(snapshot, f, indent=2)

    return filepath


def run_watch_mode(reader: 'Halo2StatsReader', args) -> None:
    """
    Watch mode: continuously monitor for game completions.

    Uses fingerprint-based deduplication — no state machine needed.
    Each poll: check if PGCR Display (or PCR) has data with a new fingerprint.
    If the fingerprint changed, it's a new game result — capture and save.

    Probes PGCR Display first (0x56B900+0x90), falls back to PCR (0x55CAF0).
    """
    history_dir = args.history_dir
    os.makedirs(history_dir, exist_ok=True)

    last_fingerprint = None

    print(f"Watch mode active. Polling every {args.watch_interval}s.")
    print(f"History will be saved to: {os.path.abspath(history_dir)}/")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            players = None
            source = None

            # Try PGCR Display first (reliable), then PCR (may be empty)
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
                    last_fingerprint = fingerprint

                    gametype_id = reader.read_gametype()
                    teams = reader.read_teams()
                    snapshot = build_snapshot(
                        players, source=source,
                        gametype_id=gametype_id.value if gametype_id else None,
                        teams=teams,
                    )

                    print(f"[Watch] Game detected! ({len(players)} players, source: {source})")

                    if args.json:
                        print(json.dumps(snapshot, indent=2))
                    else:
                        # CLI --gametype flag overrides; otherwise use enum-derived name
                        gametype_for_display = args.gametype
                        if not gametype_for_display and gametype_id and gametype_id.value > 0:
                            gametype_for_display = GAMETYPE_NAMES.get(gametype_id, str(gametype_id)).lower()
                        print_scoreboard_rich(players, gametype=gametype_for_display, teams=teams)

                    filepath = save_game_history(snapshot, history_dir)
                    print(f"  -> Saved to {filepath}\n")

        except Exception as e:
            print(f"[Watch] Error: {e}")

        time.sleep(args.watch_interval)


def _parse_thread_id(notification: str) -> Optional[int]:
    """Extract thread ID from breakpoint notification.

    Example: 'break addr=0x0023975c thread=28 stop' -> 28
    """
    m = re.search(r'thread=(\d+)', notification)
    return int(m.group(1)) if m else None


def run_watch_mode_breakpoint(reader: 'Halo2StatsReader', client: XBDMClient, args) -> None:
    """
    Watch mode using XBDM breakpoint at 0x23975C for instant game-end detection.

    Sets a hardware breakpoint on the PGCR clear function. When a game ends,
    the engine calls this function, the breakpoint fires, and the Xbox halts.
    We resume execution (continue thread + go per SDK), then poll until PGCR
    Display has valid player data and capture the stats.

    Much faster than polling (instant detection vs 3s delay).
    """
    history_dir = args.history_dir
    os.makedirs(history_dir, exist_ok=True)

    last_fingerprint = None
    bp_addr_hex = f"0x{PGCR_BREAKPOINT_ADDR:08X}"

    # Clear any stale breakpoints first
    client.clear_all_breakpoints()
    try:
        client.continue_execution()
    except Exception:
        pass
    time.sleep(0.2)

    # Set breakpoint
    print(f"Setting breakpoint at {bp_addr_hex}...")
    if not client.set_breakpoint(PGCR_BREAKPOINT_ADDR):
        print("ERROR: Failed to set breakpoint. Falling back to polling mode.")
        run_watch_mode(reader, args)
        return

    # Open notification listener
    print("Opening notification listener...")
    listener = XBDMNotificationListener(client.host, client.port, timeout=10.0)
    if not listener.connect():
        print("ERROR: Failed to connect notification listener. Falling back to polling mode.")
        client.clear_breakpoint(PGCR_BREAKPOINT_ADDR)
        run_watch_mode(reader, args)
        return

    print(f"Breakpoint watch mode active at {bp_addr_hex}.")
    print(f"History will be saved to: {os.path.abspath(history_dir)}/")
    print("Waiting for game end (breakpoint trigger)...")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            # Use select() to reliably block on the notification socket.
            # This prevents the spin-loop bug where _recv_line returns None
            # instantly on a degraded connection.
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
                # 30-second timeout, no data — just keep waiting
                continue

            # Data available on socket
            notification = listener.wait_for_notification(timeout=2)
            if not notification:
                print("[Breakpoint] Connection appears dead, exiting.")
                break

            notification_stripped = notification.strip()
            ts = time.strftime("%H:%M:%S")

            # Filter: only act on 'break' notifications for our address
            if 'break' not in notification.lower():
                # Informational (execution started/stopped) — ignore
                continue

            addr_match = f"{PGCR_BREAKPOINT_ADDR:x}" in notification.lower()
            if not addr_match:
                # Different breakpoint address — resume and ignore
                print(f"[{ts}] Other breakpoint, resuming: {notification_stripped}")
                thread_id = _parse_thread_id(notification)
                if thread_id is not None:
                    client.continue_thread(thread_id)
                client.continue_execution()
                continue

            print(f"[{ts}] Breakpoint fired at {bp_addr_hex}!")

            # The breakpoint fires at the ENTRY of the PGCR clear function.
            # The Xbox is halted, so PGCR data still has the current game's
            # stats. Read everything NOW (while halted) before resuming.
            players = None
            teams = None
            try:
                players = reader.read_active_pgcr_display()
                teams = reader.read_teams()
            except Exception as e:
                print(f"[{ts}] Error reading stats while halted: {e}")

            # Now resume execution: DmContinueThread before DmGo per SDK
            thread_id = _parse_thread_id(notification)
            if thread_id is not None:
                client.continue_thread(thread_id)
            client.continue_execution()

            if not players:
                print(f"[{ts}] No valid players in PGCR (may be game start)")
                continue

            fingerprint = compute_game_fingerprint(players)
            if fingerprint == last_fingerprint:
                print(f"[{ts}] Same game (duplicate fingerprint), skipping.")
                continue

            last_fingerprint = fingerprint

            try:
                # Don't use PGCR header gametype — it's unreliable (stale
                # from previous games). Use medal-based heuristic or user
                # override via -g flag instead.
                gametype_id = None
                if players:
                    from halo2_structs import detect_gametype_from_medals
                    gametype_id = detect_gametype_from_medals(players)

                snapshot = build_snapshot(
                    players, source="pgcr_display",
                    gametype_id=gametype_id.value if gametype_id else None,
                    teams=teams,
                )

                print(f"[{ts}] Game captured! ({len(players)} players)")

                if args.json:
                    print(json.dumps(snapshot, indent=2))
                else:
                    gametype_for_display = args.gametype
                    if not gametype_for_display and gametype_id and gametype_id.value > 0:
                        gametype_for_display = GAMETYPE_NAMES.get(gametype_id, str(gametype_id)).lower()
                    print_scoreboard_rich(players, gametype=gametype_for_display, teams=teams)

                filepath = save_game_history(snapshot, history_dir)
                print(f"  -> Saved to {filepath}\n")
                print("Waiting for next game...\n")
            except Exception as e:
                print(f"[{ts}] Error reading stats: {e}")

    except KeyboardInterrupt:
        print("\nStopping breakpoint watch mode...")
    finally:
        print(f"Clearing breakpoint at {bp_addr_hex}...")
        client.clear_all_breakpoints()
        try:
            client.continue_execution()
        except Exception:
            pass
        listener.close()
        print("Breakpoint cleared, listener closed.")


def print_scoreboard_rich(players: List[PCRPlayerStats],
                          gametype: Optional[str] = None,
                          pgcr_display: Optional[List[PGCRDisplayStats]] = None,
                          all_players: Optional[List[Optional[PCRPlayerStats]]] = None,
                          teams: Optional[List[TeamStats]] = None):
    """Print a detailed scoreboard with medals, accuracy, and gametype stats."""
    if not players:
        print("No players found in game.")
        return

    # Auto-detect gametype from medals if not specified
    if not gametype:
        gametype = detect_gametype_from_medals(players)

    sorted_players = sorted(players, key=lambda p: p.kills, reverse=True)

    # Build slot-index-to-name lookup for killed-by display
    slot_names = {}
    if all_players:
        for idx, p in enumerate(all_players):
            if p and p.player_name.strip():
                slot_names[idx] = p.player_name

    print("\n" + "=" * 72)
    print(" HALO 2 POST-GAME CARNAGE REPORT")
    print("=" * 72)

    # Print team scores if available
    if teams:
        print("\n TEAM SCORES")
        sorted_teams = sorted(teams, key=lambda t: t.place)
        team_parts = []
        for t in sorted_teams:
            place_label = t.place_string if t.place_string else f"#{t.place + 1}"
            team_parts.append(f" {t.name}: {t.score} ({place_label})")
        print("   ".join(team_parts))

    for i, player in enumerate(sorted_players, 1):
        name = player.player_name[:16].ljust(16)
        k, d, a = player.kills, player.deaths, player.assists
        kd = k / max(d, 1)

        place_str = player.place_string or f"#{player.place}"
        score_str = player.score_string or ""
        try:
            team_label = GameTeam(player.team).name.capitalize()
        except ValueError:
            team_label = f"Team{player.team}"
        print(f"\n {i:2d}. {name}  {place_str:>4s}  Score: {score_str}  [{team_label}]")
        print(f"     K:{k:3d}  D:{d:3d}  A:{a:3d}  S:{player.suicides:2d}  K/D:{kd:.2f}")

        if player.total_shots > 0:
            acc = player.shots_hit / player.total_shots * 100
            print(f"     Accuracy: {acc:.1f}%  ({player.shots_hit}/{player.total_shots} shots, {player.headshots} headshots)")

        if player.medals_earned > 0:
            medal_names = decode_medals(player.medals_earned_by_type)
            if medal_names:
                print(f"     Medals ({player.medals_earned}): {', '.join(medal_names)}")
            else:
                print(f"     Medals: {player.medals_earned}")

        if player.gametype_value0 != 0 or player.gametype_value1 != 0:
            if gametype:
                gt_stats = player.get_gametype_stats(gametype)
                gt_parts = [f"{name}: {val}" for name, val in gt_stats.items() if val != 0]
                if gt_parts:
                    print(f"     {gametype.upper()}: {', '.join(gt_parts)}")
            else:
                print(f"     Gametype Values: {player.gametype_value0}, {player.gametype_value1}")

        if pgcr_display:
            for display in pgcr_display:
                if display.player_name == player.player_name and any(v > 0 for v in display.killed_by):
                    killed_by_parts = []
                    for idx, count in enumerate(display.killed_by):
                        if count > 0:
                            killer = slot_names.get(idx, f"P{idx}")
                            if idx == 0 and not slot_names.get(0):
                                killer = "self"
                            killed_by_parts.append(f"{killer}: {count}")
                    if killed_by_parts:
                        print(f"     Killed by: {', '.join(killed_by_parts)}")
                    break

    print("\n" + "=" * 72)
    print()


def print_scoreboard_display(players: List[PGCRDisplayStats]):
    """Print a scoreboard from PGCR Display data (used when PCR is empty)."""
    if not players:
        print("No players found in game.")
        return

    sorted_players = sorted(players, key=lambda p: p.kills, reverse=True)

    print("\n" + "=" * 72)
    print(" HALO 2 POST-GAME CARNAGE REPORT")
    print("=" * 72)

    for i, player in enumerate(sorted_players, 1):
        name = player.player_name[:16].ljust(16)
        k, d, a = player.kills, player.deaths, player.assists
        kd = k / max(d, 1)

        place_str = player.place_string or f"#{player.place}"
        score_str = player.score_string or ""
        print(f"\n {i:2d}. {name}  {place_str:>4s}  Score: {score_str}")
        print(f"     K:{k:3d}  D:{d:3d}  A:{a:3d}  S:{player.suicides:2d}  K/D:{kd:.2f}")

        if player.total_shots > 0:
            acc = player.shots_hit / player.total_shots * 100
            print(f"     Accuracy: {acc:.1f}%  ({player.shots_hit}/{player.total_shots} shots, {player.headshots} headshots)")

        if any(v > 0 for v in player.killed_by):
            killed_by_parts = []
            for idx, count in enumerate(player.killed_by):
                if count > 0:
                    # Try to find killer name from the player list
                    killer = f"P{idx}"
                    for p in players:
                        if p.place == idx + 1:
                            killer = p.player_name
                            break
                    killed_by_parts.append(f"{killer}: {count}")
            if killed_by_parts:
                print(f"     Killed by: {', '.join(killed_by_parts)}")

    print("\n" + "=" * 72)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Read live Halo 2 statistics via XBDM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --host 192.168.1.100              # Read stats once (rich output)
  %(prog)s --host 127.0.0.1 --watch          # Watch for game completions
  %(prog)s --host 127.0.0.1 --poll 5         # Poll every 5 seconds
  %(prog)s --host 127.0.0.1 --json --save    # JSON output + save to history
  %(prog)s --host 127.0.0.1 --pgcr-display   # Include killed-by data
  %(prog)s --host 127.0.0.1 -g slayer        # Label gametype-specific stats
        """
    )

    parser.add_argument(
        "--host", "-H",
        default="127.0.0.1",
        help="Xbox/Xemu IP address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=731,
        help="XBDM port (default: 731)"
    )
    parser.add_argument(
        "--poll", "-P",
        type=float,
        default=0,
        help="Poll interval in seconds (0 = single read)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path for JSON data"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON instead of formatted text"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose debug output"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=5.0,
        help="Connection timeout in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--live", "-l",
        action="store_true",
        help="Read LIVE stats during gameplay (HaloCaster addresses)"
    )
    parser.add_argument(
        "--slow", "-s",
        action="store_true",
        help="Use slower, safer read delays (200ms instead of 50ms)"
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Watch for game completions and auto-capture PCR stats"
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=3.0,
        help="Seconds between watch-mode probes (default: 3.0)"
    )
    parser.add_argument(
        "--history-dir",
        default="history",
        help="Directory for auto-saved game history (default: history/)"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to history directory"
    )
    parser.add_argument(
        "--pgcr-display",
        action="store_true",
        help="Also read PGCR display data (killed-by info, only on post-game screen)"
    )
    parser.add_argument(
        "--gametype", "-g",
        choices=["slayer", "ctf", "oddball", "koth", "juggernaut", "territories", "assault"],
        help="Gametype for interpreting gametype-specific stat fields"
    )
    parser.add_argument(
        "--simple",
        action="store_true",
        help="Use simple K/D/A output instead of detailed scoreboard"
    )
    parser.add_argument(
        "--breakpoint", "-b",
        action="store_true",
        help="Use XBDM breakpoint for instant game-end detection (instead of polling)"
    )

    args = parser.parse_args()

    # Connect to XBDM
    print(f"Connecting to XBDM at {args.host}:{args.port}...")
    read_delay = 0.2 if args.slow else 0.05  # 200ms slow mode, 50ms normal
    client = XBDMClient(args.host, args.port, timeout=args.timeout, read_delay=read_delay)
    if args.slow:
        print("Using slow mode (200ms between reads)")

    if not client.connect():
        print("ERROR: Failed to connect to XBDM", file=sys.stderr)
        print("Make sure:", file=sys.stderr)
        print("  - For Xemu: xbdm_gdb_bridge is running", file=sys.stderr)
        print("  - For Xbox: Console is on with XBDM enabled", file=sys.stderr)
        print(f"  - Port {args.port} is accessible", file=sys.stderr)
        sys.exit(1)

    print("Connected!")

    reader = Halo2StatsReader(client, verbose=args.verbose)

    try:
        # Watch mode takes over entirely
        if args.watch:
            if args.breakpoint:
                run_watch_mode_breakpoint(reader, client, args)
            else:
                run_watch_mode(reader, args)
            return

        while True:
            if args.live:
                # Live stats mode (HaloCaster addresses)
                if args.json or args.output:
                    snapshot = reader.get_live_snapshot()

                    if args.output:
                        with open(args.output, 'w') as f:
                            json.dump(snapshot, f, indent=2)
                        print(f"Live stats saved to {args.output}")

                    if args.json:
                        print(json.dumps(snapshot, indent=2))
                else:
                    life_cycle = reader.read_life_cycle()
                    life_cycle_str = life_cycle.name if life_cycle else "UNKNOWN"
                    players = reader.read_all_live_players()
                    print_live_scoreboard(players, life_cycle_str)

            else:
                # PCR stats mode - try PGCR Display first (more reliable), fall back to PCR
                # Both sources return PCRPlayerStats (same struct layout)
                all_indexed = None
                source = "pcr"

                if reader.probe_pgcr_display_populated():
                    players = reader.read_active_pgcr_display()
                    source = "pgcr_display"
                    if players:
                        print("[Note] Using PGCR Display data")
                else:
                    players = []

                if not players:
                    all_indexed = reader.read_all_players_indexed()
                    players = [p for p in all_indexed if p is not None]
                    source = "pcr"

                # Read gametype enum and team data
                gametype_enum = reader.read_gametype()
                teams = reader.read_teams()
                gametype_id_val = gametype_enum.value if gametype_enum else None

                if args.json or args.output:
                    snapshot = build_snapshot(
                        players, source=source,
                        gametype_id=gametype_id_val, teams=teams,
                    )

                    if args.output:
                        with open(args.output, 'w') as f:
                            json.dump(snapshot, f, indent=2)
                        print(f"Stats saved to {args.output}")

                    if args.json:
                        print(json.dumps(snapshot, indent=2))
                else:
                    # CLI --gametype flag overrides; otherwise use enum-derived name
                    gametype_for_display = args.gametype
                    if not gametype_for_display and gametype_enum and gametype_enum.value > 0:
                        gametype_for_display = GAMETYPE_NAMES.get(gametype_enum, str(gametype_enum)).lower()

                    if args.simple:
                        print_scoreboard(players)
                    else:
                        print_scoreboard_rich(
                            players,
                            gametype=gametype_for_display,
                            all_players=all_indexed,
                            teams=teams,
                        )

                if args.save and players:
                    snapshot = build_snapshot(
                        players, source=source,
                        gametype_id=gametype_id_val, teams=teams,
                    )
                    filepath = save_game_history(snapshot, args.history_dir)
                    print(f"Saved to {filepath}")

            if args.poll <= 0:
                break

            time.sleep(args.poll)

    except KeyboardInterrupt:
        print("\nStopped.")

    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
