"""
Halo 2 Memory Structures and Addresses

Based on analysis of:
- HaloCaster (xemuh2stats) - live in-game stats
- Yelo Carnage - post-game carnage report stats (via XBDM breakpoints)
- OpenSauce project - canonical structure definitions
  Source: https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp

Memory addresses are for retail Halo 2 Xbox v1.0/v1.5.
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import IntEnum, IntFlag


# =============================================================================
# Enumerations
# =============================================================================

class GameTeam(IntEnum):
    RED = 0
    BLUE = 1
    YELLOW = 2
    GREEN = 3
    PURPLE = 4
    ORANGE = 5
    BROWN = 6
    PINK = 7
    NEUTRAL = 8


class PlayerColor(IntEnum):
    WHITE = 0
    STEEL = 1
    RED = 2
    ORANGE = 3
    GOLD = 4
    OLIVE = 5
    GREEN = 6
    SAGE = 7
    CYAN = 8
    TEAL = 9
    COBALT = 10
    BLUE = 11
    VIOLET = 12
    PURPLE = 13
    PINK = 14
    CRIMSON = 15
    BROWN = 16
    TAN = 17


class CharacterType(IntEnum):
    MASTERCHIEF = 0
    DERVISH = 1
    SPARTAN = 2
    ELITE = 3


class Handicap(IntEnum):
    NONE = 0
    MINOR = 1
    MODERATE = 2
    SEVERE = 3


# Gametype enum - readable via XBDM at 0x50224C
# Source: xbox7887 memory research
class GameType(IntEnum):
    NONE = 0
    CTF = 1
    SLAYER = 2
    ODDBALL = 3
    KOTH = 4
    # 5 = race (deprecated), 6 = terminator (deprecated)
    JUGGERNAUT = 7
    TERRITORIES = 8
    ASSAULT = 9  # xbox7887: "bombs"


GAMETYPE_NAMES = {
    GameType.NONE: "None",
    GameType.CTF: "CTF",
    GameType.SLAYER: "Slayer",
    GameType.ODDBALL: "Oddball",
    GameType.KOTH: "KOTH",
    GameType.JUGGERNAUT: "Juggernaut",
    GameType.TERRITORIES: "Territories",
    GameType.ASSAULT: "Assault",
}


# From Yelo Carnage Stats.cs - GameResultsStatistic enum
class GameResultsStatistic(IntEnum):
    """Statistics tracked in game results (from Yelo Carnage)."""
    GAMES_PLAYED = 0
    GAMES_QUIT = 1
    GAMES_DISCONNECTED = 2
    GAMES_COMPLETED = 3
    GAMES_WON = 4
    GAMES_TIED = 5
    ROUNDS_WON = 6
    KILLS = 7
    ASSISTS = 8
    DEATHS = 9
    BETRAYALS = 10
    SUICIDES = 11
    MOST_KILLS_IN_A_ROW = 12
    SECONDS_ALIVE = 13
    CTF_FLAG_SCORES = 14
    CTF_FLAG_GRABS = 15
    CTF_FLAG_CARRIER_KILLS = 16
    CTF_FLAG_RETURNS = 17
    CTF_BOMB_SCORES = 18
    CTF_BOMB_PLANTS = 19
    CTF_BOMB_CARRIER_KILLS = 20
    CTF_BOMB_GRABS = 21
    CTF_BOMB_RETURNS = 22
    ODDBALL_TIME_WITH_BALL = 23
    ODDBALL_UNUSED = 24
    ODDBALL_KILLS_AS_CARRIER = 25
    ODDBALL_BALL_CARRIER_KILLS = 26
    KOTH_TIME_ON_HILL = 27
    KOTH_TOTAL_CONTROL_TIME = 28
    KOTH_NUMBER_OF_CONTROLS = 29  # unused
    KOTH_LONGEST_CONTROL_TIME = 30  # unused
    RACE_LAPS = 31  # unused
    RACE_TOTAL_LAP_TIME = 32  # unused
    RACE_FASTEST_LAP_TIME = 33  # unused
    HEADHUNTER_HEADS_PICKED_UP = 34  # unused
    HEADHUNTER_HEADS_DEPOSITED = 35  # unused
    HEADHUNTER_NUMBER_OF_DEPOSITS = 36  # unused
    HEADHUNTER_LARGEST_DEPOSIT = 37  # unused
    JUGGERNAUT_KILLS = 38
    JUGGERNAUT_KILLS_AS_JUGGERNAUT = 39
    JUGGERNAUT_TOTAL_CONTROL_TIME = 40
    JUGGERNAUT_NUMBER_OF_CONTROLS = 41  # unused
    JUGGERNAUT_LONGEST_CONTROL_TIME = 42  # unused
    TERRITORIES_TAKEN = 43
    TERRITORIES_LOST = 44


# From Yelo Carnage Stats.cs - GameResultsMedal enum
class GameResultsMedal(IntEnum):
    """Medal types from game results (from Yelo Carnage)."""
    MULTI_KILL_2 = 0       # Double Kill
    MULTI_KILL_3 = 1       # Triple Kill
    MULTI_KILL_4 = 2       # Overkill
    MULTI_KILL_5 = 3       # Killtacular
    MULTI_KILL_6 = 4       # Killtrocity
    MULTI_KILL_7_OR_MORE = 5  # Killimanjaro+
    SNIPER_KILL = 6
    COLLISION_KILL = 7     # Splatter
    BASH_KILL = 8          # Beat Down
    STEALTH_KILL = 9       # Assassination
    KILLED_VEHICLE = 10
    BOARDED_VEHICLE = 11   # Carjack
    GRENADE_STICK = 12     # Stick
    FIVE_KILLS_IN_A_ROW = 13   # Killing Spree
    TEN_KILLS_IN_A_ROW = 14    # Killing Frenzy
    FIFTEEN_KILLS_IN_A_ROW = 15  # Running Riot
    TWENTY_KILLS_IN_A_ROW = 16   # Rampage
    TWENTY_FIVE_KILLS_IN_A_ROW = 17  # Untouchable
    CTF_FLAG_GRAB = 18
    CTF_FLAG_CARRIER_KILL = 19
    CTF_FLAG_RETURNED = 20
    CTF_BOMB_PLANTED = 21
    CTF_BOMB_CARRIER_KILL = 22
    CTF_BOMB_DEFUSED = 23


# Medal display names (matching GameResultsMedal enum order)
MEDAL_NAMES = {
    GameResultsMedal.MULTI_KILL_2: "Double Kill",
    GameResultsMedal.MULTI_KILL_3: "Triple Kill",
    GameResultsMedal.MULTI_KILL_4: "Overkill",
    GameResultsMedal.MULTI_KILL_5: "Killtacular",
    GameResultsMedal.MULTI_KILL_6: "Killtrocity",
    GameResultsMedal.MULTI_KILL_7_OR_MORE: "Killimanjaro+",
    GameResultsMedal.SNIPER_KILL: "Sniper Kill",
    GameResultsMedal.COLLISION_KILL: "Splatter",
    GameResultsMedal.BASH_KILL: "Beat Down",
    GameResultsMedal.STEALTH_KILL: "Assassination",
    GameResultsMedal.KILLED_VEHICLE: "Destroyed Vehicle",
    GameResultsMedal.BOARDED_VEHICLE: "Carjack",
    GameResultsMedal.GRENADE_STICK: "Stick",
    GameResultsMedal.FIVE_KILLS_IN_A_ROW: "Killing Spree",
    GameResultsMedal.TEN_KILLS_IN_A_ROW: "Killing Frenzy",
    GameResultsMedal.FIFTEEN_KILLS_IN_A_ROW: "Running Riot",
    GameResultsMedal.TWENTY_KILLS_IN_A_ROW: "Rampage",
    GameResultsMedal.TWENTY_FIVE_KILLS_IN_A_ROW: "Untouchable",
    GameResultsMedal.CTF_FLAG_GRAB: "Flag Grab",
    GameResultsMedal.CTF_FLAG_CARRIER_KILL: "Flag Carrier Kill",
    GameResultsMedal.CTF_FLAG_RETURNED: "Flag Returned",
    GameResultsMedal.CTF_BOMB_PLANTED: "Bomb Planted",
    GameResultsMedal.CTF_BOMB_CARRIER_KILL: "Bomb Carrier Kill",
    GameResultsMedal.CTF_BOMB_DEFUSED: "Bomb Defused",
}


def decode_medals(medals_by_type: int) -> List[str]:
    """
    Decode medals_earned_by_type bitmask into list of medal names.

    Args:
        medals_by_type: Bitmask from PCRPlayerStats.medals_earned_by_type

    Returns:
        List of medal name strings for each set bit
    """
    earned = []
    for medal in GameResultsMedal:
        if medals_by_type & (1 << medal.value):
            earned.append(MEDAL_NAMES.get(medal, medal.name))
    return earned


def detect_gametype_from_medals(players) -> Optional[str]:
    """
    Auto-detect gametype from medal bitmasks and score string format.

    Detection order:
    1. CTF medals (bits 18-20) -> "ctf"
    2. Assault medals (bits 21-23) -> "assault"
    3. Time-format scores (e.g. "1:32") -> "oddball" (could also be KOTH)
    4. Otherwise -> None (likely Slayer, Juggernaut, or Territories)

    Returns:
        Gametype string or None if unable to determine
    """
    combined_medals = 0
    for p in players:
        combined_medals |= p.medals_earned_by_type

    CTF_BITS = (1 << 18) | (1 << 19) | (1 << 20)  # Flag Grab, Carrier Kill, Returned
    ASSAULT_BITS = (1 << 21) | (1 << 22) | (1 << 23)  # Bomb Planted, Carrier Kill, Defused

    if combined_medals & CTF_BITS:
        return "ctf"
    if combined_medals & ASSAULT_BITS:
        return "assault"

    # Detect time-based gametypes from score string format (e.g. "1:32", ":00")
    for p in players:
        if p.score_string and ':' in p.score_string:
            return "oddball"

    return None


# =============================================================================
# Memory Addresses
# =============================================================================
#
# Address Types:
# 1. XBDM Direct - Work directly with Xemu's XBDM (verified working)
# 2. PCR (Post-game) - Only populated after game ends (from Yelo/OpenSauce)
# 3. HaloCaster Offsets - Need XBE base translation for XBDM use
#
# HaloCaster Address Calculation:
#   Xbox Virtual = XBE_BASE + HaloCaster_Offset
#   XBE_BASE = 0x8005C000
#   Physical = Xbox Virtual - 0x80000000
#
# Source: https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp
# Also: Yelo Carnage Stats.cs - "1.0 Address: 0x55CAF0"

# XBE base address for Xbox virtual address calculation
XBE_BASE = 0x8005C000

# HaloCaster offsets (relative to XBE base 0x8005C000 in Xbox virtual memory)
# Source: Form1.cs resolve_addresses() lines 878-893
# Xbox Virtual Address = 0x8005C000 + offset
HALOC_OFFSETS = {
    "game_stats": 0x35ADF02,           # s_game_stats array, stride 0x36A per player
    "session_players": 0x35AD344,      # s_player_properties, stride 0xA4 per player
    "weapon_stats": 0x35ADFE0,         # Per-player per-weapon, stride 0x10 per weapon
    "medal_stats": 0x35ADF4E,          # Per-player medal counts, stride 0x36A per player
    "life_cycle": 0x35E4F04,           # Game state enum (0=None..7=Matchmaking)
    "post_game_report": 0x363A990,     # Post-game report, stride 0x114 per player
    "variant_info": 0x35AD0EC,         # Game variant: name, type, scenario path
    "profile_enabled": 0x3569128,      # Dedi mode toggle (bool)
    "game_engine_globals": 0x35A53B8,  # Game engine state
    "players": 0x35A44F4,              # Pointer to game_state_players
    "objects": 0x35BBBD0,              # Pointer to game_state_objects
    "game_results_globals": 0x35ACFB0, # Game results (players 0-4)
    "game_results_globals_extra": 0x35CF014,  # Game results (players 5-15)
    "disable_rendering": 0x3520E22,    # Rendering toggle (bool)
    "lobby_players": 0x35CC008,        # Lobby player data, stride 0x10C per player
    "tags": 0x360558C,                 # Tag database pointer (used for validation)
}

# Direct Xbox memory addresses (verified working with Xemu XBDM)
# These addresses work directly - no translation needed
ADDRESSES = {
    # Gametype enum - single int32 value
    # Source: xbox7887 memory research
    # Values: 0=None, 1=CTF, 2=Slayer, 3=Oddball, 4=KOTH, 7=Jugg, 8=Terr, 9=Assault
    "gametype_enum": 0x50224C,

    # Post-game Carnage Report stats (pcr_stat_player array)
    # Only populated AFTER game ends, shows zeros during gameplay
    # Size: 0x114 bytes per player, 16 players max
    # Source: Yelo Carnage Stats.cs - "1.0 Address: 0x55CAF0"
    "pcr_stats": 0x55CAF0,

    # Team data - contiguous after PCR player array (0x55CAF0 + 16*0x114 = 0x55DC30)
    # Stride: 0x84 per team, up to 8 teams
    # Source: xbox7887 memory research
    "team_data": 0x55DC30,

    # Profile/session data (found via memory scanning)
    # Contains player name but stats don't update during gameplay
    "profile_data": 0x53D000,

    # String table addresses (from v1.5 map file, verified working)
    "str_kills": 0x4603B8,
    "str_deaths": 0x4603A8,
}

# Yelo Carnage breakpoint and patch addresses
# Source: Yelo Carnage Program.Watch.cs
YELO_ADDRESSES = {
    # PGCR Breakpoint - Yelo sets a breakpoint here to detect when
    # the post-game carnage report is ready to be read
    # Usage: XBox.SetBreakPoint(0x233194)
    "pgcr_breakpoint": 0x233194,

    # AI Enable patch - allows AI in multiplayer
    # Yelo patches bytes at this address: 0x68, 0xF6, 0x79, 0x1C, 0x00, 0xC3
    # Usage: XBox.SetMemory(0x1C79E5, 0x68, 0xF6, 0x79, 0x1C, 0x00, 0xC3)
    "ai_enable_patch": 0x1C79E5,
}

# Empirically discovered Xbox addresses (via diff_monitor.py analysis)
# These are actual Xbox physical addresses found during gameplay
DISCOVERED_ADDRESSES = {
    # Player profile region - contains player name in UTF-16LE
    # Stride: 0x90 (144 bytes) per player
    "profile_base": 0x53E0C0,
    "profile_stride": 0x90,

    # Session player data - contains player name near PCR area
    # Stride: 0x1F8 (504 bytes) per player
    "session_player_base": 0x55D790,
    "session_player_stride": 0x1F8,

    # Player structure with name and partial stats
    # Contains: header, player name (UTF-16), stats fields
    "player_struct_base": 0x53D000,

    # Addresses that change during gameplay (position, timers)
    # These update in real-time but are not stats
    "game_state_area": 0x55C300,
    "game_state_extended": 0x510000,

    # Cached stats values (found but don't update in real-time)
    # These may snapshot at certain game events
    "cached_deaths_array": 0x53D08C,  # 16 int32s, one per player
    "cached_deaths_pcr": 0x55C580,
    "cached_deaths_pcr2": 0x55C6F0,

    # PGCR DISPLAY STRUCTURE (found during empirical testing!)
    # This is different from PCR at 0x55CAF0 - contains actual display data
    # Only populated during post-game carnage report screen
    "pgcr_display_base": 0x56B900,
    "pgcr_display_size": 0x200,  # At least 512 bytes per player
}

# Important findings from empirical analysis:
# 1. PCR at 0x55CAF0 only populates AFTER game ends (and may show zeros!)
# 2. PGCR DISPLAY at 0x56B900 contains actual data shown on post-game screen
# 3. HaloCaster's live stats addresses are Windows HOST process addresses,
#    not Xbox addresses - they cannot be used with XBDM
# 4. The "cached" addresses above snapshot at game events but don't update
#    in real-time during active gameplay
# 5. For true live stats, HaloCaster uses QMP to read from XEMU's Windows
#    process memory, which is a completely different address space

# PGCR Display Structure offsets (at 0x56B900):
# NOTE: This structure only populates during the post-game carnage screen!
# NOTE: Different layout than PCR at 0x55CAF0!
#
# Verified offsets (tested with 0 kills, 4 deaths, 4 suicides, 109 shots, 1st place):
#   0x60: Kills (int32) - showed 0
#   0x64: Deaths (int32) - showed 0 (duplicate? or different meaning)
#   0x68: Assists (int32) - showed 0
#   0x6C: Suicides (int32) - showed 0 (duplicate? or different meaning)
#   0x84: Place (int32) - showed 1 (1st place)
#   0x90: Player name (UTF-16LE, 32 bytes) - "Default"
#   0xCC: Score string display (UTF-16LE) - "-4"
#   0xF4: Deaths (int32) - showed 4 ✓
#   0xFC: Suicides (int32) - showed 4 ✓
#   0x114: Total shots fired (int32) - showed 109 ✓
#   0x118: Shots hit (int32) - showed 0 ✓
#   0x11C: Headshots (int32) - showed 0 ✓
#   0x120: Killed-by array start (16 int32s)
#          - Slot 0 = killed by self (suicides) = 4 ✓
#          - Slot 1-15 = killed by player N
#   0x168: Place string display (UTF-16LE) - "1st"

# Live stats XBDM Addresses
# XBDM (via xbdm_gdb_bridge/GDB) reads Xbox virtual addresses.
# HaloCaster offsets are XBE-relative. The Xbox kernel virtual address is:
#   Xbox VA = XBE_BASE + offset = 0x8005C000 + offset
#
# The 0x80000000+ range is the kernel's contiguous physical RAM mapping.
# User-space VAs in the 0x036xxxxx range are NOT mapped, so we must use
# kernel VAs (0x83xxxxxx) for XBDM reads of game engine data.
#
# Physical address (for reference only): 0x5C000 + offset
PHYSICAL_BASE = 0x5C000  # XBE_BASE - 0x80000000

LIVE_ADDRESSES = {
    "game_stats": XBE_BASE + HALOC_OFFSETS["game_stats"],                # 0x83609F02
    "weapon_stats": XBE_BASE + HALOC_OFFSETS["weapon_stats"],            # 0x83609FE0
    "medal_stats": XBE_BASE + HALOC_OFFSETS["medal_stats"],              # 0x83609F4E
    "session_players": XBE_BASE + HALOC_OFFSETS["session_players"],      # 0x83609344
    "life_cycle": XBE_BASE + HALOC_OFFSETS["life_cycle"],                # 0x83640F04
    "variant_info": XBE_BASE + HALOC_OFFSETS["variant_info"],            # 0x836090EC
    "post_game_report": XBE_BASE + HALOC_OFFSETS["post_game_report"],    # 0x83696990
    "players_ptr": XBE_BASE + HALOC_OFFSETS["players"],                  # 0x835FA4F4
    "objects_ptr": XBE_BASE + HALOC_OFFSETS["objects"],                  # 0x83617BD0
    "tags_ptr": XBE_BASE + HALOC_OFFSETS["tags"],                        # 0x8366158C
    "game_results_extra": XBE_BASE + HALOC_OFFSETS["game_results_globals_extra"],  # 0x8362B014
    "game_results_globals": XBE_BASE + HALOC_OFFSETS["game_results_globals"],      # 0x83608FB0
    "lobby_players": XBE_BASE + HALOC_OFFSETS.get("lobby_players", 0x35CC008),     # 0x8362C008
    "profile_enabled": XBE_BASE + HALOC_OFFSETS.get("profile_enabled", 0x3569128), # 0x835C5128
}

# Life cycle states (from HaloCaster life_cycle enum)
class LifeCycle(IntEnum):
    NONE = 0
    PRE_GAME = 1
    IN_LOBBY = 2
    IN_GAME = 3
    POST_GAME = 4

def get_address(name: str) -> int:
    """Get Xbox virtual memory address by name."""
    return ADDRESSES.get(name, 0)


def haloc_to_xbox_virtual(haloc_offset: int) -> int:
    """
    Convert HaloCaster offset to Xbox virtual address.

    Args:
        haloc_offset: Offset from HaloCaster (e.g., 0x35ADF02)

    Returns:
        Xbox virtual address (e.g., 0x83603B02)

    Note:
        These addresses may not work directly with XBDM on Xemu.
        Further translation may be needed.
    """
    return XBE_BASE + haloc_offset


def xbox_virtual_to_physical(xbox_virtual: int) -> int:
    """
    Convert Xbox virtual address to physical RAM address.

    Args:
        xbox_virtual: Xbox virtual address (0x80000000+)

    Returns:
        Physical address (usable with XBDM)
    """
    if xbox_virtual >= 0x80000000:
        return xbox_virtual - 0x80000000
    return xbox_virtual


def get_haloc_address(name: str) -> int:
    """
    Get physical address from HaloCaster offset name.

    This converts HaloCaster offsets to addresses that might work with XBDM.
    """
    if name not in HALOC_OFFSETS:
        return 0
    xbox_virt = haloc_to_xbox_virtual(HALOC_OFFSETS[name])
    return xbox_virtual_to_physical(xbox_virt)


# Structure sizes and strides
GAME_STATS_SIZE = 0x36A      # Stride between players in game_stats/weapon_stats/medal_stats
GAME_STATS_STRUCT = 0x36     # Actual s_game_stats size (54 bytes)
SESSION_PLAYER_SIZE = 0xA4   # Size of s_player_properties (164 bytes)
PCR_PLAYER_SIZE = 0x114      # Size of pcr_stat_player (276 bytes)
WEAPON_STAT_SIZE = 0x10      # Size per weapon stats entry (16 bytes)
MEDAL_STATS_STRUCT = 0x30    # Actual s_medal_stats size (48 bytes, 24 ushorts)
WEAPON_COUNT = 41            # Number of weapon types (indices 0-40)
LOBBY_PLAYER_SIZE = 0x10C    # Lobby player entry stride (268 bytes)


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class GameStats:
    """
    Live in-game statistics for a player.

    Based on s_game_stats from HaloCaster.
    Total struct size: 54 bytes (0x36)
    """
    kills: int = 0
    assists: int = 0
    deaths: int = 0
    betrayals: int = 0
    suicides: int = 0
    best_spree: int = 0
    total_time_alive: int = 0

    # CTF
    ctf_scores: int = 0
    ctf_flag_steals: int = 0
    ctf_flag_saves: int = 0
    ctf_unknown: int = 0

    # Assault
    assault_suicides: int = 0
    assault_scores: int = 0
    assault_bomber_kills: int = 0
    assault_bomb_grabbed: int = 0
    assault_bomb_unknown: int = 0

    # Oddball
    oddball_score: int = 0  # uint32
    oddball_ball_kills: int = 0
    oddball_carried_kills: int = 0

    # King of the Hill
    koth_kills_as_king: int = 0
    koth_kings_killed: int = 0

    # Juggernaut
    juggernauts_killed: int = 0
    kills_as_juggernaut: int = 0
    juggernaut_time: int = 0

    # Territories
    territories_taken: int = 0
    territories_lost: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'GameStats':
        """Parse GameStats from raw memory bytes."""
        if len(data) < 54:
            raise ValueError(f"Need at least 54 bytes, got {len(data)}")

        # Unpack all fields (little-endian)
        # Format: 17 ushorts, 1 uint, 8 more ushorts
        fields = struct.unpack('<17H I 8H', data[:54])

        return cls(
            kills=fields[0],
            assists=fields[1],
            deaths=fields[2],
            betrayals=fields[3],
            suicides=fields[4],
            best_spree=fields[5],
            total_time_alive=fields[6],
            ctf_scores=fields[7],
            ctf_flag_steals=fields[8],
            ctf_flag_saves=fields[9],
            ctf_unknown=fields[10],
            assault_suicides=fields[11],
            assault_scores=fields[12],
            assault_bomber_kills=fields[13],
            assault_bomb_grabbed=fields[14],
            assault_bomb_unknown=fields[15],
            oddball_score=fields[17],  # This is the uint32 at index 17
            oddball_ball_kills=fields[18],
            oddball_carried_kills=fields[19],
            koth_kills_as_king=fields[20],
            koth_kings_killed=fields[21],
            juggernauts_killed=fields[22],
            kills_as_juggernaut=fields[23],
            juggernaut_time=fields[24],
            territories_taken=fields[25],
            territories_lost=fields[26],
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "kills": self.kills,
            "assists": self.assists,
            "deaths": self.deaths,
            "betrayals": self.betrayals,
            "suicides": self.suicides,
            "best_spree": self.best_spree,
            "total_time_alive": self.total_time_alive,
            "ctf": {
                "scores": self.ctf_scores,
                "flag_steals": self.ctf_flag_steals,
                "flag_saves": self.ctf_flag_saves,
            },
            "assault": {
                "suicides": self.assault_suicides,
                "scores": self.assault_scores,
                "bomber_kills": self.assault_bomber_kills,
                "bomb_grabbed": self.assault_bomb_grabbed,
            },
            "oddball": {
                "score": self.oddball_score,
                "ball_kills": self.oddball_ball_kills,
                "carried_kills": self.oddball_carried_kills,
            },
            "koth": {
                "kills_as_king": self.koth_kills_as_king,
                "kings_killed": self.koth_kings_killed,
            },
            "juggernaut": {
                "juggernauts_killed": self.juggernauts_killed,
                "kills_as_juggernaut": self.kills_as_juggernaut,
                "time": self.juggernaut_time,
            },
            "territories": {
                "taken": self.territories_taken,
                "lost": self.territories_lost,
            },
        }


# Weapon indices (0-40) and display names
# Source: HaloCaster weapon_stat.cs weapon_list + friend's Executive Resolver data
WEAPON_NAMES = [
    "Guardians",            # 0
    "Falling Damage",       # 1
    "Collision Damage",     # 2
    "Generic Melee",        # 3
    "Generic Explosion",    # 4
    "Magnum",               # 5
    "Plasma Pistol",        # 6
    "Needler",              # 7
    "SMG",                  # 8
    "Plasma Rifle",         # 9
    "Battle Rifle",         # 10
    "Carbine",              # 11
    "Shotgun",              # 12
    "Sniper Rifle",         # 13
    "Beam Rifle",           # 14
    "Brute Plasma Rifle",   # 15
    "Rocket Launcher",      # 16
    "Fuel Rod",             # 17
    "Brute Shot",           # 18
    "Disintegrator",        # 19
    "Sentinel Beam",        # 20
    "Sentinel RPG",         # 21
    "Energy Sword",         # 22
    "Frag Grenade",         # 23
    "Plasma Grenade",       # 24
    "Flag Melee",           # 25
    "Bomb Melee",           # 26
    "Ball Melee",           # 27
    "Human Turret",         # 28
    "Plasma Turret",        # 29
    "Banshee",              # 30
    "Ghost",                # 31
    "Mongoose",             # 32
    "Scorpion",             # 33
    "Spectre Driver",       # 34
    "Spectre Gunner",       # 35
    "Warthog Driver",       # 36
    "Warthog Gunner",       # 37
    "Wraith",               # 38
    "Tank",                 # 39
    "Bomb Explosion",       # 40
]


@dataclass
class WeaponStat:
    """
    Per-weapon statistics for a single player.

    Source: HaloCaster weapon_stat.cs
    Stride: 0x10 (16 bytes) per weapon, but only 12 bytes of data used.
    Note: gap at offset +0x04 (2 bytes unused between deaths and suicide).
    """
    kills: int = 0
    deaths: int = 0
    suicide: int = 0
    shots_fired: int = 0
    shots_hit: int = 0
    head_shots: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'WeaponStat':
        """Parse WeaponStat from 16 bytes of raw memory."""
        if len(data) < 14:
            raise ValueError(f"Need at least 14 bytes, got {len(data)}")
        # +0x00: kills(2) +0x02: deaths(2) +0x04: gap(2) +0x06: suicide(2)
        # +0x08: shots_fired(2) +0x0A: shots_hit(2) +0x0C: head_shots(2)
        kills, deaths, _, suicide, shots_fired, shots_hit, head_shots = \
            struct.unpack('<7H', data[:14])
        return cls(
            kills=kills, deaths=deaths, suicide=suicide,
            shots_fired=shots_fired, shots_hit=shots_hit, head_shots=head_shots,
        )

    def to_dict(self) -> dict:
        return {
            "kills": self.kills, "deaths": self.deaths, "suicide": self.suicide,
            "shots_fired": self.shots_fired, "shots_hit": self.shots_hit,
            "head_shots": self.head_shots,
        }


@dataclass
class MedalStats:
    """
    Per-player medal counts.

    Source: HaloCaster medal_stats.cs
    Total struct size: 48 bytes (0x30), 24 ushorts.
    Base: medal_stats + (player_index * 0x36A)
    Players 5+: game_results_globals_extra + 0x4C + ((player_index - 5) * 0x36A)
    """
    double_kill: int = 0
    triple_kill: int = 0
    killtacular: int = 0
    kill_frenzy: int = 0
    killtrocity: int = 0
    killamanjaro: int = 0
    sniper_kill: int = 0
    road_kill: int = 0
    bone_cracker: int = 0
    assassin: int = 0
    vehicle_destroyed: int = 0
    car_jacking: int = 0
    stick_it: int = 0
    killing_spree: int = 0
    running_riot: int = 0
    rampage: int = 0
    berserker: int = 0
    over_kill: int = 0
    flag_taken: int = 0
    flag_carrier_kill: int = 0
    flag_returned: int = 0
    bomb_planted: int = 0
    bomb_carrier_kill: int = 0
    bomb_returned: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'MedalStats':
        """Parse MedalStats from raw memory bytes."""
        if len(data) < 48:
            raise ValueError(f"Need at least 48 bytes, got {len(data)}")
        fields = struct.unpack('<24H', data[:48])
        return cls(
            double_kill=fields[0], triple_kill=fields[1],
            killtacular=fields[2], kill_frenzy=fields[3],
            killtrocity=fields[4], killamanjaro=fields[5],
            sniper_kill=fields[6], road_kill=fields[7],
            bone_cracker=fields[8], assassin=fields[9],
            vehicle_destroyed=fields[10], car_jacking=fields[11],
            stick_it=fields[12], killing_spree=fields[13],
            running_riot=fields[14], rampage=fields[15],
            berserker=fields[16], over_kill=fields[17],
            flag_taken=fields[18], flag_carrier_kill=fields[19],
            flag_returned=fields[20], bomb_planted=fields[21],
            bomb_carrier_kill=fields[22], bomb_returned=fields[23],
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v > 0}

    def total(self) -> int:
        return sum(self.__dict__.values())


@dataclass
class VariantInfo:
    """
    Current game variant info.

    Source: HaloCaster variant_details.cs
    Base: variant_info address
    """
    variant_name: str = ""
    game_type: int = 0
    scenario_path: str = ""

    GAME_TYPE_NAMES = {
        0: "None", 1: "CTF", 2: "Slayer", 3: "Oddball",
        4: "KOTH", 7: "Juggernaut", 8: "Territories",
        9: "Assault", 11: "VIP",
    }

    @classmethod
    def from_bytes(cls, data: bytes) -> 'VariantInfo':
        """Parse VariantInfo from raw memory bytes."""
        if len(data) < 0x131:
            raise ValueError(f"Need at least 305 bytes, got {len(data)}")
        # +0x00: variant name (Unicode, 16 wchars = 32 bytes)
        try:
            variant_name = data[0:32].decode('utf-16-le').rstrip('\x00')
        except:
            variant_name = ""
        # +0x40: game type enum (1 byte)
        game_type = data[0x40]
        # +0x130: scenario path (ASCII, 256 bytes)
        try:
            scenario_path = data[0x130:0x230].split(b'\x00')[0].decode('ascii')
        except:
            scenario_path = ""
        return cls(variant_name=variant_name, game_type=game_type, scenario_path=scenario_path)

    @property
    def game_type_name(self) -> str:
        return self.GAME_TYPE_NAMES.get(self.game_type, f"Unknown({self.game_type})")

    def to_dict(self) -> dict:
        return {
            "variant_name": self.variant_name,
            "game_type": self.game_type,
            "game_type_name": self.game_type_name,
            "scenario_path": self.scenario_path,
        }


@dataclass
class PlayerProperties:
    """
    Player session properties (name, team, appearance, etc.)

    Based on s_player_properties from HaloCaster.
    Total struct size: 164 bytes (0xA4)
    """
    player_name: str = ""
    team: GameTeam = GameTeam.NEUTRAL
    primary_color: PlayerColor = PlayerColor.WHITE
    secondary_color: PlayerColor = PlayerColor.WHITE
    tertiary_color: PlayerColor = PlayerColor.WHITE
    quaternary_color: PlayerColor = PlayerColor.WHITE
    character_type: CharacterType = CharacterType.SPARTAN
    handicap: Handicap = Handicap.NONE
    displayed_skill: int = 0
    overall_skill: int = 0
    is_griefer: bool = False

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PlayerProperties':
        """Parse PlayerProperties from raw memory bytes."""
        if len(data) < 0xA4:
            raise ValueError(f"Need at least 164 bytes, got {len(data)}")

        # Player name is wide string (UTF-16LE) at offset 0, 16 chars max
        name_bytes = data[0:32]
        try:
            name = name_bytes.decode('utf-16-le').rstrip('\x00')
        except:
            name = ""

        # s_player_profile_traits at offset 0x40 (verified from HaloCaster real_time_player_stats.cs)
        # Layout: name(32) + spawn_protection_time(4) + gap_24(28) = 0x40
        profile_offset = 0x40

        # s_player_profile: 4 color bytes + character_type + emblem_info(3)
        primary = data[profile_offset] if profile_offset < len(data) else 0
        secondary = data[profile_offset + 1] if profile_offset + 1 < len(data) else 0
        tertiary = data[profile_offset + 2] if profile_offset + 2 < len(data) else 0
        quaternary = data[profile_offset + 3] if profile_offset + 3 < len(data) else 0
        char_type = data[profile_offset + 4] if profile_offset + 4 < len(data) else 0

        # After profile_traits(16) + clan_name(32) + clan_identifiers(12) = +0x7C
        # Verified from HaloCaster s_player_properties struct layout
        team = data[0x7C] if 0x7C < len(data) else 8
        handicap = data[0x7D] if 0x7D < len(data) else 0
        displayed_skill = data[0x7E] if 0x7E < len(data) else 0
        overall_skill = data[0x7F] if 0x7F < len(data) else 0
        is_griefer = data[0x80] if 0x80 < len(data) else 0

        return cls(
            player_name=name,
            team=GameTeam(min(team, 8)),
            primary_color=PlayerColor(min(primary, 17)),
            secondary_color=PlayerColor(min(secondary, 17)),
            tertiary_color=PlayerColor(min(tertiary, 17)),
            quaternary_color=PlayerColor(min(quaternary, 17)),
            character_type=CharacterType(min(char_type, 3)),
            handicap=Handicap(min(handicap, 3)),
            displayed_skill=displayed_skill,
            overall_skill=overall_skill,
            is_griefer=bool(is_griefer),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.player_name,
            "team": self.team.name.lower(),
            "character": self.character_type.name.lower(),
            "colors": {
                "primary": self.primary_color.name.lower(),
                "secondary": self.secondary_color.name.lower(),
                "tertiary": self.tertiary_color.name.lower(),
                "quaternary": self.quaternary_color.name.lower(),
            },
            "handicap": self.handicap.name.lower(),
            "skill": {
                "displayed": self.displayed_skill,
                "overall": self.overall_skill,
            },
            "is_griefer": self.is_griefer,
        }


@dataclass
class PCRPlayerStats:
    """
    Post-game Carnage Report stats (pcr_stat_player from OpenSauce).

    Source: https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp
    Also: Yelo Carnage Stats.cs

    Structure layout (total size: 0x114 = 276 bytes):
        0x00: PlayerName[16]     (wchar_t, 32 bytes)
        0x20: DisplayName[16]    (wchar_t, 32 bytes)
        0x40: ScoreString[16]    (wchar_t, 32 bytes)
        0x60: Kills              (int32)
        0x64: Deaths             (int32)
        0x68: Assists            (int32)
        0x6C: Suicides           (int32)
        0x70: Place              (int16)
        0x72: Unknown            (int16)
        0x74: Unknown            (byte + pad24)
        0x78: Unknown            (int32)
        0x7C: MedalsEarned       (int32)
        0x80: MedalsEarnedByType (flags)
        0x84: TotalShots         (int32)
        0x88: ShotsHit           (int32)
        0x8C: HeadShots          (int32)
        0x90: Killed[16]         (int32 array - who you killed, by player index)
        0xD0: Unknown[4]         (16-byte structure)
        0xE0: PlaceString[16]    (wchar_t, 32 bytes)
        0x100: Unknown[3]        (12-byte structure)
        0x10C: GameTypeValue0    (int32 - varies by gametype)
        0x110: GameTypeValue1    (int32 - varies by gametype)

    GameType-specific values at 0x10C/0x110 (union, from OpenSauce):
        CTF:         FlagCarrierKills (Flag Saves), FlagGrabs (Flag Steals)
        Slayer:      AverageLife, MostKillsInARow (Best Spree)
        Oddball:     BallCarrierKills, KillsAsCarrier
        KOTH:        TotalControlTime, TimeOnHill
        Juggernaut:  JuggernautKills, KillsAsJuggernaut
        Territories: TerritoriesTaken, TerritoriesLost
        Assault:     BombGrabs, BombCarrierKills
    """
    player_name: str = ""
    display_name: str = ""
    score_string: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    suicides: int = 0
    place: int = 0
    place_string: str = ""
    medals_earned: int = 0
    medals_earned_by_type: int = 0  # Bitmask of medal types
    total_shots: int = 0
    shots_hit: int = 0
    headshots: int = 0
    killed: List[int] = field(default_factory=list)  # 16 entries: who you killed
    # Gametype-specific stats
    gametype_value0: int = 0
    gametype_value1: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PCRPlayerStats':
        """Parse PCR stats from raw memory bytes."""
        if len(data) < PCR_PLAYER_SIZE:
            raise ValueError(f"Need at least {PCR_PLAYER_SIZE} bytes")

        # Names at offsets 0x00, 0x20, and 0x40 (16 wide chars each)
        try:
            player_name = data[0:32].decode('utf-16-le').rstrip('\x00')
            display_name = data[0x20:0x40].decode('utf-16-le').rstrip('\x00')
            score_string = data[0x40:0x60].decode('utf-16-le').rstrip('\x00')
        except:
            player_name = ""
            display_name = ""
            score_string = ""

        # Core stats at offset 0x60
        kills, deaths, assists, suicides = struct.unpack('<IIII', data[0x60:0x70])

        # Place at 0x70
        place = struct.unpack('<H', data[0x70:0x72])[0]

        # Medals at 0x7C and 0x80
        medals_earned = struct.unpack('<I', data[0x7C:0x80])[0]
        medals_by_type = struct.unpack('<I', data[0x80:0x84])[0]

        # Shots at 0x84
        total_shots, shots_hit, headshots = struct.unpack('<III', data[0x84:0x90])

        # Killed array at 0x90 (16 ints - who you killed)
        killed = list(struct.unpack('<16I', data[0x90:0xD0]))

        # Place string at 0xE0
        try:
            place_string = data[0xE0:0x100].decode('utf-16-le').rstrip('\x00')
        except:
            place_string = ""

        # Gametype-specific values at 0x10C
        gametype_value0 = struct.unpack('<I', data[0x10C:0x110])[0]
        gametype_value1 = struct.unpack('<I', data[0x110:0x114])[0]

        return cls(
            player_name=player_name,
            display_name=display_name,
            score_string=score_string,
            kills=kills,
            deaths=deaths,
            assists=assists,
            suicides=suicides,
            place=place,
            place_string=place_string,
            medals_earned=medals_earned,
            medals_earned_by_type=medals_by_type,
            total_shots=total_shots,
            shots_hit=shots_hit,
            headshots=headshots,
            killed=killed,
            gametype_value0=gametype_value0,
            gametype_value1=gametype_value1,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        accuracy = (self.shots_hit / self.total_shots * 100) if self.total_shots > 0 else 0

        return {
            "name": self.player_name,
            "display_name": self.display_name,
            "score_string": self.score_string,
            "place": self.place,
            "place_string": self.place_string,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "suicides": self.suicides,
            "kd_ratio": round(self.kills / max(self.deaths, 1), 2),
            "medals": {
                "total": self.medals_earned,
                "by_type": self.medals_earned_by_type,
            },
            "accuracy": {
                "total_shots": self.total_shots,
                "shots_hit": self.shots_hit,
                "headshots": self.headshots,
                "percentage": round(accuracy, 1),
            },
            "killed": self.killed,
            "gametype_values": [self.gametype_value0, self.gametype_value1],
        }

    def get_gametype_stats(self, gametype: str) -> dict:
        """
        Get gametype-specific interpretation of values at 0x10C/0x110.

        Args:
            gametype: One of "ctf", "slayer", "oddball", "koth", "juggernaut",
                      "territories", "assault"

        Returns:
            Dictionary with gametype-specific stat names and values
        """
        mappings = {
            "ctf": {"Flag Saves": self.gametype_value0, "Flag Steals": self.gametype_value1},
            "slayer": {"Avg Life": self.gametype_value0, "Best Spree": self.gametype_value1},
            "oddball": {"Ball Carrier Kills": self.gametype_value0, "Kills As Carrier": self.gametype_value1},
            "koth": {"Control Time": self.gametype_value0, "Time On Hill": self.gametype_value1},
            "juggernaut": {"Juggernaut Kills": self.gametype_value0, "Kills As Juggernaut": self.gametype_value1},
            "territories": {"Territories Taken": self.gametype_value0, "Territories Lost": self.gametype_value1},
            "assault": {"Bomb Grabs": self.gametype_value0, "Bomb Carrier Kills": self.gametype_value1},
        }
        return mappings.get(gametype.lower(), {"value0": self.gametype_value0, "value1": self.gametype_value1})


@dataclass
class PGCRDisplayStats:
    """
    Post-Game Carnage Report DISPLAY structure (empirically discovered).

    This is the structure that populates the actual PGCR screen display.
    Located at 0x56B900 (different from PCR at 0x55CAF0!).
    Only populated during the post-game carnage report screen.

    NOTE: This structure has a DIFFERENT layout than pcr_stat_player!

    Empirically verified offsets (tested with known stats):
        0x84:  Place (int32) - 1st, 2nd, etc.
        0x90:  Player name (UTF-16LE, 32 bytes)
        0xCC:  Score string display (UTF-16LE) - e.g., "-4"
        0xF0:  Kills (int32) - verified: helldotcom=11
        0xF4:  Deaths (int32)
        0xF8:  Assists (int32) - unverified offset, adjacent to kills/deaths
        0xFC:  Suicides (int32)
        0x114: Total shots fired (int32)
        0x118: Shots hit (int32)
        0x11C: Headshots (int32)
        0x120: Killed-by array (16 int32s) - killed_by[0] = self/suicides
        0x168: Place string (UTF-16LE) - "1st", "2nd", etc.
    """
    player_name: str = ""
    score_string: str = ""
    place: int = 0
    place_string: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    suicides: int = 0
    total_shots: int = 0
    shots_hit: int = 0
    headshots: int = 0
    killed_by: List[int] = field(default_factory=list)  # 16 entries

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PGCRDisplayStats':
        """Parse PGCR display stats from raw memory bytes."""
        if len(data) < 0x200:
            raise ValueError(f"Need at least 512 bytes, got {len(data)}")

        # Place at 0x84
        place = struct.unpack('<I', data[0x84:0x88])[0]

        # Player name at 0x90
        try:
            player_name = data[0x90:0xB0].decode('utf-16-le').rstrip('\x00')
        except:
            player_name = ""

        # Score string at 0xCC
        try:
            score_string = data[0xCC:0xEC].decode('utf-16-le').rstrip('\x00')
        except:
            score_string = ""

        # Stats - kills at 0xF0 verified empirically (helldotcom=11)
        kills = struct.unpack('<I', data[0xF0:0xF4])[0]
        deaths = struct.unpack('<I', data[0xF4:0xF8])[0]
        assists = struct.unpack('<I', data[0xF8:0xFC])[0]
        suicides = struct.unpack('<I', data[0xFC:0x100])[0]
        total_shots = struct.unpack('<I', data[0x114:0x118])[0]
        shots_hit = struct.unpack('<I', data[0x118:0x11C])[0]
        headshots = struct.unpack('<I', data[0x11C:0x120])[0]

        # Killed-by array at 0x120 (16 ints)
        killed_by = list(struct.unpack('<16I', data[0x120:0x160]))

        # Place string at 0x168
        try:
            place_string = data[0x168:0x188].decode('utf-16-le').rstrip('\x00')
        except:
            place_string = ""

        return cls(
            player_name=player_name,
            score_string=score_string,
            place=place,
            place_string=place_string,
            kills=kills,
            deaths=deaths,
            assists=assists,
            suicides=suicides,
            total_shots=total_shots,
            shots_hit=shots_hit,
            headshots=headshots,
            killed_by=killed_by,
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        accuracy = (self.shots_hit / self.total_shots * 100) if self.total_shots > 0 else 0

        return {
            "name": self.player_name,
            "score_string": self.score_string,
            "place": self.place,
            "place_string": self.place_string,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "suicides": self.suicides,
            "accuracy": {
                "total_shots": self.total_shots,
                "shots_hit": self.shots_hit,
                "headshots": self.headshots,
                "percentage": round(accuracy, 1),
            },
            "killed_by": self.killed_by,
        }


@dataclass
class PlayerStats:
    """Combined player statistics (properties + game stats)."""
    index: int
    properties: PlayerProperties
    game_stats: GameStats
    address: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "index": self.index,
            "player": self.properties.to_dict(),
            "stats": self.game_stats.to_dict(),
            "_debug": {
                "address": f"0x{self.address:08X}",
            }
        }


# =============================================================================
# Helper Functions
# =============================================================================

def calculate_pcr_address(player_index: int) -> int:
    """
    Calculate memory address for player's PCR (Post-game Carnage Report) stats.

    This is the primary stats structure for Halo 2.
    Address: 0x55CAF0 + (player_index * 0x114)

    Args:
        player_index: Player slot (0-15)

    Returns:
        Xbox virtual memory address
    """
    base = get_address("pcr_stats")
    return base + (player_index * PCR_PLAYER_SIZE)


# Convenience alias
calculate_player_stats_address = calculate_pcr_address


def calculate_live_stats_address(player_index: int) -> int:
    """
    Calculate memory address for player's LIVE game stats during gameplay.

    This reads from the real-time stats structure used by HaloCaster.
    Address: LIVE_ADDRESSES["game_stats"] + (player_index * GAME_STATS_SIZE)

    For players 5-15, stats are stored in a separate overflow area.

    Args:
        player_index: Player slot (0-15)

    Returns:
        Xbox virtual memory address for live stats
    """
    if player_index <= 4:
        return LIVE_ADDRESSES["game_stats"] + (player_index * GAME_STATS_SIZE)
    else:
        # Players 5-15 are in the "extra" region
        return LIVE_ADDRESSES["game_results_extra"] + ((player_index - 5) * GAME_STATS_SIZE)


def calculate_session_player_address(player_index: int) -> int:
    """
    Calculate memory address for player's session properties (name, team, etc.)

    Args:
        player_index: Player slot (0-15)

    Returns:
        Xbox virtual memory address for session player data
    """
    return LIVE_ADDRESSES["session_players"] + (player_index * SESSION_PLAYER_SIZE)


def calculate_medal_stats_address(player_index: int) -> int:
    """
    Calculate memory address for player's medal stats during gameplay.

    Base: medal_stats + (player_index * 0x36A)
    Players 5+: game_results_globals_extra + 0x4C + ((player_index - 5) * 0x36A)
    """
    if player_index <= 4:
        return LIVE_ADDRESSES["medal_stats"] + (player_index * GAME_STATS_SIZE)
    else:
        return LIVE_ADDRESSES["game_results_extra"] + 0x4C + ((player_index - 5) * GAME_STATS_SIZE)


def calculate_weapon_stats_address(player_index: int, weapon_index: int = 0) -> int:
    """
    Calculate memory address for player's weapon stats during gameplay.

    Base: weapon_stats + (player_index * 0x36A) + (weapon_index * 0x10)
    Players 5+: game_results_globals_extra + 0xDE + ((player_index - 5) * 0x36A) + (weapon_index * 0x10)
    """
    weapon_offset = weapon_index * WEAPON_STAT_SIZE
    if player_index <= 4:
        return LIVE_ADDRESSES["weapon_stats"] + (player_index * GAME_STATS_SIZE) + weapon_offset
    else:
        return LIVE_ADDRESSES["game_results_extra"] + 0xDE + ((player_index - 5) * GAME_STATS_SIZE) + weapon_offset


def get_live_address(name: str) -> int:
    """Get Xbox virtual memory address for live stats by name."""
    return LIVE_ADDRESSES.get(name, 0)


# PGCR Display constants
#
# The PGCR Display structure at 0x56B900 has a 0x90-byte header followed by
# pcr_stat_player records at stride 0x114 (same layout as PCR at 0x55CAF0).
# This means PCRPlayerStats.from_bytes() works directly on the player data!
#
# Structure:
#   0x56B900: 0x90 bytes of header
#     +0x84: gametype enum (int32) — same values as GameType IntEnum
#     +0x88: unknown (possibly map/scenario tag datum)
#   0x56B990: Player 0 (0x114 bytes, same as pcr_stat_player)
#   0x56BAA4: Player 1
#   0x56BBB8: Player 2
#   ...
PGCR_DISPLAY_HEADER = 0x56B900
PGCR_DISPLAY_HEADER_SIZE = 0x90
PGCR_DISPLAY_GAMETYPE_OFFSET = 0x84  # Gametype enum within header (int32)
PGCR_DISPLAY_GAMETYPE_ADDR = 0x56B984  # Absolute address (0x56B900 + 0x84)
PGCR_DISPLAY_BASE = 0x56B990  # First player record (header + 0x90)
PGCR_DISPLAY_SIZE = 0x114     # Same stride as PCR player records

# Team data constants
# PCR team data: 0x55DC30 = immediately after 16 PCR player records (0x55CAF0 + 16*0x114)
# PGCR Display team data: 0x56CAD0 = immediately after 16 PGCR player records (0x56B990 + 16*0x114)
# On docker-bridged-xemu, PCR team data is EMPTY — use PGCR Display team data instead
# Source: xbox7887 memory research (PCR), verified via hex dump (PGCR)
TEAM_DATA_BASE = 0x55DC30
PGCR_DISPLAY_TEAM_BASE = 0x56CAD0  # 0x56B990 + 16*0x114
TEAM_DATA_STRIDE = 0x84  # 132 bytes per team
MAX_TEAMS = 8

# PGCR breakpoint address - fires when engine clears PGCR display at game end
# Confirmed via live testing (0x233194 from Yelo Carnage is CC padding in our XBE build)
PGCR_BREAKPOINT_ADDR = 0x23975C


@dataclass
class TeamStats:
    """
    Post-game team statistics.

    Available at two locations (same 0x84-byte stride, same field layout):
    - PCR: 0x55DC30 (after 16 PCR player records) — EMPTY on docker-bridged-xemu
    - PGCR Display: 0x56CAD0 (after 16 PGCR player records) — PRIMARY source

    Layout per team (verified via hex dump on PGCR Display):
        0x00: Team name (wchar_t[32], 64 bytes UTF-16LE)
        0x40: Team score (int32)
        0x60: Team place (int16, 0-indexed)
        0x62: Unknown (int16)
        0x64: Place string (UTF-16LE, e.g. "1st", "2nd")
    """
    name: str = ""
    score: int = 0
    place: int = 0
    place_string: str = ""
    index: int = 0

    @classmethod
    def from_bytes(cls, data: bytes, index: int = 0) -> 'TeamStats':
        """Parse TeamStats from raw memory bytes."""
        if len(data) < TEAM_DATA_STRIDE:
            raise ValueError(f"Need at least {TEAM_DATA_STRIDE} bytes, got {len(data)}")
        try:
            name = data[0:64].decode('utf-16-le').rstrip('\x00')
        except (UnicodeDecodeError, ValueError):
            name = ""
        score = struct.unpack('<i', data[0x40:0x44])[0]
        place = struct.unpack('<h', data[0x60:0x62])[0]
        try:
            place_string = data[0x64:0x84].decode('utf-16-le').rstrip('\x00')
        except (UnicodeDecodeError, ValueError):
            place_string = ""
        return cls(name=name, score=score, place=place, place_string=place_string, index=index)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "index": self.index,
            "name": self.name,
            "score": self.score,
            "place": self.place,
        }
        if self.place_string:
            result["place_string"] = self.place_string
        return result


def calculate_pgcr_display_team_address(team_index: int) -> int:
    """
    Calculate memory address for team data in PGCR Display area.

    Located at 0x56CAD0 (immediately after 16 PGCR player records).
    This is the PRIMARY source — PCR team data at 0x55DC30 is empty on
    docker-bridged-xemu.

    Args:
        team_index: Team slot (0-7)

    Returns:
        Xbox memory address for the team record
    """
    return PGCR_DISPLAY_TEAM_BASE + (team_index * TEAM_DATA_STRIDE)


def calculate_team_data_address(team_index: int) -> int:
    """
    Calculate memory address for PCR team data (fallback).

    Args:
        team_index: Team slot (0-7)

    Returns:
        Xbox memory address for the team record
    """
    return TEAM_DATA_BASE + (team_index * TEAM_DATA_STRIDE)


def calculate_pgcr_display_address(player_index: int) -> int:
    """
    Calculate memory address for player's PGCR display stats.

    The PGCR Display at 0x56B900 has a 0x90-byte header, then standard
    pcr_stat_player records at 0x114 stride starting at 0x56B990.
    Only populated during the post-game carnage report screen.

    Args:
        player_index: Player slot (0-15)

    Returns:
        Xbox memory address for the player record
    """
    return PGCR_DISPLAY_BASE + (player_index * PGCR_DISPLAY_SIZE)
