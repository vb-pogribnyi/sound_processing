// =====================================================================
// fsmc_muxed_burst_psram.v
//
// Emulates an external memory device on the STM32F407 FSMC bus,
// configured in CubeMX as:
//
//      Memory type          : PSRAM
//      Memory data width    : 8 bits
//      Data/Address mux     : Enable
//      Burst access mode    : Enable
//      Wait signal          : Enable   (FSMC_NWAIT used for burst handshake,
//                                       FSMC_NL / NADV for address-valid)
//
// Only FSMC_AD[7:0] is physically connected — no separate FSMC_A lines.
// The 8-bit address is fully carried on the muxed AD bus.
//
// STM32F407 pin              this module's port
// -------------------------  -----------------------
// FSMC_AD[7:0]               fsmc_ad   (address during NADV phase, data otherwise)
// FSMC_NE1                   fsmc_ne
// FSMC_NL  (NADV)            fsmc_nadv
// FSMC_NOE                   fsmc_noe
// FSMC_NWE                   fsmc_nwe
// FSMC_CLK                   fsmc_clk
// FSMC_NWAIT                 fsmc_nwait
//
// -----------------------------------------------------------------------
// Bus protocol
// -----------------------------------------------------------------------
// WRITE (always asynchronous on F4, even when burst reads are enabled):
//
//   NE   \_____________________________________________/
//   NADV \______/
//   AD    ==addr[7:0]==><========= write data =========>
//   NWE           \_______________________/
//                                         ^-- data captured here (discarded)
//
// BURST READ (one address phase, then data clocked on FSMC_CLK with NWAIT):
//
//   NE    \_____________________________________________________________/
//   NADV  \______/
//   AD     ==addr[7:0]==><-- driven by THIS module from here on -------->
//   NOE           \_________________________________________________/
//   CLK     ______/^^\__/^^\__/^^\__/^^\__/^^\__/^^\__/^^\__/^^\______
//   NWAIT  ____________/‾‾‾‾‾‾‾‾‾‾‾‾‾\__________________________________
//                        |<- latency ->| each CLK edge after this = 1 byte
//          (active HIGH = "wait" - matches STM32F405/407 errata ES0182
//           sec. 2.3.2, which requires WAITPOL=1 / active-high NWAIT)
//
// A single (non-burst) read is the degenerate case: NE/NOE released after
// the first data beat.
//
// -----------------------------------------------------------------------
// Emulated content
// -----------------------------------------------------------------------
// For any 8-bit address A, the device returns the byte formed by swapping
// its two nibbles, e.g.:
//      A = 0xAB  ->  data = 0xBA
//      A = 0xCD  ->  data = 0xDC
// During a burst, address auto-increments by 1 each clock beat (wraps
// at 0xFF -> 0x00), and the formula is recomputed fresh each beat.
//
// Writes are accepted with correct bus timing but do not change the
// read-back pattern -- this is a pattern generator, not real storage.
//
// NOTE: simulation-only behavioral model (transparent latch, #delay
// continuous assigns) -- not synthesisable.
// =====================================================================

module FSMC #(
    parameter LATENCY_CYCLES  = 2,  // FSMC_CLK wait cycles before first burst byte (min 1)
    parameter WAIT_ACTIVE_LOW = 0,  // NWAIT polarity. Default 0 (active HIGH) to match the
                                     // STM32F405/407 errata workaround (ES0182 sec. 2.3.2):
                                     // WAITPOL must be set to 1 (active high) or the real MCU
                                     // can hang in synchronous/burst mode with no fault raised.
                                     // Set to 1 only if you have a documented reason to use
                                     // active-low polarity on your specific part/revision.
    parameter ACCESS_DELAY    = 5,  // ns internal delay on fsmc_ad / fsmc_nwait outputs
    parameter WAIT_TIMING_BEFORE_WS = 1
                                     // 1 = NWAIT reports, one FSMC_CLK cycle in ADVANCE,
                                     //     whether the *upcoming* cycle is a wait cycle
                                     //     (matches HAL's FMC_WAIT_TIMING_BEFORE_WS).
                                     // 0 = NWAIT reports the *current* cycle's status
                                     //     (matches FMC_WAIT_TIMING_DURING_WS).
                                     // Must match whatever WaitSignalActive is set to
                                     // in CubeMX/HAL, or the latency accounting will be
                                     // off by one cycle and reads will return garbage.
)(
    inout  wire [3:0] fsmc_ad,    // muxed address / data bus
    input  wire       fsmc_ne,    // chip select, active low
    input  wire       fsmc_nadv,  // address valid (FSMC_NL / NADV), active low
    input  wire       fsmc_noe,   // read enable, active low
    input  wire       fsmc_nwe,   // write enable, active low
    input  wire       fsmc_clk,   // synchronous burst clock
    output wire       fsmc_nwait  // wait signal, polarity per WAIT_ACTIVE_LOW
);

    // ---------------------------------------------------------------
    // Pattern: swap the two nibbles of the 8-bit address
    // ---------------------------------------------------------------
    function [7:0] swap_nibbles;
        input [7:0] a;
        begin
            // swap_nibbles = {a[3:0], a[7:4]};
            swap_nibbles = {a[3:0], a[1:0], a[3:2]};
            // swap_nibbles = 8'h06;
        end
    endfunction

    // ---------------------------------------------------------------
    // Address phase: transparent latch while NADV is low; frozen on
    // the rising edge of NADV (= address-valid window closes)
    // ---------------------------------------------------------------
    reg [7:0] latch_addr;

    always @(*) begin
        if (!fsmc_nadv)
            latch_addr[3:0] = fsmc_ad[3:0];
    end

    reg [7:0] burst_start_addr;

    always @(posedge fsmc_nadv) begin
        burst_start_addr <= latch_addr;
    end

    // ---------------------------------------------------------------
    // Burst-read FSM, clocked by FSMC_CLK; async reset on NE high
    // ---------------------------------------------------------------
    localparam ST_IDLE    = 2'd0,
               ST_LATENCY = 2'd1,
               ST_STREAM  = 2'd2;

    reg [1:0] state;
    reg [7:0] cur_addr;
    reg [7:0] lat_cnt;

    wire read_selected = (~fsmc_ne) & (~fsmc_noe);

    initial begin
        state            = ST_IDLE;
        cur_addr         = 8'h00;
        lat_cnt          = 8'h00;
        burst_start_addr = 8'h00;
        latch_addr       = 8'h00;
    end

    always @(posedge fsmc_clk or posedge fsmc_ne) begin
        if (fsmc_ne) begin
            state <= ST_IDLE;
        end else if (!fsmc_noe) begin
            case (state)
                ST_IDLE: begin
                    cur_addr <= burst_start_addr;
                    if (LATENCY_CYCLES <= 1) begin
                        state <= ST_STREAM;
                    end else begin
                        lat_cnt <= LATENCY_CYCLES - 1;
                        state   <= ST_LATENCY;
                    end
                end
                ST_LATENCY: begin
                    if (lat_cnt <= 8'd1)
                        state <= ST_STREAM;
                    else
                        lat_cnt <= lat_cnt - 8'd1;
                end
                ST_STREAM: begin
                    cur_addr <= cur_addr + 8'd1;  // wraps 0xFF -> 0x00
                end
                default: state <= ST_IDLE;
            endcase
        end else begin
            state <= ST_IDLE;  // NOE released -> burst ends
        end
    end

    // ---------------------------------------------------------------
    // One-cycle-ahead prediction of the FSM's next state. Needed for
    // "before wait state" NWAIT timing: the memory must report, during
    // the CURRENT cycle, whether the *next* cycle will still be a wait
    // cycle - not whether the current one is. This mirrors the case
    // statement above purely combinationally (same inputs, no clock),
    // so it always reflects what the registered FSM is about to become
    // at the next clock edge.
    // ---------------------------------------------------------------
    reg [1:0] next_state;
    always @(*) begin
        if (fsmc_ne || fsmc_noe) begin
            next_state = ST_IDLE;
        end else begin
            case (state)
                ST_IDLE:    next_state = (LATENCY_CYCLES <= 1) ? ST_STREAM : ST_LATENCY;
                ST_LATENCY: next_state = (lat_cnt <= 8'd1) ? ST_STREAM : ST_LATENCY;
                ST_STREAM:  next_state = ST_STREAM;
                default:    next_state = ST_IDLE;
            endcase
        end
    end

    // ---------------------------------------------------------------
    // Drive AD bus with pattern data only while streaming valid bytes
    // ---------------------------------------------------------------
    assign #(ACCESS_DELAY) fsmc_ad =
        (read_selected && state == ST_STREAM) ? swap_nibbles(cur_addr) : 8'bz;

    // ---------------------------------------------------------------
    // NWAIT: "please wait" during latency, deasserted once ready.
    // Reports either the current cycle (state) or the next one
    // (next_state), per WAIT_TIMING_BEFORE_WS.
    // ---------------------------------------------------------------
    wire [1:0] wait_ref_state = WAIT_TIMING_BEFORE_WS ? next_state : state;
    wire wait_needed = read_selected && (wait_ref_state != ST_STREAM);
    assign #(ACCESS_DELAY) fsmc_nwait =
        WAIT_ACTIVE_LOW ? (wait_needed ? 1'b0 : 1'b1)
                        : (wait_needed ? 1'b1 : 1'b0);

    // ---------------------------------------------------------------
    // Write path: bus-timing realism only; pattern never changes
    // ---------------------------------------------------------------
    always @(posedge fsmc_nwe) begin
        if (~fsmc_ne)
            $display("[%0t ns] %m: WRITE addr=0x%02h data=0x%02h (ignored)",
                     $time, burst_start_addr, fsmc_ad);
    end

endmodule