# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Maintenance:** Keep this file up to date as the project evolves. When adding new features, changing addresses, modifying CLI flags, or altering architecture, update the relevant sections here.

## Project Overview

Cross-platform Python tool to read Halo 2 multiplayer post-game statistics from Xbox/Xemu via XBDM (Xbox Debug Monitor) and QMP (QEMU Machine Protocol). Linux-compatible alternative to Windows-only HaloCaster.

**Requirements:** Python 3.7+ (standard library only for core tool; `psycopg2-binary` + `openpyxl` optional for export scripts — see `exports/requirements.txt`)

**Target setup:** Docker-bridged Xemu with CerbiosDebug XBDM at `172.20.0.51:731`, QMP at `172.20.0.10:4444`

## Commands

```bash
# Test XBDM connection
python xbdm_client.py [host]

# Read post-game stats (default: tries PGCR Display first, falls back to PCR)
python halo2_stats.py --host 172.20.0.51

# Watch for game completions and auto-save history (polls every 3s)
python halo2_stats.py --host 172.20.0.51 --watch

# Watch using XBDM breakpoint for instant game-end detection
python halo2_stats.py --host 172.20.0.51 --watch --breakpoint

# One-shot save to history directory
python halo2_stats.py --host 172.20.0.51 --save

# JSON output / PGCR tabular format / simple K/D/A
python halo2_stats.py --host 172.20.0.51 --json
python halo2_stats.py --host 172.20.0.51 --pgcr
python halo2_stats.py --host 172.20.0.51 --simple

# Additional flags (work with both XBDM and QMP):
#   --poll 2             Poll every N seconds (non-watch mode; 0 = single read)
#   --watch-interval 5   Seconds between watch-mode probes (watch mode only, default 3s)
#   --timeout 10         Connection timeout in seconds (default 5)
#   --output stats.json  Save JSON output to file
#   --slow               200ms read delay instead of 50ms (XBDM only)
#   --save-ram           Save full 64MB RAM snapshot at game end (QMP only)
#   -g ctf               Label gametype-specific stats
#   --verbose            Debug logging

# --- QMP mode (reads same PGCR data via QEMU Machine Protocol) ---
python halo2_stats.py --host 172.20.0.10 --qmp 4444
python halo2_stats.py --host 172.20.0.10 --qmp 4444 --watch

# Test QMP connection
python qmp_client.py 172.20.0.10 4444

# --- Exports ---
python exports/db_export.py --init-schema              # PostgreSQL (requires psycopg2-binary)
python exports/db_export.py --import-history
python exports/xlsx_export.py --history-dir history/ -o halo2_stats.xlsx  # Excel (requires openpyxl)
python exports/xlsx_export.py --per-game --style bungie -o exports/bungie/

# View game history in browser
python pgcr_server.py [port]            # default 8080, serves pgcr_viewer.html
```

**Watch mode** (`--watch`): Polls PGCR Display every 3s (or use `--breakpoint` for instant detection via XBDM breakpoint at `0x23975C`). Detects game end by player name presence, deduplicates via fingerprint hash, auto-saves JSON + hex memdump to `history/`.

**QMP mode** (`--qmp PORT`): Reads the same PGCR data as XBDM but via QMP. User-space VAs translated to physical via `gva2gpa` page table walk. **`--breakpoint` is XBDM-only**. Requires Xemu launched with `-qmp tcp:0.0.0.0:PORT,server,nowait`.

## Code Architecture

```
addresses.json           # Canonical address/offset/struct reference (language-agnostic)
addresses.py             # JSON loader: exposes all constants as Python module-level vars
       |
xbdm_client.py           # XBDM protocol: TCP:731, getmem2, walkmem, modsections, breakpoints
qmp_client.py            # QMP protocol: TCP:4444, xp physical reads, JSON command/response
       |
halo2_structs.py         # Data layer: struct parsing, enums, dataclasses (imports addresses.py)
       |
halo2_stats.py           # CLI: stats reader, scoreboard display, JSON/text output, watch mode
       |
exports/db_export.py     # PostgreSQL export (optional: psycopg2-binary)
exports/xlsx_export.py   # Excel export (optional: openpyxl)
pgcr_server.py           # HTTP server: serves history JSON via web UI
pgcr_viewer.html         # Browser-based game history viewer (served by pgcr_server.py)

_archive/                # Archived research scripts, live_stats.py, full addresses reference
documentation/           # Xbox SDK reference docs (XboxSDK.chm, H2WhitePaper.rtf)
```

**Key classes:**
- `XBDMClient` — TCP connection, `read_memory(addr, len)`, 50ms rate limiting, breakpoints
- `QMPClient` — QMP protocol, `read_memory(addr, len)` drop-in replacement for XBDMClient. VA→PA translations cached per-page but **go stale between games** — must call `clear_va_cache()`
- `XBDMNotificationListener` — Async XBDM notifications (breakpoint events)
- `PCRPlayerStats` — Post-game player struct (0x114 bytes). Used for both PCR and PGCR Display reads
- `TeamStats` — Post-game team struct (0x84 bytes stride)
- `GameType` — IntEnum (0=None, 1=CTF, 2=Slayer, 3=Oddball, 4=KOTH, 7=Juggernaut, 8=Territories, 9=Assault)
- `Halo2StatsReader` — High-level: reads players, teams, gametype; validates names; probes PGCR Display

**Data flow:**
1. `probe_pgcr_display_populated()` — check 32 bytes at 0x56B990 for valid ASCII name
2. If populated → `read_active_pgcr_display()` at PGCR Display addresses
3. If empty → fallback to `read_all_players_indexed()` at PCR addresses (0x55CAF0)
4. `read_gametype_discovered()` reads enum from `0x52ED24` via linear physical offset
5. `read_teams()` reads team data from 0x56CAD0 (PGCR) or 0x55DC30 (PCR fallback)
6. `build_snapshot()` assembles JSON with schema_version 3

**JSON schema v3:** `{ schema_version, timestamp, fingerprint, source, gametype, gametype_id, player_count, players[], teams[] }`. Export scripts consume this from `history/`.

**Linear physical read (QMP only):** `_read_via_data_section_offset(va)` translates only the .data section START VA (`0x46D6E0`) to physical, then adds offset. Bypasses stale per-page PTEs since .data is physically contiguous.

## Memory Layout

### Address Table

| Address | Name | Notes |
|---------|------|-------|
| `0x52ED24` | **Gametype Enum** | int32, verified all 7 gametypes. **PRIMARY source**. Timing-sensitive |
| `0x56B900` | **PGCR Display** | PRIMARY source. 0x90-byte header + player records + team records |
| `0x56B990` | Player 0 in PGCR Display | First player = 0x56B900 + 0x90 |
| `0x56CAD0` | **Team Data (PGCR)** | After 16 player records. 0x84 stride, up to 8 teams |
| `0x23975C` | **PGCR Breakpoint** | Code address: PGCR clear function, fires at game end |
| `0x55CAF0` | PCR (fallback) | EMPTY on docker-bridged-xemu |
| `0x56B984` | Gametype (PGCR header) | **STALE** — always reads 5. Do not rely on |

Player N: `0x56B990 + N * 0x114` (stride = 276 bytes, max 16 players)
Team N: `0x56CAD0 + N * 0x84` (stride = 132 bytes, max 8 teams)

### pcr_stat_player struct (0x114 = 276 bytes)

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
| 0x72 | int16 | Team index |
| 0x74 | bool | Observer |
| 0x78 | int16 | Rank (1-50) |
| 0x7C | int32 | Medals earned (count) |
| 0x80 | int32 | Medals by type (24-bit bitmask) |
| 0x84 | int32 | Total shots |
| 0x88 | int32 | Shots hit |
| 0x8C | int32 | Headshots |
| 0x90 | int32[16] | Killed array (kills vs each player slot) |
| 0xE0 | UTF-16LE[16] | Place string ("1st", "2nd", etc.) |
| 0x10C | int32 | GameType value 0 (union) |
| 0x110 | int32 | GameType value 1 (union) |

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

## Important Constraints

- **VA→PA cache goes stale between games** (QMP only): Must call `clear_va_cache()` when detecting a new game. For .data section reads, use `_read_via_data_section_offset()` which bypasses stale per-page PTEs
- **50ms rate limit** between XBDM reads prevents Xemu freezes (configurable via `--slow` for 200ms)
- **PGCR Display is the reliable source**, not PCR (PCR is empty on docker-bridged-xemu)
- **ASCII validation required** on player names (check 0x20-0x7E range). See `_is_valid_player_name()`
- **Port 731** is XBDM (not 9269 which is GDB)
- `PYTHONIOENCODING=utf-8` needed on Windows for non-ASCII gamertags
- **HaloCaster offsets DO NOT WORK** via QMP `xp` reads — they use Windows `ReadProcessMemory` on the Xemu process (host VAs), a completely different mechanism. All offsets read as zeros. See `_archive/RESEARCH_SUMMARY.md` for full analysis
- **No tests**: Hardware-dependent tool. Manual testing against live Xemu instance required

## Reference Projects

- `c:\Users\james\code\yelo-neighborhood\Yelo Carnage\Stats.cs` — PCR struct reference, medal/gametype enums
- `c:\Users\james\code\HaloCaster\` — Windows-only reader using ReadProcessMemory on Xemu.exe. Useful as struct/enum reference only, not for addresses
- OpenSauce: `Networking/Statistics.hpp` — Canonical struct definitions (pcr_stat_player = 0x114 bytes)
