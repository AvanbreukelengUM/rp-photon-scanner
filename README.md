# rp-photon-counter and scanner

Original counter by XavierIsabel: https://github.com/XavierIsabel/rp-photon-counter

FPGA-based photon counter for the [Red Pitaya STEMlab 125-14](https://redpitaya.com/stemlab-125-14/). Real-time pulse counting at 125 MSPS using the onboard FPGA, with a TCP server and Python client for remote control and live monitoring. Devised to be used in tandem with PyMoDAQ (https://github.com/AvanbreukelengUM/pymodaq_plugins_redpitaya/tree/dev_L2C_dilu_photon_dev).

[//]: # (Designed for SiPM/SPAD single-photon detectors. Tested with the [Thorlabs PDA42]&#40;https://www.thorlabs.com/thorproduct.cfm?partnumber=PDA42&#41; SiPM amplified detector for Raman spectroscopy and low-light applications.)

## Features

- **125 MSPS** continuous pulse detection on FPGA (no dead gaps)
- Configurable **threshold discriminator** with adjustable dead time
- **32-bit pulse counter** + gated count rate measurement
- **TCP server** on Red Pitaya ARM for remote control
- **Python client** for software triggering and count retrieving
- Runs alongside the standard Red Pitaya v0.94 ecosystem (web UI and SCPI commands still work)

## Hardware Requirements

- Red Pitaya STEMlab 125-14 (tested on Pro v2.0, model `z10_125_pro_v2`)
- Detector with voltage pulse output between -20V and 20V, with pulses longer than 18ns
- SMA cable connecting detector to IN1
- Direct Ethernet connection between Red Pitaya and PC

### Input Configuration

Set the **HV jumper** (right position) behind the IN1 SMA connector for the +-20V input range if your detector outputs more than 1V high pulses.

## Getting Started

### Prerequisites

- [Xilinx Vivado 2020.1 WebPACK](https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/vivado-design-tools/archive.html) (free, for building FPGA bitstream)
- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- SSH access to Red Pitaya (`root` / `root` default credentials). In the following, replace the IP address with your RedPitaya's.

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
   make clean
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
   scp red_pitaya.bit.bin root@169.254.121.34:/root/photon_scanner.bit.bin
   ssh root@169.254.121.34
   mount -o rw,remount /opt/redpitaya
   cp /root/photon_scanner.bit.bin /opt/redpitaya/fpga/z10_125_pro_v2/v0.94/fpga.bit.bin
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
1. **Send Server file to RP** :
   ```bash
   cd ~/rp-photon-counter/server
   scp photon_server_scanner.py root@169.254.121.34:/root/photon_server_scanner.py
   
3. **Make Server starting file** on the RP:
   ```bash
   ssh root@<RP_IP>
   cat > /root/start_photon_scanner.sh <<'EOF'
   #!/bin/sh
   cd /root
   exec python3 /root/photon_server_scanner.py --port 5555
   EOF
    ```
2. **Then make it executable**
    ```bash
   chmod +x /root/start_photon_scanner.sh
   ```

3. **Start the TCP server** on the Red Pitaya:
   ```bash
   ssh root@<RP_IP> '/root/start_photon_scanner.sh'
   ```

4. **Run the live monitor** on your PC:
   ```bash
   cd client
   uv run python3 live_monitor.py --threshold 28
   ```

5. **Or use the Python client** programmatically:
   ```python
   from photon_client import PhotonCounter

   pc = PhotonCounter("169.254.32.2")
   pc.set_threshold(28)
   pc.set_deadtime(16)
   pc.set_pixels(1)
   pc.enable()

   rates = pc.get_trig_rates()
   print(f"Count rates:", rates ," cps")
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

The FPGA module (`photon_scanner.sv`) taps into the Red Pitaya's ADC at 125 MSPS and performs real-time threshold discrimination:

0. **Triggering**: Waits for either a software trigger or trigger from the ASG generator (indicating start of generation)
1. **Threshold crossing detection**: Fires when `ADC[n] >= threshold` and `ADC[n-1] < threshold`
2. **Dead time**: Ignores subsequent crossings for a configurable number of clock cycles
3. **Counting**: Increments a 32-bit counter per detected pulse; also computes gated count rate

All configuration and readout happens through memory-mapped registers at base address `0x40700000`, accessible from Linux via `/dev/mem`.

## License

MIT
