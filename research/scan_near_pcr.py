#!/usr/bin/env python3
"""
Scan memory regions near known PCR address to find live stats.

The PCR address 0x55CAF0 works. Let's explore nearby memory.
"""

import argparse
import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from xbdm_client import XBDMClient


def hexdump_line(data: bytes, addr: int) -> str:
    """Single line hex dump."""
    hex_part = ' '.join(f'{b:02X}' for b in data[:16])
    ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:16])
    return f"{addr:08X}: {hex_part:<48} {ascii_part}"


def scan_region(client: XBDMClient, start: int, end: int, chunk: int = 64):
    """Scan a memory region and show non-zero areas."""
    print(f"\nScanning 0x{start:08X} - 0x{end:08X} ({(end-start)//1024}KB)")
    print("-" * 70)

    addr = start
    empty_count = 0
    found_data = False

    while addr < end:
        time.sleep(0.1)  # Rate limit

        data = client.read_memory(addr, chunk)
        if data is None:
            print(f"  [!] Read failed at 0x{addr:08X}")
            break

        # Check if chunk has data
        if any(b != 0 for b in data):
            if empty_count > 0:
                print(f"  ... ({empty_count} empty chunks skipped)")
                empty_count = 0

            print(f"  {hexdump_line(data, addr)}")
            found_data = True
        else:
            empty_count += 1

        addr += chunk

    if empty_count > 0:
        print(f"  ... ({empty_count} empty chunks at end)")

    if not found_data:
        print("  (all zeros)")

    return found_data


def main():
    parser = argparse.ArgumentParser(description="Scan memory near PCR address")
    parser.add_argument("--host", "-H", default="127.0.0.1", help="XBDM host")
    parser.add_argument("--port", "-p", type=int, default=731, help="XBDM port")
    args = parser.parse_args()

    print("=" * 70)
    print(" Memory Scanner - Finding Live Stats Near PCR")
    print("=" * 70)

    client = XBDMClient(args.host, args.port, read_delay=0.1)

    if not client.connect():
        print("ERROR: Failed to connect")
        sys.exit(1)

    print("Connected!\n")

    # PCR is at 0x55CAF0, size 0x114 * 16 players = 0x1140
    # Let's scan around it

    PCR_BASE = 0x55CAF0
    PCR_SIZE = 0x1140  # 16 players

    regions = [
        # Before PCR
        ("Before PCR (-4KB)", PCR_BASE - 0x1000, PCR_BASE),

        # PCR itself
        ("PCR Stats", PCR_BASE, PCR_BASE + PCR_SIZE),

        # After PCR
        ("After PCR (+4KB)", PCR_BASE + PCR_SIZE, PCR_BASE + PCR_SIZE + 0x1000),

        # Lower memory where game data might be
        ("Low memory (0x10000-0x11000)", 0x10000, 0x11000),

        # Around profile_data address
        ("Profile area (0x53D000)", 0x53D000, 0x53E000),
    ]

    for name, start, end in regions:
        print(f"\n{'='*70}")
        print(f" {name}")
        print('='*70)

        try:
            scan_region(client, start, end, 64)
        except KeyboardInterrupt:
            print("\n[Interrupted]")
            break
        except Exception as e:
            print(f"  Error: {e}")

    print("\n" + "=" * 70)
    print(" Scan complete!")
    print("=" * 70)

    client.disconnect()


if __name__ == "__main__":
    main()
