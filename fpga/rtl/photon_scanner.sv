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

// 0x28  TRIG_TOTAL_GATES  R/W  Number of gates to count (N)
// 0x34  TRIG_READ_INDEX   R/W  Index for reading back counts (0 to N-1)
// 0x38  TRIG_STATUS       R    [0]=trig_active, [1]=trig_done
// 0x40  REG_SOFT_TRIG         R/W  Allows to set trig_active to 1 and force the counting of photons (software trigger)
// 0x500-0x14FF TRIG_COUNTS[0..255] R  Counts per gate (32-bit each)
////////////////////////////////////////////////////////////////////////////////

// Configuration registers
logic        reg_enable;
logic        reg_reset;
logic signed [15:0] reg_threshold;
logic [15:0] reg_deadtime;
logic [31:0] reg_gate_period;

logic [10:0] reg_trig_total_gates;   // Number of gates to count (N)
logic       reg_soft_trig;        // Software trigger, overwriting trig_active, Written by the bus (combinational)


// Status / readback registers
parameter MAX_TRIG_GATES = 1024;  // Max number of gates (adjust as needed) //here
logic [31:0] counted_gates [0:MAX_TRIG_GATES-1]; // Counts per gate
//(* ram_style = "block" *) logic [31:0] counted_gates [0:MAX_TRIG_GATES-1];
//logic [9:0]  reg_trig_read_index;    // Index for reading back counts
logic [9:0]  current_trig_gate;      // Current gate index (0 to N-1)
logic        trig_active;            // Triggered counting is active
logic        trig_done;              // All gates counted

// Internal signals
logic signed [15:0] adc_prev;        // previous ADC sample
logic        in_deadtime;            // dead time active flag
logic [15:0] deadtime_cnt;           // dead time counter
logic [31:0] gate_counter;           // gate period counter

// Pulse detection
logic pulse_detected;

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

    reg_trig_total_gates <= 11'd1;       // Default: 1 gate
//    reg_trig_read_index  <= 10'd0;        // Start reading from index 0
    reg_soft_trig        <= 1'b0;        // Disarmed by default
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
        20'h00028: reg_trig_total_gates <= sys_wdata[10:0];
 /*       20'h00028: begin
          // Clamp reg_trig_total_gates to MAX_TRIG_GATES
          if (sys_wdata[8:0] > MAX_TRIG_GATES)
            reg_trig_total_gates <= MAX_TRIG_GATES;
          else
            reg_trig_total_gates <= sys_wdata[8:0];
        end      */
//        20'h34: reg_trig_read_index <= sys_wdata[9:0];
        20'h40: reg_soft_trig <= sys_wdata[0];  // Directly trigger through software (bit 0)
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
      20'h00014: sys_rdata <= reg_gate_period;
      20'h00028: sys_rdata <= {23'b0, reg_trig_total_gates[10:0]}; // TRIG_TOTAL_GATES
//      20'h00034: sys_rdata <= {23'b0, reg_trig_read_index[9:0]}; // TRIG_READ_INDEX
      20'h00038: sys_rdata <= {30'b0, trig_active, trig_done};   // TRIG_STATUS
      20'h00040: sys_rdata <= {30'b0, reg_soft_trig};          // REG_SOFT_TRIG
      default: begin
      // TRIG_COUNTS[0..255] at 0x500-0x14FF
        if (sys_addr[19:0] >= 20'h500 && sys_addr[19:0] < 20'h1504)
          sys_rdata <= counted_gates[sys_addr[12:2] - 10'd320];
        else
          sys_rdata <= 32'h0;
      end
    endcase
  end
end

//////////////////////////////////////////////////////////////////////////////////
// Trigger rising-edge detection
////////////////////////////////////////////////////////////////////////////////

// Synchronize and detect rising edge on trig_in and trig_soft
logic trig_in_s0, trig_in_s1;
logic trig_soft_s0, trig_soft_s1;
always_ff @(posedge clk_i) begin
  if (~rstn_i) begin
    trig_in_s0 <= 1'b0;
    trig_in_s1 <= 1'b0;
    trig_soft_s0 <= 1'b0;
    trig_soft_s1 <= 1'b0;
  end else begin
    // Synchronize trig_in
    trig_in_s0 <= trig_in;
    trig_in_s1 <= trig_in_s0;

    trig_soft_s0 <= reg_soft_trig;
    trig_soft_s1 <= trig_soft_s0;
  end
end

// Rising edge detection (on original trig, after synchronization)
wire trig_in_rising_edge = trig_in_s0 & ~trig_in_s1;
wire trig_soft_rising_edge = trig_soft_s0 & ~trig_soft_s1;


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
//    adc_prev <= '0;
  end else if (reg_enable) begin
//    adc_prev <= adc_dat_i;
//    if (reg_enable) begin
      if (pulse_detected) begin
        // Enter dead time, immediately latch crossing value
        in_deadtime  <= 1'b1;
        deadtime_cnt <= reg_deadtime;
      end else if (in_deadtime) begin
        if (deadtime_cnt == 0)
          in_deadtime <= 1'b0;
        else
          deadtime_cnt <= deadtime_cnt - 1;
      end
    end
  end
//end


////////////////////////////////////////////////////////////////////////////////
// Pulse counter and gated count rate
////////////////////////////////////////////////////////////////////////////////

always_ff @(posedge clk_i) begin
  if (~rstn_i || reg_reset) begin
    gate_counter     <= '0;
    trig_active       <= 1'b0;
    trig_done         <= 1'b0;
    current_trig_gate <= '0;
//    for (int i = 0; i < MAX_TRIG_GATES; i++)
//        counted_gates[i] <= '0;
  end
  else if (reg_enable) begin
    // Start counting on rising edge of trig_in
    if (trig_in_rising_edge|| trig_soft_rising_edge) begin
      trig_active       <= 1'b1;
      trig_done         <= 1'b0;
      current_trig_gate <= '0;
      gate_counter      <= '0;
//      for (int i = 0; i < reg_trig_total_gates; i++)
//        counted_gates[i] <= '0;
    end
    if (trig_active) begin
        if (gate_counter == 0)
            counted_gates[current_trig_gate] <= '0;
      // Count photons in current gate
        if (pulse_detected) begin
            if (counted_gates[current_trig_gate] != 32'hFFFFFFFF)
              counted_gates[current_trig_gate] <= counted_gates[current_trig_gate] + 1;
        end
        // Advance gate or finish
        if (gate_counter >= reg_gate_period - 1) begin
            gate_counter <= '0;
            if (current_trig_gate < reg_trig_total_gates - 1) begin
                current_trig_gate <= current_trig_gate + 1;
            end else begin
                trig_active <= 1'b0;
                trig_done   <= 1'b1;
            end
        end else begin
            gate_counter <= gate_counter + 1;
        end
    end
  end
end

endmodule: photon_scanner