# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cross-platform Python tool to read Halo 2 multiplayer statistics from Xbox/Xemu via XBDM (Xbox Debug Monitor) protocol. Linux-compatible alternative to Windows-only HaloCaster.

**Requirements:** Python 3.7+ (standard library only for core tool; `psycopg2-binary` + `openpyxl` optional for export scripts — see `exports/requirements.txt`)

**Target setup:** Docker-bridged Xemu with CerbiosDebug XBDM at `172.20.0.51:731`

## Commands

```bash
# Test XBDM connection
python xbdm_client.py [host]

# Read post-game stats (default: tries PGCR Display first, falls back to PCR)
python halo2_stats.py --host 172.20.0.51

# Watch for game completions and auto-save history
python halo2_stats.py --host 172.20.0.51 --watch

# One-shot save to history directory
python halo2_stats.py --host 172.20.0.51 --save

# Label gametype-specific stats
python halo2_stats.py --host 172.20.0.51 -g ctf

# Simple K/D/A output (old format)
python halo2_stats.py --host 172.20.0.51 --simple

# JSON output
python halo2_stats.py --host 172.20.0.51 --json

# Hex dump PGCR Display header (research)
python halo2_stats.py --host 172.20.0.51 --dump-header

# XBDM diagnostics (in research/)
python research/discover_addresses.py    # walkmem + modsections
python xbdm_client.py [host]             # connection test

# Export to PostgreSQL (requires psycopg2-binary, uses DATABASE_URL env var)
python exports/db_export.py --init-schema              # create tables
python exports/db_export.py --import-history           # import all history/*.json
python exports/db_export.py --import-file <path>       # import single file
python exports/db_export.py --summary                  # print aggregate stats

# Export to Excel (requires openpyxl)
python exports/xlsx_export.py --history-dir history/ -o halo2_stats.xlsx
python exports/xlsx_export.py --from 2026-02-05 --to 2026-02-10 -o stats.xlsx
```

**Watch mode** (`--watch`): Polls PGCR Display every 3s. Detects game end by player name presence, deduplicates via fingerprint hash (MD5 of sorted player names + K/D/A/S), auto-saves to `history/`.

**History directory** (`history/`): JSON files named `YYYY-MM-DD_HH-MM-SS_<fingerprint>.json`.

**Live stats** (`live_stats.py`): Extracted module containing code for reading real-time in-game stats (per-weapon breakdowns, detailed medal counts, game variant info). **Does not work** via XBDM — HaloCaster addresses land in an uncommitted kernel VA gap (`0x83145000-0x83AC4000`). See `live_stats.py` header for detailed explanation and future fix options.

**Research scripts** (`research/`): Debugging and memory discovery tools, not part of production. See `research/README.md`.

## Code Architecture

```
xbdm_client.py           # XBDM protocol: TCP:731, getmem2, walkmem, modsections, breakpoints
       |
halo2_structs.py         # Data layer: addresses, struct parsing, enums, dataclasses
       |
halo2_stats.py           # CLI: stats reader, scoreboard display, JSON/text output, watch mode
       |
exports/db_export.py     # PostgreSQL export (optional: psycopg2-binary)
exports/xlsx_export.py   # Excel export (optional: openpyxl)

live_stats.py            # Live in-game stats (non-functional via XBDM, future QMP)
research/                # Debugging/discovery scripts (not production)
```

**Key classes:**
- `XBDMClient` - TCP connection, `read_memory(addr, len)`, 50ms rate limiting, `walk_memory()`, `get_module_sections()`, `set_breakpoint()`, `continue_execution()`, `continue_thread()`
- `XBDMNotificationListener` - Separate TCP connection for async XBDM notifications (breakpoint events)
- `PCRPlayerStats` - Post-game player struct (0x114 bytes), `from_bytes()` parser. Used for **both** PCR and PGCR Display reads (same struct layout at different base addresses)
- `TeamStats` - Post-game team struct (0x84 bytes stride at 0x55DC30). Name, score, place.
- `GameType` - IntEnum for gametype (0=None, 1=CTF, 2=Slayer, ..., 9=Assault) readable from 0x50224C
- `Halo2StatsReader` - High-level: reads players, teams, gametype; validates names; probes PGCR Display
- `Halo2Database` (exports/db_export.py) - PostgreSQL interface: `init_schema()`, `import_snapshot()`, `import_history_dir()`

**Data flow (default one-shot read):**
1. `probe_pgcr_display_populated()` — lightweight check: read 32 bytes at 0x56B990, validate ASCII name
2. If populated → `read_active_pgcr_display()` using `PCRPlayerStats.from_bytes()` at PGCR Display addresses
3. If empty → fallback to `read_all_players_indexed()` at PCR addresses (0x55CAF0)
4. Both paths produce `List[PCRPlayerStats]` — same struct, different base address
5. `read_gametype()` reads enum from PGCR Display header at 0x56B984 (replaces medal-based heuristic)
6. `read_teams()` reads team data from 0x56CAD0 (PGCR) or 0x55DC30 (PCR fallback)
7. `build_snapshot()` assembles JSON with schema_version 3, gametype_id, teams

## Memory Layout (Confirmed Feb 2026)

### What works via XBDM

| Address | Name | Notes |
|---------|------|-------|
| `0x50224C` | Gametype Enum (xbox7887) | Reads as zero on docker-bridged-xemu. Not used |
| `0x55CAF0` | PCR | EMPTY on docker-bridged-xemu. Fallback only |
| `0x55DC30` | Team Data (PCR) | EMPTY on docker-bridged-xemu. Fallback only |
| `0x56B900` | **PGCR Display** | PRIMARY source. 0x90-byte header + player records + team records |
| `0x56B984` | **Gametype Enum** | int32 in PGCR header (+0x84). Populated during gameplay AND post-game |
| `0x56B990` | Player 0 in PGCR Display | First player = 0x56B900 + 0x90 |
| `0x56CAD0` | **Team Data (PGCR)** | After 16 player records. 0x84 stride, up to 8 teams |
| `0x23975C` | **PGCR Breakpoint** | Code address: PGCR clear function, fires at game end. Resume with `continue thread=N` then `go` per SDK |

Player N address: `0x56B990 + N * 0x114` (stride = 276 bytes, max 16 players)
Team N address: `0x56CAD0 + N * 0x84` (stride = 132 bytes, max 8 teams)

### pcr_stat_player struct (0x114 = 276 bytes)

Source: OpenSauce `Networking/Statistics.hpp`, verified against Yelo Carnage `Stats.cs`

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | UTF-16LE[16] | Player name |
| 0x20 | UTF-16LE[16] | Display name |
| 0x40 | UTF-16LE[16] | Score string |
| 0x60 | int32 | Kills |
| 0x64 | int32 | Deaths |
| 0x68 | int32 | Assists |
| 0x6C | int32 | Suicides |
| 0x70 | int16 | Place (0-indexed) |
| 0x72 | int16 | Team index (0=Red, 1=Blue, 2=Yellow, etc.) |
| 0x74 | bool (1 byte) | Observer (spectating?) |
| 0x78 | int16 | Rank (Halo 2 skill rank 1-50) |
| 0x7A | int16 | Rank verified |
| 0x7C | int32 | Medals earned (count) |
| 0x80 | int32 | Medals by type (24-bit bitmask) |
| 0x84 | int32 | Total shots |
| 0x88 | int32 | Shots hit |
| 0x8C | int32 | Headshots |
| 0x90 | int32[16] | Killed array (kills vs each player slot) |
| 0xE0 | UTF-16LE[16] | Place string ("1st", "2nd", etc.) |
| 0x10C | int32 | GameType value 0 (union) |
| 0x110 | int32 | GameType value 1 (union) |

### team_stats struct (0x84 = 132 bytes)

Source: xbox7887 memory locations + hex dump verification. Located after 16 player records in both PCR (0x55DC30) and PGCR Display (0x56CAD0).

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | UTF-16LE[32] | Team name (64 bytes, e.g. "Blue Team") |
| 0x40 | int32 | Score |
| 0x60 | int16 | Place (0-indexed) |
| 0x64 | UTF-16LE | Place string ("1st", "2nd", etc.) |

### Gametype value union (0x10C / 0x110)

| Gametype | Value 0 | Value 1 |
|----------|---------|---------|
| CTF | Flag Saves | Flag Steals |
| Slayer | Avg Life | Best Spree |
| Oddball | Ball Carrier Kills | Kills As Carrier |
| KOTH | Control Time | Time On Hill |
| Juggernaut | Juggernaut Kills | Kills As Juggernaut |
| Territories | Territories Taken | Territories Lost |
| Assault | Bomb Grabs | Bomb Carrier Kills |

### Medal bitmask (24 bits)

Bits 0-5: multi-kills (Double through Killimanjaro). Bits 6-12: style (Sniper, Splatter, Beat Down, Assassination, Vehicle, Carjack, Stick). Bits 13-17: sprees (5/10/15/20/25 kills). Bits 18-20: CTF (Flag Grab, Carrier Kill, Returned). Bits 21-23: Assault (Bomb Planted, Carrier Kill, Defused).

### What does NOT work via XBDM

HaloCaster offsets (game_stats at `0x35ADF02`, stride `0x36A`) land at physical ~54MB, inside an uncommitted kernel VA gap (`0x83145000-0x83AC4000`). These are valid in Xemu's flat 64MB RAM but inaccessible via XBDM's `getmem2`. They require QMP (QEMU Machine Protocol) to read.

### Gametype detection

**Primary**: `read_gametype()` reads the `GameType` enum from PGCR Display header at `0x56B984` (offset +0x84). Populated both during gameplay and on post-game screen. Resolves all gametypes including Slayer/Juggernaut/Territories.

**Fallback**: `detect_gametype_from_medals()` checks medal bits: CTF (18-20), Assault (21-23), time-format scores for Oddball/KOTH. Cannot distinguish Slayer/Juggernaut/Territories without medals.

**Note**: xbox7887's documented address `0x50224C` reads as zero on docker-bridged-xemu — do not use.

## Important Constraints

- **50ms rate limit** between XBDM reads prevents Xemu freezes (configurable via `--slow` for 200ms)
- **PGCR Display is the reliable source**, not PCR (PCR is empty on docker-bridged-xemu)
- **ASCII validation required** on player names to reject garbage memory (check 0x20-0x7E range). See `_is_valid_player_name()` in halo2_stats.py
- **Module name** is `halo2ship.exe` (base=0x000118E0), .data section at 0x0046D6E0
- **Port 731** is XBDM (not 9269 which is GDB)
- `PYTHONIOENCODING=utf-8` needed on Windows for non-ASCII gamertags
- **XBDM variant**: Target setup uses CerbiosDebug (native XBDM on modded Xbox/Xemu). Alternative: xbdm_gdb_bridge translates XBDM to Xemu's GDB stub (localhost setups)
- **No tests**: This is a hardware-dependent tool. No automated test suite — manual testing against live Xemu instance required

## Reference Projects

- `c:\Users\james\code\yelo-neighborhood\Yelo Carnage\Stats.cs` - PCR struct reference, medal/gametype enums
- `c:\Users\james\code\yelo-neighborhood\Yelo Carnage\Program.Watch.cs` - Breakpoint reference (0x233194 is CC padding in our build; use 0x23975C instead)
- `c:\Users\james\code\HaloCaster\` - QMP-based reader, HaloCaster offsets in `Form1.cs` resolve_addresses()
- OpenSauce: `Networking/Statistics.hpp` - Canonical struct definitions (pcr_stat_player = 0x114 bytes)
