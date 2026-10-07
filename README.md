# rp-photon-counter and scanner

Original counter by XavierIsabel: https://github.com/XavierIsabel/rp-photon-counter

FPGA-based photon counter for the [Red Pitaya STEMlab 125-14 PRO Gen 2](https://redpitaya.readthedocs.io/en/latest/developerGuide/hardware/GEN2/125-14_Gen2_Pro/top.html). Real-time pulse counting at 125 MSPS using the onboard FPGA, with a TCP server and Python client for remote control and live monitoring. Devised to be used in tandem with PyMoDAQ (https://github.com/AvanbreukelengUM/pymodaq_plugins_redpitaya/tree/dev_L2C_dilu_photon_dev).


## Features

- **125 MSPS** continuous pulse detection on FPGA (no dead gaps)
- Configurable **threshold discriminator** with adjustable dead time
- **32-bit pulse counter** + gated count rate measurement
- **Triggered gated counting**: on a trigger edge (from the ASG or a software trigger), records counts in up to 4096 consecutive gates (e.g. scan pixels) for readout in one shot
- **TCP server** on Red Pitaya ARM for remote control
- **Python client** for software triggering and count retrieving
- Runs alongside the standard Red Pitaya v0.94 ecosystem (web UI and SCPI commands still work)
- Prebuilt bitstreams included for 128 / 256 / 512 / 1024 / 4096 maximum gates (fpga/BIT_scanner_*)

## Hardware Requirements

- Red Pitaya STEMlab 125-14 PRO Gen 2 (model `z10_125_pro_v2`). Likely compatible with other models.
- Detector with voltage pulse output between -20V and 20V, with pulses longer than 18ns
- SMA cable connecting detector to IN1
- If desired, an actuator to scan connected to OUT1
- Direct Ethernet connection between Red Pitaya and PC

### Input Configuration

Set the **HV jumper** (right position) behind the IN1 SMA connector for the +-20V input range if your detector outputs more than 1V high pulses.

## Getting Started

### Prerequisites

- [Xilinx Vivado 2020.1 WebPACK](https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/vivado-design-tools/archive.html) (free, for building FPGA bitstream)
- SSH access to Red Pitaya (`root` / `root` default credentials). In the following, replace the IP address with your RedPitaya's.

### Build and Deploy
Alternatively, skip the build: a prebuilt .bit/.bit.bin for each supported gate depth is available under fpga/BIT_scanner_128|256|512|1024|4096/. For manual top-level patching (e.g. on a Z20), see fpga/patch_top_z10.md.

In the following, replace the <RP_IP> address with your RedPitaya's.

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
   scp red_pitaya.bit.bin root@<RP_IP>:/root/photon_scanner.bit.bin
   ssh root@<RP_IP>
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
   scp photon_server_scanner.py root@<RP_IP>:/root/photon_server_scanner.py
   
2. **Make Server starting file** on the RP:
   ```bash
   ssh root@<RP_IP>
   cat > /root/start_photon_scanner.sh <<'EOF'
   #!/bin/sh
   cd /root
   exec python3 /root/photon_server_scanner.py --port 5555
   EOF
    ```
3. **Then make it executable**
    ```bash
   chmod +x /root/start_photon_scanner.sh
   ```

4. **Start the TCP server** on the Red Pitaya:
   ```bash
   ssh root@<RP_IP> '/root/start_photon_scanner.sh'
   ```

5. **Use the Python client** programmatically:
   ```python
   from photon_client_scanner import PhotonScanner

   pc = PhotonScanner("<RP_IP>")
   pc.set_threshold(205) # in HV mode, 205 ADC points equals 500mV
   pc.set_deadtime(16)  # 16 cycles = 128 ns
   
   pc.set_gate_period(125_000_000)  # 1 s per gate
   pc.set_pixels(1) # number of gates to record
   pc.enable()
   pc.reset()
   pc.trig_soft(True)
   while not pc.get_trig_status().trig_done:
      pass
   rates = pc.get_trig_rates() # counts/s per gate/pixel
   print(f"Count rates:", rates ," cps")
   pc.trig_soft(False)
   pc.close()
   ```

### Finding the Right Threshold

Run a threshold scan to find the optimal discrimination point for your detector:


```bash
# With detector connected and covered (dark counts only):
# Sweep threshold and observe where count rate drops sharply.
# 1 ADC point (threshold) equals around 2.44mV in HV mode. 100mV is around 41 ADC points in HV mode.
```

## Project Structure

```
rp-photon-scanner/
  fpga/
    rtl/
      photon_scanner.sv       # Scanner module: counting + triggered gated acquisition
      photon_counter.sv       # Counter-only variant (with pulse-height histogram)
    BIT_scanner_128|256|512|1024|4096/   # Prebuilt bitstreams per max gate count
    apply_patch.sh            # Patches Red Pitaya top module
    patch_top_z10.md          # Manual patch instructions (Z10/Z20)
  server/
    photon_server_scanner.py  # TCP server (runs on RP ARM)
    photon_server.py          # Server for the counter-only firmware
  client/
    photon_client_scanner.py  # Python client library (scanner)
    photon_client.py          # Python client library (counter)
    live_monitor.py           # Real-time matplotlib plotting
    pyproject.toml            # Python project config
  Test/
    0D_test.py                # Continuous counting test
    0D_test_soft_trigger.py   # Soft-triggered gated acquisition test
    Scan_test.py              # ASG-triggered scan test
  test_devmem_scanner.sh      # Low-level register test (SSH + devmem)
```

## How It Works

The FPGA module (`photon_scanner.sv`) taps into the Red Pitaya's ADC at 125 MSPS and performs real-time threshold discrimination:

0. **Triggering**: Waits for either a software trigger (TRIG_SOFT 1) or trigger from the ASG generator (indicating start of generation)
1. **Threshold crossing detection**: Fires when `ADC[n] >= threshold` and `ADC[n-1] < threshold`
2. **Dead time**: Ignores subsequent crossings for a configurable number of clock cycles
3. **Counting**: Increments a 32-bit counter per detected pulse per gate; advances to the next gate after the configured gate period, until N gates are recorded (SET_TRIG_TOTAL_GATES)

All configuration and readout happens through memory-mapped registers at base address `0x40700000`, accessible from Linux via `/dev/mem`.

### FPGA register map (sys\[7\], base 0x40700000)


| Offset  | Name                   | Access | Description                               |
| ------- | ---------------------- | ------ | ----------------------------------------- |
| 0x00    | CTRL                   | R/W    | \[0\] enable, \[1\] reset (auto-clears)   |
| 0x04    | THRESHOLD              | R/W    | 16-bit signed threshold (ADC units)       |
| 0x08    | DEAD\_TIME             | R/W    | Dead time in clock cycles                 |
| 0x14    | GATE\_PERIOD           | R/W    | Gate period in clock cycles (125e6 = 1 s) |
| 0x1C    | STATUS                 | R      | \[0\] enabled, \[1\] overflow             |
| 0x28    | TRIG\_TOTAL\_GATES     | R/W    | Number of gates to record (max 4095)      |
| 0x38    | TRIG\_STATUS           | R      | \[0\] trig\_active, \[1\] trig\_done      |
| 0x40    | SOFT\_TRIG             | R/W    | Software trigger                          |
| 0x500–… | TRIG\_COUNTS\[0..N-1\] | R      | Per-gate counts (32-bit each)             |


### TCP protocol

Line-based, one response per line. Commands (also listed by `HELP`):


| Command                                  | Description                                    |
| ---------------------------------------- | ---------------------------------------------- |
| `ENABLE` / `DISABLE` / `RESET`           | Enable, disable, or reset counting             |
| `SET_THRESHOLD <val>`                    | Signed 16-bit threshold (ADC units)            |
| `SET_DEADTIME <cycles>`                  | Dead time in 125 MHz cycles (1 = 8 ns)         |
| `SET_GATE <cycles>`                      | Gate period in clock cycles                    |
| `SET_TRIG_TOTAL_GATES <N>`               | Number of gates to record per trigger (≤ 4095) |
| `TRIG_SOFT <0|1>`                        | Generate a software trigger                    |
| `GET_TRIG_STATUS`                        | `trig_active`, `trig_done` flags               |
| `GET_TRIG_COUNTS` / `GET_TRIG_COUNT <i>` | Raw per-gate counts                            |
| `GET_TRIG_RATES` / `GET_TRIG_RATE <i>`   | Per-gate counts converted to counts/s          |
| `GET_CONFIG` / `GET_TRIG_CONFIG`         | Configuration readback                         |
| `HELP`                                   | List all commands                              |


A quick register-level smoke test can be run over SSH:

```bash
ssh root@<RP_IP> 'bash -s' < test_devmem_scanner.sh
```

## License

MIT
