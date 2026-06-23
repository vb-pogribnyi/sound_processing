// =====================================================================
// FSMC.v
//
// Bridges the STM32F407 FSMC bus (8-bit muxed PSRAM + burst read +
// address valid, truncated to 4 physical data/address lines) to the
// psram_fifo FIFO controller (psram_fifo.v / PSRAM.v) backed by a real
// APS6404L QSPI PSRAM chip.
//
// PCB note: only FSMC_AD[3:0] are routed - no FSMC_A lines, no
// FSMC_AD[7:4]. The 4-bit address space (0x0-0xF) is therefore all
// that exists; addresses 0x0-0x3 are used to carry one 16-bit FIFO
// word as four 4-bit nibbles.
//
// STM32F407 pin              this module's port
// -------------------------  -----------------------
// FSMC_AD[3:0]               fsmc_ad   (address during NADV phase, data otherwise)
// FSMC_NE1                   fsmc_ne
// FSMC_NL  (NADV)            fsmc_nadv
// FSMC_NOE                   fsmc_noe
// FSMC_NWE                   fsmc_nwe
// FSMC_CLK                   fsmc_clk
// FSMC_NWAIT                 fsmc_nwait
//
// In addition to the FSMC pins, this module now also needs:
//   sys_clk / reset_n  - a free-running clock + reset for the PSRAM
//                        FIFO engine. FSMC_CLK is NOT used for this,
//                        because on real silicon it is only guaranteed
//                        to toggle while the STM32 has an active burst
//                        transaction in flight - the SPI engine talking
//                        to the real PSRAM chip needs a clock that runs
//                        continuously regardless of FSMC bus activity.
//                        Drive these from your FPGA's own oscillator/PLL
//                        and power-on-reset network.
//   psram_sclk/ce_n/si/so - passed straight through to the APS6404L.
//
// -----------------------------------------------------------------------
// Nibble <-> word convention (4 nibbles per 16-bit FIFO word)
// -----------------------------------------------------------------------
//   FSMC address   word bits     (0 = first nibble transferred)
//   ------------   -----------
//   0x0            [3:0]   (LSB nibble)
//   0x1            [7:4]
//   0x2            [11:8]
//   0x3            [15:12] (MSB nibble)
//
// WRITE: accumulate nibbles from addresses 0,1,2,3 (firmware must write
// in that order); the write to address 0x3 triggers the push of the
// completed 16-bit word into the FIFO.
//
// READ: a read starting at address 0x0 triggers a pop from the FIFO and
// STALLS the bus (via FSMC_NWAIT) until the popped word has actually
// arrived from the real SPI PSRAM chip - this can take hundreds of
// sys_clk cycles, much longer than the small fixed LATENCY_CYCLES used
// for simple memory emulation. Addresses 0x1-0x3 (or address 0x0 read
// again without 4 nibbles having been consumed first - not tracked,
// see limitations below) just replay nibbles of the value already
// fetched, with the modest LATENCY_CYCLES delay. Both a single 4-beat
// burst (one address phase, four FSMC_CLK beats) and four separate
// single-beat reads work correctly with this scheme.
//
// -----------------------------------------------------------------------
// Limitations / things to be aware of
// -----------------------------------------------------------------------
//  - If the FIFO is empty when address 0x0 is read, this module does
//    NOT stall forever: it returns whatever was last latched into
//    rd_holding (stale data) immediately. There is currently no way for
//    firmware to distinguish "freshly popped" from "stale/no data" -
//    if you need that, expose psram_fifo's fifo_empty flag at another
//    address (not implemented here).
//  - If the FIFO is full when address 0x3 is written, psram_fifo's
//    existing behaviour applies: the write is silently dropped. There
//    is currently no status feedback for this either.
//  - MAX_WAIT_CYCLES (see below) is a safety net so a stuck/failed SPI
//    transaction can never hang the STM32 forever, but it should never
//    actually be hit in normal operation - size it generously above the
//    real worst-case pop latency for your CLK_DIV/SYS_CLK_MHZ settings.
//  - This bridge assumes nADC=1 (one 16-bit word per FIFO entry) to
//    match the four-address (0x0-0x3) scheme described above. It is
//    hardcoded into the psram_fifo instantiation below; supporting more
//    channels would need a larger address range.
//  - Reads/writes beyond addresses 0x0-0x3 are not meaningful (nibble
//    select wraps every 4 addresses, aliasing back onto the same word).
//
// NOTE: ACCESS_DELAY/#-delay statements are simulation-only modelling
// aids - not synthesisable as-is; replace/remove for real synthesis if
// your toolchain rejects delay-controlled continuous assignments.
// =====================================================================

module FSMC #(
    parameter LATENCY_CYCLES  = 2,  // FSMC_CLK wait cycles before streaming a CACHED nibble
                                     // (addresses 0x1-0x3, or 0x0 when the FIFO was empty)
    parameter WAIT_ACTIVE_LOW = 0,  // NWAIT polarity. Default 0 (active HIGH) per the
                                     // STM32F405/407 errata workaround (ES0182 sec. 2.3.2).
    parameter ACCESS_DELAY    = 5,  // ns internal delay on fsmc_ad / fsmc_nwait outputs (sim only)
    parameter WAIT_TIMING_BEFORE_WS = 1,
                                     // 1 = NWAIT reports the *upcoming* cycle's status
                                     //     (HAL's FMC_WAIT_TIMING_BEFORE_WS).
                                     // 0 = NWAIT reports the *current* cycle's status
                                     //     (FMC_WAIT_TIMING_DURING_WS).
    parameter MAX_WAIT_CYCLES  = 4096,
                                     // Safety timeout (in fsmc_clk cycles) while waiting for a
                                     // FIFO pop to complete. Must comfortably exceed the real
                                     // worst-case SPI round-trip time for one 16-bit pop,
                                     // converted into fsmc_clk cycles via your actual clock
                                     // ratio. With the psram_fifo defaults (nADC=1, CLK_DIV=4)
                                     // a pop takes roughly (8+24+8+16)*2*CLK_DIV = 448 sys_clk
                                     // cycles - scale that by fsmc_clk's period vs sys_clk's and
                                     // add margin. If this default proves too small for your
                                     // configuration, increase it; do NOT decrease it casually.
    // Pass-through parameters for the instantiated psram_fifo
    parameter PSRAM_CLK_DIV     = 4,
    parameter PSRAM_SYS_CLK_MHZ = 50,
    parameter PSRAM_FIFO_DEPTH  = 256
)(
    // ---- FSMC bus (from STM32) ----
    inout  wire [3:0] fsmc_ad,    // muxed address / data bus
    input  wire       fsmc_ne,    // chip select, active low
    input  wire       fsmc_nadv,  // address valid (FSMC_NL / NADV), active low
    input  wire       fsmc_noe,   // read enable, active low
    input  wire       fsmc_nwe,   // write enable, active low
    input  wire       fsmc_clk,   // synchronous burst clock
    output wire       fsmc_nwait, // wait signal, polarity per WAIT_ACTIVE_LOW

    // ---- free-running clock/reset for the PSRAM FIFO engine ----
    input  wire        sys_clk,
    input  wire        reset_n,   // async active-low reset, shared with psram_fifo

    // ---- APS6404L QSPI PSRAM pins (passed straight through) ----
    output wire         psram_sclk,
    output wire         psram_ce_n,
    output wire         psram_si,
    input  wire         psram_so
);

    // ---------------------------------------------------------------
    // Address phase: transparent latch while NADV is low; frozen on
    // the rising edge of NADV. Only 4 bits exist (4 lines routed).
    // ---------------------------------------------------------------
    reg [3:0] latch_addr;

    always @(*) begin
        if (!fsmc_nadv)
            latch_addr = fsmc_ad;
    end

    reg [3:0] burst_start_addr;

    always @(posedge fsmc_nadv or negedge reset_n) begin
        if (!reset_n)
            burst_start_addr <= 4'h0;
        else
            burst_start_addr <= latch_addr;
    end

    // =================================================================
    // Clock-domain crossing: FSMC (fsmc_clk, bursty) <-> PSRAM FIFO (sys_clk, free-running)
    // =================================================================

    // ---- Requests: fsmc_clk -> sys_clk, toggle-style (psram_fifo edge-detects internally) ----
    reg rd_req_tog_fsmc, wr_req_tog_fsmc;
    reg [1:0] rd_req_tog_sync, wr_req_tog_sync;

    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            rd_req_tog_sync <= 2'b00;
            wr_req_tog_sync <= 2'b00;
        end else begin
            rd_req_tog_sync <= {rd_req_tog_sync[0], rd_req_tog_fsmc};
            wr_req_tog_sync <= {wr_req_tog_sync[0], wr_req_tog_fsmc};
        end
    end

    // ---- Completion: sys_clk single-cycle data_valid -> toggle -> fsmc_clk edge-detect ----
    wire        psram_data_valid;
    wire [15:0] psram_data_out;
    wire        psram_fifo_full;
    wire        psram_fifo_empty;

    reg data_valid_tog_sysclk;
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n)
            data_valid_tog_sysclk <= 1'b0;
        else if (psram_data_valid)
            data_valid_tog_sysclk <= ~data_valid_tog_sysclk;
    end

    reg [1:0] data_valid_tog_sync_fsmc;
    reg       data_valid_tog_sync_fsmc_prev;
    reg       fifo_empty_sync1, fifo_empty_sync2;

    always @(posedge fsmc_clk or negedge reset_n) begin
        if (!reset_n) begin
            data_valid_tog_sync_fsmc      <= 2'b00;
            data_valid_tog_sync_fsmc_prev <= 1'b0;
            fifo_empty_sync1               <= 1'b1;  // assume empty at reset - it genuinely is,
            fifo_empty_sync2               <= 1'b1;  // and "not empty" is the unsafe default here
        end else begin
            data_valid_tog_sync_fsmc      <= {data_valid_tog_sync_fsmc[0], data_valid_tog_sysclk};
            data_valid_tog_sync_fsmc_prev <= data_valid_tog_sync_fsmc[1];
            fifo_empty_sync1               <= psram_fifo_empty;
            fifo_empty_sync2               <= fifo_empty_sync1;
        end
    end

    // A rising or falling edge on the synchronized toggle both count as
    // "one completion happened" - that's all a toggle signal needs.
    wire data_valid_edge_fsmc = (data_valid_tog_sync_fsmc[1] != data_valid_tog_sync_fsmc_prev);
    wire fifo_empty_fsmc      = fifo_empty_sync2;

    // =================================================================
    // WRITE path: accumulate 4 nibbles, push to the FIFO on address 0x3
    // =================================================================
    reg [15:0] wr_accum;

    always @(posedge fsmc_nwe or negedge reset_n) begin
        if (!reset_n) begin
            wr_accum        <= 16'h0000;
            wr_req_tog_fsmc <= 1'b0;
        end else if (~fsmc_ne) begin
            case (burst_start_addr[1:0])
                2'd0: wr_accum[3:0]   <= fsmc_ad;
                2'd1: wr_accum[7:4]   <= fsmc_ad;
                2'd2: wr_accum[11:8]  <= fsmc_ad;
                2'd3: begin
                    wr_accum[15:12] <= fsmc_ad;
                    // Push the completed word. wr_accum[11:0] already holds
                    // the previous three nibbles by now; this nonblocking
                    // update of wr_accum[15:12] settles well before the
                    // multi-cycle CDC synchronizer above lets psram_fifo
                    // actually sample wr_accum, so the full 16-bit value
                    // is guaranteed correct by the time it's latched.
                    wr_req_tog_fsmc <= ~wr_req_tog_fsmc;
                end
            endcase
        end
    end

    // =================================================================
    // READ path: burst-read FSM, clocked by FSMC_CLK
    // =================================================================
    localparam ST_IDLE      = 2'd0,
               ST_LATENCY   = 2'd1,
               ST_WAIT_POP  = 2'd2,
               ST_STREAM    = 2'd3;

    reg  [1:0]  state;
    reg  [3:0]  cur_addr;
    reg  [7:0]  lat_cnt;
    reg  [31:0] wait_cnt;
    reg  [15:0] rd_holding;

    wire read_selected = (~fsmc_ne) & (~fsmc_noe);

    initial begin
        state            = ST_IDLE;
        cur_addr         = 4'h0;
        lat_cnt          = 8'h00;
        wait_cnt         = 32'h0;
        rd_holding       = 16'h0000;
        burst_start_addr = 4'h0;
        latch_addr       = 4'h0;
    end

    always @(posedge fsmc_clk or posedge fsmc_ne or negedge reset_n) begin
        if (!reset_n) begin
            state           <= ST_IDLE;
            cur_addr        <= 4'h0;
            lat_cnt         <= 8'h0;
            wait_cnt        <= 32'h0;
            rd_holding      <= 16'h0000;
            rd_req_tog_fsmc <= 1'b0;
        end else if (fsmc_ne) begin
            state <= ST_IDLE;
        end else if (!fsmc_noe) begin
            case (state)
                ST_IDLE: begin
                    cur_addr <= burst_start_addr;
                    if (burst_start_addr == 4'd0) begin
                        if (fifo_empty_fsmc) begin
                            // nothing to pop - don't stall, just replay stale rd_holding
                            state <= ST_STREAM;
                        end else begin
                            rd_req_tog_fsmc <= ~rd_req_tog_fsmc;  // trigger a pop
                            wait_cnt        <= 32'd0;
                            state           <= ST_WAIT_POP;
                        end
                    end else begin
                        if (LATENCY_CYCLES <= 1) begin
                            state <= ST_STREAM;
                        end else begin
                            lat_cnt <= LATENCY_CYCLES - 1;
                            state   <= ST_LATENCY;
                        end
                    end
                end
                ST_LATENCY: begin
                    if (lat_cnt <= 8'd1)
                        state <= ST_STREAM;
                    else
                        lat_cnt <= lat_cnt - 8'd1;
                end
                ST_WAIT_POP: begin
                    if (data_valid_edge_fsmc) begin
                        rd_holding <= psram_data_out;
                        state      <= ST_STREAM;
                    end else if (wait_cnt >= MAX_WAIT_CYCLES) begin
                        // safety net only - should not trigger in normal operation
                        state <= ST_STREAM;
                    end else begin
                        wait_cnt <= wait_cnt + 32'd1;
                    end
                end
                ST_STREAM: begin
                    cur_addr <= cur_addr + 4'd1;  // wraps; only [1:0] is meaningful
                end
                default: state <= ST_IDLE;
            endcase
        end else begin
            state <= ST_IDLE;  // NOE released -> access ends
        end
    end

    // ---------------------------------------------------------------
    // One-cycle-ahead prediction of the FSM's next state - needed for
    // "before wait state" NWAIT timing. Mirrors the case statement
    // above exactly (same conditions, purely combinational).
    // ---------------------------------------------------------------
    reg [1:0] next_state;
    always @(*) begin
        if (fsmc_ne || fsmc_noe) begin
            next_state = ST_IDLE;
        end else begin
            case (state)
                ST_IDLE: begin
                    if (burst_start_addr == 4'd0) begin
                        next_state = fifo_empty_fsmc ? ST_STREAM : ST_WAIT_POP;
                    end else begin
                        next_state = (LATENCY_CYCLES <= 1) ? ST_STREAM : ST_LATENCY;
                    end
                end
                ST_LATENCY:  next_state = (lat_cnt <= 8'd1) ? ST_STREAM : ST_LATENCY;
                ST_WAIT_POP: next_state = (data_valid_edge_fsmc || (wait_cnt >= MAX_WAIT_CYCLES))
                                          ? ST_STREAM : ST_WAIT_POP;
                ST_STREAM:   next_state = ST_STREAM;
                default:     next_state = ST_IDLE;
            endcase
        end
    end

    // ---------------------------------------------------------------
    // Select which nibble of rd_holding to present (address mod 4)
    // ---------------------------------------------------------------
    function [3:0] select_nibble;
        input [15:0] word;
        input [1:0]  sel;
        begin
            case (sel)
                2'd0: select_nibble = word[3:0];
                2'd1: select_nibble = word[7:4];
                2'd2: select_nibble = word[11:8];
                default: select_nibble = word[15:12];
            endcase
        end
    endfunction

    // ---------------------------------------------------------------
    // Drive AD bus with a holding-register nibble only while streaming
    // ---------------------------------------------------------------
    assign #(ACCESS_DELAY) fsmc_ad =
        (read_selected && state == ST_STREAM) ? select_nibble(rd_holding, cur_addr[1:0]) : 4'bz;

    // ---------------------------------------------------------------
    // NWAIT: "please wait" while not yet streaming; reports either the
    // current cycle (state) or the next one (next_state), per
    // WAIT_TIMING_BEFORE_WS.
    // ---------------------------------------------------------------
    wire [1:0] wait_ref_state = WAIT_TIMING_BEFORE_WS ? next_state : state;
    wire wait_needed = read_selected && (wait_ref_state != ST_STREAM);
    assign #(ACCESS_DELAY) fsmc_nwait =
        WAIT_ACTIVE_LOW ? (wait_needed ? 1'b0 : 1'b1)
                        : (wait_needed ? 1'b1 : 1'b0);

    // =================================================================
    // PSRAM FIFO instance (nADC fixed at 1 - one 16-bit word per entry,
    // matching the four-nibble-address scheme implemented above)
    // =================================================================
    PSRAM #(
        .nADC        (1),
        .CLK_DIV     (PSRAM_CLK_DIV),
        .SYS_CLK_MHZ (PSRAM_SYS_CLK_MHZ),
        .FIFO_DEPTH  (PSRAM_FIFO_DEPTH)
    ) u_psram_fifo (
        .sys_clk     (sys_clk),
        .reset_n     (reset_n),
        .data_in     (wr_accum),
        .wr_toggle   (wr_req_tog_sync[1]),
        .rd_toggle   (rd_req_tog_sync[1]),
        .data_out    (psram_data_out),
        .data_valid  (psram_data_valid),
        .fifo_full   (psram_fifo_full),
        .fifo_empty  (psram_fifo_empty),
        .psram_sclk  (psram_sclk),
        .psram_ce_n  (psram_ce_n),
        .psram_si    (psram_si),
        .psram_so    (psram_so)
    );

endmodule