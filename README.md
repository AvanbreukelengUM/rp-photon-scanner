# rp-photon-counter

FPGA-based photon counter for the [Red Pitaya STEMlab 125-14](https://redpitaya.com/stemlab-125-14/). Real-time pulse counting at 125 MSPS using the onboard FPGA, with a TCP server and Python client for remote control and live monitoring.

Designed for single-photon detectors

## Features

- **125 MSPS** continuous pulse detection on FPGA (no dead gaps)
- Configurable **threshold discriminator** with adjustable dead time
- **32-bit pulse counter** + gated count rate measurement
- **64-bin pulse height histogram** for amplitude analysis
- **TCP server** on Red Pitaya ARM for remote control
- **Python client** with real-time matplotlib live monitoring
- Runs alongside the standard Red Pitaya v0.94 ecosystem (web UI still works)

## Hardware Requirements

- Red Pitaya STEMlab 125-14 (tested on Pro v2.0, model `z10_125_pro_v2`)
- SiPM or SPAD detector with voltage pulse output (e.g., Thorlabs PDA42)
- SMA cable connecting detector to IN1
- Direct Ethernet connection between Red Pitaya and PC

### Input Configuration

Set the **HV jumper** (right position) behind the IN1 SMA connector for the +-20V input range. This is required for the PDA42 which outputs up to +-2V.

## Getting Started

### Prerequisites

- [Xilinx Vivado 2020.1 WebPACK](https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/vivado-design-tools/archive.html) (free, for building FPGA bitstream)
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- SSH access to Red Pitaya (`root` / `root` default credentials)

### Build and Deploy

1. **Clone the Red Pitaya FPGA repo** into this project:
   ```bash
   cd ~/rp-photon-counter
   git clone --depth 1 https://github.com/RedPitaya/RedPitaya-FPGA.git
   ```

2. **Patch the FPGA project** to add the photon scanner module:
   ```bash
   bash fpga/apply_patch.sh
   ```

3. **Build the bitstream** (takes ~20 minutes):
   ```bash
   source /opt/Xilinx/Vivado/2020.1/settings64.sh
   cd RedPitaya-FPGA
   make PRJ=v0.94 MODEL=Z10
   ```
   Note: The build will report an error about `xsct` — this is expected (FSBL compilation, not needed).

4. **Convert the bitstream**:
   ```bash
   cd prj/v0.94/out
   echo "all:{ red_pitaya.bit }" > red_pitaya.bif
   bootgen -image red_pitaya.bif -arch zynq -process_bitstream bin -o red_pitaya.bit.bin -w
   ```

5. **Deploy to Red Pitaya**:
   ```bash
   scp red_pitaya.bit.bin root@169.254.121.34:/root/photon_counter.bit.bin
   ssh root@169.254.121.34
   mount -o rw,remount /opt/redpitaya
   cp /root/photon_counter.bit.bin /opt/redpitaya/fpga/z10_125_pro_v2/v0.94/fpga.bit.bin
   sync
   mount -o ro,remount /opt/redpitaya
   reboot
   ```

6. **Verify deployment** after reboot:
   ```bash
   ssh root@<RP_IP>
   /opt/redpitaya/bin/monitor 0x40700014   # Should return 0x07735940 (gate period default)
   ```

### Usage
0. **Make Server starting file** on the RP:
   ```
   cat > /root/start_photon.sh <<'EOF'
   #!/bin/sh
   cd /root
   exec python3 /root/photon_serverr.py --port 5555
   EOF
    ```
Then make it executable:

 ```chmod +x /root/start_photon.sh ```

0. **Start the TCP server** on the Red Pitaya:
   ```bash
   ssh root@<RP_IP> '/root/start_photon.sh'
   ```

1. **Run the live monitor** on your PC:
   ```bash
   cd client
   uv run python3 live_monitor.py --threshold 28 --histogram
   ```

2. **Or use the Python client** programmatically:
   ```python
   from photon_client import PhotonCounter

   pc = PhotonCounter("169.254.32.2")
   pc.set_threshold(28)
   pc.set_deadtime(16)
   pc.enable()

   rate = pc.get_rate()
   print(f"Count rate: {rate.cps:.0f} cps")

   histogram = pc.get_histogram()
   pc.close()
   ```

### Finding the Right Threshold

Run a threshold scan to find the optimal discrimination point for your detector:

```bash
# With detector connected and covered (dark counts only):
# Sweep threshold and observe where count rate drops sharply.
# For PDA42 SiPM in HV mode: optimal threshold ~28 ADC units
# Dark count rate at threshold 28: ~5,000 cps (typical for 3mm TEC-cooled SiPM)
```

## Project Structure

```
rp-photon-counter/
  fpga/
    rtl/photon_counter.sv    # FPGA module (SystemVerilog)
    apply_patch.sh           # Patches Red Pitaya top module
  server/
    photon_server.py         # TCP server (runs on RP ARM)
  client/
    photon_client.py         # Python client library
    live_monitor.py          # Real-time matplotlib plotting
    pyproject.toml           # Python project config
  test_devmem.sh             # Low-level register test
```

## How It Works

The FPGA module (`photon_counter.sv`) taps into the Red Pitaya's ADC data stream at 125 MSPS and performs real-time threshold discrimination:

1. **Threshold crossing detection**: Fires when `ADC[n] >= threshold` and `ADC[n-1] < threshold`
2. **Dead time**: Ignores subsequent crossings for a configurable number of clock cycles
3. **Counting**: Increments a 32-bit counter per detected pulse; also computes gated count rate
4. **Histogram**: Bins the ADC value at each threshold crossing into a 64-bin histogram

All configuration and readout happens through memory-mapped registers at base address `0x40700000`, accessible from Linux via `/dev/mem`.

## License

MIT
