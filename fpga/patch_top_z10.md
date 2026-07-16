# How to patch red_pitaya_top_Z20.sv

In `RedPitaya-FPGA/prj/v0.94/rtl/red_pitaya_top.sv`, make these changes:

## 1. Replace the sys[7] stub with photon_counter

Find this line (near the end, before `endif`):

    sys_bus_stub sys_bus_stub_7 (sys[7]);

Replace with:

    photon_scanner i_photon_scanner (
      .clk_i      (adc_clk       ),
      .rstn_i     (adc_rstn      ),
      .adc_dat_i  (adc_dat[0]    ),  // ADC channel 1
      .trig_in    (trig_asg_out  ),  // Connect to ASG trigger\
      .sys_addr   (sys[7].addr   ),
      .sys_wdata  (sys[7].wdata  ),
      .sys_wen    (sys[7].wen    ),
      .sys_ren    (sys[7].ren    ),
      .sys_rdata  (sys[7].rdata  ),
      .sys_err    (sys[7].err    ),
      .sys_ack    (sys[7].ack    )
    );

## 2. Add photon_counter.sv to the project

Copy `fpga/rtl/photon_scanner.sv` to `RedPitaya-FPGA/prj/v0.94/rtl/photon_scanner.sv`

The Vivado project's TCL script should pick it up automatically if it scans the rtl/ directory,
or you may need to add it manually in Vivado's source list.
