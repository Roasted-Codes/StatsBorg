"""
Find the boundary of accessible kernel VA memory.
SAFE: One fresh TCP connection per read, long delays, minimal reads.

Usage: python debug_boundary.py [host]
"""
import socket
import sys
import time

HOST = sys.argv[1] if len(sys.argv) > 1 else "172.20.0.51"
PORT = 731
TIMEOUT = 5.0

def test_single_read(addr: int, length: int = 16) -> tuple:
    """Open fresh connection, read one address, close. Returns (bytes_got, hex_preview)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)
    try:
        sock.connect((HOST, PORT))
    except:
        return (-1, "")

    # Read banner
    buf = b""
    try:
        while not buf.endswith(b"\r\n"):
            buf += sock.recv(1)
    except:
        sock.close()
        return (-1, "")

    # Send getmem2
    cmd = f"getmem2 addr=0x{addr:08X} length=0x{length:X}\r\n"
    sock.send(cmd.encode('ascii'))

    # Read status line
    status = b""
    try:
        while not status.endswith(b"\r\n"):
            status += sock.recv(1)
    except:
        sock.close()
        return (-1, "")

    status_str = status.decode('ascii', errors='replace').strip()

    if not status_str.startswith("203"):
        sock.send(b"bye\r\n")
        sock.close()
        return (-2, status_str)

    # Read binary data
    data = b""
    sock.settimeout(1.5)
    try:
        while len(data) < length:
            chunk = sock.recv(min(length - len(data), 4096))
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass

    preview = " ".join(f"{b:02x}" for b in data[:8]) if data else ""

    try:
        sock.send(b"bye\r\n")
    except:
        pass
    sock.close()
    return (len(data), preview)

def main():
    print(f"Testing kernel VA accessibility on {HOST}:{PORT}")
    print(f"One fresh connection per test, 1s between tests\n")

    tests = [
        (0x80000000, "Phys 0MB  (RAM base)"),
        (0x81000000, "Phys 16MB"),
        (0x82000000, "Phys 32MB"),
        (0x83000000, "Phys 48MB"),
        (0x83600000, "Phys 54MB (near game_stats)"),
        (0x83609F00, "game_stats aligned"),
        (0x83FF0000, "Phys ~64MB (near end)"),
    ]

    for addr, label in tests:
        time.sleep(1.0)  # 1 second between tests
        nbytes, preview = test_single_read(addr)
        if nbytes > 0:
            print(f"  0x{addr:08X}  OK ({nbytes}B)  [{preview}]  {label}")
        elif nbytes == 0:
            print(f"  0x{addr:08X}  EMPTY (0B)                       {label}")
        elif nbytes == -2:
            print(f"  0x{addr:08X}  ERROR: {preview:24s}  {label}")
        else:
            print(f"  0x{addr:08X}  CONN FAIL                        {label}")

    print("\nDone.")

if __name__ == "__main__":
    main()
