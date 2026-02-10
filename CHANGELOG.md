# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2024-12-11

### Fixed

**CRITICAL: Corrected memory addresses for XBDM protocol**

The original HaloCaster addresses were for reading Xemu's Windows process memory
(via ReadProcessMemory + QMP), NOT for XBDM protocol. Using those addresses with
XBDM caused emulator freezes.

#### Correct Address (from OpenSauce/Yelo)
- **PCR Stats**: `0x55CAF0` - Direct Xbox virtual address
- Structure: `pcr_stat_player` (0x114 bytes per player, 16 players max)
- Source: [OpenSauce Statistics.hpp](https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp)
- Also: Yelo Carnage `Stats.cs` comment: "1.0 Address: 0x55CAF0"

#### Wrong Addresses (HaloCaster - DO NOT USE WITH XBDM)
The following are Xemu process memory offsets, NOT Xbox virtual addresses:
- `0x35ADF02` (game_stats) - WRONG for XBDM
- `0x35AD344` (session_players) - WRONG for XBDM
- These only work with Windows ReadProcessMemory + QMP address translation

### Changed
- Removed incorrect address calculations
- Now uses `PCRPlayerStats` structure exclusively
- Simplified stats reader to use single address base

---

## [0.1.0] - 2024-12-11

### Added

Initial proof-of-concept release for cross-platform Halo 2 stats reading.

#### Core Features
- **XBDM Client** (`xbdm_client.py`): Pure Python implementation of XBDM protocol
  - TCP connection to port 731
  - `getmem2` binary memory reading
  - Fallback to text-format `getmem` for compatibility
  - `setmem` memory writing support
  - Connection banner handling
  - Proper disconnection cleanup

- **Halo 2 Structures** (`halo2_structs.py`): Memory layout definitions
  - `PCRPlayerStats`: 276-byte (0x114) post-game carnage report structure
  - Player name, kills, deaths, assists, suicides, medals, accuracy
  - Memory address: `0x55CAF0` (16 player slots)

- **Stats Reader** (`halo2_stats.py`): Main CLI application
  - Read stats from Xbox/Xemu via XBDM
  - Pretty console scoreboard output
  - JSON output for machine consumption
  - Polling mode for continuous updates
  - Active player detection

#### Memory Address
From OpenSauce/Yelo Carnage (correct for XBDM):
- PCR Stats: `0x55CAF0` (stride: 0x114 per player)

#### Supported Statistics
- Basic: Kills, Deaths, Assists, Betrayals, Suicides, Best Spree
- CTF: Scores, Flag Steals, Flag Saves
- Assault: Scores, Bomber Kills, Bomb Grabs
- Oddball: Score, Ball Kills, Carried Kills
- King of the Hill: Kills as King, Kings Killed
- Juggernaut: Juggernauts Killed, Kills as Juggernaut, Time
- Territories: Taken, Lost

### Technical Notes

This project was created to replace HaloCaster's Windows-only approach:
- **Old method**: Windows ReadProcessMemory + QEMU QMP → reads Xemu's process memory
- **New method**: XBDM protocol over TCP → works with any XBDM-compatible target

The XBDM protocol is the standard Xbox Debug Monitor interface used by:
- Xbox Development Kits
- Modded retail Xbox consoles with custom XBDM
- xbdm_gdb_bridge (translates XBDM commands to Xemu's GDB stub)

### Known Limitations

- Memory addresses are for retail Halo 2 Xbox version only
- Different game versions (PAL, NTSC, updates) may have different addresses
- Requires xbdm_gdb_bridge for Xemu support (direct XBDM not available in Xemu)
- No medal or weapon stat parsing yet (structures defined but not wired up)

### Dependencies

- Python 3.7+ (standard library only, no pip packages required)
- For Xemu: [xbdm_gdb_bridge](https://github.com/abaire/xbdm_gdb_bridge)

