"""
Debug XBDM protocol - GENTLE version with long delays to prevent Xemu freezes.
Shows exact bytes received to diagnose parsing issues.

Usage: python debug_xbdm_protocol.py [host]
"""
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.0.51"
PORT = 731
TIMEOUT = 5.0
READ_DELAY = 0.5  # 500ms between reads - very conservative

def hexdump(data: bytes, prefix: str = "  ") -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04x}: {hex_part:<48s} {ascii_part}")
    return "\n".join(lines)

def recv_status_and_data(sock, expected_data_len: int) -> tuple:
    """Read status line byte-by-byte, then read exact binary data."""
    # Read status line byte by byte
    status_bytes = b""
    sock.settimeout(TIMEOUT)
    try:
        while True:
            b = sock.recv(1)
            if not b:
                break
            status_bytes += b
            if status_bytes.endswith(b"\r\n"):
                break
    except socket.timeout:
        return status_bytes, b"", "timeout reading status line"

    status_line = status_bytes.decode('ascii', errors='replace').strip()

    if not status_line.startswith("203"):
        return status_bytes, b"", f"non-203 status: {status_line}"

    # Read exactly expected_data_len bytes of binary data
    data = b""
    remaining = expected_data_len
    sock.settimeout(3.0)
    try:
        while remaining > 0:
            chunk = sock.recv(min(remaining, 4096))
            if not chunk:
                break
            data += chunk
            remaining -= len(chunk)
    except socket.timeout:
        pass

    # Check if there's trailing data (like \r\n)
    trailing = b""
    sock.settimeout(0.3)
    try:
        trailing = sock.recv(64)
    except socket.timeout:
        pass

    return status_bytes, data, trailing

def test_read(sock, label: str, addr: int, length: int):
    """Send getmem2 and show detailed response."""
    print(f"\n--- {label} ---")
    print(f"  addr=0x{addr:08X}  len=0x{length:X}")

    cmd = f"getmem2 addr=0x{addr:08X} length=0x{length:X}\r\n"
    sock.send(cmd.encode('ascii'))

    status_raw, data, trailing = recv_status_and_data(sock, length)
    status_str = status_raw.decode('ascii', errors='replace').strip()

    print(f"  status: \"{status_str}\"")
    print(f"  data: {len(data)} bytes (expected {length})")

    if data:
        print(hexdump(data))

    if isinstance(trailing, bytes) and trailing:
        print(f"  trailing ({len(trailing)} bytes): {trailing.hex()} = {trailing.decode('ascii', errors='replace')!r}")

    if len(data) != length:
        print(f"  *** MISMATCH: got {len(data)}, expected {length} ***")

    return len(data) == length

def main():
    print(f"Connecting to {HOST}:{PORT}...")
    print(f"Using {READ_DELAY*1000:.0f}ms delay between reads (gentle mode)")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)

    try:
        sock.connect((HOST, PORT))
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # Read banner
    banner = b""
    sock.settimeout(3.0)
    try:
        while True:
            b = sock.recv(1)
            if not b:
                break
            banner += b
            if banner.endswith(b"\r\n"):
                break
    except socket.timeout:
        pass
    print(f"Banner: {banner.decode('ascii', errors='replace').strip()!r}")

    tests = [
        ("User-space: profile @ 0x53D008",     0x53D008,    32),
        ("Kernel VA: RAM base @ 0x80000000",    0x80000000,  32),
        ("Kernel VA: game_stats @ 0x83609F02",  0x83609F02,  54),
        ("Kernel VA: life_cycle @ 0x83640F04",  0x83640F04,   4),
        ("Kernel VA: variant_info @ 0x836090EC", 0x836090EC, 64),
    ]

    for i, (label, addr, length) in enumerate(tests):
        time.sleep(READ_DELAY)
        ok = test_read(sock, label, addr, length)
        if not ok:
            print(f"  Read failed, stopping to avoid freeze")
            break

    try:
        sock.send(b"bye\r\n")
    except:
        pass
    sock.close()
    print(f"\nDone.")

if __name__ == "__main__":
    main()
