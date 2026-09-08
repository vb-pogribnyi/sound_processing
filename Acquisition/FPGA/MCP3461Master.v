`include "src/MCP3461Reader.v"

module MCP3461Master #(
    parameter NUM_ADC   = 32,
    parameter ADC_ADDR  = 0
) (
    input wire i_CLK50,
    input wire i_INTERRUPT,
    input wire [2:0] i_GAIN,         // MCP3461 PGA gain code (CONFIG2[5:3])
    input wire [2:0] i_NUM_ADC_LOG2, // effective channel count: EFF = 1<<this (STM32 @0xD)
    input wire i_IGNORE_VALID,       // SW2: 1 = drop the address-ack term from o_RDY (diagnostic)
    input wire i_FREERUN,            // SW3: 1 = read every loop, ignore DRDY/IRQ pacing (diagnostic)
    input wire [NUM_ADC-1:0] i_MISO,
    // output wire sel_interrupt,
    output reg o_MOSI,
    output reg o_CS,
    output wire o_SCLK,
    output wire o_MCLK,
    output reg [2:0] o_STATE,
    output wire [16 * NUM_ADC-1:0] o_VALUE,
    output wire o_RDY,
    output wire o_VALID,             // combined address-ack validity of the EFF active ADCs
    // ---- diagnostics (i_CLK50 domain) ----
    output wire [NUM_ADC-1:0] o_READER_RDY,   // per-channel frame-ready (DR_STATUS fresh)
    output wire [NUM_ADC-1:0] o_READER_VALID, // per-channel address-ack pass
    output wire o_RDY_ALL            // all ACTIVE channels ready, validity IGNORED (vs o_RDY)
);
reg [7:0] tx_buff [0:16];
reg [7:0] tx_len = 0;
reg [7:0] cfg [0:4];
reg [3:0] byte_idx;
reg [2:0] bit_idx;
reg [7:0] tx_shift_reg;
reg [1:0] addr = ADC_ADDR;

reg transmitting = 0;
reg trigger = 0;
reg sclk = 0;
integer i;
assign o_SCLK = sclk & !o_CS;
// From table 6-2 of the datasheet:
// First 2 bits is the device address, following 4 bits is register address
// then the w/r type with 10 being incremental write and 01 being static read
localparam cmd_read_int = 8'h15;    // 00 0101 01
localparam cmd_read_val = 8'h01;    // 00 0000 01
// localparam cmd_read_val = 8'h09;    // 00 0011 01
localparam cmd_write_cfg = 8'h06;   // 00 0001 10
localparam	TIMEOUT = 4;
localparam	FRESH       = 3'h0,
            ALIVE       = 3'h1,
            CONFIGURING = 3'h2,
            READING     = 3'h3,
            ERROR       = 3'h4;
reg [1:0] cnt = 0;
reg [16:0] to_cnt = TIMEOUT;
// Read once per data-ready. WATCHDOG is a safety net: if IRQ never arrives
// (e.g. unwired) the stream still advances, just slowly + obviously degraded.
localparam WATCHDOG = 17'd50000;     // ~4 ms @ 12.5 MHz state rate
reg  [1:0] irq_sync = 2'b11;         // 2-FF sync of IRQ (active low); 11 = not ready
wire data_ready = ~irq_sync[1];      // 1 = ADC has a fresh conversion waiting
// Live PGA-gain control: 2-FF sync the select, rebuild CONFIG2, and re-run the
// config write whenever the selection changes. Base CONFIG2 = 0xC5
// (BOOST=11 -> 2x bias current, AZ_MUX=1, low bits=01); only GAIN[2:0]
// (bits 5:3) is swapped in. BOOST=2x gives the modulator the most bias
// current, so it settles fastest and is least likely to overload/latch into
// the high-noise state on an input transient (at the cost of higher power).
reg  [2:0] gain_s0 = 3'b000, gain_s1 = 3'b000;  // synced gain select
reg  [2:0] gain_applied = 3'b000;               // gain currently written to the ADC
reg  [2:0] nadc_s0 = 3'd1, nadc_s1 = 3'd1;      // synced effective-count log2 (default EFF=2)
wire [7:0] config2 = {2'b11, gain_s1, 3'b101};  // CONFIG2: BOOST=2x + selected gain
wire gain_changed = (gain_s1 != gain_applied);
wire [NUM_ADC-1:0] reader_rdy;
wire [NUM_ADC-1:0] reader_valid;
// EFF = 1<<nadc_s1 active channels. active_mask marks them; inactive lanes are
// forced to 1 in each reduction below so an unpopulated channel can neither gate
// nor invalidate the real ones. Generic for any NUM_ADC: bit m is active iff
// m < EFF. nadc_s1 in 0..5 -> EFF in {1,2,4,8,16,32}; EFF>=NUM_ADC = all active.
wire [7:0] eff_count = (8'd1 << nadc_s1);   // 1,2,4,...,128
reg [NUM_ADC-1:0] active_mask;
integer mi;
always @(*) begin
    for (mi = 0; mi < NUM_ADC; mi = mi + 1)
        active_mask[mi] = (mi < eff_count);
end
// Enforce is_valid: ready only when every ACTIVE channel is data-ready AND passes
// its address-ack check. o_VALID = all active channels valid (FSMC status bit2).
// SW2 override (i_IGNORE_VALID): drop the address-ack term so a channel that
// fails its validity check can no longer stall the shared sample clock. This
// isolates whether the validity gate is what throttles the live stream.
assign o_RDY   = i_IGNORE_VALID
               ? &( reader_rdy                 | ~active_mask)
               : &((reader_rdy & reader_valid) | ~active_mask);
assign o_VALID = &(reader_valid | ~active_mask);
// Diagnostics: ready across all ACTIVE channels with validity IGNORED (so the
// health integrator / counters can compare "would-be sample rate" against the
// gated o_RDY), plus the raw per-channel bitmaps.
assign o_RDY_ALL      = &(reader_rdy | ~active_mask);
assign o_READER_RDY   = reader_rdy;
assign o_READER_VALID = reader_valid;
genvar gi;
generate
for (gi = 0; gi < NUM_ADC ; gi = gi + 1) begin: readers
    MCP3461Reader reader (
        .i_CLK50(i_CLK50),
        .i_MISO(i_MISO[gi]),
        .i_SCLK(sclk),
        .i_CS(o_CS),
        .o_RDY(reader_rdy[gi]),
        .o_VALUE(o_VALUE[16 * (gi+1)-1:16 * gi]),
        .o_VALID(reader_valid[gi])
    );
end
endgenerate;
initial begin
    o_CS = 1;
    o_STATE = FRESH;
    cfg[0] = 8'hC3;  // CONFIG0. Internal ref, external MCLK, no current, conv mode
    cfg[1] = 8'h00;  // CONFIG1. No prescaler, smallest oversampling
    cfg[2] = 8'h45;  // CONFIG2 - VESTIGIAL: the ALIVE-state write uses the `config2`
                     // wire (BOOST=2x + switch-selected gain), NOT this value.
    cfg[3] = 8'hC0;  // CONFIG3. Continuous conversion, 16-bit coding, no CRC, no calibration
    cfg[4] = 8'h00;  // IRQ. Enabled, no "start" interrupt
    // Actually from this point on the default configuration is OK.
    // cfg[5] = 8'h01;  // MUX. Measuring CH0 vs CH1
    // cfg[6] = 8'h45;  // SCAN. 
    // Fill configuration...
    
end
// SDI (MOSI) clocked on rising edge, update should be on falling edge
// SDO (MISO) clocked out on falling edge, read should be on rising edge.
assign o_MCLK = (cnt >= 2);
always @(posedge i_CLK50) begin
    cnt <= cnt + 1;
    irq_sync <= {irq_sync[0], i_INTERRUPT};   // synchronize the async IRQ pin
    gain_s0  <= i_GAIN;                        // synchronize the gain-select switches
    gain_s1  <= gain_s0;
    nadc_s0  <= i_NUM_ADC_LOG2;                // synchronize the effective-count select
    nadc_s1  <= nadc_s0;
    if (cnt == 0) begin // 6 MHZ clock
        sclk <= !sclk; 

        // The state-machine sets transmission data and trigger, if required.
        case(o_STATE)
            FRESH: begin    // Just powered up, maybe not yet initialized
                if (to_cnt > 0) begin  // HOOLD
                    to_cnt <= to_cnt - 1;
                end
                else begin
                    if (!trigger && !transmitting && tx_len == 0) begin
                        tx_len <= 1;
                        tx_buff[0] <= cmd_read_int;
                        tx_buff[0][7] <= addr[1];
                        tx_buff[0][6] <= addr[0];
                        trigger <= 1;
                    end
                    if (!trigger && !transmitting && tx_len > 0) begin
                        // TODO: Check if the answer is valid
                        // That would mean the ADC is ready to talk.
                        tx_len <= 0;
                        o_STATE <= ALIVE;
                    end
                end
            end
            ALIVE: begin    // The ADC is ready to be configured
                if (!trigger && !transmitting && o_CS && tx_len == 0) begin
                    tx_len <= 6;
                    tx_buff[0] <= cmd_write_cfg;
                    tx_buff[0][7] <= addr[1];
                    tx_buff[0][6] <= addr[0];
                    tx_buff[1] <= cfg[0];
                    tx_buff[2] <= cfg[1];
                    tx_buff[3] <= config2;   // CONFIG2 with switch-selected PGA gain
                    tx_buff[4] <= cfg[3];
                    tx_buff[5] <= cfg[4];
                    trigger <= 1;
                end
                if (!trigger && !transmitting && tx_len > 0) begin
                    // TODO: Check if the answer is valid
                    // That would mean the ADC is configured.
                    tx_len <= 0;
                    o_STATE <= READING;
                    gain_applied <= gain_s1;   // record the gain we just wrote
                    to_cnt <= TIMEOUT;
                end
            end
            READING: begin    // Main loop: one read per data-ready (DRDY/IRQ)
                if (!trigger && !transmitting && o_CS && tx_len == 0) begin
                    // Read only when the ADC asserts IRQ (a fresh conversion is
                    // waiting). This gives uniform sample timing and exactly one
                    // read per conversion - no duplicates, no missed/overwritten
                    // samples. Reading ADCDATA clears IRQ until the next
                    // conversion. to_cnt is only a watchdog fallback.
                    if (gain_changed) begin
                        o_STATE <= ALIVE;   // re-apply config when PGA gain switch changes
                    end
                    // SW3 override (i_FREERUN): trigger a read every loop, ignoring
                    // DRDY/IRQ. If the stream speeds up markedly with this on, the
                    // ADC IRQ/conversion cadence - not the FPGA - was the bottleneck.
                    else if (i_FREERUN || data_ready || to_cnt == 0) begin
                        tx_len <= 3;    // status byte + 2 ADC data bytes
                        tx_buff[0] <= cmd_read_val;
                        tx_buff[0][7] <= addr[1];
                        tx_buff[0][6] <= addr[0];
                        tx_buff[1] <= 0;
                        tx_buff[2] <= 0;
                        trigger <= 1;
                        to_cnt <= WATCHDOG;     // re-arm watchdog
                    end else if (to_cnt > 0) begin
                        to_cnt <= to_cnt - 1;
                    end
                end
                if (!trigger && !transmitting && o_CS && tx_len > 0) begin
                    tx_len <= 0;    // read complete; IRQ now cleared by the read
                end
            end
        endcase
        if (trigger && !transmitting) begin
            transmitting <= 1;
            trigger <= 0;
            byte_idx <= 0;
            bit_idx <= 7;
            tx_shift_reg <= tx_buff[0];
        end
        if (transmitting) begin
            if (sclk) begin // Falling edge; sclk will update to low at the end of posedge handler
                tx_shift_reg <= {tx_shift_reg[6:0], 1'b0};
                o_MOSI <= tx_shift_reg[7];
                o_CS <= 0;
                if (bit_idx == 0) begin
                    byte_idx <= byte_idx + 1;
                    tx_shift_reg <= tx_buff[byte_idx + 1];
                    bit_idx <= 7;
                end
                else begin
                    bit_idx <= bit_idx - 1;
                end
                if (bit_idx == 7) begin
                    if (byte_idx == tx_len) begin
                        transmitting <= 0;
                    end
                end
            end
        end
        else begin
            o_CS <= 1;
        end
    end
end
endmodule