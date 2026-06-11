////////////////////////////////////////////////////////////////////////////////
// Photon Counter Module for Red Pitaya STEMlab 125-14
//
// Real-time pulse detection on ADC channel with configurable threshold
// and dead time. Provides pulse counting, gated count rate, and optional
// pulse height histogram via system bus registers.
//
// System bus slot: sys[7] -> base address 0x40700000
////////////////////////////////////////////////////////////////////////////////

module photon_scanner (
  // System signals
  input  logic           clk_i,      // 125 MHz ADC clock
  input  logic           rstn_i,     // active-low reset
  input  logic           trig_in,    // Trigger input from FPGA trigger system

  // ADC input (16-bit signed, 2's complement from ADC IO block)
  input  logic signed [16-1:0] adc_dat_i,

  // System bus (directly wired to sys[7])
  input  logic [32-1:0]  sys_addr,
  input  logic [32-1:0]  sys_wdata,
  input  logic           sys_wen,
  input  logic           sys_ren,
  output logic [32-1:0]  sys_rdata,
  output logic           sys_err,
  output logic           sys_ack
);

////////////////////////////////////////////////////////////////////////////////
// Register map (active address bits [19:0] from bus interconnect)
//
// 0x00  CTRL        R/W  [0]=enable, [1]=reset (auto-clears)
// 0x04  THRESHOLD   R/W  16-bit signed threshold
// 0x08  DEAD_TIME   R/W  dead time in clock cycles (16-bit)
// 0x0C  COUNT       R    32-bit cumulative pulse count
// 0x10  COUNT_RATE  R    pulses counted in last gate period
// 0x14  GATE_PERIOD R/W  gate period in clock cycles (32-bit)
// 0x18  PEAK_LAST   R    peak ADC value of most recent pulse
// 0x1C  STATUS      R    [0]=enabled, [1]=counting overflow
// 0x20  ADC_RAW     R    current ADC sample (for threshold tuning)
// 0x100-0x4FF HIST[0..255] R  256 x 32-bit pulse height histogram

// 0x24  HIST_SHIFT        R/W  histogram bit shift
// 0x28  TRIG_TOTAL_GATES  R/W  Number of gates to count (N)
// 0x2C  TRIG_ENABLE       R/W  Enable triggered mode (1=active)
// 0x30  TRIG_ARM          R/W  Arm trigger (1=wait for trig_in)
// 0x34  TRIG_READ_INDEX   R/W  Index for reading back counts (0 to N-1)
// 0x38  TRIG_STATUS       R    [0]=trig_active, [1]=trig_done
// 0x100-0x4FF HIST[0..255] R  256 x 32-bit pulse height histogram
// 0x500-0x14FF TRIG_COUNTS[0..255] R  Counts per gate (32-bit each)
////////////////////////////////////////////////////////////////////////////////

// Configuration registers
logic        reg_enable;
logic        reg_reset;
logic signed [15:0] reg_threshold;
logic [15:0] reg_deadtime;
logic [31:0] reg_gate_period;
logic [3:0]  reg_hist_shift;     // histogram bit shift (0-10)

logic [31:0] reg_trig_total_gates;   // Number of gates to count (N)
logic        reg_trig_enable;        // Enable triggered mode (1=active)
logic        reg_trig_arm;           // Arm trigger (1=wait for trig_in)

// Status / readback registers
logic [31:0] pulse_count;
logic [31:0] count_rate;
logic [15:0] peak_last;
logic        overflow;

parameter MAX_TRIG_GATES = 512;  // Max number of gates (adjust as needed)
logic [31:0] counted_gates [0:MAX_TRIG_GATES-1]; // Counts per gate
logic [8:0]  reg_trig_read_index;    // Index for reading back counts
logic [8:0]  current_trig_gate;      // Current gate index (0 to N-1)
logic        trig_active;            // Triggered counting is active
logic        trig_done;              // All gates counted

// Internal signals
logic signed [15:0] adc_prev;        // previous ADC sample
logic        in_deadtime;            // dead time active flag
logic [15:0] deadtime_cnt;           // dead time counter
logic [31:0] gate_counter;           // gate period counter
logic [31:0] gate_pulse_count;       // pulses in current gate
logic        trig_armed;             // Trigger armed flag

// Pulse detection
logic pulse_detected;

// Histogram BRAM (64 bins x 32 bits) — reduced for Z7010
logic [31:0] hist_mem [0:63];
logic [5:0]  hist_bin;               // bin index for current pulse
logic        hist_wen;               // histogram write enable

////////////////////////////////////////////////////////////////////////////////
// Write registers
////////////////////////////////////////////////////////////////////////////////

always_ff @(posedge clk_i) begin
  if (~rstn_i) begin
    reg_enable      <= 1'b0;
    reg_reset       <= 1'b0;
    reg_threshold   <= 16'sd100;     // default threshold
    reg_deadtime    <= 16'd16;       // 128 ns default
    reg_gate_period <= 32'd125_000_000; // 1 second default
    reg_hist_shift  <= 4'd0;           // bits [5:0] by default
    
    reg_trig_total_gates <= 32'd1;       // Default: 1 gate
    reg_trig_enable      <= 1'b0;        // Disabled by default
    reg_trig_arm         <= 1'b0;        // Disarmed by default
    reg_trig_read_index  <= 8'd0;        // Start reading from index 0
  end else begin
    // auto-clear reset bit
    if (reg_reset)
      reg_reset <= 1'b0;

    if (sys_wen) begin
      case (sys_addr[19:0])
        20'h00: begin
          reg_enable <= sys_wdata[0];
          reg_reset  <= sys_wdata[1];
        end
        20'h04: reg_threshold   <= sys_wdata[15:0];
        20'h08: reg_deadtime    <= sys_wdata[15:0];
        20'h14: reg_gate_period <= sys_wdata;
        20'h24: reg_hist_shift  <= sys_wdata[3:0];
        
        20'h28: reg_trig_total_gates <= sys_wdata[8:0]; // 8-bit max (512)
        20'h2C: reg_trig_enable <= sys_wdata[0];
        20'h30: reg_trig_arm    <= sys_wdata[0];
        20'h34: reg_trig_read_index <= sys_wdata[8:0];
        default: ;
      endcase
    end
  end
end

////////////////////////////////////////////////////////////////////////////////
// Read registers + bus acknowledge
// Must set sys_ack and sys_rdata in the same clock cycle (RP bus protocol)
////////////////////////////////////////////////////////////////////////////////

wire sys_en = sys_wen | sys_ren;

always @(posedge clk_i)
if (~rstn_i) begin
  sys_err   <= 1'b0;
  sys_ack   <= 1'b0;
  sys_rdata <= 32'h0;
end else begin
  sys_err <= 1'b0;
  sys_ack <= sys_en;

  if (sys_ren) begin
    case (sys_addr[19:0])
      20'h00000: sys_rdata <= {30'b0, reg_reset, reg_enable};
      20'h00004: sys_rdata <= {{16{reg_threshold[15]}}, reg_threshold};
      20'h00008: sys_rdata <= {16'b0, reg_deadtime};
      20'h0000C: sys_rdata <= pulse_count;
      20'h00010: sys_rdata <= count_rate;
      20'h00014: sys_rdata <= reg_gate_period;
      20'h00018: sys_rdata <= {16'b0, peak_last};
      20'h0001C: sys_rdata <= {30'b0, overflow, reg_enable};
      20'h00020: sys_rdata <= {{16{adc_dat_i[15]}}, adc_dat_i};
      20'h00024: sys_rdata <= {28'b0, reg_hist_shift};
   //   20'h00028: sys_rdata <= gate_counter;
   
      20'h00028: sys_rdata <= {23'b0, reg_trig_total_gates[8:0]}; // TRIG_TOTAL_GATES
      20'h0002C: sys_rdata <= {31'b0, reg_trig_enable};          // TRIG_ENABLE
      20'h00030: sys_rdata <= {31'b0, reg_trig_arm};             // TRIG_ARM
      20'h00034: sys_rdata <= {23'b0, reg_trig_read_index[8:0]}; // TRIG_READ_INDEX
      20'h00038: sys_rdata <= {30'b0, trig_active, trig_done};   // TRIG_STATUS
      default: begin
      // TRIG_COUNTS[0..255] at 0x500-0x14FF
        if (sys_addr[19:0] >= 20'h500 && sys_addr[19:0] < 20'h1500)
          sys_rdata <= counted_gates[sys_addr[8:0]];
        // HIST[0..255] at 0x100-0x4FF
        else if (sys_addr[19:0] >= 20'h100 && sys_addr[19:0] < 20'h200)
          sys_rdata <= hist_mem[sys_addr[7:2]];
        else
          sys_rdata <= 32'h0;
      end
        //if (sys_addr[19:0] >= 20'h100 && sys_addr[19:0] < 20'h200)
        //  sys_rdata <= hist_mem[sys_addr[7:2]];
       // else
        //  sys_rdata <= 32'h0;
     // end
    endcase
  end
end

//////////////////////////////////////////////////////////////////////////////////
// Trigger rising-edge detection
////////////////////////////////////////////////////////////////////////////////

logic trig_in_prev;

always_ff @(posedge clk_i) begin
  if (~rstn_i) begin
    trig_in_prev <= 1'b0;
    trig_armed <= 1'b0;
    trig_active <= 1'b0;
    trig_done <= 1'b0;
    current_trig_gate <= 8'd0;
  end else begin
    trig_in_prev <= trig_in;
    // Arm the trigger if requested
    if (reg_trig_arm)
      trig_armed <= 1'b1;
    else
      trig_armed <= 1'b0;
  end
end

wire trig_in_rising_edge = trig_in & ~trig_in_prev;

////////////////////////////////////////////////////////////////////////////////
// Pulse detection logic
////////////////////////////////////////////////////////////////////////////////

// Store previous sample for edge detection
always_ff @(posedge clk_i) begin
  if (~rstn_i)
    adc_prev <= '0;
  else
    adc_prev <= adc_dat_i;
end

// Rising edge threshold crossing: current >= threshold AND previous < threshold
assign pulse_detected = reg_enable
                      & ~in_deadtime
                      & (adc_dat_i >= reg_threshold)
                      & (adc_prev  <  reg_threshold);

////////////////////////////////////////////////////////////////////////////////
// Dead time handler
////////////////////////////////////////////////////////////////////////////////

always_ff @(posedge clk_i) begin
  if (~rstn_i || reg_reset) begin
    in_deadtime  <= 1'b0;
    deadtime_cnt <= '0;
    peak_last    <= '0;
  end else if (reg_enable) begin
    if (pulse_detected) begin
      // Enter dead time, immediately latch crossing value
      in_deadtime  <= 1'b1;
      deadtime_cnt <= reg_deadtime;
      peak_last    <= {2'b0, adc_dat_i[13:0]};  // capture 14-bit ADC, zero-extend
    end else if (in_deadtime) begin
      if (deadtime_cnt == 0)
        in_deadtime <= 1'b0;
      else
        deadtime_cnt <= deadtime_cnt - 1;
    end
  end
end

////////////////////////////////////////////////////////////////////////////////
// Pulse counter and gated count rate (non-triggered-mode)
////////////////////////////////////////////////////////////////////////////////

always_ff @(posedge clk_i) begin
  if (~rstn_i || reg_reset) begin
    pulse_count      <= '0;
    count_rate       <= '0;
    gate_counter     <= '0;
    gate_pulse_count <= '0;
    overflow         <= 1'b0;
  end else if (reg_enable && !reg_trig_enable) begin
    // Cumulative counter
    if (pulse_detected) begin
      if (pulse_count == 32'hFFFFFFFF)
        overflow <= 1'b1;
      else
        pulse_count <= pulse_count + 1;
        gate_pulse_count <= gate_pulse_count + 1;
    end

    // Gate period: latch count_rate and reset gate counter
    if (gate_counter >= reg_gate_period - 1) begin
      count_rate       <= gate_pulse_count + (pulse_detected ? 32'd1 : 32'd0);
      gate_pulse_count <= '0;
      gate_counter     <= '0;
    end else begin
      gate_counter <= gate_counter + 1;
    end

    // peak_last is now latched in the dead time handler block
  end
end

//////////////////////////////////////////////////////////////////////////////////
// Triggered gated counting logic
////////////////////////////////////////////////////////////////////////////////

always_ff @(posedge clk_i) begin
  if (~rstn_i || reg_reset) begin
    trig_active <= 1'b0;
    trig_done <= 1'b0;
    current_trig_gate <= 8'd0;
    for (int i = 0; i < MAX_TRIG_GATES; i++)
      counted_gates[i] <= 32'd0;
  end else if (reg_trig_enable && trig_armed) begin
    // Start counting on rising edge of trig_in
    if (trig_in_rising_edge) begin
      trig_active <= 1'b1;
      trig_done <= 1'b0;
      current_trig_gate <= 8'd0;
      for (int i = 0; i < MAX_TRIG_GATES; i++)
        counted_gates[i] <= 32'd0;
    end

    // Count photons in current gate
    if (trig_active && pulse_detected) begin
      if (counted_gates[current_trig_gate] != 32'hFFFFFFFF)
        counted_gates[current_trig_gate] <= counted_gates[current_trig_gate] + 1;
    end

    // Move to next gate or stop if all gates are done
    if (trig_active && gate_counter >= reg_gate_period - 1) begin
      gate_counter <= 32'd0;
      if (current_trig_gate < reg_trig_total_gates - 1) begin
        current_trig_gate <= current_trig_gate + 1;
      end else begin
        trig_active <= 1'b0;
        trig_done <= 1'b1;
      end
    end
  end
end

////////////////////////////////////////////////////////////////////////////////
// Pulse height histogram
////////////////////////////////////////////////////////////////////////////////

// When dead time ends, bin the peak value into histogram
// Use upper 8 bits of the unsigned peak value as bin index
always_ff @(posedge clk_i) begin
  if (~rstn_i || reg_reset) begin
    hist_wen <= 1'b0;
    hist_bin <= '0;
  end else begin
    // Delayed one cycle from pulse_detected so peak_last is stable
    hist_wen <= pulse_detected;
    hist_bin <= (peak_last >> reg_hist_shift) & 6'h3F; // bin the crossing value
  end
end

// Histogram BRAM write
always_ff @(posedge clk_i) begin
  if (~rstn_i || reg_reset) begin
    for (int i = 0; i < 64; i++)
      hist_mem[i] <= '0;
  end else if (hist_wen) begin
    if (hist_mem[hist_bin] != 32'hFFFFFFFF)
      hist_mem[hist_bin] <= hist_mem[hist_bin] + 1;
  end
end

endmodule: photon_scanner
