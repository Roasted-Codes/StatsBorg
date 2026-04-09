# Halo 2 Stat Reading: Complete Technical Reference

This document summarizes all research done across StatsBorg, HaloCaster (Windows C#), and HaloCaster Linux (Python). It is intended as a handoff document for building a new unified project.

## Table of Contents

1. [The Problem](#the-problem)
2. [Three Memory Reading Approaches](#three-memory-reading-approaches)
3. [How QMP Works](#how-qmp-works)
4. [HaloCasterLinux Deep Dive](#halocasterlinux-deep-dive)
5. [StatsBorg Deep Dive](#statsborg-deep-dive)
6. [HaloCaster Windows Deep Dive](#halocaster-windows-deep-dive)
7. [Why HaloCaster Offsets Fail in StatsBorg](#why-halocaster-offsets-fail-in-statsborg)
8. [Two Completely Different Data Sources](#two-completely-different-data-sources)
9. [Complete Offset Reference](#complete-offset-reference)
10. [Complete Struct Reference](#complete-struct-reference)
11. [Feature Matrix](#feature-matrix)
12. [What Each Project Uniquely Contributes](#what-each-project-uniquely-contributes)
13. [Architecture for a Unified Tool](#architecture-for-a-unified-tool)
14. [Existing Codebases and File Locations](#existing-codebases-and-file-locations)

---

## The Problem

Xemu (Xbox emulator) runs Halo 2. We want to read game statistics from the emulated Xbox's memory. There are three ways to do this, and each has different tradeoffs.

The Xbox has 64MB of RAM. When xemu starts, it allocates a big buffer on the host machine to hold that 64MB. All Halo 2 data — player stats, game state, weapons, medals — lives somewhere inside that buffer.

The challenge: how do you locate and read that data?

---

## Three Memory Reading Approaches

### Approach 1: Host Process Memory (HaloCaster Windows + Linux)

**How it works:** Open the xemu process and read its memory directly.

```
Xbox Virtual Address (e.g. 0x8005C000 + 0x35ADF02)
  → QMP gva2gpa → Guest Physical Address
    → QMP gpa2hva → Host Virtual Address (pointer inside xemu's process)
      → ReadProcessMemory (Windows) or process_vm_readv (Linux)
        → Raw bytes
```

- QMP is used ONCE at startup for address translation, never again
- All reads go through the host OS's process memory API
- Reads from xemu's internal RAM buffer at host virtual addresses
- **Can access ALL Xbox memory** including kernel-space structures
- **Requires same machine** — must have the xemu process handle/PID
- **Very fast** — direct memory read, no protocol overhead, supports batch reads

### Approach 2: QMP Guest Physical Reads (StatsBorg)

**How it works:** Ask QEMU to read guest physical memory via the `xp` command.

```
Xbox Virtual Address (e.g. 0x56B990)
  → QMP gva2gpa → Guest Physical Address
    → QMP xp → Raw bytes (read by QEMU internally)
```

- QMP is used for EVERY read (each read is a JSON command/response round-trip)
- QEMU reads its own internal memory and returns the data over TCP
- **Cannot access kernel VA gap** (0x83145000-0x83AC4000) — reads as zeros
- **Works remotely** — QMP is TCP, works across Docker/network/machines
- **Slower** — network round-trip per read, no batch support

### Approach 3: XBDM (StatsBorg)

**How it works:** Xbox Debug Monitor protocol over TCP port 731.

```
Xbox Virtual Address (e.g. 0x56B990)
  → XBDM getmem2 command → Raw bytes
```

- Direct debug protocol built into the Xbox/xemu (CerbiosDebug)
- Text-based TCP protocol, 50ms rate limiting to prevent freezes
- Can read user-space memory, set breakpoints, get module sections
- **Cannot read kernel VA gap** — returns 404
- **Supports breakpoints** — instant game-end detection (vs polling)
- **Works remotely** — TCP on port 731

---

## How QMP Works

QMP (QEMU Machine Protocol) is a JSON-based control channel for QEMU/xemu. Connect via TCP (default port 4444). Xemu must be launched with:

```
xemu -qmp tcp:0.0.0.0:4444,server,nowait
```

### Connection Handshake

```
1. Connect TCP
2. Receive: {"QMP": {"version": ..., "capabilities": [...]}}
3. Send: {"execute": "qmp_capabilities"}
4. Receive: {"return": {}}
```

### Key Commands Used

All memory-related commands go through the Human Monitor Protocol (HMP) wrapper:

```json
{"execute": "human-monitor-command", "arguments": {"command-line": "<HMP command>"}}
```

| HMP Command | Purpose | Returns |
|-------------|---------|---------|
| `gva2gpa <addr>` | Xbox guest virtual → guest physical address | `"gpa: 0xNNNNNN"` |
| `gpa2hva <addr>` | Guest physical → host virtual address (in xemu process) | `"0xNNNN is 0xNNNNNN"` |
| `xp /NNNxb <addr>` | Read N bytes from guest physical address | Hex dump |
| `stop` | Pause emulation | `{"return": {}}` |
| `cont` | Resume emulation | `{"return": {}}` |
| `query-status` | Check if paused | `{"return": {"running": true/false}}` |

### The Critical Distinction

- **`gpa2hva`** gives you a pointer inside xemu's process memory. Use with `ReadProcessMemory` or `process_vm_readv`. This is what HaloCaster uses.
- **`xp`** asks QEMU to read guest physical memory and return the bytes over the socket. This is what StatsBorg uses.

Both can read the same user-space data. But `xp` returns **zeros** for certain kernel-space memory regions that `gpa2hva` + host-process-read can access successfully.

---

## HaloCasterLinux Deep Dive

**Location:** `HaloCaster/HaloCasterLinux/`

### Architecture

```
run.py                    # Entry point, CLI args, launches web or CLI mode
halocaster/
  engine.py               # Core: connect, poll loop, read all stats
  qmp.py                  # QMP client (gva2gpa + gpa2hva only)
  memory.py               # process_vm_readv() reader + xemu PID finder
  offsets.py              # All memory offsets, enums, weapon/map names
  stats.py                # Dataclasses: GameStats, MedalStats, WeaponStats, PlayerStats
  config.py               # Config loader (JSON)
  export.py               # XLSX + CSV export
  sftp.py                 # SFTP upload + VPS webhook
  player_tracker.py       # Player quit detection + movement logging
  web.py                  # Flask + SocketIO real-time dashboard
templates/
  index.html              # Full web dashboard
docker-compose.yml        # Docker config (pid:host, SYS_PTRACE)
requirements.txt          # flask, flask-socketio, openpyxl, paramiko, etc.
```

### Connection Pipeline

```python
# 1. Find xemu PID by scanning /proc/*/comm
pid = find_xemu_pid()  # iterates /proc, looks for "xemu" in comm

# 2. QMP: one-time address translation
qmp = QMPClient('localhost', 4444)
qmp.connect()  # TCP connect, read greeting, negotiate capabilities
host_base = qmp.translate(0x80000000) + 0x5C000
# translate() = gpa2hva(gva2gpa(0x80000000))
# Result: a host virtual address pointing to XBE base in xemu's memory
# QMP is NEVER used again after this line

# 3. Open memory reader
mem = MemoryReader(pid)  # verifies process_vm_readv access

# 4. Calculate all addresses as host_base + offset
addr_game_stats = host_base + 0x35ADF02
addr_medal_stats = host_base + 0x35ADF4E
addr_weapon_stats = host_base + 0x35ADFE0
# ... etc
```

### Memory Reading: process_vm_readv

Linux syscall that reads from another process's virtual address space. Uses scatter/gather I/O vectors (`iovec` structs) for batch reads.

```python
# Single read
libc.process_vm_readv(pid, local_iov, 1, remote_iov, 1, 0)

# Batch read (44 regions in ONE syscall)
libc.process_vm_readv(pid, local_iovs, 44, remote_iovs, 44, 0)
```

**Per-player batch read** reads 44 regions at once: game stats (0x36 bytes) + medals (0x30 bytes) + session data (0x80 bytes) + 41 weapon blocks (0x10 each).

**Docker requirements** for process_vm_readv on a host process:
```yaml
pid: "host"           # Share host PID namespace
privileged: true
cap_add: [SYS_PTRACE]
security_opt: [seccomp:unconfined]
```

### Player Data Split

Players 0-4 are at the base offset. Players 5-15 overflow to a separate address:

```python
if player_index < 5:
    addr = host_base + Offsets.GAME_STATS + (index * PLAYER_STRIDE)
else:
    addr = host_base + Offsets.GAME_RESULTS_EXTRA + ((index - 5) * PLAYER_STRIDE)
```

### Polling

Default: 10 Hz (100ms). Background daemon thread calls `get_game_state()` which reads life_cycle, variant_info, and all player stats each tick. Callbacks notify the web UI via SocketIO.

### Additional Features

- **Dedi mode**: Writes `False` to `host_base + 0x3569128` (profile_enabled) to disable profile selection — turns xemu into a dedicated server
- **Player tracker**: Preserves stats for players who quit mid-game by caching by Xbox identifier
- **Fallback MAC**: Generates `H2CR` + name letters when real MAC is all zeros
- **Emblem rendering**: Reads emblem colors/shapes, generates carnagereport.com URLs
- **SFTP upload**: Auto-uploads XLSX/CSV to VPS via paramiko after each game
- **VPS webhook**: Pushes live scoreboard JSON to remote HTTP API
- **Movement logging**: Records player state each tick for theater/replay analysis
- **xdotool integration**: Sends keyboard input to xemu window (pass leader, snapshot loading)

---

## StatsBorg Deep Dive

**Location:** Root of StatsBorg repo

### Architecture

```
addresses.json            # Canonical address/offset/struct reference
addresses.py              # JSON loader → Python module-level constants
xbdm_client.py            # XBDM protocol client (TCP:731)
qmp_client.py             # QMP protocol client (TCP:4444, uses xp for reads)
halo2_structs.py          # Struct parsing, enums, dataclasses
live_stats.py             # Live stats structs (non-functional — wrong addresses)
halo2_stats.py            # Main CLI: reader, scoreboard, watch mode, JSON output
pgcr_server.py            # HTTP server for browser-based history viewer
exports/
  db_export.py            # PostgreSQL export
  xlsx_export.py          # Excel export (bungie/rampant styles)
  pgcr_viewer.html        # Browser PGCR viewer
```

### Connection Pipeline (QMP mode)

```python
# 1. Connect QMP
client = QMPClient(host, port)
client.connect()

# 2. For each memory read:
#    a. gva2gpa: Xbox VA → guest physical (cached per-page)
#    b. xp: read guest physical memory
data = client.read_memory(0x56B990, 0x114)
# Internally: gva2gpa(0x56B990) → physical, then xp at physical addr
```

### Connection Pipeline (XBDM mode)

```python
# 1. Connect XBDM
client = XBDMClient(host, 731)

# 2. Read memory directly by Xbox VA
data = client.read_memory(0x56B990, 0x114)
# Sends: getmem2 addr=0x56B990 length=0x114
# 50ms rate limiting between reads
```

### Key Innovations

1. **Linear physical offset trick** (QMP only): Xbox page table entries for individual .data section pages go stale between games. Instead of translating each address individually, StatsBorg translates only the .data section start VA (`0x46D6E0`) and adds a fixed byte offset. The .data section is physically contiguous even when individual PTEs are wrong.

2. **VA→PA cache with staleness handling**: QMP translations are cached per-page but the cache must be cleared between games (`clear_va_cache()`) because Xbox remaps user-space pages.

3. **Gametype discovery at `0x52ED24`**: Found via differential memory scanning of full .data section snapshots across 7 different gametypes. Only address in the entire 1MB .data section that holds the correct gametype enum for all 7 game modes.

4. **XBDM breakpoint detection**: Sets breakpoint at `0x23975C` (PGCR clear function) for instant game-end detection instead of polling.

5. **Game deduplication**: MD5 fingerprint of sorted player names + K/D/A/S + score_string + shots/headshots + gametype values. Prevents duplicate saves if the same post-game screen is read multiple times.

### Watch Mode

Polls PGCR Display every 3s (or uses breakpoint for instant detection). Detects game end by checking for valid ASCII player name at `0x56B990`. Re-reads after 1 second to verify stability (not mid-transition). Saves JSON + raw hex dump + annotated hex dump to `history/` directory.

### JSON Schema (v3)

```json
{
  "schema_version": 3,
  "timestamp": "2026-02-18T15:30:00",
  "fingerprint": "a1b2c3d4",
  "source": "pgcr_display",
  "gametype": "slayer",
  "gametype_id": 2,
  "player_count": 4,
  "players": [
    {
      "player_name": "Player1",
      "kills": 10, "deaths": 5, "assists": 3, "suicides": 0,
      "place": 0, "team_index": 0,
      "medals_earned": 2, "medals_bitmask": 65,
      "total_shots": 100, "shots_hit": 45, "headshots": 12,
      "gametype_value0": 3525, "gametype_value1": 7,
      "gametype_stats": {"avg_life": 3525, "best_spree": 7}
    }
  ],
  "teams": [
    {"team_name": "Red Team", "score": "25", "place": 0, "team_id": 0}
  ]
}
```

---

## HaloCaster Windows Deep Dive

**Location:** `HaloCaster/Halo2/xemuh2stats-main/WhatTheFuck/`

C# WinForms application. Uses the exact same approach as HaloCasterLinux but with `ReadProcessMemory` (Win32 API) instead of `process_vm_readv`:

```csharp
// Two global singletons:
Program.memory  // ReadProcessMemory wrapper on xemu.exe
Program.qmp     // QMP for address translation only

// Connection:
Process xemu = Process.GetProcessesByName("xemu")[0];
Program.qmp = new QmpProxy(port);     // QMP connect
Program.memory = new MemoryHandler(xemu);  // OpenProcess(PROCESS_ALL_ACCESS)

// Address resolution:
var host_base = (long)Program.qmp.Translate(0x80000000) + 0x5C000;
// Then: host_base + offset for each data structure

// All reads:
Program.memory.ReadInt(resolved_address);  // ReadProcessMemory
```

The `QmpProxy.Read()` method (using QMP `x` command) exists in the code but is **dead code — never called**. All data reads go through `ReadProcessMemory`.

### Additional Features Not in Linux Version

- **Tag system traversal** — resolves weapon/vehicle types from tag datums
- **Object system** — reads biped positions, velocities, health, shields, grenades
- **Live kill feed** — circular buffer of 1000 kill/carry/score events
- **Pattern scanning** — `VirtualQueryEx` + pattern matching with masks to find structures
- **Memory writing** — `WriteProcessMemory` for dedi mode, game state manipulation
- **Player data streaming** — TCP/UDP streaming of player data to external consumers

---

## Why HaloCaster Offsets Fail in StatsBorg

The HaloCaster offsets (like `0x35ADF02` for game_stats) correspond to Xbox kernel-space virtual addresses:

```
XBE_BASE (0x8005C000) + 0x35ADF02 = 0x83609F02
```

This address (`0x83609F02`) falls in the **kernel VA gap** (0x83145000-0x83AC4000). These virtual addresses are:

- **Not committed in Xbox page tables** — XBDM returns 404 ("memory not mapped")
- **Accessible via host process memory** — because `gpa2hva` bypasses the Xbox page tables entirely and gives you a pointer into xemu's internal RAM buffer
- **Return zeros via QMP `xp`** — the `xp` command reads guest physical memory, but the data simply isn't at the computed physical address when accessed this way

This was confirmed in February 2026: every HaloCaster offset reads as all zeros via both XBDM (404) and QMP `xp` (zeros).

**The bottom line:** To use HaloCaster offsets, you MUST read from the host process (Approach 1). You cannot use QMP `xp` (Approach 2) or XBDM (Approach 3) for these addresses.

---

## Two Completely Different Data Sources

### Live In-Game Data (HaloCaster offsets)

Read via host process memory. Available during gameplay, updates in real-time.

- **Base:** `host_base + offset` (where `host_base = gpa2hva(gva2gpa(0x80000000)) + 0x5C000`)
- **Player stride:** `0x36A` (874 bytes) per player
- **Includes:** kills, deaths, assists, betrayals, suicides, best spree, time alive, per-gametype stats, per-weapon stats (41 weapons), individual medal counts (24 types), player identity, emblem data
- **Split:** Players 0-4 at `GAME_STATS`, players 5-15 at `GAME_RESULTS_EXTRA`

### Post-Game Carnage Report (PGCR Display)

Read via XBDM or QMP `xp`. Available only at the post-game screen.

- **Base:** `0x56B900` (PGCR Display header), players start at `0x56B990`
- **Player stride:** `0x114` (276 bytes) per player
- **Includes:** kills, deaths, assists, suicides, place, team, rank, medals bitmask (24-bit yes/no), shots/hits/headshots, killed-by array, score/place strings, two gametype-specific values
- **Missing:** betrayals, best spree, time alive, per-weapon breakdown, individual medal counts, player identity/MAC/emblem

### Overlap

Both sources provide: kills, deaths, assists, suicides, and gametype-specific stat values. But the in-game data has significantly richer detail (per-weapon, per-medal counts, betrayals, sprees, etc).

---

## Complete Offset Reference

### HaloCaster Offsets (relative to XBE base 0x8005C000, add to host_base)

| Offset | Name | Size | Notes |
|--------|------|------|-------|
| `0x35ADF02` | GAME_STATS | 0x36 per player | K/D/A/betrayals/suicides/spree/time_alive + gametype stats |
| `0x35ADF4E` | MEDAL_STATS | 0x30 per player | 24 medal types, each uint16 count |
| `0x35ADFE0` | WEAPON_STATS | 0x10 × 41 per player | Per-weapon: kills/deaths/suicide/shots/hits/headshots |
| `0x35E4F04` | LIFE_CYCLE | int32 | 0=None, 1=PreGame, 2=InLobby, 3=InGame, 4=PostGame, 5=Leaving, 6=Joining, 7=Matchmaking |
| `0x35AD0EC` | VARIANT_INFO | ~0x230 | Game variant name (UTF-16), gametype (byte at +0x40), scenario path (ASCII at +0x130) |
| `0x35AD344` | SESSION_PLAYERS | 0xA4 per player | Player name (UTF-16), team (byte at +0x7C), profile/emblem (at +0x40) |
| `0x35CF014` | GAME_RESULTS_EXTRA | 0x36A per player | Overflow for players 5-15 (same layout as GAME_STATS region) |
| `0x3595E00` | GAME_STATE_PLAYERS | 0x21C per player | Xbox identifier (ulong at +0x06), MAC address (6 bytes at +0x0E) |
| `0x3569128` | PROFILE_ENABLED | bool | Write False to enable dedi mode |
| `0x363A990` | POST_GAME_REPORT | — | Defined but not actively read |
| `0x35A53B8` | GAME_ENGINE_GLOBALS | — | Defined but not actively read |
| `0x35A44F4` | PLAYERS | — | Defined but not actively read |
| `0x35BBBD0` | OBJECTS | — | Object table (positions, health, weapons) |
| `0x35ACFB0` | GAME_RESULTS_GLOBALS | — | Kill feed event buffer at +0x24F84 |
| `0x3520E22` | DISABLE_RENDERING | bool | Toggle xemu rendering |
| `0x35CC008` | LOBBY_PLAYERS | — | Lobby player data |
| `0x360558C` | TAGS | — | Tag table for weapon/object identification |

### StatsBorg Post-Game Offsets (Xbox virtual addresses)

| Address | Name | Notes |
|---------|------|-------|
| `0x52ED24` | **Gametype Enum** | int32, confirmed for all 7 gametypes. Must read while PGCR populated |
| `0x56B900` | PGCR Display Header | 0x90 bytes, includes stale gametype at +0x84 |
| `0x56B990` | PGCR Display Player 0 | First player record |
| `0x56CAD0` | Team Data (PGCR) | After 16 player records, 0x84 stride, up to 8 teams |
| `0x55CAF0` | PCR (fallback) | Empty on docker-bridged-xemu |
| `0x55DC30` | Team Data (PCR, fallback) | Empty on docker-bridged-xemu |
| `0x23975C` | PGCR Breakpoint | Code address for XBDM breakpoint at game end |

### XBE Memory Sections

```
.text    0x00012000 - 0x00383D2C   3.46 MB   CODE
DSOUND   0x00383D40 - 0x00391464   54 KB     DATA
.rdata   0x0041B600 - 0x0046D6CC   321 KB    RONLY
.data    0x0046D6E0 - 0x00573858   1.02 MB   RW     ← PGCR, PCR, gametype here
DOLBY    0x00573860 - 0x0057A9E0   28 KB     CODE
```

---

## Complete Struct Reference

### s_game_stats (0x36 = 54 bytes per player) — HaloCaster live data

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | uint16 | Kills |
| 0x02 | uint16 | Assists |
| 0x04 | uint16 | Deaths |
| 0x06 | uint16 | Betrayals |
| 0x08 | uint16 | Suicides |
| 0x0A | uint16 | Best spree |
| 0x0C | uint16 | Time alive |
| 0x0E | uint16 | CTF scores |
| 0x10 | uint16 | CTF flag steals |
| 0x12 | uint16 | CTF flag saves |
| 0x14 | uint16 | CTF unknown |
| 0x18 | uint16 | Assault score |
| 0x1A | uint16 | Assault bomber kills |
| 0x1C | uint16 | Assault bomb grabbed |
| 0x20 | uint32 | Oddball score |
| 0x24 | uint16 | Oddball ball kills |
| 0x26 | uint16 | Oddball carried kills |
| 0x28 | uint16 | KOTH kills as king |
| 0x2A | uint16 | KOTH kings killed |
| 0x2C | uint16 | Juggernauts killed |
| 0x2E | uint16 | Kills as juggernaut |
| 0x30 | uint16 | Juggernaut time |
| 0x32 | uint16 | Territories taken |
| 0x34 | uint16 | Territories lost |

### s_medal_stats (0x30 = 48 bytes per player) — HaloCaster live data

24 medals, each uint16 (count, not just present/absent):

| Offset | Medal |
|--------|-------|
| 0x00 | Double Kill |
| 0x02 | Triple Kill |
| 0x04 | Killtacular |
| 0x06 | Kill Frenzy |
| 0x08 | Killtrocity |
| 0x0A | Killamanjaro |
| 0x0C | Sniper Kill |
| 0x0E | Road Kill |
| 0x10 | Bone Cracker (Beat Down) |
| 0x12 | Assassin |
| 0x14 | Vehicle Destroyed |
| 0x16 | Car Jacking |
| 0x18 | Stick It |
| 0x1A | Killing Spree |
| 0x1C | Running Riot |
| 0x1E | Rampage |
| 0x20 | Berserker |
| 0x22 | Overkill |
| 0x24 | Flag Taken |
| 0x26 | Flag Carrier Kill |
| 0x28 | Flag Returned |
| 0x2A | Bomb Planted |
| 0x2C | Bomb Carrier Kill |
| 0x2E | Bomb Returned |

### s_weapon_stat (0x10 = 16 bytes per weapon per player) — HaloCaster live data

41 weapons, stride 0x10:

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | uint16 | Kills |
| 0x02 | uint16 | Deaths |
| 0x06 | uint16 | Suicide |
| 0x08 | uint16 | Shots fired |
| 0x0A | uint16 | Shots hit |
| 0x0C | uint16 | Headshots |

Weapon indices (0-40): Guardians, Falling Damage, Collision, Melee, Explosion, Magnum, Plasma Pistol, Needler, SMG, Plasma Rifle, Battle Rifle, Carbine, Shotgun, Sniper Rifle, Beam Rifle, Brute Plasma Rifle, Rocket Launcher, Fuel Rod, Brute Shot, Disintegrator, Sentinel Beam, Sentinel RPG, Energy Sword, Frag Grenade, Plasma Grenade, Flag Melee, Bomb Melee, Ball Melee, Human Turret, Plasma Turret, Banshee, Ghost, Mongoose, Scorpion, Spectre Driver, Spectre Gunner, Warthog Driver, Warthog Gunner, Wraith, Tank, Bomb Explosion

### pcr_stat_player (0x114 = 276 bytes per player) — StatsBorg post-game data

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
| 0x7A | int16 | Rank verified |
| 0x7C | int32 | Medals earned (count) |
| 0x80 | int32 | Medals bitmask (24-bit, yes/no only) |
| 0x84 | int32 | Total shots |
| 0x88 | int32 | Shots hit |
| 0x8C | int32 | Headshots |
| 0x90 | int32[16] | Killed-by array (kills vs each player slot) |
| 0xE0 | UTF-16LE[16] | Place string ("1st", "2nd", etc.) |
| 0x10C | int32 | Gametype value 0 |
| 0x110 | int32 | Gametype value 1 |

### team_stats (0x84 = 132 bytes per team) — StatsBorg post-game data

| Offset | Type | Field |
|--------|------|-------|
| 0x00 | UTF-16LE[32] | Team name (64 bytes) |
| 0x40 | UTF-16LE | Score string |
| 0x60 | int16 | Place (0-indexed) |
| 0x62 | int16 | Team identity index |
| 0x64 | UTF-16LE | Place string |

---

## Feature Matrix

| Feature | HaloCasterLinux | StatsBorg | HaloCaster Windows |
|---------|:-:|:-:|:-:|
| **Data Reading** | | | |
| Live in-game stats | Yes | No | Yes |
| Post-game carnage report | No | Yes | Yes |
| Per-weapon breakdown (41 weapons) | Yes | No | Yes |
| Individual medal counts | Yes | No | Yes |
| Betrayals, best spree, time alive | Yes | No | Yes |
| Killed-by matrix | No | Yes | No |
| Score/place strings | No | Yes | No |
| Team names/scores | No | Yes | Yes |
| Gametype detection | variant_info+0x40 | 0x52ED24 | variant_info+0x40 |
| Game lifecycle state | Yes | No | Yes |
| Map name | Yes | No | Yes |
| Player Xbox ID + MAC | Yes | No | Yes |
| Player emblem | Yes | No | Yes |
| Object positions/health | No | No | Yes |
| Kill feed events | No | No | Yes |
| **Connectivity** | | | |
| Remote/Docker (network) | No | Yes | No |
| Same-machine only | Yes | No | Yes |
| XBDM breakpoint detection | No | Yes | No |
| **Platform** | | | |
| Linux | Yes | Yes | No |
| Windows | No | Yes | Yes |
| **Output** | | | |
| Web dashboard (real-time) | Yes (Flask+SocketIO) | Yes (static viewer) | Yes (WinForms) |
| JSON history + dedup | No | Yes | No |
| Excel export | Yes | Yes | No |
| PostgreSQL export | No | Yes | No |
| SFTP/VPS push | Yes | No | No |
| **Control** | | | |
| Dedi mode (memory write) | Yes | No | Yes |
| Player quit tracking | Yes | No | Yes |
| Snapshot loading | Yes (QMP loadvm) | No | No |

---

## What Each Project Uniquely Contributes

### From HaloCasterLinux (keep)

- `process_vm_readv` batch reader with scatter/gather — efficient host-process memory reading
- All HaloCaster offsets and struct parsers (game_stats, medal_stats, weapon_stats)
- Player tracker with quit detection and fallback MAC generation
- Flask + SocketIO real-time web dashboard
- SFTP auto-upload + VPS webhook for remote scoreboards
- Dedi mode memory writing
- Lifecycle state tracking (lobby/starting/in_game/post_game)
- Map name resolution from scenario path
- Docker compose with correct security flags for process_vm_readv

### From StatsBorg (keep)

- QMP `xp` guest physical memory reader — works remotely/Docker without process access
- XBDM client with breakpoint support for instant game-end detection
- Post-game PGCR Display parsing (score strings, place strings, team data, killed-by matrix)
- Gametype address `0x52ED24` discovery and linear physical offset trick
- Game deduplication via fingerprint hash
- JSON history format (schema v3) with structured export pipeline
- PostgreSQL export + Excel export with multiple styles
- VA→PA cache with staleness handling

### From HaloCaster Windows (reference only — don't port the code)

- Struct definitions and offset values (already ported to Linux/Python)
- Tag system traversal patterns (for future weapon/object identification)
- Object system for positions/health/shields (not yet in Linux version)
- Kill feed circular buffer parsing (not yet in Linux version)

---

## Architecture for a Unified Tool

A combined tool would have two memory backends that share the same data pipeline:

```
┌─────────────────────────────────────────────────────────┐
│                    Unified Reader                        │
│                                                         │
│  ┌─────────────────┐      ┌──────────────────────────┐  │
│  │ Host Process     │      │ Remote/QMP               │  │
│  │ Backend          │      │ Backend                  │  │
│  │                  │      │                          │  │
│  │ QMP gpa2hva      │      │ QMP xp                   │  │
│  │ + process_vm_readv│     │ (guest physical reads)   │  │
│  │ (Linux)          │      │                          │  │
│  │                  │      │ XBDM getmem2             │  │
│  │ QMP gpa2hva      │      │ (breakpoint support)     │  │
│  │ + ReadProcessMem │      │                          │  │
│  │ (Windows, future)│      │                          │  │
│  └────────┬─────────┘      └────────────┬─────────────┘  │
│           │                              │                │
│           │  ┌───────────────────────┐   │                │
│           └──│   Data Layer          │───┘                │
│              │                       │                    │
│              │  Live Stats Parser    │                    │
│              │  PGCR Display Parser  │                    │
│              │  Gametype Detection   │                    │
│              │  Team Data            │                    │
│              └───────────┬───────────┘                    │
│                          │                                │
│              ┌───────────┴───────────┐                    │
│              │   Output Layer        │                    │
│              │                       │                    │
│              │  JSON History         │                    │
│              │  Web Dashboard        │                    │
│              │  XLSX/CSV Export      │                    │
│              │  PostgreSQL Export    │                    │
│              │  SFTP/VPS Push       │                    │
│              └───────────────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

### Backend Selection Logic

```
If running on same machine as xemu:
  → Use Host Process backend (process_vm_readv or ReadProcessMemory)
  → Access ALL data: live stats + post-game PGCR
  → 10 Hz polling for live data

If running remotely / in Docker (no process access):
  → Use Remote/QMP backend
  → Access post-game PGCR only (user-space .data section)
  → Use XBDM breakpoint or 3s polling for game detection
  → HaloCaster offsets will NOT work
```

### Docker Considerations

If xemu runs in Docker and the stat reader runs in a separate container:
- **Host Process backend**: Both containers need `pid: "host"` + `SYS_PTRACE` to share the PID namespace
- **Remote/QMP backend**: Just needs QMP TCP access (port 4444), works across any network boundary

If xemu runs on bare metal and the stat reader runs in Docker:
- **Host Process backend**: Container needs `pid: "host"` + `SYS_PTRACE`
- **Remote/QMP backend**: Works with just network access

---

## Existing Codebases and File Locations

| Codebase | Location | Language |
|----------|----------|----------|
| StatsBorg | `c:\Users\james\code\StatsBorg\` | Python |
| HaloCaster Linux | `c:\Users\james\code\StatsBorg\HaloCaster\HaloCasterLinux\` | Python |
| HaloCaster Windows | `c:\Users\james\code\HaloCaster\Halo2\xemuh2stats-main\WhatTheFuck\` | C# |
| Yelo Carnage (reference) | `c:\Users\james\code\yelo-neighborhood\Yelo Carnage\` | C# |

### Key Reference Files

- **StatsBorg QMP client**: `StatsBorg/qmp_client.py` — QMP with gva2gpa + xp reads + VA cache
- **StatsBorg XBDM client**: `StatsBorg/xbdm_client.py` — XBDM protocol + breakpoints
- **StatsBorg main reader**: `StatsBorg/halo2_stats.py` — PGCR reading, watch mode, JSON output
- **StatsBorg structs**: `StatsBorg/halo2_structs.py` — PCRPlayerStats, TeamStats, GameType enum
- **StatsBorg addresses**: `StatsBorg/addresses.json` — canonical address/struct reference
- **HaloCasterLinux engine**: `HaloCasterLinux/halocaster/engine.py` — connection + polling + all reads
- **HaloCasterLinux memory**: `HaloCasterLinux/halocaster/memory.py` — process_vm_readv wrapper
- **HaloCasterLinux QMP**: `HaloCasterLinux/halocaster/qmp.py` — gva2gpa + gpa2hva (no xp)
- **HaloCasterLinux offsets**: `HaloCasterLinux/halocaster/offsets.py` — all offsets, enums, weapons, maps
- **HaloCasterLinux stats**: `HaloCasterLinux/halocaster/stats.py` — GameStats, MedalStats, WeaponStats
- **HaloCasterLinux web**: `HaloCasterLinux/halocaster/web.py` — Flask + SocketIO dashboard
- **HaloCaster Windows QMP**: `WhatTheFuck/classes/qmp_communicator.cs` — QmpProxy with gpa2hva + Translate
- **HaloCaster Windows memory**: `WhatTheFuck/MemoryHandler.cs` — ReadProcessMemory wrapper
- **HaloCaster Windows offsets**: `WhatTheFuck/Form1.cs:873-994` — resolve_addresses()
- **Yelo Carnage PCR struct**: `Yelo Carnage/Stats.cs` — pcr_stat_player reference
- **OpenSauce**: `Networking/Statistics.hpp` — canonical struct definitions

### Dependencies

**StatsBorg core**: Python 3.7+, standard library only
**StatsBorg exports**: `psycopg2-binary`, `openpyxl`
**HaloCasterLinux**: `flask`, `flask-socketio`, `python-socketio`, `eventlet`, `openpyxl`, `gevent`, `gevent-websocket`, `paramiko`, `requests`
