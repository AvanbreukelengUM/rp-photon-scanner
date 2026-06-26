#!/usr/bin/env python3
"""
Photon Counter TCP Server — runs on Red Pitaya ARM Linux.

Memory-maps the FPGA registers and exposes a simple text protocol
over TCP port 5555 for configuration and readout.

Usage:
    python3 photon_server.py [--port 5555]
"""

import mmap
import os
import socket
import struct
import sys
import threading
import time
import argparse

# FPGA register base address for sys[7]
BASE_ADDR = 0x40700000
ADDR_SPAN = 0x2000  # 8 KB to cover registers + histogram + gate counts

# Register offsets (existing)
REG_CTRL        = 0x00
REG_THRESHOLD   = 0x04
REG_DEADTIME    = 0x08
REG_GATE_PERIOD = 0x14
REG_STATUS      = 0x1C

# New register offsets for triggered gated counting
REG_TRIG_TOTAL_GATES = 0x28  # Number of gates (9-bit)
REG_TRIG_READ_INDEX  = 0x34  # Index for reading gate counts (9-bit)
REG_TRIG_STATUS      = 0x38  # [0]=trig_active, [1]=trig_done
REG_SOFT_TRIG        = 0x40  # R/W  Allows to generate a trig_rising edge and force the counting of photons (software trigger)
REG_TRIG_COUNTS_BASE = 0x500  # Base address for gate counts (256 x 4 bytes)

MAX_TRIG_GATES = 1728 # Maximum number of gates

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
    def __init__(self, port=5555):
        self.port = port
        self.regs = FPGARegs()

        self.rate_history = []  # Store counts here
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
                print("Enabled")
                return "OK"

            elif parts[0] == "DISABLE":
                self.regs.write32(REG_CTRL, 0x00)
                print("Disabled")
                return "OK"

            elif parts[0] == "RESET":
                ctrl = self.regs.read32(REG_CTRL)
                self.regs.write32(REG_CTRL, ctrl | 0x02)
                print("Reset")
                return "OK"

            elif parts[0] == "SET_THRESHOLD":
                val = int(parts[1])
                self.regs.write32(REG_THRESHOLD, val & 0xFFFF)
                print(f"OK threshold={val}")
                return f"OK threshold={val}"

            elif parts[0] == "SET_DEADTIME":
                val = int(parts[1])
                self.regs.write32(REG_DEADTIME, val & 0xFFFF)
                print(f"OK deadtime={val}")
                return f"OK deadtime={val}"

            elif parts[0] == "SET_GATE":
                val = int(parts[1])
                self.regs.write32(REG_GATE_PERIOD, val)
                print(f"OK gate_period={val}")
                return f"OK gate_period={val}"

            elif parts[0] == "GET_CONFIG":
                threshold = self.regs.read_signed16(REG_THRESHOLD)
                deadtime = self.regs.read32(REG_DEADTIME) & 0xFFFF
                gate = self.regs.read32(REG_GATE_PERIOD)
                ctrl = self.regs.read32(REG_CTRL)
                # print(f"enabled={ctrl & 1} threshold={threshold} "
                #         f"deadtime={deadtime} gate_period={gate} "
                #         f"hist_shift={hist_shift}")
                return (f"enabled={ctrl & 1} threshold={threshold} "
                        f"deadtime={deadtime} gate_period={gate} ")

            # New commands for triggered gated counting

            elif parts[0] == "SET_TRIG_TOTAL_GATES":
                val = int(parts[1])
                if val < 0 or val > MAX_TRIG_GATES:
                    print(f"ERR: trig_total_gates must be between 0 and {MAX_TRIG_GATES}")
                    self.regs.write32(REG_TRIG_TOTAL_GATES, MAX_TRIG_GATES % 0x800)  # 10-bit max
                    return f"ERR: trig_total_gates must be between 0 and {MAX_TRIG_GATES}. Maximum set"
                self.regs.write32(REG_TRIG_TOTAL_GATES, val % 0x800)  # 10-bit max
                print(f"OK trig_total_gates={val % 0x800}")
                return f"OK trig_total_gates={val % 0x800}"

            elif parts[0] == "GET_TRIG_STATUS":
                status = self.regs.read32(REG_TRIG_STATUS)
                # print("trig_status",status)
                trig_done = status & 1
                trig_active = (status >> 1) & 1
                # print(f"trig_active={trig_active} trig_done={trig_done}")
                return f"trig_active={trig_active} trig_done={trig_done}"

            elif parts[0] == "GET_TRIG_COUNTS":
                num_gates = self.regs.read32(REG_TRIG_TOTAL_GATES) % 0x800
                counts = []
                # print("number of gates: ", num_gates)
                for i in range(num_gates):
                    val = self.regs.read32(REG_TRIG_COUNTS_BASE + i * 4)
                    # print("number of counts: ", val,"for gate: ", i, "at register: ", REG_TRIG_COUNTS_BASE + i * 4)
                    counts.append(str(val))
                # print(" ".join(counts))
                return " ".join(counts)

            elif parts[0] == "GET_TRIG_RATES":
                num_gates = self.regs.read32(REG_TRIG_TOTAL_GATES) % 0x800
                # print("number of gates: ",num_gates)
                rates = []
                gate = self.regs.read32(REG_GATE_PERIOD)
                for i in range(num_gates):
                    counts = self.regs.read32(REG_TRIG_COUNTS_BASE + i*4)
                    # print("number of counts: ",counts)
                    if gate > 0:
                        rates.append(str(counts * 125_000_000.0 / gate))
                    else:
                        rates.append("")
                # print(" ".join(rates))
                return " ".join(rates)

            elif parts[0] == "GET_TRIG_RATES_DEBUG":
                num = self.regs.read32(REG_TRIG_TOTAL_GATES)
                print(f"num: {num}")
                num_gates =  num % 0x800
                print("Number of gates: ",num_gates)
                rates = []
                gate = self.regs.read32(REG_GATE_PERIOD)
                for i in range(num_gates):
                    counts = self.regs.read32(REG_TRIG_COUNTS_BASE + i*4)
                    print("number of counts: ", counts,"for gate: ", i, "at register: ", REG_TRIG_COUNTS_BASE + i * 4)
                    if gate > 0:
                        rates.append(str(counts * 125_000_000.0 / gate))
                    else:
                        rates.append("")
                return " ".join(rates)


            elif parts[0] == "GET_TRIG_COUNT":
                index = int(parts[1]) if len(parts) > 1 else 0
                if index < 0 or index >= MAX_TRIG_GATES:
                    return f"ERR: index must be between 0 and {MAX_TRIG_GATES-1}"
                val = self.regs.read32(REG_TRIG_COUNTS_BASE + index * 4)
                # print( f"TRIG_COUNT={val}")
                return f"{val}"

            elif parts[0] == "GET_TRIG_RATE":
                index = int(parts[1]) if len(parts) > 1 else 0
                gate = self.regs.read32(REG_GATE_PERIOD)
                if index < 0 or index >= MAX_TRIG_GATES:
                    return f"ERR: index must be between 0 and {MAX_TRIG_GATES-1}"
                counts = self.regs.read32(REG_TRIG_COUNTS_BASE + index * 4)
                if gate > 0:
                    val = counts * 125_000_000.0 / gate
                else:
                    val = 0
                # print( f"TRIG_RATE={val}")
                return f"{val}"


            elif parts[0] == "GET_TRIG_CONFIG":
                ctrl = self.regs.read32(REG_CTRL)
                trig_soft = self.regs.read32(REG_SOFT_TRIG) & 1
                trig_total_gates = self.regs.read32(REG_TRIG_TOTAL_GATES) % 0x800
                # print(f"trig_enable={trig_enable} trig_arm={trig_arm} "
                #         f"trig_total_gates={trig_total_gates}")
                return (f"enable={ctrl & 1} trig_soft={trig_soft}"
                        f"trig_total_gates={trig_total_gates}")

            # Streaming commands for triggered mode
            elif parts[0] == "TRIG_SOFT":
                val = int(parts[1])
                self.regs.write32(REG_SOFT_TRIG, val & 0x1)
                # print(f"OK trig_soft={val}")
                return f"OK trig_soft={val}"

            elif parts[0] == "HELP":
                print(
                    "Commands: ENABLE, DISABLE, RESET, "
                    "SET_THRESHOLD <val>, SET_DEADTIME <cycles>, SET_GATE <cycles>, "
                    "GET_STATUS, "
                    "GET_CONFIG, "
                    "SET_TRIG_TOTAL_GATES <N>, "
                    "GET_TRIG_STATUS, GET_TRIG_COUNTS, GET_TRIG_COUNT <index>, GET_TRIG_RATES, GET_TRIG_RATE <index>, GET_TRIG_CONFIG, "
                    "STOP, HELP"
                )
                return (
                    "Commands: ENABLE, DISABLE, RESET, "
                    "SET_THRESHOLD <val>, SET_DEADTIME <cycles>, SET_GATE <cycles>, "
                    "GET_STATUS, "
                    "GET_CONFIG, "
                    "SET_TRIG_TOTAL_GATES <N>, "
                    "GET_TRIG_STATUS, GET_TRIG_COUNTS, GET_TRIG_COUNT <index>, GET_TRIG_RATES, GET_TRIG_RATE <index>, GET_TRIG_CONFIG, "
                    "STOP, HELP"
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

        except Exception as e:
            print(f"Client error: {e}")
        finally:
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
    parser = argparse.ArgumentParser(description="Photon Scanner TCP Server")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()

    server = PhotonServer(port=args.port)
    server.run()
