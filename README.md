# StatsBorg — Halo 2 Post-Game Stats Reader

Cross-platform Python tool to read Halo 2 multiplayer post-game statistics from Xbox/Xemu via XBDM (Xbox Debug Monitor) and QMP (QEMU Machine Protocol). Linux-compatible alternative to Windows-only HaloCaster.

## Features

- **Cross-platform**: Works on Windows, Linux, and macOS
- **Dual protocol**: XBDM (direct Xbox memory) and QMP (Xemu guest physical memory)
- **Post-game stats**: Kills, deaths, assists, suicides, accuracy, medals, gametype-specific stats
- **Team support**: Team names, scores, and per-player team assignments
- **Watch mode**: Auto-detects game completions and saves history
- **JSON output**: Machine-readable output for integrations
- **Rich scoreboard**: Detailed output with accuracy, medals, gametype stats
- **Game mode stats**: CTF, Slayer, Assault, Oddball, KOTH, Juggernaut, Territories
- **Export pipeline**: Optional PostgreSQL and Excel export scripts

## Requirements

- Python 3.7+ (standard library only — no pip dependencies)
- One of:
  - Xbox with XBDM enabled (debug kit or modded console with CerbiosDebug)
  - Xemu emulator with [xbdm_gdb_bridge](https://github.com/abaire/xbdm_gdb_bridge) or native CerbiosDebug
  - Xemu with QMP enabled (`-qmp tcp:0.0.0.0:4444,server,nowait`)
- Halo 2 running on the Xbox/emulator

## Usage

### XBDM (direct Xbox memory reads)

```bash
# Read post-game stats
python halo2_stats.py --host 172.20.0.51

# Watch for game completions and auto-save history
python halo2_stats.py --host 172.20.0.51 --watch

# Watch with instant breakpoint detection (instead of polling)
python halo2_stats.py --host 172.20.0.51 --watch --breakpoint

# One-shot save to history directory
python halo2_stats.py --host 172.20.0.51 --save

# JSON output
python halo2_stats.py --host 172.20.0.51 --json

# Test XBDM connection
python xbdm_client.py 172.20.0.51
```

### QMP (Xemu guest physical memory reads)

```bash
# Read post-game stats via QMP (same output as XBDM)
python halo2_stats.py --host 172.20.0.10 --qmp 4444

# Watch mode via QMP
python halo2_stats.py --host 172.20.0.10 --qmp 4444 --watch

# Test QMP connection
python qmp_client.py 172.20.0.10 4444 --pgcr
```

## Project Structure

```
xbdm_client.py           # XBDM protocol client (TCP:731)
qmp_client.py            # QMP protocol client (TCP:4444, guest physical reads)
halo2_structs.py          # Data structures, addresses, struct parsing
halo2_stats.py            # Main CLI tool
live_stats.py             # Live in-game stats structs/parsers
exports/
  db_export.py            # PostgreSQL export (requires psycopg2-binary)
  xlsx_export.py          # Excel export (requires openpyxl)
  requirements.txt        # Optional dependencies for export scripts
research/                 # Debugging and memory discovery scripts
```

## Export (Optional)

Export scripts require additional dependencies:

```bash
pip install -r exports/requirements.txt

# PostgreSQL export
python exports/db_export.py --init-schema
python exports/db_export.py --import-history

# Excel export
python exports/xlsx_export.py --history-dir history/ -o halo2_stats.xlsx
```

## How It Works

1. Connect via XBDM (port 731) or QMP (port 4444)
2. Probe PGCR Display at `0x56B900` for populated player data
3. Read player stats (0x114-byte structs), team data, and gametype from memory
4. Parse into structured data and output as rich scoreboard or JSON

The primary data source is the **PGCR Display** structure at `0x56B900`, which contains a 0x90-byte header followed by 16 player records and 8 team records. QMP translates Xbox virtual addresses to physical via `gva2gpa` page table walk, making both protocols read the exact same data.

## Credits

- Memory structures from [OpenSauce](https://github.com/OpenSauce-Halo-CE/OpenSauce) (`Networking/Statistics.hpp`)
- Research informed by [HaloCaster](https://github.com/I2aMpAnT/HaloCaster) and [Yelo Carnage](https://github.com/OpenSauce-Halo-CE/OpenSauce)
- Address reference from xbox7887 stats memory documentation
