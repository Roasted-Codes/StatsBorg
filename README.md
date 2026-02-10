# Halo 2 Stats Reader

Cross-platform live statistics collection for Halo 2 via XBDM protocol.

## Overview

This tool reads live game statistics directly from Halo 2's memory on Xbox (or Xemu emulator) using the Xbox Debug Monitor (XBDM) protocol. Unlike other approaches that rely on Windows-specific memory reading APIs, this tool communicates directly with XBDM on port 731, making it fully cross-platform.

## Features

- **Cross-platform**: Works on Windows, Linux, and macOS
- **Direct XBDM**: Reads memory via standard XBDM protocol (no Windows APIs)
- **Live stats**: Real-time kill/death/assist tracking
- **JSON output**: Machine-readable output for integrations
- **Polling mode**: Continuous stats updates at configurable intervals
- **Game mode stats**: Supports CTF, Assault, Oddball, KOTH, Juggernaut, Territories

## Requirements

- Python 3.7+
- One of:
  - Xbox with XBDM enabled (debug kit or modded console)
  - Xemu emulator with [xbdm_gdb_bridge](https://github.com/abaire/xbdm_gdb_bridge)
- Halo 2 running on the Xbox/emulator

## Installation

```bash
# Clone this repository
git clone <this-repo>
cd halo2-stats

# No additional dependencies required - uses Python standard library only
```

## Usage

### Basic Usage

```bash
# Read stats once from Xbox at 192.168.1.100
python halo2_stats.py --host 192.168.1.100

# Read stats from Xemu (localhost via xbdm_gdb_bridge)
python halo2_stats.py --host 127.0.0.1
```

### Output Modes

```bash
# Pretty console output (default)
python halo2_stats.py --host 127.0.0.1

# JSON output to console
python halo2_stats.py --host 127.0.0.1 --json

# Save JSON to file
python halo2_stats.py --host 127.0.0.1 --output stats.json
```

### Polling Mode

```bash
# Update every 5 seconds
python halo2_stats.py --host 127.0.0.1 --poll 5

# Update every second with JSON output
python halo2_stats.py --host 127.0.0.1 --poll 1 --json
```

### All Options

```
usage: halo2_stats.py [-h] [--host HOST] [--port PORT] [--poll POLL]
                      [--output OUTPUT] [--json] [--verbose] [--timeout TIMEOUT]

Read live Halo 2 statistics via XBDM

options:
  -h, --help            show this help message and exit
  --host HOST, -H HOST  Xbox/Xemu IP address (default: 127.0.0.1)
  --port PORT, -p PORT  XBDM port (default: 731)
  --poll POLL, -P POLL  Poll interval in seconds (0 = single read)
  --output OUTPUT, -o OUTPUT
                        Output file path for JSON data
  --json, -j            Output as JSON instead of formatted text
  --verbose, -v         Enable verbose debug output
  --timeout TIMEOUT, -t TIMEOUT
                        Connection timeout in seconds (default: 5.0)
```

## JSON Output Format

```json
{
  "timestamp": "2024-01-15T14:30:00.123456",
  "player_count": 4,
  "team_scores": {
    "red": 15,
    "blue": 12
  },
  "teams": {
    "red": [/* player objects */],
    "blue": [/* player objects */]
  },
  "players": [
    {
      "index": 0,
      "player": {
        "name": "Player1",
        "team": "red",
        "character": "spartan",
        "colors": {
          "primary": "red",
          "secondary": "white"
        }
      },
      "stats": {
        "kills": 10,
        "assists": 3,
        "deaths": 5,
        "betrayals": 0,
        "suicides": 1,
        "best_spree": 4,
        "ctf": { "scores": 0, "flag_steals": 0 },
        "oddball": { "score": 0, "ball_kills": 0 }
      }
    }
  ]
}
```

## Architecture

```
┌─────────────────┐     TCP:731     ┌──────────────────┐     XBDM     ┌──────────┐
│ halo2_stats.py  │ ─────────────── │ xbdm_gdb_bridge  │ ───────────  │   Xemu   │
│  (this tool)    │                 │  (for emulator)  │              │  Halo 2  │
└─────────────────┘                 └──────────────────┘              └──────────┘

                    OR (real hardware)

┌─────────────────┐     TCP:731     ┌──────────┐
│ halo2_stats.py  │ ─────────────── │   Xbox   │
│  (this tool)    │                 │  xbdm    │
└─────────────────┘                 └──────────┘
```

## How It Works

1. Connect to XBDM on port 731 (standard Xbox Debug Monitor port)
2. Use `getmem2` command to read raw memory from known addresses
3. Parse memory into structured data (kills, deaths, player names, etc.)
4. Format and output as text or JSON

### Memory Addresses (Halo 2 Xbox)

| Data | Base Address | Notes |
|------|--------------|-------|
| Game Stats | XBE+0x35ADF02 | Live K/D/A per player |
| Session Players | XBE+0x35AD344 | Player names, teams |
| Weapon Stats | XBE+0x35ADFE0 | Per-weapon breakdown |
| Medal Stats | XBE+0x35ADF4E | Medals earned |

## Troubleshooting

### "Failed to connect to XBDM"

1. **For Xemu**: Make sure `xbdm_gdb_bridge` is running first
2. **For real Xbox**: Ensure XBDM is loaded and network is configured
3. Check that port 731 is not blocked by firewall
4. Verify the IP address is correct

### "No players found"

- Make sure a game is actually in progress (not in menus)
- In System Link lobbies, stats may not populate until match starts
- Try with `--verbose` to see what addresses are being read

### "Failed to read memory"

- XBDM connection may have timed out
- Memory addresses may differ for different game versions
- Check `xbdm_gdb_bridge` logs for errors

## Credits

- Based on research from [HaloCaster](https://github.com/I2aMpAnT/HaloCaster)
- Memory structures from [Yelo Carnage](https://github.com/OpenSauce-Halo-CE/OpenSauce)
- Uses [xbdm_gdb_bridge](https://github.com/abaire/xbdm_gdb_bridge) for Xemu support

## License

MIT License - See LICENSE file for details
