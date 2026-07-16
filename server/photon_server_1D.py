#!/usr/bin/env python3
"""
Photon Counter TCP Server — runs on Red Pitaya ARM Linux.

Memory-maps the FPGA registers and exposes a simple text protocol
over TCP port 5556 for configuration and readout.

Usage:
    python3 photon_server.py [--port 5556]
"""

import mmap
import os
import socket
import struct
import sys
import threading
import time
import argparse

from fontTools.merge.util import current_time

# FPGA register base address for sys[7]
BASE_ADDR = 0x40700000
ADDR_SPAN = 0x1000  # 4 KB covers registers + histogram

# Register offsets
REG_CTRL        = 0x00
REG_THRESHOLD   = 0x04
REG_DEADTIME    = 0x08
REG_COUNT       = 0x0C
REG_COUNT_RATE  = 0x10
REG_GATE_PERIOD = 0x14
REG_PEAK_LAST   = 0x18
REG_STATUS      = 0x1C
REG_ADC_RAW     = 0x20
REG_HIST_SHIFT  = 0x24
REG_HIST_BASE   = 0x100  # 64 x 4 bytes


class FPGARegs:
    """Memory-mapped access to FPGA registers via /dev/mem."""

    def __init__(self, base=BASE_ADDR, span=ADDR_SPAN):
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.mm = mmap.mmap(
            self.fd, span,
            mmap.MAP_SHARED,
            mmap.PROT_READ | mmap.PROT_WRITE,
            offset=base
        )

    def read32(self, offset):
        self.mm.seek(offset)
        return struct.unpack("<I", self.mm.read(4))[0]

    def write32(self, offset, value):
        self.mm.seek(offset)
        self.mm.write(struct.pack("<I", value & 0xFFFFFFFF))

    def read_signed16(self, offset):
        val = self.read32(offset) & 0xFFFF
        if val >= 0x8000:
            val -= 0x10000
        return val

    def close(self):
        self.mm.close()
        os.close(self.fd)


class PhotonServer:
    def __init__(self, port=5556):
        self.port = port
        self.regs = FPGARegs()
        self.streaming = False
        self.stream_interval = 0.001  # seconds

        self.streaming1D = False
        self.rate_history = []  # <-- Store counts here
        self.last_rate = None
        self.stream1d_packets_to_send = 1  # Number of gate periods to store
        self.clocks_per_second = 125_000_000
        self.next_gate_time = 0
        self.gate_count = 0
        self.gate_period_seconds = 1

    def handle_command(self, cmd):
        """Process a single command string, return response string."""
        parts = cmd.strip().upper().split()
        if not parts:
            return "ERR: empty command"

        try:
            if parts[0] == "ENABLE":
                self.regs.write32(REG_CTRL, 0x01)
                return "OK"

            elif parts[0] == "DISABLE":
                self.regs.write32(REG_CTRL, 0x00)
                return "OK"

            elif parts[0] == "RESET":
                ctrl = self.regs.read32(REG_CTRL)
                self.regs.write32(REG_CTRL, ctrl | 0x02)
                return "OK"

            elif parts[0] == "SET_THRESHOLD":
                val = int(parts[1])
                # Store as unsigned 16-bit (FPGA interprets as signed)
                self.regs.write32(REG_THRESHOLD, val & 0xFFFF)
                return f"OK threshold={val}"

            elif parts[0] == "SET_DEADTIME":
                val = int(parts[1])
                self.regs.write32(REG_DEADTIME, val & 0xFFFF)
                return f"OK deadtime={val}"

            elif parts[0] == "SET_GATE":
                val = int(parts[1])
                self.regs.write32(REG_GATE_PERIOD, val)
                return f"OK gate_period={val}"

            elif parts[0] == "GET_COUNT":
                count = self.regs.read32(REG_COUNT)
                return f"{count}"

            elif parts[0] == "GET_RATE":
                rate = self.regs.read32(REG_COUNT_RATE)
                gate = self.regs.read32(REG_GATE_PERIOD)
                # Convert to counts per second
                if gate > 0:
                    cps = rate * 125_000_000.0 / gate
                else:
                    cps = 0.0
                return f"{rate} {cps:.1f}"

            # New code -----------
            # elif parts[0] == "GET_ALL_RATES":
            #     # Send entire buffer and clear it
            #     response = " ".join(map(str, self.rate_history))
            #     self.rate_history = []
            #     return response
            # -------------------

            elif parts[0] == "GET_ADC":
                raw = self.regs.read_signed16(REG_ADC_RAW)
                return f"{raw}"

            elif parts[0] == "GET_PEAK":
                peak = self.regs.read32(REG_PEAK_LAST) & 0xFFFF
                return f"{peak}"

            elif parts[0] == "GET_STATUS":
                status = self.regs.read32(REG_STATUS)
                enabled = status & 1
                ovf = (status >> 1) & 1
                count = self.regs.read32(REG_COUNT)
                rate = self.regs.read32(REG_COUNT_RATE)
                return f"enabled={enabled} overflow={ovf} count={count} rate={rate}"

            elif parts[0] == "GET_HISTOGRAM":
                bins = []
                for i in range(64):
                    val = self.regs.read32(REG_HIST_BASE + i * 4)
                    bins.append(str(val))
                return " ".join(bins)

            elif parts[0] == "SET_HIST_SHIFT":
                val = int(parts[1])
                self.regs.write32(REG_HIST_SHIFT, val & 0xF)
                return f"OK hist_shift={val}"

            elif parts[0] == "GET_CONFIG":
                threshold = self.regs.read_signed16(REG_THRESHOLD)
                deadtime = self.regs.read32(REG_DEADTIME) & 0xFFFF
                gate = self.regs.read32(REG_GATE_PERIOD)
                ctrl = self.regs.read32(REG_CTRL)
                hist_shift = self.regs.read32(REG_HIST_SHIFT) & 0xF
                return (f"enabled={ctrl & 1} threshold={threshold} "
                        f"deadtime={deadtime} gate_period={gate} "
                        f"hist_shift={hist_shift}")

            elif parts[0] == "STREAM":
                if len(parts) > 1:
                    self.stream_interval = int(parts[1]) / 1000.0
                self.streaming = True
                return "OK streaming"

            elif parts[0] == "STREAM1D":
                if len(parts) > 1:
                    self.stream_interval = int(parts[1]) / 1000.0
                self.streaming1D = True
                # self.next_gate_time = time.perf_counter()
                self.gate_count = 0
                self.gate_period_seconds = self.regs.read32(REG_GATE_PERIOD)/ 125_000_000
                self.stream1d_packets_to_send = max(1, int(self.stream_interval / self.gate_period_seconds))
                self.next_gate_time = time.perf_counter() + self.gate_period_seconds
                return "OK streaming1D"

            elif parts[0] == "STOP":
                self.streaming = False
                self.streaming1D = False
                return "OK stopped"

            elif parts[0] == "HELP":
                return (
                    "Commands: ENABLE, DISABLE, RESET, "
                    "SET_THRESHOLD <val>, SET_DEADTIME <cycles>, SET_GATE <cycles>, "
                    "GET_COUNT, GET_RATE, GET_ADC, GET_PEAK, GET_STATUS, "
                    "GET_HISTOGRAM, GET_CONFIG, "
                    "STREAM [interval_ms], STOP, HELP"
                )

            else:
                return f"ERR: unknown command '{parts[0]}'"

        except (IndexError, ValueError) as e:
            return f"ERR: {e}"

    def handle_client(self, conn, addr):
        print(f"Client connected: {addr}")
        conn.settimeout(0.001)
        last_time = 0
        try:
            while True:
                # Check for incoming commands
                try:
                    data = conn.recv(4096)
                    if not data:
                        break
                    for line in data.decode().strip().split("\n"):
                        response = self.handle_command(line)
                        conn.sendall((response + "\n").encode())
                except socket.timeout:
                    pass

                # Stream data if enabled
                if self.streaming:
                    rate = self.regs.read32(REG_COUNT_RATE)
                    count = self.regs.read32(REG_COUNT)
                    gate = self.regs.read32(REG_GATE_PERIOD)
                    if gate > 0:
                        cps = rate * 125_000_000.0 / gate
                    else:
                        cps = 0.0
                    ts = time.perf_counter()
                    msg = f"STREAM {ts:.3f} {count} {rate} {cps:.1f}\n"
                    try:
                        conn.sendall(msg.encode())
                    except BrokenPipeError:
                        break
                    time.sleep(self.stream_interval)

                # Stream data in packets if enabled
                elif self.streaming1D:
                    ts = time.perf_counter()
                    if ts >= self.next_gate_time:
                        rate = self.regs.read32(REG_COUNT_RATE)
                        count = self.regs.read32(REG_COUNT)
                        gate = self.regs.read32(REG_GATE_PERIOD)
                        if gate > 0:
                            cps = rate * 125_000_000.0 / gate
                        else:
                            cps = 0.0
                        # ts = time.perf_counter()

                        # Store data with the *expected* gate time (not current_time)
                        self.rate_history.append((ts, count, rate, cps))
                        self.gate_count += 1
                        self.next_gate_time += self.gate_period_seconds  # Schedule next gate

                        # Send packet when buffer is full
                        if self.gate_count >= self.stream1d_packets_to_send:
                            msg = "STREAM1D " + " ".join(
                                f"{t:.6f},{c},{r},{cps:.1f}"
                                for t, c, r, cps in self.rate_history
                            ) + "\n"
                            # msg = f"STREAM {ts:.3f} {count} {rate} {cps:.1f}\n"
                            try:
                                conn.sendall(msg.encode())
                            except BrokenPipeError:
                                break
                            self.rate_history = []
                            self.gate_count = 0
                    # time.sleep(self.stream_interval)

                else:
                    time.sleep(0.001)

        except Exception as e:
            print(f"Client error: {e}")
        finally:
            self.streaming = False
            conn.close()
            print(f"Client disconnected: {addr}")

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.port))
        srv.listen(1)
        print(f"Photon Counter server listening on port {self.port}")
        print("Waiting for client...")

        try:
            while True:
                conn, addr = srv.accept()
                t = threading.Thread(target=self.handle_client, args=(conn, addr))
                t.daemon = True
                t.start()
        except KeyboardInterrupt:
            print("\nShutting down...")
        finally:
            srv.close()
            self.regs.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Photon Counter TCP Server")
    parser.add_argument("--port", type=int, default=5556)
    args = parser.parse_args()

    server = PhotonServer(port=args.port)
    server.run()
