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

from photon_client_1D import PhotonCounter

import matplotlib
matplotlib.use("TkAgg")

def main():
    parser = argparse.ArgumentParser(description="Live Photon Counter Monitor")
    parser.add_argument("--host", default="169.254.121.34", help="Red Pitaya IP")
    parser.add_argument("--port", type=int, default=5556)
    parser.add_argument("--threshold", type=int, default=100,
                        help="Detection threshold (ADC units)")
    parser.add_argument("--deadtime", type=int, default=0,
                        help="Dead time (clock cycles, 1=8ns)")
    parser.add_argument("--gate-ms", type=int, default=1,
                        help="Gate period in milliseconds")
    # parser.add_argument("--history", type=int, default=1000,
    #                     help="Number of data points in plot")
    parser.add_argument("--stream-ms", type=int, default=20,
                        help="Stream update interval in ms")
    parser.add_argument("--histogram", action="store_true",
                        help="Also show pulse height histogram")
    parser.add_argument("--window", type=int, default=25,
                        help="Length of plot window in seconds")
    args = parser.parse_args()

    # Connect and configure
    print(f"Connecting to {args.host}:{args.port}...")
    pc = PhotonCounter(args.host, args.port)

    print("Configuring...")
    pc.reset()
    pc.set_threshold(args.threshold)
    pc.set_deadtime(args.deadtime)
    gate_cycles = int(args.gate_ms * 125_000)
    pc.set_gate_period(gate_cycles)
    pc.enable()

    print(f"  Threshold: {args.threshold} ADC units")
    print(f"  Dead time: {args.deadtime} cycles ({args.deadtime * 8} ns)")
    print(f"  Gate period: {args.gate_ms} ms ({gate_cycles} cycles)")

    # Data buffers
    history = int(args.window/args.gate_ms*1000)
    times = deque(maxlen=history)
    rates = deque(maxlen=history)
    # times = deque(maxlen=args.history)
    # rates = deque(maxlen=args.history)
    t0 = time.time()
    t0 = 1777999270
    args.histogram = False
    # Setup plot
    if args.histogram:
        fig, (ax_rate, ax_hist) = plt.subplots(2, 1, figsize=(10, 8))
    else:
        fig, ax_rate = plt.subplots(1, 1, figsize=(10, 4))
        ax_hist = None

    line_rate, = ax_rate.plot([], [], 'b-', linewidth=1)
    ax_rate.set_xlabel("Time (s)")
    ax_rate.set_ylabel("Count Rate (cps)")
    ax_rate.set_title("Photon Count Rate")
    ax_rate.grid(True, alpha=0.3)
    #
    # if ax_hist:
    #     # bar_hist = ax_hist.bar(range(256), [0]*256, width=1.0, color='steelblue')
    #     # ax_hist.set_xlabel("Pulse Height Bin")
    #     # ax_hist.set_ylabel("Counts")
    #     # ax_hist.set_title("Pulse Height Histogram")
    #     # ax_hist.set_xlim(0, 256)
    #     bar_hist = ax_hist.bar(range(64), [0] * 64, width=1.0, color='steelblue')
    #     ax_hist.set_xlabel("Pulse Height Bin")
    #     ax_hist.set_ylabel("Counts")
    #     ax_hist.set_title("Pulse Height Histogram")
    #     ax_hist.set_xlim(0, 64)

    fig.tight_layout()

    # Start streaming
    # pc.start_stream(args.stream_ms)
    pc.start_stream1D(args.stream_ms)
    print("Streaming1D... Close the plot window to stop.")

    def update(frame):
        # Read stream data
        points = pc.read_stream1D()
        # points = pc.read_stream()
        print(points)

        if points:
            for point in points:
                ts, total, gate_count, cps = point

                t = ts - t0 if t0 else 0
                times.append(t)
                rates.append(cps)
                # print(t)

                line_rate.set_data(list(times), list(rates))
                ax_rate.relim()
                ax_rate.autoscale_view(scalex=False, scaley=True)
                #
                t_now = times[-1]
                ax_rate.set_xlim(t_now - args.window, t_now +1)
        else: print("no points")

        # if points:
        #     ts, total, gate_count, cps = points
        #
        #     t = ts - t0 if t0 else 0
        #     times.append(t)
        #     rates.append(cps)
        #     # print(t)
        #
        #     line_rate.set_data(list(times), list(rates))
        #     ax_rate.relim()
        #     ax_rate.autoscale_view(scalex=False, scaley=True)
        #     #
        #     t_now = times[-1]
        #     ax_rate.set_xlim(t_now - args.window, t_now + 1)
        # else:
        #     print("no points")

        # Update histogram less frequently
        # if ax_hist and frame % 10 == 0:
        #     try:
        #         pc.stop_stream()
        #         hist = pc.get_histogram()
        #         pc.start_stream(args.stream_ms)
        #         for bar, h in zip(bar_hist, hist):
        #             bar.set_height(h)
        #         ax_hist.relim()
        #         ax_hist.autoscale_view()
        #     except Exception:
        #         pass

        artists = [line_rate]
        # if ax_hist:
        #     artists.extend(bar_hist)

        # if time.time() - t0 > 10:
            # print(np.size(times))

        return artists

    ani = animation.FuncAnimation(
        fig, update, interval=args.stream_ms, blit=False, cache_frame_data=False
    )
    plt.show()
    # try:
    #     plt.show()
    # except KeyboardInterrupt:
    #     pass
    # finally:
    #     pc.stop_stream()
    #     pc.disable()
    #     pc.close()
    #     print("Done.")


if __name__ == "__main__":
    main()
