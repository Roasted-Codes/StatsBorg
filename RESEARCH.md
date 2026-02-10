# Research Notes

Technical research and findings for the Halo 2 Stats Reader project.

---

## Current Status

**Phase:** Address Discovery
**Blocker:** Live stats memory address not yet found

### What Works
- XBDM connection to Xemu via xbdm_gdb_bridge on port 731
- Memory reading with rate limiting (50ms delay)
- String table verification (e.g., `0x4603B8` = "kills")
- Profile data at `0x53D008` (player name)
- PCR structure parsing (`PCRPlayerStats`, `GameStats`, `PGCRDisplayStats`)

### What Doesn't Work
- **Live stats during gameplay** - HaloCaster addresses (`0x35ADxxxx`) are Windows process memory, not Xbox memory
- PCR at `0x55CAF0` only populates **after** game ends
- Heavy memory scanning can freeze Xemu even with rate limiting

---

## Memory Address Research

### Address Space Mapping (Resolved Feb 2026)

HaloCaster reads Xemu's **Windows process memory** via:
- QMP (QEMU Monitor Protocol) for address translation
- `ReadProcessMemory()` Windows API to read flat RAM buffer

We read **Xbox virtual memory** via XBDM (CerbiosDebug native, port 731).

**HaloCaster Base Address Calculation** (from `Form1.cs:resolve_addresses()`):
```
Host Address = QMP.Translate(0x80000000) + 0x5C000 + offset
Physical RAM Address = 0x5C000 + offset
Kernel VA = 0x80000000 + 0x5C000 + offset = 0x8005C000 + offset
```

**XBDM Memory Access Limitation (Confirmed Feb 2026):**

XBDM (CerbiosDebug) can only read committed virtual memory pages. The `walkmem` command
reveals a GAP in the kernel VA space from 0x83145000 to 0x83AC4000 (~49MB to ~59MB physical).
All HaloCaster live stats offsets land in this uncommitted region:

| Address | Physical | Status | Why |
|---------|----------|--------|-----|
| `0x83609F02` | 54.04 MB | **INACCESSIBLE** | Uncommitted kernel pages |
| `0x83609344` | 54.04 MB | **INACCESSIBLE** | Uncommitted kernel pages |
| `0x83640F04` | 54.25 MB | **INACCESSIBLE** | Uncommitted kernel pages |
| `0x836090EC` | 54.04 MB | **INACCESSIBLE** | Uncommitted kernel pages |

This physical region is likely GPU/contiguous physical memory allocated via `MmAllocateContiguousMemory`.
The GPU accesses it directly via physical address, not through the CPU's MMU page tables.
HaloCaster reads it from the HOST side where all 64MB is a flat buffer (ReadProcessMemory).

**Working addresses** (in .data section, committed pages):

| Source | Address | What It Is | Works with XBDM? |
|--------|---------|------------|------------------|
| Yelo/OpenSauce | `0x55CAF0` | PCR stats array | Yes, post-game only (in .data) |
| Empirical | `0x56B900` | PGCR display | Yes, post-game screen only (in .data) |
| Empirical | `0x53D008` | Profile data | Yes (in .data) |

**Conclusion:** Live stats require QMP (reads host process memory). Post-game stats work via XBDM.

### XBE Memory Layout (from `modules` + `modsections`)

```
Module: halo2ship.exe  base=0x000118E0  size=0x005ADBC0

Section         Start        End          Size       Prot
.text           0x00012000   0x00383D2C   3.46 MB    CODE
DSOUND          0x00383D40   0x00391464   54 KB      DATA
.rdata          0x0041B600   0x0046D6CC   321 KB     RONLY
.data           0x0046D6E0   0x00573858   1.02 MB    RW     ← PCR, PGCR here
DOLBY           0x00573860   0x0057A9E0   28 KB      CODE
```

### XBDM Accessible Range (from `walkmem` + boundary testing)

```
User-space committed:  0x00010000 - 0x005C1000  (~5.7 MB)
Kernel committed:      0x80000000 - 0x83145000  (~49.3 MB)
Kernel gap:            0x83145000 - 0x83AC4000  (UNCOMMITTED - GPU/contiguous)
Kernel committed:      0x83AC4000 - 0x84010000  (~5.3 MB)
XBDM module:          0xB000D000 - 0xB0075000
```

### Discovered Addresses (Empirical)

Found via `diff_monitor.py` memory scanning:

```
Profile region:       0x53E0C0 (stride 0x90 per player)
Session players:      0x55D790 (stride 0x1F8 per player)
Player struct:        0x53D000 (contains name, partial stats)
Game state area:      0x55C300 (changes during gameplay)
PGCR display:         0x56B900 (only during post-game screen)
```

### PGCR Display Structure (0x56B900)

Different layout than PCR at `0x55CAF0`. Verified offsets:

| Offset | Type | Field | Verified Value |
|--------|------|-------|----------------|
| 0x84 | int32 | Place | 1 (1st place) |
| 0x90 | UTF-16 | Player name | "Default" |
| 0xCC | UTF-16 | Score string | "-4" |
| 0xF4 | int32 | Deaths | 4 |
| 0xFC | int32 | Suicides | 4 |
| 0x114 | int32 | Total shots | 109 |
| 0x118 | int32 | Shots hit | 0 |
| 0x11C | int32 | Headshots | 0 |
| 0x120 | int32[16] | Killed-by array | [4, 0, 0, ...] |
| 0x168 | UTF-16 | Place string | "1st" |

### Next Steps for Live Stats

**XBDM path is a dead end for live stats** (HaloCaster offsets are in uncommitted GPU memory).

**QMP is the path forward:**
1. Expose QMP port (4444) from Docker container
2. Implement Python QMP client (JSON over TCP, `human-monitor-command` + `x` command)
3. Read at physical addresses: `0x5C000 + haloc_offset`
4. Reference: HaloCaster `qmp_communicator.cs` for full implementation

---

## XBDM Protocol

### Overview

XBDM (Xbox Debug Monitor) runs on port 731. Text-based protocol similar to FTP.

```
Client connects → Server: "201- connected\r\n"
Client: "getmem2 addr=0x55CAF0 length=0x100\r\n"
Server: "203- binary response follows\r\n" + <binary data>
Client: "bye\r\n"
```

### Key Commands

| Command | Response | Description |
|---------|----------|-------------|
| `getmem2 addr=X length=Y` | 203 + binary | Read memory (preferred) |
| `getmem addr=X length=Y` | 200 + hex text | Read memory (fallback) |
| `setmem addr=X data=HEX` | 200 | Write memory |
| `modules` | 202 + list | List loaded modules |
| `dmversion` | Version info | Debug monitor version |
| `stop` | Pause execution | Freeze game |
| `go` | Resume execution | Unfreeze game |
| `bye` | Disconnect | Close connection |

### Rate Limiting (Critical)

**Problem:** Rapid memory reads freeze Xemu/Xbox.

**Solution:** 50ms minimum delay between `getmem2` calls.

```python
# In XBDMClient
DEFAULT_READ_DELAY = 0.05  # 50ms between reads
MIN_READ_DELAY = 0.01      # 10ms absolute minimum (risky)
```

**Why it matters:**
- Each read requires XBDM to copy data and send over network
- Unthrottled reads monopolize CPU, starve the game
- 128MB debug kits handle this better than 64MB retail

### Best Practices

1. **Throttle reads** - 50ms delay minimum, more for scanning
2. **Read efficiently** - One struct at a time, not huge ranges
3. **Handle errors** - 404 = unmapped memory, don't retry forever
4. **Single connection** - Reuse socket, don't reconnect repeatedly
5. **Avoid writes** - Stay read-only unless necessary
6. **No file I/O during gameplay** - Can freeze console

### Error Codes

| Code | Meaning |
|------|---------|
| 200 | Success (text response) |
| 201 | Connected |
| 202 | Multiline response follows |
| 203 | Binary response follows |
| 401 | Max connections exceeded (limit: 4) |
| 404 | Memory not mapped |

---

## Xemu Networking

### NAT Mode vs Bridge Mode

| Mode | System Link | Debugging | Recommended For |
|------|-------------|-----------|-----------------|
| NAT | No | Easy (localhost) | Development/debugging |
| Bridge | Yes | Hard (firewall issues) | LAN multiplayer |

### NAT Mode (Default)

- Xbox behind virtual router inside Xemu
- Connect to `127.0.0.1:731` for XBDM
- xbdm_gdb_bridge works easily
- **Cannot** do real system link

### Bridge Mode

- Xbox gets real LAN IP
- Required for system link
- Debugging complications:
  - Must bind to LAN IP, not `127.0.0.1`
  - Must open firewall port 731
  - Need raw networking permissions

### Bridge Mode Debugging Setup

**Linux:**
```bash
# Give xemu raw networking capability
sudo setcap cap_net_raw,cap_net_admin=eip /path/to/xemu

# Open firewall
sudo ufw allow 731/tcp
```

**Windows:**
- Create inbound firewall rule for TCP port 731
- Bind debug bridge to `0.0.0.0:731` or LAN IP

**Key rule:** For bridged guest to reach host service, service must bind to LAN IP, not `127.0.0.1`.

---

## Reference Materials

### External Sources

- [XboxDevWiki - XBDM](https://xboxdevwiki.net/Xbox_Debug_Monitor)
- [OpenSauce Statistics.hpp](https://github.com/smx-smx/open-sauce/blob/master/OpenSauce/Halo2/Halo2_Xbox/Networking/Statistics.hpp)
- [xbdm_gdb_bridge](https://github.com/abaire/xbdm_gdb_bridge)

### Local Reference Files

- `halo v1.5.xbe.orig.map` - Symbol map with string addresses

### HaloCaster Source (External)

Key files for address reference:
- `Form1.cs` lines 767-782 - Address offsets
- `objects/game_stats.cs` - s_game_stats structure (54 bytes, stride 0x36A)
- `objects/real_time_player_stats.cs` - Player properties

### Yelo Carnage Source (External)

- `Stats.cs` - PCR structure at `0x55CAF0`
- Uses XBDM breakpoint at `0x233194` to detect post-game

---

## Version Notes

- Addresses are for **retail Halo 2 Xbox v1.0/v1.5**
- PAL, NTSC, and update versions may differ
- Debug XBE may have different addresses than retail
