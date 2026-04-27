#!/usr/bin/env python3
"""Bidirectional UDP relay for MAVLink.

Forwards MAVLink traffic between PX4 SITL and a remote MAVSDK instance so you
can run the simulation on one machine and drone-follow on another.

PX4 SITL binds to a local port (14580 by default) and sends MAVLink to a
remote port (14540 by default).  This relay binds to the remote port so it
captures PX4's outgoing stream, then forwards it to the remote machine.
Return traffic from the remote MAVSDK is forwarded back to PX4's local port
(learned dynamically from packet source addresses).

Usage:
    sim/mavlink_relay.py 192.168.1.50
    sim/mavlink_relay.py 192.168.1.50 --px4-port 14540 --remote-port 14540
"""

import argparse
import select
import signal
import socket
import sys


def main():
    p = argparse.ArgumentParser(description="MAVLink bidirectional UDP relay")
    p.add_argument("remote_host",
                   help="IP address of the remote machine running drone-follow")
    p.add_argument("--px4-port", type=int, default=14540,
                   help="PX4 SITL MAVLink target port to listen on (default: 14540)")
    p.add_argument("--remote-port", type=int, default=14540,
                   help="Port on the remote machine (default: 14540)")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.px4_port))

    remote_addr = (args.remote_host, args.remote_port)
    px4_source = None  # learned from first PX4 packet

    print(f"[relay] Listening on 0.0.0.0:{args.px4_port}")
    print(f"[relay] Remote:     {args.remote_host}:{args.remote_port}")

    running = True

    def shutdown(*_):
        nonlocal running
        running = False
        print("\n[relay] Stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    fwd_count = 0
    while running:
        readable, _, _ = select.select([sock], [], [], 1.0)
        for _ in readable:
            data, addr = sock.recvfrom(65535)
            if addr[0] == "127.0.0.1":
                # From PX4 → remember its source port, forward to remote
                px4_source = addr
                sock.sendto(data, remote_addr)
            else:
                # From remote MAVSDK → forward to PX4
                if px4_source:
                    sock.sendto(data, px4_source)
            fwd_count += 1
            if fwd_count % 1000 == 0:
                print(f"[relay] Forwarded {fwd_count} packets")


if __name__ == "__main__":
    main()
