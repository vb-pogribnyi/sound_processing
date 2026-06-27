// =====================================================================
// OV5640.v
//
// Minimal OV5640 camera front-end for the "only 3 DVP data lines wired"
// board (D3, D6, D7 routed; D[9:0] otherwise floating). It:
//   1. generates XVCLK for the sensor (sys_clk / 2),
//   2. drives the power-up/reset sequence and configures the sensor over
//      SCCB (write-only I2C-like master + a baked register ROM),
//   3. captures the 3 available DVP data bits in the PCLK domain,
//   4. accumulates a per-frame "average red" and "average green" proxy,
//   5. crosses the two 4-bit averages into the sys_clk domain for the
//      FSMC bridge to expose at addresses 0x9 (red) and 0xA (green).
//
// ---------------------------------------------------------------------
// Colour discrimination (why D3/D6/D7 give red vs green)
// ---------------------------------------------------------------------
// The ROM configures RAW Bayer output (FORMAT_CONTROL_00 (0x4300)=0x00,
// FORMAT MUX (0x501F)=0x03). One pixel is sent per PCLK, and the pixel's
// COLOUR is set by its position in the Bayer mosaic, not by which bit it
// lands on. With 0x4300=0x00 the pattern is:
//     even line: B G B G ...
//     odd  line: G R G R ...          (BGGR)
// so red pixels sit at (odd column, odd line), blue at (even,even), and
// green at the other two corners (twice as many as red).
//
// We sample the SAME three wired bits {D7,D6,D3} for every pixel as a
// coarse 3-bit brightness, and bin each pixel into red_acc / green_acc by
// its Bayer position. Because red and green use identical bits, they are
// directly comparable: a white field gives red ~= green, a red field
// gives red >> green, a green field gives green >> red.
//
// This is phase-robust: there is no high/low byte to mis-align (RGB565
// had that problem). The only position dependence is the Bayer phase,
// which shifts with the window offset - flip RED_COL_PAR / RED_LINE_PAR
// if red and green come out swapped on your board.
//
// Note: the exact bus->bit mapping of D7/D6/D3 does not matter for the
// red-vs-green COMPARISON (both colours use the same bits); it only sets
// the absolute brightness scale. Tune RED_SHIFT / GREEN_SHIFT for that.
//
// ---------------------------------------------------------------------
// Averaging
// ---------------------------------------------------------------------
// Per active pixel the samples are summed into wide accumulators over a
// whole frame (frame delimited by VSYNC). At frame end each sum is right-
// shifted (RED_SHIFT / GREEN_SHIFT) and saturated to 4 bits. The shift is
// a fixed scale chosen for the configured frame size (QVGA, 320x240);
// retune the *_SHIFT parameters if you change resolution. No divider is
// used (frame size is constant), so a full-bright frame approaches 0xF
// and a dark frame approaches 0x0.
//
// SCCB is open-drain on SIOD (drive 0 / release to Z, external pull-up).
// SIOC is driven push-pull. The ROM is a STARTER subset (reset, clocks,
// PLL for low rate, RGB565 format, a QVGA window, 50 Hz). For production
// image quality append the full vendor/ESP32 default register list at the
// marked extension point.
// =====================================================================

module OV5640 #(
    parameter SYS_CLK_HZ  = 50000000, // sys_clk frequency
    parameter SCCB_DIV    = 64,       // sys_clk ticks per SCCB quarter-bit (~195 kHz @50MHz/64)
    parameter PWRUP_TICKS = 24'd1000, // SCCB ticks to wait after reset release before config
                                      // (real silicon wants ~20 ms; default kept modest, override in sim)
    parameter RED_SHIFT     = 5'd14,  // red_acc  >> shift -> 4-bit average (tuned for QVGA RAW)
    parameter GREEN_SHIFT   = 5'd15,  // +1 vs RED: Bayer has 2x as many green pixels as red
    parameter RED_COL_PAR   = 1'b1,   // column parity of red pixels (flip if R/G swapped)
    parameter RED_LINE_PAR  = 1'b1    // line   parity of red pixels (flip if R/G swapped)
)(
    input  wire i_CLK,       // free-running sys clock (SYS_CLK_HZ)
    input  wire i_RST_N,     // async active-low reset

    // ---- camera control / clock ----
    output reg  o_XCLK,      // XVCLK to sensor (sys_clk / 2)
    output reg  o_SIOC,      // SCCB clock (push-pull)
    inout  wire o_SIOD,      // SCCB data  (open-drain)
    output wire o_PWDN,      // power-down (active high) - held de-asserted
    output reg  o_RESETB,    // sensor reset, active low

    // ---- DVP capture (PCLK domain) ----
    input  wire i_PCLK,
    input  wire i_HREF,
    input  wire i_VSYNC,
    input  wire i_D7,
    input  wire i_D6,
    input  wire i_D3,

    // ---- frame-averaged outputs (i_CLK / sys_clk domain) ----
    output reg  [3:0] o_RED,    // 4-bit average red    (FSMC 0x9)
    output reg  [3:0] o_GREEN,  // 4-bit average green  (FSMC 0xA)
    output wire       o_CFG_DONE
);

    // -----------------------------------------------------------------
    // NOTE on reset: this board has no reset net wired - i_RST_N is tied
    // high at the top level (fsmc_reset = 1'b1). The module therefore must
    // NOT depend on a reset pulse: every register carries an `initial`
    // value so it powers up correctly straight from FPGA configuration
    // (Xilinx ISE honours FF initial values). The async-reset branches are
    // kept only so the module is still resettable if a reset is ever wired.
    // -----------------------------------------------------------------

    // -----------------------------------------------------------------
    // XVCLK: sys_clk / 2  (25 MHz from 50 MHz; within the 6-27 MHz range)
    // -----------------------------------------------------------------
    initial o_XCLK = 1'b0;
    always @(posedge i_CLK or negedge i_RST_N) begin
        if (!i_RST_N) o_XCLK <= 1'b0;
        else          o_XCLK <= ~o_XCLK;
    end

    assign o_PWDN = 1'b0;   // never power the sensor down

    // -----------------------------------------------------------------
    // SCCB quarter-bit tick generator
    // -----------------------------------------------------------------
    reg [15:0] tick_div;
    reg        tick;
    initial begin
        tick_div = 16'd0;
        tick     = 1'b0;
    end
    always @(posedge i_CLK or negedge i_RST_N) begin
        if (!i_RST_N) begin
            tick_div <= 16'd0;
            tick     <= 1'b0;
        end else if (tick_div >= (SCCB_DIV - 1)) begin
            tick_div <= 16'd0;
            tick     <= 1'b1;
        end else begin
            tick_div <= tick_div + 16'd1;
            tick     <= 1'b0;
        end
    end

    // -----------------------------------------------------------------
    // Configuration ROM:  {reg[15:0], data[7:0]}
    //   reg == 16'hFFFF -> delay, data = number of SCCB ticks (x256)
    //   reg == 16'h0000 -> end of list
    // STARTER subset - extend at the marked point for full image quality.
    // -----------------------------------------------------------------
    localparam CFG_MAX = 64;
    reg [23:0] cfg_mem [0:CFG_MAX-1];

    integer k;
    initial begin
        for (k = 0; k < CFG_MAX; k = k + 1) cfg_mem[k] = 24'h000000;
        // --- reset + power ---
        cfg_mem[ 0] = {16'h3008, 8'h82};   // software reset
        cfg_mem[ 1] = {16'hFFFF, 8'd4};    // delay
        cfg_mem[ 2] = {16'h3008, 8'h42};   // power down while configuring
        cfg_mem[ 3] = {16'h3103, 8'h13};   // sysclk from PLL
        cfg_mem[ 4] = {16'h3017, 8'hFF};   // io direction
        cfg_mem[ 5] = {16'h3018, 8'hFF};
        cfg_mem[ 6] = {16'h302C, 8'hC3};   // drive capability
        cfg_mem[ 7] = {16'h4740, 8'h21};   // PCLK/HREF/VSYNC polarity
        // --- PLL: low pixel clock for an easy 3-wire capture ---
        cfg_mem[ 8] = {16'h3034, 8'h1A};   // 10-bit mode
        cfg_mem[ 9] = {16'h3035, 8'h21};   // system clock divider (slow)
        cfg_mem[10] = {16'h3036, 8'h38};   // PLL multiplier (low)
        cfg_mem[11] = {16'h3037, 8'h11};   // pre-divider / root
        cfg_mem[12] = {16'h3108, 8'h16};   // clock dividers
        cfg_mem[13] = {16'h3824, 8'h04};   // DVP PCLK divider
        cfg_mem[14] = {16'h460C, 8'h20};   // PCLK auto
        // --- ISP / format: RAW Bayer (so colour = pixel position) ---
        cfg_mem[15] = {16'h5000, 8'hA7};   // ISP enables (DPC etc.)
        cfg_mem[16] = {16'h5001, 8'h83};   // scale OFF (RAW is not scaled), AWB/SDE on
        cfg_mem[17] = {16'h4300, 8'h00};   // FORMAT_CONTROL_00 = RAW, BGGR sequence
        cfg_mem[18] = {16'h501F, 8'h03};   // FORMAT MUX = ISP RAW (after DPC)
        // --- QVGA (320x240) window with 2x2 binning ---
        cfg_mem[19] = {16'h3800, 8'h00};   // X start = 0
        cfg_mem[20] = {16'h3801, 8'h00};
        cfg_mem[21] = {16'h3802, 8'h00};   // Y start = 0
        cfg_mem[22] = {16'h3803, 8'h00};
        cfg_mem[23] = {16'h3804, 8'h0A};   // X end = 2623
        cfg_mem[24] = {16'h3805, 8'h3F};
        cfg_mem[25] = {16'h3806, 8'h07};   // Y end = 1951
        cfg_mem[26] = {16'h3807, 8'h9F};
        cfg_mem[27] = {16'h3808, 8'h01};   // X output = 320
        cfg_mem[28] = {16'h3809, 8'h40};
        cfg_mem[29] = {16'h380A, 8'h00};   // Y output = 240
        cfg_mem[30] = {16'h380B, 8'hF0};
        cfg_mem[31] = {16'h380C, 8'h08};   // total X = 2060
        cfg_mem[32] = {16'h380D, 8'h0C};
        cfg_mem[33] = {16'h380E, 8'h03};   // total Y = 984
        cfg_mem[34] = {16'h380F, 8'hD8};
        cfg_mem[35] = {16'h3810, 8'h00};   // X offset = 16
        cfg_mem[36] = {16'h3811, 8'h10};
        cfg_mem[37] = {16'h3812, 8'h00};   // Y offset = 8
        cfg_mem[38] = {16'h3813, 8'h08};
        cfg_mem[39] = {16'h3814, 8'h31};   // X subsample increment (binning)
        cfg_mem[40] = {16'h3815, 8'h31};   // Y subsample increment (binning)
        cfg_mem[41] = {16'h3820, 8'h41};   // vflip normal + vertical binning
        cfg_mem[42] = {16'h3821, 8'h01};   // horizontal binning
        cfg_mem[43] = {16'h4514, 8'hAA};   // binning BLC pattern
        cfg_mem[44] = {16'h4520, 8'h0B};
        // --- light frequency / power on ---
        cfg_mem[45] = {16'h3C00, 8'h04};   // 50 Hz
        cfg_mem[46] = {16'h3008, 8'h02};   // power up / start streaming
        cfg_mem[47] = {16'hFFFF, 8'd4};    // settle
        // <<< EXTENSION POINT: append the full vendor default register
        //     list here (indices 48..CFG_MAX-2) for proper image quality >>>
        cfg_mem[48] = {16'h0000, 8'h00};   // end of list
    end

    // -----------------------------------------------------------------
    // Power-up + SCCB sequencer
    // -----------------------------------------------------------------
    localparam S_RST     = 3'd0,  // hold RESETB low
               S_PWRUP   = 3'd1,  // wait before first SCCB transfer
               S_LOAD    = 3'd2,  // fetch ROM entry
               S_DELAY   = 3'd3,  // ROM delay entry
               S_START   = 3'd4,  // I2C start
               S_BYTE    = 3'd5,  // shift a byte (+ ack bit)
               S_STOP    = 3'd6,  // I2C stop
               S_DONE    = 3'd7;

    reg [2:0]  cstate;
    reg [7:0]  cfg_idx;
    reg [23:0] cfg_entry;
    reg [23:0] delay_cnt;

    reg [1:0]  phase;       // quarter-bit phase 0..3
    reg [3:0]  bit_cnt;     // 0..8 (8 data bits + ack)
    reg [1:0]  byte_idx;    // 0..3 within a register write
    reg [7:0]  shifter;     // current byte, MSB first
    reg        sda_drv0;    // 1 => pull SIOD low, 0 => release (Z -> '1')

    wire [15:0] entry_reg  = cfg_entry[23:8];
    wire [7:0]  entry_data = cfg_entry[7:0];

    assign o_SIOD     = sda_drv0 ? 1'b0 : 1'bz;
    assign o_CFG_DONE = (cstate == S_DONE);

    // Power-up startup values (no reset net on this board): hold RESETB low
    // and preload the full PWRUP delay so S_RST emits a proper reset pulse.
    initial begin
        cstate    = S_RST;
        cfg_idx   = 8'd0;
        cfg_entry = 24'd0;
        delay_cnt = PWRUP_TICKS;   // long RESETB-low pulse, not ~0
        phase     = 2'd0;
        bit_cnt   = 4'd0;
        byte_idx  = 2'd0;
        shifter   = 8'd0;
        sda_drv0  = 1'b0;          // SIOD released (idle high via pull-up)
        o_SIOC    = 1'b1;          // SCCB clock idle high
        o_RESETB  = 1'b0;          // sensor held in reset at config
    end

    // byte to send for the current byte_idx
    reg [7:0] cur_byte;
    always @(*) begin
        case (byte_idx)
            2'd0: cur_byte = 8'h78;            // device write address
            2'd1: cur_byte = entry_reg[15:8];  // reg high
            2'd2: cur_byte = entry_reg[7:0];   // reg low
            default: cur_byte = entry_data;    // data
        endcase
    end

    always @(posedge i_CLK or negedge i_RST_N) begin
        if (!i_RST_N) begin
            cstate    <= S_RST;
            cfg_idx   <= 8'd0;
            cfg_entry <= 24'd0;
            delay_cnt <= 24'd0;
            phase     <= 2'd0;
            bit_cnt   <= 4'd0;
            byte_idx  <= 2'd0;
            shifter   <= 8'd0;
            sda_drv0  <= 1'b0;   // release (idle high)
            o_SIOC    <= 1'b1;   // idle high
            o_RESETB  <= 1'b0;   // hold sensor in reset
            delay_cnt <= PWRUP_TICKS;
        end else if (tick) begin
            case (cstate)
                // ---- hold reset low for the power-up window, then release ----
                S_RST: begin
                    o_RESETB <= 1'b0;
                    if (delay_cnt <= 24'd1) begin
                        o_RESETB  <= 1'b1;        // release reset
                        delay_cnt <= PWRUP_TICKS; // settle before SCCB
                        cstate    <= S_PWRUP;
                    end else
                        delay_cnt <= delay_cnt - 24'd1;
                end
                S_PWRUP: begin
                    o_RESETB <= 1'b1;
                    if (delay_cnt <= 24'd1) cstate <= S_LOAD;
                    else delay_cnt <= delay_cnt - 24'd1;
                end
                // ---- fetch next ROM entry ----
                S_LOAD: begin
                    cfg_entry <= cfg_mem[cfg_idx];
                    if (cfg_mem[cfg_idx][23:8] == 16'h0000) begin
                        cstate <= S_DONE;
                    end else if (cfg_mem[cfg_idx][23:8] == 16'hFFFF) begin
                        // delay entry: data * 256 ticks
                        delay_cnt <= {cfg_mem[cfg_idx][7:0], 8'h00};
                        cfg_idx   <= cfg_idx + 8'd1;
                        cstate    <= S_DELAY;
                    end else begin
                        phase    <= 2'd0;
                        byte_idx <= 2'd0;
                        sda_drv0 <= 1'b0;   // ensure idle-high before start
                        o_SIOC   <= 1'b1;
                        cstate   <= S_START;
                    end
                end
                S_DELAY: begin
                    if (delay_cnt <= 24'd1) cstate <= S_LOAD;
                    else delay_cnt <= delay_cnt - 24'd1;
                end
                // ---- I2C start: SDA 1->0 while SCL high ----
                S_START: begin
                    case (phase)
                        2'd0: begin sda_drv0 <= 1'b0; o_SIOC <= 1'b1; end // SDA=1,SCL=1
                        2'd1: begin sda_drv0 <= 1'b1; o_SIOC <= 1'b1; end // SDA=0,SCL=1
                        2'd2: begin o_SIOC <= 1'b0; end                   // SCL=0
                        2'd3: begin
                            o_SIOC  <= 1'b0;
                            bit_cnt <= 4'd0;
                            shifter <= cur_byte;
                            cstate  <= S_BYTE;
                        end
                    endcase
                    phase <= phase + 2'd1;
                end
                // ---- shift one byte, MSB first, then a release (ack) bit ----
                S_BYTE: begin
                    case (phase)
                        2'd0: begin
                            o_SIOC <= 1'b0;
                            if (bit_cnt < 4'd8)
                                sda_drv0 <= ~shifter[7];   // drive bit (open-drain)
                            else
                                sda_drv0 <= 1'b0;          // ack: release SDA
                        end
                        2'd1: o_SIOC <= 1'b1;
                        2'd2: o_SIOC <= 1'b1;
                        2'd3: begin
                            o_SIOC  <= 1'b0;
                            if (bit_cnt < 4'd8) begin
                                shifter <= {shifter[6:0], 1'b0};
                                bit_cnt <= bit_cnt + 4'd1;
                            end else begin
                                // byte (incl ack) done
                                if (byte_idx == 2'd3) begin
                                    cstate <= S_STOP;
                                end else begin
                                    byte_idx <= byte_idx + 2'd1;
                                    bit_cnt  <= 4'd0;
                                    shifter  <= (byte_idx == 2'd0) ? entry_reg[15:8] :
                                                (byte_idx == 2'd1) ? entry_reg[7:0]  :
                                                                     entry_data;
                                end
                            end
                        end
                    endcase
                    phase <= phase + 2'd1;
                end
                // ---- I2C stop: SDA 0->1 while SCL high ----
                S_STOP: begin
                    case (phase)
                        2'd0: begin sda_drv0 <= 1'b1; o_SIOC <= 1'b0; end // SDA=0,SCL=0
                        2'd1: begin o_SIOC <= 1'b1; end                   // SCL=1
                        2'd2: begin sda_drv0 <= 1'b0; o_SIOC <= 1'b1; end // SDA=1,SCL=1
                        2'd3: begin
                            sda_drv0 <= 1'b0; o_SIOC <= 1'b1;
                            cfg_idx  <= cfg_idx + 8'd1;
                            cstate   <= S_LOAD;
                        end
                    endcase
                    phase <= phase + 2'd1;
                end
                S_DONE: begin
                    o_SIOC   <= 1'b1;
                    sda_drv0 <= 1'b0;
                end
                default: cstate <= S_RST;
            endcase
        end
    end

    // =================================================================
    // RAW-Bayer capture + per-colour accumulation  (PCLK domain)
    //
    // One pixel per PCLK (no byte phase). Each pixel's colour comes from
    // its (column,line) parity; the SAME bits {D7,D6,D3} are sampled for
    // every pixel, so red and green compare directly. Green has 2x the
    // pixel count of red, rebalanced by GREEN_SHIFT = RED_SHIFT + 1.
    // =================================================================
    localparam ACC_W = 32;

    reg        href_d, vsync_d;
    reg [11:0] col_idx;                 // pixel column within the current line
    reg [11:0] line_idx;                // line within the current frame
    reg [ACC_W-1:0] red_acc, green_acc;
    reg [3:0]  red_avg_p, green_avg_p;  // latched frame averages (PCLK)
    reg        frame_tog;               // toggles each completed frame

    initial begin
        href_d = 1'b0; vsync_d = 1'b0;
        col_idx = 12'd0; line_idx = 12'd0;
        red_acc = {ACC_W{1'b0}}; green_acc = {ACC_W{1'b0}};
        red_avg_p = 4'd0; green_avg_p = 4'd0; frame_tog = 1'b0;
    end

    // saturating scale of an accumulator to a nibble
    function [3:0] sat_nibble;
        input [ACC_W-1:0] acc;
        input [4:0]       sh;
        reg   [ACC_W-1:0] scaled;
        begin
            scaled = acc >> sh;
            sat_nibble = (scaled[ACC_W-1:4] != 0) ? 4'hF : scaled[3:0];
        end
    endfunction

    // coarse 3-bit brightness, identical bits for every pixel
    wire [2:0] pix_sample = {i_D7, i_D6, i_D3};
    // Bayer classification of the pixel currently on the bus
    wire is_red  = (col_idx[0] == RED_COL_PAR)  && (line_idx[0] == RED_LINE_PAR);
    wire is_blue = (col_idx[0] != RED_COL_PAR)  && (line_idx[0] != RED_LINE_PAR);
    wire is_green = ~is_red & ~is_blue;

    always @(posedge i_PCLK or negedge i_RST_N) begin
        if (!i_RST_N) begin
            href_d     <= 1'b0;
            vsync_d    <= 1'b0;
            col_idx    <= 12'd0;
            line_idx   <= 12'd0;
            red_acc    <= {ACC_W{1'b0}};
            green_acc  <= {ACC_W{1'b0}};
            red_avg_p  <= 4'd0;
            green_avg_p<= 4'd0;
            frame_tog  <= 1'b0;
        end else begin
            href_d  <= i_HREF;
            vsync_d <= i_VSYNC;

            // frame boundary on VSYNC rising: latch averages, clear sums
            if (i_VSYNC & ~vsync_d) begin
                red_avg_p   <= sat_nibble(red_acc,   RED_SHIFT);
                green_avg_p <= sat_nibble(green_acc, GREEN_SHIFT);
                frame_tog   <= ~frame_tog;
                red_acc     <= {ACC_W{1'b0}};
                green_acc   <= {ACC_W{1'b0}};
                col_idx     <= 12'd0;
                line_idx    <= 12'd0;
            end else if (i_HREF) begin
                // accumulate this pixel into its Bayer colour bin
                if (is_red)
                    red_acc   <= red_acc   + pix_sample;
                else if (is_green)
                    green_acc <= green_acc + pix_sample;
                col_idx <= col_idx + 12'd1;
            end else if (href_d) begin
                // line just ended (HREF falling): next line, reset column
                line_idx <= line_idx + 12'd1;
                col_idx  <= 12'd0;
            end
        end
    end

    // -----------------------------------------------------------------
    // CDC: frame averages (PCLK) -> sys_clk on frame_tog edge
    // -----------------------------------------------------------------
    reg [2:0] tog_sync;
    initial begin
        tog_sync = 3'd0;
        o_RED    = 4'd0;
        o_GREEN  = 4'd0;
    end
    always @(posedge i_CLK or negedge i_RST_N) begin
        if (!i_RST_N) begin
            tog_sync <= 3'd0;
            o_RED    <= 4'd0;
            o_GREEN  <= 4'd0;
        end else begin
            tog_sync <= {tog_sync[1:0], frame_tog};
            if (tog_sync[2] ^ tog_sync[1]) begin
                o_RED   <= red_avg_p;    // stable: written one PCLK before the toggle
                o_GREEN <= green_avg_p;
            end
        end
    end

endmodule
