# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Maintenance:** Keep this file up to date as the project evolves. When adding new features, changing addresses, modifying CLI flags, or altering architecture, update the relevant sections here.

**🚨 CRITICAL: Always ask for user confirmation before pushing to GitHub!**

## Project Overview

Cross-platform Python tool to read Halo 2 multiplayer statistics from Xbox/Xemu via XBDM (Xbox Debug Monitor) and QMP (QEMU Machine Protocol). Linux-compatible alternative to Windows-only HaloCaster.

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

# Watch using XBDM breakpoint for instant game-end detection (instead of polling)
python halo2_stats.py --host 172.20.0.51 --watch --breakpoint

# One-shot save to history directory
python halo2_stats.py --host 172.20.0.51 --save

# Poll at custom interval (seconds)
python halo2_stats.py --host 172.20.0.51 --poll 2

# Label gametype-specific stats
python halo2_stats.py --host 172.20.0.51 -g ctf

# Simple K/D/A output (old format)
python halo2_stats.py --host 172.20.0.51 --simple

# JSON output
python halo2_stats.py --host 172.20.0.51 --json

# Hex dump PGCR Display header (research)
python halo2_stats.py --host 172.20.0.51 --dump-header

# Additional flags (work with both XBDM and QMP):
#   --watch-interval 5   Custom watch poll interval (default 3s)
#   --timeout 10         Connection timeout in seconds (default 5)
#   --output stats.json  Save JSON output to file
#   --slow               200ms read delay instead of 50ms (XBDM only)
#   --verbose            Debug logging

# --- QMP mode (reads same PGCR data via QEMU Machine Protocol) ---

# Read post-game stats via QMP (same output as XBDM)
python halo2_stats.py --host 172.20.0.10 --qmp 4444

# Watch mode via QMP (polls, auto-saves, identical to XBDM --watch)
python halo2_stats.py --host 172.20.0.10 --qmp 4444 --watch

# Poll via QMP every 2 seconds
python halo2_stats.py --host 172.20.0.10 --qmp 4444 --poll 2

# Test QMP connection + PGCR read
python qmp_client.py 172.20.0.10 4444 --pgcr

# Test QMP connection (live stats, HaloCaster addresses)
python qmp_client.py [host] [port]

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

# View game history in browser
python pgcr_server.py                   # serves pgcr_viewer.html + /api/games from history/
```

**Watch mode** (`--watch`): Polls PGCR Display every 3s (or use `--breakpoint` for instant detection via XBDM breakpoint at `0x23975C`). Detects game end by player name presence, deduplicates via fingerprint hash (MD5 of sorted player names + K/D/A/S + score_string + shots/headshots + gametype values), auto-saves JSON + raw hex memdump to `history/`. Includes 1-second stability check (re-reads to ensure PGCR isn't mid-transition).

**History directory** (`history/`): JSON files named `YYYY-MM-DD_HH-MM-SS_<fingerprint>.json` and raw memory dumps named `YYYY-MM-DD_HH-MM-SS_<fingerprint>_memdump.txt`. Directory is gitignored.

**QMP mode** (`--qmp PORT`): Reads the same PGCR data as XBDM but via QMP (QEMU Machine Protocol). User-space VAs are automatically translated to physical addresses via `gva2gpa` page table walk. Most flags (`--watch`, `--save`, `--json`, `--poll`) work identically. **`--breakpoint` is XBDM-only** (requires `XBDMNotificationListener` for async breakpoint events; does not work with QMP). Requires Xemu launched with `-qmp tcp:0.0.0.0:PORT,server,nowait`.

**Live stats** (`--live`): Reads HaloCaster kernel-space addresses for in-game stats. **Does not work** — see "HaloCaster Offset Incompatibility" below. The `live_stats.py` module contains all structs and address mappings but the addresses are wrong for our setup.

## Code Architecture

```
addresses.json           # Canonical address/offset/struct reference (language-agnostic)
addresses.py             # JSON loader: exposes all constants as Python module-level vars
       |
xbdm_client.py           # XBDM protocol: TCP:731, getmem2, walkmem, modsections, breakpoints
qmp_client.py            # QMP protocol: TCP:4444, xp physical reads, JSON command/response
       |
halo2_structs.py         # Data layer: struct parsing, enums, dataclasses (imports addresses.py)
live_stats.py            # Live stats: structs, parsers, address calc (imports addresses.py)
       |
halo2_stats.py           # CLI: stats reader, scoreboard display, JSON/text output, watch mode
       |
exports/db_export.py     # PostgreSQL export (optional: psycopg2-binary)
exports/xlsx_export.py   # Excel export (optional: openpyxl)
pgcr_server.py           # HTTP server: serves history JSON via web UI (pgcr_viewer.html)

research/                # Debugging/discovery scripts (not production)
documentation/           # Xbox SDK reference docs (XboxSDK.chm, H2WhitePaper.rtf) — gitignored
```

**Key classes:**
- `XBDMClient` — TCP connection, `read_memory(addr, len)`, 50ms rate limiting, `walk_memory()`, `get_module_sections()`, `set_breakpoint()`, `continue_execution()`, `continue_thread()`
- `QMPClient` — QMP protocol over TCP, `read_memory(addr, len)` as drop-in replacement for `XBDMClient`. Auto-detects address type: user-space VAs (< 0x80000000) go through `gva2gpa` page table walk, kernel VAs strip the high bit. VA→PA translations are cached per-page but **go stale between games** — must call `clear_va_cache()` when detecting a new game. Also exposes `translate_va()`, `_read_physical()`, and `read_memory_va()` directly
- `XBDMNotificationListener` — Separate TCP connection for async XBDM notifications (breakpoint events)
- `PCRPlayerStats` — Post-game player struct (0x114 bytes), `from_bytes()` parser. Used for **both** PCR and PGCR Display reads (same struct layout at different base addresses)
- `TeamStats` — Post-game team struct (0x84 bytes stride). Name, score, place.
- `GameType` — IntEnum (0=None, 1=CTF, 2=Slayer, 3=Oddball, 4=KOTH, 7=Juggernaut, 8=Territories, 9=Assault)
- `Halo2StatsReader` — High-level: reads players, teams, gametype; validates names; probes PGCR Display
- `Halo2Database` (exports/db_export.py) — PostgreSQL interface: `init_schema()`, `import_snapshot()`, `import_history_dir()`
- `PGCRDisplayStats` (live_stats.py) — Legacy struct from early research. **Not used in production** — `PCRPlayerStats.from_bytes()` handles both PCR and PGCR Display reads since they share the same 0x114-byte layout

**Client interchangeability:** `QMPClient.read_memory(addr, len)` is a drop-in replacement for `XBDMClient.read_memory(addr, len)`. `Halo2StatsReader` accepts either as its `client` parameter. For user-space VAs (< 0x80000000), QMPClient automatically does a `gva2gpa` page table walk; for kernel VAs (>= 0x80000000), it strips the high bit. VA→PA translations are cached per-page but **go stale between games** — Xbox remaps user-space pages to different physical addresses each game. Watch mode calls `clear_va_cache()` when detecting a new game.

**Data flow (default one-shot read):**
1. `probe_pgcr_display_populated()` — lightweight check: read 32 bytes at 0x56B990, validate ASCII name
2. If populated → `read_active_pgcr_display()` using `PCRPlayerStats.from_bytes()` at PGCR Display addresses
3. If empty → fallback to `read_all_players_indexed()` at PCR addresses (0x55CAF0)
4. Both paths produce `List[PCRPlayerStats]` — same struct, different base address
5. `read_gametype_discovered()` reads enum from `0x52ED24` via linear physical offset from .data section start. Fallback: `read_gametype()` reads stale PGCR header at `0x56B984`
6. `read_teams()` reads team data from 0x56CAD0 (PGCR) or 0x55DC30 (PCR fallback)
7. `build_snapshot()` assembles JSON with schema_version 3, gametype_id, teams

**Linear physical read (QMP only):** `_read_via_data_section_offset(va)` translates only the .data section START VA (`0x46D6E0`) to physical via `gva2gpa`, then adds a fixed offset to reach the target address. This bypasses stale per-page PTEs — Xbox page table entries for individual pages within .data can be wrong between games, but the section is physically contiguous. Used by `read_gametype_discovered()` and any future .data section reads via QMP.

**Gametype detection (SOLVED):** `read_gametype_discovered()` reads int32 at **`0x52ED24`** — verified correct for ALL 7 gametypes: CTF(1), Slayer(2), Oddball(3), KOTH(4), Juggernaut(7), Territories(8), Assault(9) via 7-way cross-reference of full .data section snapshots (Feb 2026). Only address in entire 1MB .data section that matches all 7 gametypes. **Timing-sensitive:** in breakpoint mode, must be read while Xbox is halted (before resume clears it); in polling mode, retries 3x with 500ms delay. Fallback: `read_gametype()` reads stale PGCR header at `0x56B984`.

## Memory Layout (Confirmed Feb 2026)

### Address Table

| Address | Name | Notes |
|---------|------|-------|
| `0x52ED24` | **Gametype Enum (confirmed)** | int32, verified all 7 gametypes (7-way cross-ref). **PRIMARY gametype source**. Timing-sensitive: read while PGCR populated |
| `0x50224C` | Gametype Enum (xbox7887) | Reads as zero on docker-bridged-xemu. **Do not use** |
| `0x55CAF0` | PCR | EMPTY on docker-bridged-xemu. Fallback only |
| `0x55DC30` | Team Data (PCR) | EMPTY on docker-bridged-xemu. Fallback only |
| `0x56B900` | **PGCR Display** | PRIMARY source. 0x90-byte header + player records + team records |
| `0x56B984` | Gametype Enum (PGCR) | int32 in PGCR header (+0x84). **STALE on docker-bridged-xemu** — always reads 5. Do not rely on |
| `0x56B990` | Player 0 in PGCR Display | First player = 0x56B900 + 0x90 |
| `0x56CAD0` | **Team Data (PGCR)** | After 16 player records. 0x84 stride, up to 8 teams |
| `0x23975C` | **PGCR Breakpoint** | Code address: PGCR clear function, fires at game end |

Player N address: `0x56B990 + N * 0x114` (stride = 276 bytes, max 16 players)
Team N address: `0x56CAD0 + N * 0x84` (stride = 132 bytes, max 8 teams)

**HaloCaster offsets DO NOT WORK — see "HaloCaster Offset Incompatibility" section below.** They read as all zeros via both XBDM (404: kernel VA gap) and QMP `xp` (zeros at computed physical addresses). Do not waste time trying to make them work.

### XBE Memory Layout

```
Module: halo2ship.exe  base=0x000118E0  size=0x005ADBC0

Section         Start        End          Size       Prot
.text           0x00012000   0x00383D2C   3.46 MB    CODE
DSOUND          0x00383D40   0x00391464   54 KB      DATA
.rdata          0x0041B600   0x0046D6CC   321 KB     RONLY
.data           0x0046D6E0   0x00573858   1.02 MB    RW     <- PCR, PGCR here
DOLBY           0x00573860   0x0057A9E0   28 KB      CODE
```

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

Located after 16 player records in both PCR (0x55DC30) and PGCR Display (0x56CAD0).

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | UTF-16LE[32] | Team name (64 bytes, e.g. "Blue Team") |
| 0x40 | UTF-16LE | Score string (e.g. "3", "2:00", ":32" for time-based modes) |
| 0x60 | int16 | Place (0-indexed) |
| 0x62 | int16 | Team identity index (H2 team color ID, distinct from array position) |
| 0x64 | UTF-16LE | Place string ("1st", "2nd", etc.) |

**Note:** Teams in the PGCR Display array (0x56CAD0) are NOT ordered by team index. Array position may differ from the team_id at +0x62. Use team_id to match players to teams. Score is a display string, not int32 — parse as UTF-16LE and convert (time strings like "1:30" = 90 seconds).

### Gametype value union (0x10C / 0x110)

| Gametype | Value 0 | Value 1 |
|----------|---------|---------|
| CTF | Flag Saves | Flag Steals |
| Slayer | Avg Life | Best Spree |
| Oddball | Carrier Kills | Ball Kills |
| KOTH | Kings Killed | Kills From |
| Juggernaut | Jugs Killed | Kills As Jug |
| Territories | Territories Taken | Territories Lost |
| Assault | Bomb Grabs | Bomb Carrier Kills |

**TODO: JSON formatting for Slayer "Avg Life"** — Currently output as raw seconds (e.g., `3525`). Should be formatted as MM:SS (e.g., `58:45`) in JSON output to match in-game PGCR display. Note: KOTH, Oddball, and Juggernaut `gametype_values` are integer counts, not time-based, so no formatting needed for those.

### Medal bitmask (24 bits)

Bits 0-5: multi-kills (Double through Killimanjaro). Bits 6-12: style (Sniper, Splatter, Beat Down, Assassination, Vehicle, Carjack, Stick). Bits 13-17: sprees (5/10/15/20/25 kills). Bits 18-20: CTF (Flag Grab, Carrier Kill, Returned). Bits 21-23: Assault (Bomb Planted, Carrier Kill, Defused).

## XBDM Protocol Reference

Text-based protocol on port 731, similar to FTP. Server sends `201- connected\r\n` on connect, commands end with `\r\n`.

| Command | Response | Description |
|---------|----------|-------------|
| `getmem2 addr=X length=Y` | 203 + binary | Read memory (preferred) |
| `getmem addr=X length=Y` | 200 + hex text | Read memory (fallback) |
| `setmem addr=X data=HEX` | 200 | Write memory |
| `modules` | 202 + list | List loaded modules |
| `modsections name=X` | 202 + list | List module sections |
| `walkmem` | 202 + list | List committed memory pages |
| `go` | 200 | Resume execution |
| `break addr=X` | 200 | Set breakpoint |
| `break clearall` | 200 | Clear all breakpoints |
| `continue thread=N` | 200 | Resume thread after breakpoint |
| `notifyat port=N` | 200/205 | Register for async notifications |
| `bye` | — | Disconnect |

| Status Code | Meaning |
|-------------|---------|
| 200 | Success (text response) |
| 201 | Connected |
| 202 | Multiline response follows |
| 203 | Binary response follows |
| 205 | Now a notification channel (CerbiosDebug) |
| 401 | Max connections exceeded (limit: 4) |
| 404 | Memory not mapped |

## HaloCaster Offset Incompatibility

**CRITICAL: HaloCaster offsets (variant_info, game_stats, medal_stats, etc.) DO NOT WORK in StatsBorg. Do not use them.**

HaloCaster (C#, Windows-only) reads Halo 2 data using **Windows `ReadProcessMemory`** on the Xemu process — it opens the emulator as a Windows process and reads its host virtual memory directly. Its `resolve_addresses()` in `Form1.cs` computes **host virtual addresses** inside the Xemu process:

```
host_base = qmp.Translate(0x80000000) + 0x5C000   // host VA of Xbox RAM base
variant_info_addr = host_base + 0x35AD0EC          // host VA inside Xemu process
Program.memory.ReadByte(variant_info_addr + 0x40)  // ReadProcessMemory on Xemu.exe
```

StatsBorg uses **QMP `xp` command** which reads **guest physical memory** — a completely different mechanism. Even though the math looks similar (`0x8005C000 + 0x35AD0EC = 0x836090EC` → strip to `0x036090EC`), the QMP `xp` command reads different data than ReadProcessMemory at the equivalent host address.

**Confirmed failures (Feb 2026):**
- `variant_info` at `0x35AD0EC` → physical `0x036090EC`: ALL ZEROS during live CTF game
- `game_stats` at `0x35ADF02` → physical `0x0360BF02`: ALL ZEROS
- `game_engine_globals`, `game_results_globals`, `session_players`: ALL ZEROS
- Every HaloCaster offset in `addresses.json["live_stats"]["haloc_offsets"]` reads as zeros

**Why:** HaloCaster offsets land in the kernel VA gap (`0x83145000-0x83AC4000`). These VAs are **not committed** in the Xbox page tables — XBDM returns 404. QMP's `xp` bypasses page tables and reads physical RAM directly, but the data structures simply aren't at those physical addresses on our CerbiosDebug build. The offsets are specific to HaloCaster's target build/BIOS combination.

**Bottom line:** The only reliable memory addresses are in the **user-space .data section** (`0x0046D6E0-0x00573858`): PGCR Display at `0x56B900`, PCR at `0x55CAF0`, etc. These work identically via XBDM and QMP. Any future gametype detection must use addresses in this range, not HaloCaster offsets.

## Important Constraints

- **VA→PA cache goes stale between games** (QMP only): Xbox remaps user-space pages to different physical addresses each game. Must call `clear_va_cache()` when detecting a new game in watch mode. For .data section reads, use `_read_via_data_section_offset()` which translates only the section start VA (bypasses stale per-page PTEs)
- **50ms rate limit** between XBDM reads prevents Xemu freezes (configurable via `--slow` for 200ms)
- **PGCR Display is the reliable source**, not PCR (PCR is empty on docker-bridged-xemu)
- **ASCII validation required** on player names to reject garbage memory (check 0x20-0x7E range). See `_is_valid_player_name()` in halo2_stats.py
- **Port 731** is XBDM (not 9269 which is GDB)
- `PYTHONIOENCODING=utf-8` needed on Windows for non-ASCII gamertags
- **XBDM variant**: Target setup uses CerbiosDebug (native XBDM on modded Xbox/Xemu). Alternative: xbdm_gdb_bridge translates XBDM to Xemu's GDB stub (localhost setups)
- **Xemu networking**: NAT mode = localhost, easy debugging, no system link. Bridge mode = LAN IP, system link works, must open firewall port 731 and bind to LAN IP (not 127.0.0.1)
- **No tests**: Hardware-dependent tool. Manual testing against live Xemu instance required

## Reference Projects

- `c:\Users\james\code\yelo-neighborhood\Yelo Carnage\Stats.cs` — PCR struct reference, medal/gametype enums
- `c:\Users\james\code\yelo-neighborhood\Yelo Carnage\Program.Watch.cs` — Breakpoint reference (0x233194 is CC padding in our build; use 0x23975C instead)
- `c:\Users\james\code\HaloCaster\` — Windows-only reader using ReadProcessMemory on Xemu.exe. **Its offsets do NOT work with QMP `xp` reads** (see "HaloCaster Offset Incompatibility"). Useful as struct/enum reference only, not for addresses
- OpenSauce: `Networking/Statistics.hpp` — Canonical struct definitions (pcr_stat_player = 0x114 bytes)
