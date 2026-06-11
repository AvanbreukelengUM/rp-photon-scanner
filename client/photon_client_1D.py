"""
Photon Counter Client Library — runs on your PC.

Connects to the photon_server.py TCP server on the Red Pitaya
and provides a clean Python API for photon counting.

Usage:
    from photon_client import PhotonCounter

    pc = PhotonCounter("169.254.32.2")
    pc.set_threshold(200)
    pc.set_deadtime(16)
    pc.enable()
    print(pc.get_rate())
    pc.close()
"""

import socket
import time
from dataclasses import dataclass


@dataclass
class CountRate:
    raw_counts: int       # counts in last gate period
    cps: float            # counts per second
    total_count: int = 0  # cumulative count


class PhotonCounter:
    """Client for the Red Pitaya photon counter FPGA module."""

    def __init__(self, host: str, port: int = 5556, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))
        self._buf = ""

    def _send(self, cmd: str) -> str:
        """Send command and return response line."""
        self.sock.sendall((cmd.strip() + "\n").encode())
        # Read until newline
        while "\n" not in self._buf:
            data = self.sock.recv(4096).decode()
            if not data:
                raise ConnectionError("Server closed connection")
            self._buf += data
        line, self._buf = self._buf.split("\n", 1)
        return line.strip()

    def enable(self) -> None:
        """Enable pulse counting."""
        self._send("ENABLE")

    def disable(self) -> None:
        """Disable pulse counting."""
        self._send("DISABLE")

    def reset(self) -> None:
        """Reset all counters and histogram."""
        self._send("RESET")

    def set_threshold(self, value: int) -> None:
        """Set detection threshold (signed 16-bit ADC units).

        For HV mode (+-20V range), 1 LSB ≈ 2.44 mV.
        Example: threshold=200 ≈ 488 mV.
        """
        self._send(f"SET_THRESHOLD {value}")

    def set_deadtime(self, cycles: int) -> None:
        """Set dead time in clock cycles (1 cycle = 8 ns at 125 MHz).

        Example: 16 cycles = 128 ns.
        """
        self._send(f"SET_DEADTIME {cycles}")

    def set_gate_period(self, cycles: int) -> None:
        """Set gate period for count rate measurement.

        125_000_000 = 1 second gate.
        12_500_000  = 100 ms gate.
        1_250_000   = 10 ms gate.
        """
        self._send(f"SET_GATE {cycles}")

    def get_count(self) -> int:
        """Get cumulative pulse count since last reset."""
        return int(self._send("GET_COUNT"))

    def get_rate(self) -> CountRate:
        """Get count rate (counts in last gate period + CPS)."""
        resp = self._send("GET_RATE")
        parts = resp.split()
        return CountRate(raw_counts=int(parts[0]), cps=float(parts[1]))

    def get_adc_raw(self) -> int:
        """Get current ADC sample value (signed, for threshold tuning)."""
        return int(self._send("GET_ADC"))

    def get_peak(self) -> int:
        """Get peak ADC value from most recent pulse."""
        return int(self._send("GET_PEAK"))

    def get_status(self) -> dict:
        """Get full status dictionary."""
        resp = self._send("GET_STATUS")
        result = {}
        for pair in resp.split():
            k, v = pair.split("=")
            result[k] = int(v)
        return result

    def get_config(self) -> dict:
        """Get current configuration."""
        resp = self._send("GET_CONFIG")
        result = {}
        for pair in resp.split():
            k, v = pair.split("=")
            result[k] = int(v)
        return result

    def get_histogram(self) -> list[int]:
        """Get 256-bin pulse height histogram."""
        resp = self._send("GET_HISTOGRAM")
        return [int(x) for x in resp.split()]

    def start_stream(self, interval_ms: int = 500):
        """Start streaming count data at given interval.

        After calling this, use read_stream() to get data lines.
        """
        self._send(f"STREAM {interval_ms}")

    def start_stream1D(self, interval_ms: int = 500):
        """Start streaming count data at given interval, and buffered

        After calling this, use read_stream1D() to get data lines.
        """
        self._send(f"STREAM1D {interval_ms}")

    def stop_stream(self):
        """Stop streaming."""
        self.sock.sendall(b"STOP\n")
        # Drain any pending stream data
        self.sock.settimeout(0.2)
        try:
            while True:
                data = self.sock.recv(4096)
                if not data:
                    break
        except socket.timeout:
            pass
        self.sock.settimeout(5.0)
        self._buf = ""

    def read_stream(self) -> tuple[float, int, int, float] | None:
        """Read one stream data point.

        Returns (timestamp, total_count, gate_count, cps) or None.
        """
        while "\n" not in self._buf:
            try:
                data = self.sock.recv(4096).decode()
                if not data:
                    return None
                self._buf += data
            except socket.timeout:
                return None

        line, self._buf = self._buf.split("\n", 1)
        parts = line.strip().split()
        if len(parts) >= 5 and parts[0] == "STREAM":
            return (float(parts[1]), int(parts[2]), int(parts[3]), float(parts[4]))
        return None

    # ToDo finish this code:
    def read_stream1D(self) -> list[tuple[float, int, int, float]] | None:
        """Read one stream data point.

        Returns (timestamp, total_count, gate_count, cps) or None.
        """
        while "\n" not in self._buf:
            try:
                data = self.sock.recv(4096).decode()
                if not data:
                    print("no data")
                    return None
                self._buf += data
            except socket.timeout:
                print("timeout")
                return None

        line, self._buf = self._buf.split("\n", 1)
        parts = line.strip().split()

        # if len(parts) < 2 or parts[0] != "STREAM1D":
        #     return None

        # Parse each tuple: "timestamp,count,rate,cps"
        result = []
        for data_str in parts[1:]:
            try:
                t, c, r, cps = data_str.split(',')
                result.append((float(t), int(c), int(r), float(cps)))
            except ValueError:
                continue  # Skip malformed data
        return result if result else None

        # if len(parts) >= 5 and parts[0] == "STREAM1D":
        #     return (float(parts[1]), int(parts[2]), int(parts[3]), float(parts[4]))
        # return None

    def close(self):
        """Close connection."""
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
