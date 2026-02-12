"""
Canonical address loader for Halo 2 Xbox memory constants.

Reads addresses.json once at import time and exposes all constants as
module-level variables for backward compatibility with halo2_structs.py
and live_stats.py.

Zero dependencies on other project modules (leaf module).
"""
import json
import os

# ---------------------------------------------------------------------------
# Load addresses.json
# ---------------------------------------------------------------------------

_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "addresses.json")

with open(_JSON_PATH) as _f:
    _DATA = json.load(_f)


def _parse_hex(value):
    """Convert '0x...' strings to int, pass ints through unchanged."""
    if isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return value


# ---------------------------------------------------------------------------
# Post-game addresses (halo2_structs.py constants)
# ---------------------------------------------------------------------------

_post = _DATA["post_game"]
_pgcr = _post["pgcr_display"]
_pcr = _post["pcr_fallback"]
_bp = _post["breakpoint"]
_gt_addrs = _post["gametype_addresses"]
_misc = _post["misc"]

# ADDRESSES dict — same keys and values as the old halo2_structs.ADDRESSES
ADDRESSES = {
    "gametype_enum": _parse_hex(_gt_addrs["xbox7887"]["address"]),
    "pcr_stats": _parse_hex(_pcr["player_base"]),
    "team_data": _parse_hex(_pcr["team_base"]),
    "profile_data": _parse_hex(_misc["profile_data"]),
    "str_kills": _parse_hex(_misc["str_kills"]),
    "str_deaths": _parse_hex(_misc["str_deaths"]),
}


def get_address(name: str) -> int:
    """Get Xbox virtual memory address by name."""
    return ADDRESSES.get(name, 0)


# PCR struct size
PCR_PLAYER_SIZE = _parse_hex(_pcr["player_stride"])

# PGCR Display constants
PGCR_DISPLAY_HEADER = _parse_hex(_pgcr["header"])
PGCR_DISPLAY_HEADER_SIZE = _parse_hex(_pgcr["header_size"])
PGCR_DISPLAY_GAMETYPE_OFFSET = _parse_hex(_pgcr["gametype_offset"])
PGCR_DISPLAY_GAMETYPE_ADDR = _parse_hex(_pgcr["gametype_addr"])
PGCR_DISPLAY_BASE = _parse_hex(_pgcr["player_base"])
PGCR_DISPLAY_SIZE = _parse_hex(_pgcr["player_stride"])

# Team data constants
TEAM_DATA_BASE = _parse_hex(_pcr["team_base"])
PGCR_DISPLAY_TEAM_BASE = _parse_hex(_pgcr["team_base"])
TEAM_DATA_STRIDE = _parse_hex(_pgcr["team_stride"])
MAX_TEAMS = _DATA["sizing"]["max_teams"]

# Breakpoint
PGCR_BREAKPOINT_ADDR = _parse_hex(_bp["pgcr_clear"])

# ---------------------------------------------------------------------------
# Live stats addresses (live_stats.py constants)
# ---------------------------------------------------------------------------

_live = _DATA["live_stats"]
_haloc = _live["haloc_offsets"]

XBE_BASE = _parse_hex(_live["xbe_base"])
PHYSICAL_BASE = _parse_hex(_live["physical_base"])

# Raw HaloCaster offsets (relative to XBE base)
HALOC_OFFSETS = {k: _parse_hex(v) for k, v in _haloc.items()}

# Key remapping: HALOC_OFFSETS key → LIVE_ADDRESSES key
_LIVE_KEY_REMAP = {
    "players": "players_ptr",
    "objects": "objects_ptr",
    "tags": "tags_ptr",
    "game_results_globals_extra": "game_results_extra",
}

# Xbox kernel virtual addresses (XBE_BASE + offset)
LIVE_ADDRESSES = {}
for _key, _offset in HALOC_OFFSETS.items():
    _live_key = _LIVE_KEY_REMAP.get(_key, _key)
    LIVE_ADDRESSES[_live_key] = XBE_BASE + _offset

# Yelo Carnage reference addresses
_yelo = _DATA["yelo"]
YELO_ADDRESSES = {
    "pgcr_breakpoint": _parse_hex(_yelo["pgcr_breakpoint"]),
    "ai_enable_patch": _parse_hex(_yelo["ai_enable_patch"]),
}

# Empirically discovered addresses
_disc = _DATA["discovered"]
DISCOVERED_ADDRESSES = {k: _parse_hex(v) for k, v in _disc.items()
                        if not k.startswith("_")}

# ---------------------------------------------------------------------------
# Structure sizes and strides (live_stats.py constants)
# ---------------------------------------------------------------------------

_structs = _DATA["structs"]

GAME_STATS_SIZE = _parse_hex(_structs["game_stats"]["stride"])
GAME_STATS_STRUCT = _parse_hex(_structs["game_stats"]["size"])
SESSION_PLAYER_SIZE = _parse_hex(_structs["session_player"]["size"])
WEAPON_STAT_SIZE = _parse_hex(_structs["weapon_stat"]["size"])
MEDAL_STATS_STRUCT = _parse_hex(_structs["medal_stats"]["size"])
WEAPON_COUNT = _DATA["sizing"]["weapon_count"]
LOBBY_PLAYER_SIZE = _parse_hex(_structs["lobby_player"]["size"])
MAX_PLAYERS = _DATA["sizing"]["max_players"]
VARIANT_INFO_SIZE = _parse_hex(_structs["variant_info"]["size"])

# ---------------------------------------------------------------------------
# Address helper functions (moved from live_stats.py)
# ---------------------------------------------------------------------------


def get_live_address(name: str) -> int:
    """Get Xbox kernel virtual memory address for live stats by name."""
    return LIVE_ADDRESSES.get(name, 0)


def haloc_to_xbox_virtual(haloc_offset: int) -> int:
    """Convert HaloCaster offset to Xbox kernel virtual address."""
    return XBE_BASE + haloc_offset


def xbox_virtual_to_physical(xbox_virtual: int) -> int:
    """Convert Xbox kernel virtual address to physical RAM address."""
    if xbox_virtual >= 0x80000000:
        return xbox_virtual - 0x80000000
    return xbox_virtual


def get_haloc_address(name: str) -> int:
    """Get physical address from HaloCaster offset name."""
    if name not in HALOC_OFFSETS:
        return 0
    xbox_virt = haloc_to_xbox_virtual(HALOC_OFFSETS[name])
    return xbox_virtual_to_physical(xbox_virt)
