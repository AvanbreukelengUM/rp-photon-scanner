#!/usr/bin/env python3
"""
Live Photon Counter Monitor — real-time plotting on your PC.

Connects to the Red Pitaya photon counter server and displays
a live count rate plot and optional pulse height histogram.

Usage:
    python live_monitor.py [--host 169.254.32.2] [--threshold 200] [--deadtime 16]
"""

import argparse
import sys
import time
from collections import deque

import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np

from photon_client_scanner import PhotonScanner


def main():
    parser = argparse.ArgumentParser(description="Live Photon Counter Monitor")
    parser.add_argument("--host", default="169.254.121.34", help="Red Pitaya IP")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--threshold", type=int, default=200,
                        help="Detection threshold (ADC units)")
    parser.add_argument("--deadtime", type=int, default=0,
                        help="Dead time (clock cycles, 1=8ns)")
    parser.add_argument("--gate-ms", type=int, default=100,
                        help="Gate period in milliseconds")
    parser.add_argument("--history", type=int, default=50,
                        help="Number of data points in plot")
    parser.add_argument("--stream_ms", type=int, default=100,
                        help="Plot update interval")
    args = parser.parse_args()

    # Connect and configure
    print(f"Connecting to {args.host}:{args.port}...")
    pc = PhotonScanner(args.host, args.port)

    print("Configuring...")
    pc.reset()
    pc.set_threshold(args.threshold)
    pc.set_deadtime(args.deadtime)
    gate_cycles = int(args.gate_ms * 125_000)
    pc.set_gate_period(gate_cycles)
    pc.set_pixels(1)
    pc.enable()

    print(f"  Threshold: {args.threshold} ADC units")
    print(f"  Dead time: {args.deadtime} cycles ({args.deadtime * 8} ns)")
    print(f"  Gate period: {args.gate_ms} ms ({gate_cycles} cycles)")

    # Data buffers
    times = deque(maxlen=args.history)
    rates = deque(maxlen=args.history)

    fig, ax_rate = plt.subplots(1, 1, figsize=(10, 4))

    line_rate, = ax_rate.plot([], [], 'b-', linewidth=1)
    ax_rate.set_xlabel("Time (s)")
    ax_rate.set_ylabel("Count Rate (c/s)")
    ax_rate.set_title("Photon Count Rate")
    ax_rate.grid(True, alpha=0.3)

    fig.tight_layout()

    # Start streaming
    def update(frame):
        # Read stream data
        pc.trig_soft(False)
        t0 = time.time()
        pc.trig_soft(True)
        while True:
            status = pc.get_trig_status()
            if status.trig_done:
                t1 = time.time()
                break
        point = pc.get_trig_rates()
        pc.trig_soft(False)

        if point:
            t =np.linspace(t0, t1, np.size(point))
            times.append(t)
            rates.append(point)

            line_rate.set_data(list(times), list(rates))
            ax_rate.relim()
            ax_rate.autoscale_view()

        artists = [line_rate]

    ani = animation.FuncAnimation(
        fig, update, interval=args.stream_ms, blit=False, cache_frame_data=False
    )

    try:
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        pc.disable()
        pc.close()
        print("Done.")


if __name__ == "__main__":
    main()
