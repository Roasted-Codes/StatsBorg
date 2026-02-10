#!/usr/bin/env python3
"""
Diagnostic tool to test memory address reading via XBDM.

Tests various address formats to determine what xbdm_gdb_bridge expects.
Uses very conservative delays (500ms) and single reads to prevent crashes.

Usage:
    python diagnose_addresses.py --host 127.0.0.1
"""

import argparse
import time
import sys
from xbdm_client import XBDMClient


def hexdump(data: bytes, addr: int = 0) -> str:
    """Format bytes as hex dump with ASCII."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = ' '.join(f'{b:02X}' for b in chunk)
        ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        lines.append(f"  {addr+i:08X}: {hex_part:<48} {ascii_part}")
    return '\n'.join(lines)


def test_address(client: XBDMClient, name: str, addr: int, length: int = 32) -> bool:
    """Test reading from a specific address with verbose output."""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"Address: 0x{addr:08X} ({addr:,} bytes from start)")
    print(f"Length:  {length} bytes")
    print('='*60)

    # Extra delay before read
    time.sleep(0.5)

    try:
        data = client.read_memory(addr, length)

        if data is None:
            print("Result: FAILED - No data returned")
            return False

        if len(data) != length:
            print(f"Result: PARTIAL - Got {len(data)} of {length} bytes")
        else:
            print(f"Result: SUCCESS - Got {len(data)} bytes")

        # Check if all zeros
        if all(b == 0 for b in data):
            print("Warning: All bytes are zero (might be unpopulated)")

        print("\nHex dump:")
        print(hexdump(data, addr))

        # Extra delay after read
        time.sleep(0.3)
        return True

    except Exception as e:
        print(f"Result: ERROR - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Diagnose XBDM address reading")
    parser.add_argument("--host", "-H", default="127.0.0.1", help="XBDM host")
    parser.add_argument("--port", "-p", type=int, default=731, help="XBDM port")
    args = parser.parse_args()

    print("=" * 60)
    print(" XBDM Address Diagnostic Tool")
    print("=" * 60)
    print(f"\nConnecting to {args.host}:{args.port}...")

    # Very slow read delay for safety
    client = XBDMClient(args.host, args.port, read_delay=0.5)

    if not client.connect():
        print("ERROR: Failed to connect to XBDM")
        print("\nMake sure xbdm_gdb_bridge is running!")
        sys.exit(1)

    print("Connected!\n")

    # Define test addresses
    # Format: (name, address, expected_description)
    #
    # HaloCaster uses: Xbox VA = 0x8005C000 + offset
    # Physical = Xbox VA - 0x80000000 = 0x5C000 + offset
    #
    XBE_BASE_VIRT = 0x8005C000
    XBE_BASE_PHYS = 0x5C000

    test_cases = [
        # Known working address (PCR stats)
        ("PCR Stats (physical)", 0x55CAF0, "Post-game carnage report - KNOWN WORKING"),

        # Test if virtual addresses work for PCR
        ("PCR Stats (virtual)", 0x8055CAF0, "Same as PCR but with 0x80000000"),

        # Life Cycle - try virtual format (XBE_BASE + offset)
        ("Life Cycle (virtual)", XBE_BASE_VIRT + 0x35E4F04, "Game state - 0x83640F04"),

        # Life Cycle - try physical format
        ("Life Cycle (physical)", XBE_BASE_PHYS + 0x35E4F04, "Game state - 0x03640F04"),

        # Session players - virtual
        ("Session Players (virtual)", XBE_BASE_VIRT + 0x35AD344, "Player names - 0x83609344"),

        # Session players - physical
        ("Session Players (physical)", XBE_BASE_PHYS + 0x35AD344, "Player names - 0x03609344"),

        # Game stats player 0 - virtual
        ("Game Stats P0 (virtual)", XBE_BASE_VIRT + 0x35ADF02, "Live stats - 0x83609F02"),

        # Game stats player 0 - physical
        ("Game Stats P0 (physical)", XBE_BASE_PHYS + 0x35ADF02, "Live stats - 0x03609F02"),
    ]

    results = []

    for name, addr, desc in test_cases:
        print(f"\n{desc}")
        success = test_address(client, name, addr, 32)
        results.append((name, addr, success))

        # Ask user if they want to continue after each test
        if not success:
            print("\n[!] This address failed. System might be unstable.")

        # Extra safety delay between tests
        time.sleep(1.0)

    # Summary
    print("\n" + "=" * 60)
    print(" SUMMARY")
    print("=" * 60)

    for name, addr, success in results:
        status = "[OK]  " if success else "[FAIL]"
        print(f"  {status}  0x{addr:08X}  {name}")

    print("\n" + "=" * 60)
    print(" INTERPRETATION")
    print("=" * 60)

    # Analyze results
    pcr_phys_ok = results[0][2]  # PCR physical
    pcr_virt_ok = results[1][2]  # PCR virtual
    life_phys_ok = results[2][2]  # Life cycle physical
    life_virt_ok = results[3][2]  # Life cycle virtual

    if pcr_phys_ok and not pcr_virt_ok:
        print("  → xbdm_gdb_bridge uses PHYSICAL addresses (0x00000000+)")
    elif pcr_virt_ok and not pcr_phys_ok:
        print("  → xbdm_gdb_bridge uses VIRTUAL addresses (0x80000000+)")
    elif pcr_phys_ok and pcr_virt_ok:
        print("  → xbdm_gdb_bridge accepts BOTH address formats")
    else:
        print("  → Could not determine address format (both failed)")

    if life_phys_ok or life_virt_ok:
        addr_type = "physical" if life_phys_ok else "virtual"
        print(f"  → Live stats addresses work with {addr_type} format!")
    else:
        print("  → Live stats addresses NOT working - may need different offsets")

    print()
    client.disconnect()


if __name__ == "__main__":
    main()
