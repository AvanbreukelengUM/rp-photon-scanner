"""
Photon Counter Client Library — runs on your PC.

Connects to the photon_server.py TCP server on the Red Pitaya
and provides a clean Python API for photon counting.

Usage:
    from photon_client import PhotonCounter

    pc = PhotonCounter("169.254.121.34")
    pc.set_threshold(200)
    pc.set_deadtime(16)
    pc.set_trig_total_gates(10)
    pc.enable()

    # Triggered gated counting example:
    pc.soft_trig()
    print(pc.get_trig_status())
    print(pc.get_trig_rates())
    pc.close()
"""

import socket
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple

# @dataclass
# class CountRate:
#     raw_counts: int       # counts in last gate period
#     cps: float            # counts per second
#     total_count: int = 0  # cumulative count

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

    def get_config(self) -> dict:
        """Get current configuration."""
        resp = self._send("GET_CONFIG")
        result = {}
        for pair in resp.split():
            k, v = pair.split("=")
            result[k] = int(v)
        return result

    # --- New methods for triggered gated counting ---
    def trig_soft(self, trigger: bool) -> None:
        """Software trigger the counting"""
        self._send(f"TRIG_SOFT {int(trigger)}")

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
        return [int(float(x)) for x in resp.split()]

    def get_trig_rates(self) -> List[int]:
        """Get counts for all gates as a list."""
        resp = self._send("GET_TRIG_RATES")
        return [int(float(x)) for x in resp.split()]

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
