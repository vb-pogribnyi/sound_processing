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
// Address map (4-bit space; one entry = 16*NUM_ADC bits = 4*NUM_ADC nibbles)
// -----------------------------------------------------------------------
//   For NUM_ADC=2 (entry = 32 bits = 8 nibbles):
//   addr        read                              write
//   ---------   -------------------------------   -----------------------
//   0x0-0x7     FIFO entry, nibble 0..7           0x0-0x3: debug write
//   0xB-0xE     live selected-channel value (16b) -
//   0xF         status nibble                     adc_sel (live channel)
//
//   Status nibble: bit0=fifo_empty, bit1=fifo_full, bit2=is_valid,
//                  bit3=data_ready (a prefetched entry is waiting).
//
// PRIMARY DATA SOURCE: the MCP3461 ADC pushes each completed multi-channel
// sample into the FIFO automatically (adc_value/adc_rdy). STM32 writes to
// 0x0-0x3 remain only as a debug path.
//
// READ: the FIFO entry is PREFETCHED into a holding register by a small
// engine in the free-running sys_clk domain (see "PREFETCH engine"). A read
// of address 0x0 does NOT wait for a SPI round-trip - the entry is already
// local, so it streams with only the short bounded LATENCY_CYCLES delay and
// signals the engine to fetch the next entry. Addresses 0x1..ENTRY_NIBS-1
// replay the remaining nibbles. The live value (0xB-0xE) and status (0xF)
// are always available and never stall.
//
// WHY prefetch instead of stalling: FSMC_CLK is GATED - it only toggles
// during an active access, and on real silicon it does NOT advance while
// the FPGA holds NWAIT asserted. An earlier design stalled at address
// 0x0 (NWAIT) for the whole SPI round-trip; that DEADLOCKED the STM32
// (the FSM that releases NWAIT is clocked by the very clock the STM32
// stops). Prefetching removes the long stall entirely.
//
// FIRMWARE CONTRACT (buffered read): poll status (0xF) bit3 (data-ready)
// before reading each entry, then read 0x0..(4*NUM_ADC-1). The live value
// (0xB-0xE) needs no poll: write the channel index to 0xF once, then read
// 0xB-0xE as often as wanted. Example (NUM_ADC=2):
//     while (!(*(volatile uint8_t*)(BASE+0xF) & 0x8)) { }  // wait ready
//     for (n=0;n<8;n++) word[n>>2] |= (BASE[n]&0xF) << (4*(n&3));
//
// -----------------------------------------------------------------------
// Limitations / things to be aware of
// -----------------------------------------------------------------------
//  - If firmware reads address 0x0 without a prefetched entry ready
//    (data-ready=0), the module returns stale rd_holding rather than
//    stalling. Always poll data-ready (status bit3) first.
//  - If the FIFO is full when a sample arrives, the push is silently
//    dropped (status fifo_full bit reports it).
//  - NUM_ADC must be small enough that the entry (addr 0..4*NUM_ADC-1)
//    does not overlap the control regions (live 0xB-0xE, status 0xF). With
//    only AD[3:0] routed that means NUM_ADC<=2. Wiring AD[7:4] (8-bit
//    address) would allow more channels with the control regs moved up.
//
// NOTE: ACCESS_DELAY/#-delay statements are simulation-only modelling
// aids - not synthesisable as-is; replace/remove for real synthesis if
// your toolchain rejects delay-controlled continuous assignments.
// =====================================================================

module FSMC #(
    parameter LATENCY_CYCLES  = 2,  // FSMC_CLK wait cycles before streaming a nibble
                                     // (applies to all reads: prefetched word at 0x0,
                                     //  cached nibbles 0x1-0x3, and status at 0x4)
    parameter WAIT_ACTIVE_LOW = 0,  // NWAIT polarity. Default 0 (active HIGH) per the
                                     // STM32F405/407 errata workaround (ES0182 sec. 2.3.2).
    parameter ACCESS_DELAY    = 5,  // ns internal delay on fsmc_ad / fsmc_nwait outputs (sim only)
    parameter WAIT_TIMING_BEFORE_WS = 1,
                                     // 1 = NWAIT reports the *upcoming* cycle's status
                                     //     (HAL's FMC_WAIT_TIMING_BEFORE_WS).
                                     // 0 = NWAIT reports the *current* cycle's status
                                     //     (FMC_WAIT_TIMING_DURING_WS).
    parameter NUM_ADC = 2,          // ADC channels per FIFO entry. One entry =
                                     // 16*NUM_ADC bits = 4*NUM_ADC nibbles. With only
                                     // AD[3:0] routed (4-bit address) NUM_ADC<=2 so the
                                     // entry (addr 0..4*NUM_ADC-1) leaves room for the
                                     // control registers at the top of the 4-bit space.
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

    // ---- ADC sample source (sys_clk domain, from MCP3461Master) ----
    input  wire [16*NUM_ADC-1:0] adc_value,  // concatenated 16-bit channels
    input  wire                  adc_rdy,    // pulses high when a fresh sample set is ready

    // ---- APS6404L QSPI PSRAM pins (passed straight through) ----
    output wire        psram_sclk,
    output wire        psram_ce_n,
    inout  wire [3:0]  psram_sio,   // SIO[3:0] bidirectional — matches IC pins

    // ---- status ----
    output wire        psram_is_valid  // 1 after PSRAM self-test passes
);

    // ---- derived sizes ----
    localparam ENTRY_BITS = 16 * NUM_ADC;   // bits per FIFO entry (32 for NUM_ADC=2)
    localparam ENTRY_NIBS = 4  * NUM_ADC;   // read nibbles per entry (8 for NUM_ADC=2)
    // Address map (4-bit space, AD[3:0]):
    //   0 .. ENTRY_NIBS-1 : FIFO entry nibbles (read) / debug write (0..3)
    //   LIVE_BASE..+3     : live selected-channel value (16b / 4 nibbles)
    //   STAT_ADDR         : status (read) / adc_sel (write)
    localparam [3:0] LIVE_BASE = 4'd11;     // live value at 11,12,13,14
    localparam [3:0] STAT_ADDR = 4'd15;     // status (read) / adc_sel (write)

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

    // ---- STM32 debug write request: fsmc_nwe -> sys_clk, toggle-style ----
    reg       wr_req_tog_fsmc;
    reg [1:0] wr_req_tog_sync;
    reg       wr_req_tog_sync_prev;

    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            wr_req_tog_sync      <= 2'b00;
            wr_req_tog_sync_prev <= 1'b0;
        end else begin
            wr_req_tog_sync      <= {wr_req_tog_sync[0], wr_req_tog_fsmc};
            wr_req_tog_sync_prev <= wr_req_tog_sync[1];
        end
    end
    wire stm_wr_edge = (wr_req_tog_sync[1] != wr_req_tog_sync_prev);

    wire                  psram_data_valid;
    wire [ENTRY_BITS-1:0] psram_data_out;
    wire                  psram_fifo_full;
    wire                  psram_fifo_empty;
    wire                  psram_valid_int;
    assign psram_is_valid = psram_valid_int;

    // ---- adc_sel (written by FSMC at STAT_ADDR) synchronized into sys_clk ----
    reg [3:0] adc_sel;                       // fsmc_nwe domain (write decode below)
    reg [3:0] adc_sel_sync1, adc_sel_sync2;
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            adc_sel_sync1 <= 4'h0;
            adc_sel_sync2 <= 4'h0;
        end else begin
            adc_sel_sync1 <= adc_sel;
            adc_sel_sync2 <= adc_sel_sync1;
        end
    end

    // =================================================================
    // sys_clk WRITE ARBITER + live-value register
    //
    // Two write sources feed the single PSRAM write port:
    //   * ADC samples (adc_rdy pulse, data = adc_value) - the real source
    //   * STM32 debug writes (stm_wr_edge, data = wr_accum) - occasional
    // ADC has priority; on a same-cycle collision the debug write is
    // dropped (acceptable for a manual debug path). Both psram_wr_toggle
    // and psram_wr_data are sys_clk - same domain as PSRAM, no CDC.
    //
    // live_val tracks the adc_sel-selected channel, refreshed every
    // adc_rdy, and is read back (untouched by the FIFO) at LIVE_BASE..+3.
    // =================================================================
    reg                  psram_wr_toggle;
    reg [ENTRY_BITS-1:0] psram_wr_data;
    reg [15:0]           live_val;
    reg                  adc_rdy_d;
    wire                 adc_rdy_edge = adc_rdy & ~adc_rdy_d;

    integer ch;
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            psram_wr_toggle <= 1'b0;
            psram_wr_data   <= {ENTRY_BITS{1'b0}};
            live_val        <= 16'h0000;
            adc_rdy_d       <= 1'b0;
        end else begin
            adc_rdy_d <= adc_rdy;

            if (adc_rdy_edge) begin
                // push the full multi-channel sample, refresh live value
                psram_wr_data   <= adc_value;
                psram_wr_toggle <= ~psram_wr_toggle;
                for (ch = 0; ch < NUM_ADC; ch = ch + 1)
                    if (adc_sel_sync2 == ch)
                        live_val <= adc_value[16*ch +: 16];
            end else if (stm_wr_edge) begin
                // debug: low 16 bits = the word the STM32 assembled, rest 0
                psram_wr_data   <= {{(ENTRY_BITS-16){1'b0}}, wr_accum};
                psram_wr_toggle <= ~psram_wr_toggle;
            end
        end
    end

    // =================================================================
    // PREFETCH engine (sys_clk domain - always running)
    //
    // FSMC_CLK is GATED: it only toggles while an FSMC access is in
    // flight, and (confirmed on hardware) it does NOT advance while the
    // FPGA holds NWAIT asserted. So a read must never depend on an
    // unbounded NWAIT stall that only an fsmc_clk edge can release - that
    // path deadlocks (FSM stuck in a wait state, NWAIT held, CPU frozen).
    //
    // Instead we pop the FIFO EAGERLY here, in the free-running sys_clk
    // domain, into a one-word holding register (pf_data). By the time
    // firmware reads address 0 the word is already present, so the read
    // takes only the short, bounded LATENCY path (proven to work) and
    // never the long stall.
    //
    // Handshake:
    //   pf_valid    : a prefetched word sits in pf_data, not yet consumed
    //   pf_inflight : a pop has been issued, waiting on psram_data_valid
    //   pf_rd_toggle: drives PSRAM.rd_toggle (same domain - no CDC needed)
    //   consume     : the FSMC read FSM toggles rd_consume_tog_fsmc when it
    //                 takes the word; edge-detected here to fetch the next.
    //
    // Firmware contract: poll the status register (address 0x4, bit3 =
    // data-ready = pf_valid) before reading each word. Polling both paces
    // the reads to prefetch availability AND keeps the fsmc-side
    // synchronizer of pf_valid fresh across the gated clock.
    // =================================================================
    reg [ENTRY_BITS-1:0] pf_data;
    reg        pf_valid;
    reg        pf_inflight;
    reg        pf_rd_toggle;

    reg  [1:0] consume_tog_sync;
    reg        consume_tog_sync_prev;
    wire       consume_edge_sys = (consume_tog_sync[1] != consume_tog_sync_prev);

    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            pf_data               <= {ENTRY_BITS{1'b0}};
            pf_valid              <= 1'b0;
            pf_inflight           <= 1'b0;
            pf_rd_toggle          <= 1'b0;
            consume_tog_sync      <= 2'b00;
            consume_tog_sync_prev <= 1'b0;
        end else begin
            consume_tog_sync      <= {consume_tog_sync[0], rd_consume_tog_fsmc};
            consume_tog_sync_prev <= consume_tog_sync[1];

            if (pf_inflight && psram_data_valid) begin
                pf_data     <= psram_data_out;      // pop landed -> word ready
                pf_valid    <= 1'b1;
                pf_inflight <= 1'b0;
            end else begin
                if (pf_valid && consume_edge_sys)
                    pf_valid <= 1'b0;               // FSMC took the word
                // Issue the next pop one cycle after the slot frees. Uses the
                // registered pf_valid, so a fresh consume this cycle defers the
                // pop to next cycle - harmless.
                if (!pf_valid && !pf_inflight && !psram_fifo_empty) begin
                    pf_rd_toggle <= ~pf_rd_toggle;
                    pf_inflight  <= 1'b1;
                end
            end
        end
    end

    // ---- fifo_empty / fifo_full / is_valid: sys_clk pre-register + single fsmc_clk FF ----
    // fsmc_clk is GATED - it only runs during burst reads. A pure 2-FF fsmc_clk synchronizer
    // would freeze at reset defaults (empty=1, valid=0) for the entire period between
    // transactions, causing the first read after any number of async writes to see a stale
    // "FIFO empty" and skip the pop. Fix: register these quasi-static signals in the always-
    // running sys_clk domain first so the value is current before the first fsmc_clk edge.
    reg fifo_empty_pre, fifo_full_pre, is_valid_pre;
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            fifo_empty_pre <= 1'b1;
            fifo_full_pre  <= 1'b0;
            is_valid_pre   <= 1'b0;
        end else begin
            fifo_empty_pre <= psram_fifo_empty;
            fifo_full_pre  <= psram_fifo_full;
            is_valid_pre   <= psram_valid_int;
        end
    end

    reg       fifo_empty_sync1;   // single fsmc_clk FF — source already sys_clk-stable
    reg       fifo_full_sync1;
    reg       is_valid_sync1;
    reg       pf_valid_sync1;     // data-ready (pf_valid) crossed into fsmc_clk

    always @(posedge fsmc_clk or negedge reset_n) begin
        if (!reset_n) begin
            fifo_empty_sync1 <= 1'b1;
            fifo_full_sync1  <= 1'b0;
            is_valid_sync1   <= 1'b0;
            pf_valid_sync1   <= 1'b0;
        end else begin
            fifo_empty_sync1 <= fifo_empty_pre;
            fifo_full_sync1  <= fifo_full_pre;
            is_valid_sync1   <= is_valid_pre;
            pf_valid_sync1   <= pf_valid;
        end
    end

    wire fifo_empty_fsmc = fifo_empty_sync1;
    wire fifo_full_fsmc  = fifo_full_sync1;
    wire is_valid_fsmc   = is_valid_sync1;
    wire pf_valid_fsmc   = pf_valid_sync1;

    // Status nibble @STAT_ADDR: bit0=fifo_empty, bit1=fifo_full, bit2=is_valid, bit3=data_ready
    wire [15:0] status_word = {12'b0, pf_valid_fsmc, is_valid_fsmc, fifo_full_fsmc, fifo_empty_fsmc};

    // =================================================================
    // WRITE path (fsmc_nwe domain)
    //   STAT_ADDR : write adc_sel (selected live channel)
    //   addr 0..3 : debug FIFO write - accumulate a 16-bit word, push on 0x3
    //               (pushed as the low word of an ENTRY_BITS entry, rest 0)
    // =================================================================
    reg [15:0] wr_accum;

    always @(posedge fsmc_nwe or negedge reset_n) begin
        if (!reset_n) begin
            wr_accum        <= 16'h0000;
            wr_req_tog_fsmc <= 1'b0;
            adc_sel         <= 4'h0;
        end else if (~fsmc_ne) begin
            if (burst_start_addr == STAT_ADDR) begin
                adc_sel <= fsmc_ad;                // select live channel
            end else if (burst_start_addr < 4'd4) begin
                case (burst_start_addr[1:0])
                    2'd0: wr_accum[3:0]   <= fsmc_ad;
                    2'd1: wr_accum[7:4]   <= fsmc_ad;
                    2'd2: wr_accum[11:8]  <= fsmc_ad;
                    2'd3: begin
                        wr_accum[15:12] <= fsmc_ad;
                        wr_req_tog_fsmc <= ~wr_req_tog_fsmc;  // push completed word
                    end
                endcase
            end
        end
    end

    // =================================================================
    // READ path: burst-read FSM, clocked by FSMC_CLK
    // =================================================================
    localparam ST_IDLE    = 2'd0,
               ST_LATENCY = 2'd1,
               ST_STREAM  = 2'd2;

    reg  [1:0]            state;
    reg  [3:0]            cur_addr;
    reg  [3:0]            nib_base;    // first FSMC address of the active region
    reg  [7:0]            lat_cnt;
    reg  [ENTRY_BITS-1:0] rd_holding;  // right-aligned: entry / live(16b) / status(nibble)
    reg                   rd_consume_tog_fsmc;   // toggled when a prefetched word is taken

    wire read_selected = (~fsmc_ne) & (~fsmc_noe);

    initial begin
        state               = ST_IDLE;
        cur_addr            = 4'h0;
        nib_base            = 4'h0;
        lat_cnt             = 8'h00;
        rd_holding          = {ENTRY_BITS{1'b0}};
        rd_consume_tog_fsmc = 1'b0;
        burst_start_addr    = 4'h0;
        latch_addr          = 4'h0;
    end

    always @(posedge fsmc_clk or posedge fsmc_ne or negedge reset_n) begin
        if (!reset_n) begin
            state               <= ST_IDLE;
            cur_addr            <= 4'h0;
            nib_base            <= 4'h0;
            lat_cnt             <= 8'h0;
            rd_holding          <= {ENTRY_BITS{1'b0}};
            rd_consume_tog_fsmc <= 1'b0;
        end else if (fsmc_ne) begin
            state <= ST_IDLE;
        end else if (!fsmc_noe) begin
            case (state)
                ST_IDLE: begin
                    cur_addr <= burst_start_addr;
                    // ---- region decode + load (only at a region's first address) ----
                    if (burst_start_addr < ENTRY_NIBS) begin
                        // FIFO entry region (0 .. ENTRY_NIBS-1)
                        nib_base <= 4'd0;
                        if (burst_start_addr == 4'd0 && pf_valid_fsmc) begin
                            // take the prefetched entry; addr 1.. just replay it
                            rd_holding          <= pf_data;
                            rd_consume_tog_fsmc <= ~rd_consume_tog_fsmc;  // fetch next
                        end
                    end else if (burst_start_addr >= LIVE_BASE &&
                                 burst_start_addr <  LIVE_BASE + 4'd4) begin
                        // live selected-channel value (16 bits, 4 nibbles)
                        nib_base <= LIVE_BASE;
                        if (burst_start_addr == LIVE_BASE)
                            rd_holding <= {{(ENTRY_BITS-16){1'b0}}, live_val};
                    end else if (burst_start_addr == STAT_ADDR) begin
                        // status nibble
                        nib_base   <= STAT_ADDR;
                        rd_holding <= {{(ENTRY_BITS-16){1'b0}}, status_word};
                    end else begin
                        // unused addresses - replay whatever is in rd_holding
                        nib_base <= 4'd0;
                    end
                    // uniform short bounded latency path (no long NWAIT stall)
                    if (LATENCY_CYCLES <= 1)
                        state <= ST_STREAM;
                    else begin
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
                    cur_addr <= cur_addr + 4'd1;  // advances through the region's nibbles
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
                    // every read region takes the short bounded LATENCY path
                    next_state = (LATENCY_CYCLES <= 1) ? ST_STREAM : ST_LATENCY;
                end
                ST_LATENCY:  next_state = (lat_cnt <= 8'd1) ? ST_STREAM : ST_LATENCY;
                ST_STREAM:   next_state = ST_STREAM;
                default:     next_state = ST_IDLE;
            endcase
        end
    end

    // ---------------------------------------------------------------
    // Select nibble `sel` (region-relative) of the ENTRY_BITS holding reg
    // ---------------------------------------------------------------
    function [3:0] select_nibble;
        input [ENTRY_BITS-1:0] word;
        input [2:0]            sel;     // 0 .. ENTRY_NIBS-1
        begin
            select_nibble = word[sel*4 +: 4];
        end
    endfunction

    // nibble index within the active region = absolute address - region base
    wire [3:0] nib_idx = cur_addr - nib_base;

    // ---------------------------------------------------------------
    // Drive AD bus with a holding-register nibble only while streaming
    // ---------------------------------------------------------------
    assign #(ACCESS_DELAY) fsmc_ad =
        (read_selected && state == ST_STREAM) ? select_nibble(rd_holding, nib_idx[2:0]) : 4'bz;

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
    // PSRAM FIFO instance - one ENTRY_BITS (16*NUM_ADC) word per entry.
    // Writes come from the sys_clk arbiter; reads from the prefetch engine.
    // =================================================================
    PSRAM #(
        .nADC        (NUM_ADC),
        .CLK_DIV     (PSRAM_CLK_DIV),
        .SYS_CLK_MHZ (PSRAM_SYS_CLK_MHZ),
        .FIFO_DEPTH  (PSRAM_FIFO_DEPTH)
    ) u_psram_fifo (
        .sys_clk     (sys_clk),
        .reset_n     (reset_n),
        .data_in     (psram_wr_data),       // arbiter: ADC sample or debug word
        .wr_toggle   (psram_wr_toggle),     // arbiter drives pushes (sys_clk)
        .rd_toggle   (pf_rd_toggle),        // prefetch engine drives pops (sys_clk)
        .data_out    (psram_data_out),
        .data_valid  (psram_data_valid),
        .fifo_full   (psram_fifo_full),
        .fifo_empty  (psram_fifo_empty),
        .is_valid    (psram_valid_int),
        .psram_sclk  (psram_sclk),
        .psram_ce_n  (psram_ce_n),
        .psram_sio   (psram_sio)
    );

endmodule