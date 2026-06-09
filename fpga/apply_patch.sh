#!/bin/bash
# Apply the photon_scanner module to the Red Pitaya FPGA project
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")/RedPitaya-FPGA"
RTL_DIR="$PROJECT_DIR/prj/v0.94/rtl"

echo "=== Patching Red Pitaya FPGA project ==="

# 1. Copy photon_scanner module
echo "Copying photon_scanner.sv..."
cp "$SCRIPT_DIR/rtl/photon_scanner.sv" "$RTL_DIR/photon_scanner.sv"

# 2. Patch the top module to replace sys[7] stub
echo "Patching red_pitaya_top.sv..."
TOP_FILE="$RTL_DIR/red_pitaya_top.sv"

if grep -q "photon_scanner" "$TOP_FILE"; then
    echo "  Already patched, skipping."
else
    sed -i 's|sys_bus_stub sys_bus_stub_7 (sys\[7\]);|// Photon scanner on sys[7] (base addr 0x40700000)\
    photon_scanner i_photon_scanner (\
      .clk_i      (adc_clk       ),\
      .rstn_i     (adc_rstn      ),\
      .adc_dat_i  (adc_dat[0]    ),  // ADC channel 1\
      .trig_in    (trig_asg_out  ),  // Connect to ASG trigger\
      .sys_addr   (sys[7].addr   ),\
      .sys_wdata  (sys[7].wdata  ),\
      .sys_wen    (sys[7].wen    ),\
      .sys_ren    (sys[7].ren    ),\
      .sys_rdata  (sys[7].rdata  ),\
      .sys_err    (sys[7].err    ),\
      .sys_ack    (sys[7].ack    )\
    );|' "$TOP_FILE"
    echo "  Patched successfully."
fi

echo ""
echo "=== Done ==="
echo "Next steps:"
echo "  1. Open Vivado and load the project from $PROJECT_DIR/prj/v0.94/"
echo "  2. Or build from command line: cd $PROJECT_DIR && make PRJ=v0.94 MODEL=Z10"