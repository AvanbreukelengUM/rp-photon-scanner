"""
Photon Counter Client Library — runs on your PC.

Connects to the photon_server.py TCP server on the Red Pitaya
and provides a clean Python API for photon counting.

Usage:
    from photon_client import PhotonCounter

    pc = PhotonCounter("169.254.121.34")
    pc.set_threshold(200)
    pc.set_deadtime(16)
    pc.enable()
    print(pc.get_rate())

    # Triggered gated counting example:
    pc.set_trig_enable(True)
    pc.set_trig_total_gates(10)
    pc.set_trig_arm(True)
    print(pc.get_trig_status())
    print(pc.get_trig_counts())
    pc.close()
"""

import socket
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

@dataclass
class CountRate:
    raw_counts: int       # counts in last gate period
    cps: float            # counts per second
    total_count: int = 0  # cumulative count

@dataclass
class TrigStatus:
    trig_active: bool
    trig_done: bool

class PhotonScanner:
    """Client for the Red Pitaya photon counter FPGA module."""

    def __init__(self, host: str = '169.254.121.34', port: int = 5555, timeout: float = 5.0, name="Redpitaya_PhotonScanner"):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((host, port))
        self._buf = ""
        self.name = name

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

    def get_histogram(self) -> List[int]:
        """Get 256-bin pulse height histogram."""
        resp = self._send("GET_HISTOGRAM")
        return [int(x) for x in resp.split()]

    def start_stream(self, interval_ms: int = 500):
        """Start streaming count data at given interval.

        After calling this, use read_stream() to get data lines.
        """
        self._send(f"STREAM {interval_ms}")

    def start_stream1D(self, interval_ms: int = 500):
        """Start streaming count data at given interval, and buffered.

        After calling this, use read_stream1D() to get data lines.
        """
        self._send(f"STREAM1D {interval_ms}")

    def start_stream_trig(self, interval_ms: int = 500):
        """Start streaming triggered gated counts at given interval.

        After calling this, use read_stream_trig() to get data lines.
        """
        self._send(f"STREAM_TRIG {interval_ms}")

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

    def read_stream(self) -> Optional[Tuple[float, int, int, float]]:
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

    def read_stream1D(self) -> Optional[List[Tuple[float, int, int, float]]]:
        """Read one stream data point.

        Returns a list of (timestamp, total_count, gate_count, cps) tuples or None.
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

        if len(parts) < 2 or parts[0] != "STREAM1D":
            return None

        # Parse each tuple: "timestamp,count,rate,cps"
        result = []
        for data_str in parts[1:]:
            try:
                t, c, r, cps = data_str.split(',')
                result.append((float(t), int(c), int(r), float(cps)))
            except ValueError:
                continue  # Skip malformed data
        return result if result else None

    def read_stream_trig(self) -> Optional[Tuple[float, List[int]]]:
        """Read one stream data point for triggered gated counts.

        Returns (timestamp, [count0, count1, ...]) or None.
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

        if len(parts) < 2 or parts[0] != "STREAM1D":
            return None

        # Parse timestamp and counts
        try:
            timestamp = float(parts[1])
            counts = [int(x) for x in parts[2:]]
            return (timestamp, counts)
        except ValueError:
            return None

    # --- New methods for triggered gated counting ---
    def set_trig_enable(self, enable: bool) -> None:
        """Enable or disable triggered mode."""
        self._send(f"SET_TRIG_ENABLE {int(enable)}")

    def set_trig_arm(self, arm: bool) -> None:
        """Arm or disarm the trigger."""
        self._send(f"SET_TRIG_ARM {int(arm)}")

    def set_trig_total_gates(self, num_gates: int) -> None:
        """Set the number of gates for triggered counting (1-1024)."""
        if num_gates < 1 or num_gates > 1024:
            raise ValueError("num_gates must be between 1 and 1024")
        self._send(f"SET_TRIG_TOTAL_GATES {num_gates}")

    def set_pixels(self, num_gates: int):
        self.set_trig_total_gates(num_gates)

    def get_trig_status(self) -> TrigStatus:
        """Get triggered mode status (trig_active, trig_done)."""
        resp = self._send("GET_TRIG_STATUS")
        parts = resp.split()
        return TrigStatus(
            trig_active=bool(int(parts[0].split("=")[1])),
            trig_done=bool(int(parts[1].split("=")[1]))
        )

    def get_trig_counts(self) -> List[int]:
        """Get counts for all gates as a list."""
        resp = self._send("GET_TRIG_COUNTS")
        return [int(x) for x in resp.split()]

    def get_trig_rates(self) -> List[int]:
        """Get counts for all gates as a list."""
        resp = self._send("GET_TRIG_RATES")
        return [int(x) for x in resp.split()]

    def get_trig_count(self, index: int) -> int:
        """Get count for a specific gate."""
        if index < 0 or index >= 1024:
            raise ValueError("index must be between 0 and 1023")
        return int(self._send(f"GET_TRIG_COUNT {index}"))

    def get_trig_rate(self, index: int) -> int:
        """Get count for a specific gate."""
        if index < 0 or index >= 1024:
            raise ValueError("index must be between 0 and 1023")
        return int(self._send(f"GET_TRIG_RATE {index}"))

    def get_trig_config(self) -> dict:
        """Get current triggered mode configuration."""
        resp = self._send("GET_TRIG_CONFIG")
        result = {}
        for pair in resp.split():
            k, v = pair.split("=")
            result[k] = int(v)
        return result

    def close(self):
        """Close connection."""
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
