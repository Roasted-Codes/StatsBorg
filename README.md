# StatsBorg — Halo 2 Post-Game Stats Reader

Cross-platform Python tool to read Halo 2 multiplayer post-game statistics from Xbox/Xemu via XBDM (Xbox Debug Monitor) protocol. Linux-compatible alternative to Windows-only HaloCaster.

## Features

- **Cross-platform**: Works on Windows, Linux, and macOS
- **Direct XBDM**: Reads memory via standard XBDM protocol (no Windows APIs)
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
- Halo 2 running on the Xbox/emulator

## Usage

```bash
# Read post-game stats (tries PGCR Display first, falls back to PCR)
python halo2_stats.py --host 172.20.0.51

# Watch for game completions and auto-save history
python halo2_stats.py --host 172.20.0.51 --watch

# One-shot save to history directory
python halo2_stats.py --host 172.20.0.51 --save

# JSON output
python halo2_stats.py --host 172.20.0.51 --json

# Simple K/D/A output (compact format)
python halo2_stats.py --host 172.20.0.51 --simple

# Label gametype-specific stats
python halo2_stats.py --host 172.20.0.51 -g ctf

# Hex dump PGCR Display header (research)
python halo2_stats.py --host 172.20.0.51 --dump-header

# Test XBDM connection
python xbdm_client.py 172.20.0.51
```

## Project Structure

```
xbdm_client.py           # XBDM protocol client (TCP:731)
halo2_structs.py          # Data structures, addresses, struct parsing
halo2_stats.py            # Main CLI tool
live_stats.py             # Live in-game stats (non-functional via XBDM — see file header)
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

1. Connect to XBDM on port 731
2. Probe PGCR Display at `0x56B900` for populated player data
3. Read player stats (0x114-byte structs), team data, and gametype from memory
4. Parse into structured data and output as rich scoreboard or JSON

The primary data source is the **PGCR Display** structure at `0x56B900`, which contains a 0x90-byte header followed by 16 player records and 8 team records. This is populated during gameplay and on the post-game carnage report screen.

## Credits

- Memory structures from [OpenSauce](https://github.com/OpenSauce-Halo-CE/OpenSauce) (`Networking/Statistics.hpp`)
- Research informed by [HaloCaster](https://github.com/I2aMpAnT/HaloCaster) and [Yelo Carnage](https://github.com/OpenSauce-Halo-CE/OpenSauce)
- Address reference from xbox7887 stats memory documentation
