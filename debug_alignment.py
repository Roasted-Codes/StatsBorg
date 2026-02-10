"""
Test if getmem2 requires 16-byte alignment for kernel VA reads.
Also test getmem (text fallback) which has no alignment requirement.

Usage: python debug_alignment.py [host]
"""
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.0.51"
PORT = 731
TIMEOUT = 5.0
READ_DELAY = 0.5  # 500ms between reads

def hexdump(data: bytes, prefix: str = "  ") -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04x}: {hex_part:<48s} {ascii_part}")
    return "\n".join(lines)

def recv_line(sock) -> str:
    """Read one line byte-by-byte."""
    data = b""
    sock.settimeout(TIMEOUT)
    try:
        while True:
            b = sock.recv(1)
            if not b:
                break
            data += b
            if data.endswith(b"\r\n"):
                break
    except socket.timeout:
        pass
    return data.decode('ascii', errors='replace').strip()

def recv_binary(sock, length: int) -> bytes:
    """Read exact number of binary bytes."""
    data = b""
    sock.settimeout(3.0)
    try:
        while len(data) < length:
            chunk = sock.recv(min(length - len(data), 4096))
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    return data

def test_getmem2(sock, label: str, addr: int, length: int) -> bool:
    """Test getmem2 (binary response)."""
    print(f"\n--- getmem2: {label} ---")
    print(f"  addr=0x{addr:08X} (align: {addr % 16})  len=0x{length:X} (align: {length % 16})")

    cmd = f"getmem2 addr=0x{addr:08X} length=0x{length:X}\r\n"
    sock.send(cmd.encode('ascii'))

    status = recv_line(sock)
    print(f"  status: \"{status}\"")

    if status.startswith("203"):
        data = recv_binary(sock, length)
        # Drain any trailing bytes
        sock.settimeout(0.2)
        try: sock.recv(64)
        except: pass
        print(f"  data: {len(data)} bytes (expected {length})")
        if data:
            print(hexdump(data))
        return len(data) == length
    else:
        print(f"  non-203 response")
        return False

def test_getmem(sock, label: str, addr: int, length: int) -> bool:
    """Test getmem (text/hex response) - no alignment requirement."""
    print(f"\n--- getmem: {label} ---")
    print(f"  addr=0x{addr:08X} (align: {addr % 16})  len=0x{length:X}")

    cmd = f"getmem addr=0x{addr:08X} length=0x{length:X}\r\n"
    sock.send(cmd.encode('ascii'))

    status = recv_line(sock)
    print(f"  status: \"{status}\"")

    if not status.startswith("2"):
        print(f"  error response")
        return False

    # For text getmem: read hex lines until "." terminator
    hex_data = ""
    while True:
        line = recv_line(sock)
        if not line or line == ".":
            break
        hex_data += line.replace(" ", "").replace("\r", "").replace("\n", "")
        if len(hex_data) >= length * 2:
            break

    if hex_data:
        try:
            data = bytes.fromhex(hex_data[:length * 2])
            print(f"  data: {len(data)} bytes")
            print(hexdump(data))
            return len(data) == length
        except ValueError as e:
            print(f"  hex parse error: {e}")
            print(f"  raw hex: {hex_data[:100]}")
            return False
    else:
        print(f"  no hex data received")
        return False

def main():
    print(f"Connecting to {HOST}:{PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)

    try:
        sock.connect((HOST, PORT))
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    banner = recv_line(sock)
    print(f"Banner: {banner!r}")

    # game_stats is at 0x83609F02 (offset 0x02 within 16-byte block)
    # Aligned down: 0x83609F00
    # We need to read 54 bytes of game_stats starting at offset +2

    # Test 1: getmem2 with ALIGNED address (0x83609F00), aligned length (0x40 = 64)
    time.sleep(READ_DELAY)
    test_getmem2(sock, "game_stats ALIGNED (0x83609F00, 0x40)", 0x83609F00, 0x40)

    # Test 2: getmem2 with UNALIGNED address (original 0x83609F02)
    time.sleep(READ_DELAY)
    test_getmem2(sock, "game_stats UNALIGNED (0x83609F02, 0x36)", 0x83609F02, 0x36)

    # Test 3: getmem (text mode) with UNALIGNED address - should work regardless
    time.sleep(READ_DELAY)
    test_getmem(sock, "game_stats via getmem (0x83609F02, 0x36)", 0x83609F02, 0x36)

    # Test 4: getmem2 with another aligned address - session_players
    # 0x83609344 → align = 4, round down to 0x83609340
    time.sleep(READ_DELAY)
    test_getmem2(sock, "session_players ALIGNED (0x83609340, 0x10)", 0x83609340, 0x10)

    # Test 5: getmem2 - life_cycle (0x83640F04) → align=4, round to 0x83640F00
    time.sleep(READ_DELAY)
    test_getmem2(sock, "life_cycle ALIGNED (0x83640F00, 0x10)", 0x83640F00, 0x10)

    # Test 6: getmem for variant_info (0x836090EC) → align=12, round to 0x836090E0
    time.sleep(READ_DELAY)
    test_getmem2(sock, "variant_info ALIGNED (0x836090E0, 0x80)", 0x836090E0, 0x80)

    try:
        sock.send(b"bye\r\n")
    except:
        pass
    sock.close()
    print(f"\nDone.")

if __name__ == "__main__":
    main()
