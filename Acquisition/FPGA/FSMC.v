// =====================================================================
// FSMC.v
//
// Bridges the STM32F407 FSMC bus (8-bit muxed PSRAM + burst read +
// address valid) to the psram_fifo FIFO controller (psram_fifo.v /
// PSRAM.v) backed by a real APS6404L QSPI PSRAM chip.
//
// PCB note: all 8 FSMC_AD[7:0] lines are now routed (the earlier board
// wired only AD[3:0]). The address space is byte-wide (0x00-0xFF) and
// every access transfers a full byte, so a 16-bit FIFO word is two
// bytes and one FIFO entry = 2*NUM_ADC bytes.
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
// Address map (8-bit byte space; one entry = 16*NUM_ADC bits = 2*NUM_ADC bytes)
// -----------------------------------------------------------------------
//   For NUM_ADC=32 (entry = 512 bits = 64 bytes):
//   addr          read                              write
//   -----------   -------------------------------   -----------------------
//   0x00-0x3F     FIFO entry, byte 0..63            0x00-0x01: debug write
//   0xFD-0xFE     live selected-channel value (16b) 0xFD: EFF ADC-count log2
//                                                   0xFE: acquisition control
//   0xFF          status byte                       adc_sel (live channel)
//
//   (0x09/0x0A camera averages: DISCARDED for now - the full image-reading
//    pipeline will be added later. The cam_red/cam_green inputs are still
//    synchronised internally but no longer decoded to an address.)
//
//   Status byte: bit0=fifo_empty, bit1=acq_full (STICKY - see below),
//                bit2=is_valid, bit3=data_ready (a prefetched entry waits).
//                (bit layout unchanged from the old 4-bit status nibble.)
//
//   Acquisition control (write 0xFE):
//     0x1 -> ARM: rewind PSRAM write pointer to 0, clear acq_full, enable
//                 ADC->FIFO capture.
//     0x0 -> STOP capture early (no sticky flag set).
//
// PRIMARY DATA SOURCE: the MCP3461 ADC pushes each completed multi-channel
// sample into the FIFO - but ONLY while an acquisition is armed. Capture is
// DISABLED by default out of reset; the STM32 arms it by writing 0x1 to 0xE.
// When the FIFO fills, capture stops automatically (unread data is NEVER
// overwritten) and acq_full (status bit1) latches high to tell the STM32 to
// drain the FIFO and re-arm. STM32 writes to 0x00-0x01 remain a debug path.
//
// READ: the FIFO entry is PREFETCHED into a holding register by a small
// engine in the free-running sys_clk domain (see "PREFETCH engine"). A read
// of address 0x00 does NOT wait for a SPI round-trip - the entry is already
// local, so it streams with only the short bounded LATENCY_CYCLES delay and
// signals the engine to fetch the next entry. Addresses 0x01..ENTRY_BYTES-1
// replay the remaining bytes. The live value (0xFD-0xFE) and status (0xFF)
// are always available and never stall.
//
// WHY prefetch instead of stalling: FSMC_CLK is GATED - it only toggles
// during an active access, and on real silicon it does NOT advance while
// the FPGA holds NWAIT asserted. An earlier design stalled at address
// 0x0 (NWAIT) for the whole SPI round-trip; that DEADLOCKED the STM32
// (the FSM that releases NWAIT is clocked by the very clock the STM32
// stops). Prefetching removes the long stall entirely.
//
// FIRMWARE CONTRACT (capture + drain):
//   0. Once, set the effective channel count: BASE[0xFD] = log2(EFF);   // 0->1,1->2,...,5->32
//   1. Once at startup, wait for self-test: while (!(BASE[0xFF] & 0x4)) {}  // is_valid
//   2. Arm the capture:     BASE[0xFE] = 0x1;                      // start polling
//   3. Drain entries as they arrive - reading may begin with the FIRST
//      sample; there is NO need to wait for the buffer to fill:
//        while (!(BASE[0xFF] & 0x8)) {}                            // data-ready (bit3)
//        for (n=0;n<2*EFF;n++) ((uint8_t*)word)[n] = BASE[n];      // 64 bytes for EFF=32
//      Optionally, a batch reader may instead wait for acq_full (bit1) - set
//      only if the FIFO fills before the STM32 keeps up - then drain in a
//      loop until the FIFO is empty (bit0).
//   4. Re-arm:              BASE[0xFE] = 0x1;                      // next capture
// Arming rewinds the PSRAM write pointer to 0 and clears acq_full; is_valid is
// NOT re-checked (it never clears once set), so a re-arm is immediate. The live
// value (0xFD-0xFE READ) needs no poll and is independent of capture: write the
// channel index to 0xFF once, then read 0xFD-0xFE anytime.
//
// -----------------------------------------------------------------------
// Limitations / things to be aware of
// -----------------------------------------------------------------------
//  - Capture is disabled out of reset; nothing is stored until the STM32
//    arms it (write 0x1 to 0xE). Re-arming after a full buffer DISCARDS any
//    entries the STM32 did not read - drain fully before re-arming.
//  - If firmware reads address 0x0 without a prefetched entry ready
//    (data-ready=0), the module returns stale rd_holding rather than
//    stalling. Always poll data-ready (status bit3) first.
//  - While a capture is armed, samples stop being pushed the moment the FIFO
//    is full; unread data is preserved (never overwritten) and acq_full
//    (status bit1) latches high until the next arm.
//  - NUM_ADC must be small enough that the entry (addr 0..2*NUM_ADC-1)
//    does not overlap the control regions (live 0xFD-0xFE, ctrl 0xFE,
//    status 0xFF). With the full 8-bit byte address that means the entry
//    must end below 0xFD, i.e. NUM_ADC<=126 - 32 fits comfortably.
//
// NOTE: ACCESS_DELAY/#-delay statements are simulation-only modelling
// aids - not synthesisable as-is; replace/remove for real synthesis if
// your toolchain rejects delay-controlled continuous assignments.
// =====================================================================

`timescale 1ns/1ps

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
    parameter NUM_ADC = 16,         // ADC channels per FIFO entry. One entry =
                                     // 16*NUM_ADC bits = 2*NUM_ADC bytes. With the full
                                     // 8-bit byte address the entry (addr 0..2*NUM_ADC-1)
                                     // sits below the control registers at 0xFD-0xFF.
    // Pass-through parameters for the instantiated psram_fifo
    parameter PSRAM_CLK_DIV     = 1,
    parameter PSRAM_SYS_CLK_MHZ = 50,
    parameter PSRAM_FIFO_DEPTH  = 256
)(
    // ---- FSMC bus (from STM32) ----
    inout  wire [7:0] fsmc_ad,    // muxed address / data bus (all 8 lines routed)
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

    // ---- camera frame averages (sys_clk domain, from OV5640) ----
    //   quasi-static: updated once per camera frame. Synchronised internally but
    //   NOT currently decoded to an address (discarded until the full image-read
    //   pipeline lands; the old 0x9/0x0A nibble reads are gone).
    input  wire [3:0]            cam_red,    // 4-bit average red   (reserved)
    input  wire [3:0]            cam_green,  // 4-bit average green (reserved)

    // ---- APS6404L QSPI PSRAM pins (passed straight through) ----
    output wire        psram_sclk,
    output wire        psram_ce_n,
    inout  wire [3:0]  psram_sio,   // SIO[3:0] bidirectional — matches IC pins

    // ---- status ----
    output wire        psram_is_valid, // 1 after PSRAM self-test passes

    // ---- effective ADC count + ADC address-ack validity ----
    input  wire        i_adc_valid,    // combined is_valid across EFF active ADCs (i_CLK50 domain)
    output wire [2:0]  o_num_adc_log2  // EFF = 1<<this; STM32 writes it at 0xD (feeds MCP3461Master)
);

    // ---- derived sizes ----
    localparam ENTRY_BITS  = 16 * NUM_ADC;  // bits per FIFO entry  (512 for NUM_ADC=32)
    localparam ENTRY_BYTES = 2  * NUM_ADC;  // bytes per stored entry (64 for NUM_ADC=32)
    // With all 8 AD lines routed the whole entry fits below the control regs
    // (0xFD-0xFF), so the full entry is readable: 0x00 .. ENTRY_BYTES-1.
    localparam READ_ENTRY_BYTES = ENTRY_BYTES;
    // Address map (8-bit byte space, AD[7:0]):
    //   0x00 .. ENTRY_BYTES-1 : FIFO entry bytes (read) / debug write (0x00..0x01)
    //   LIVE_BASE(0xFD)..+1   : live selected-channel value (16b / 2 bytes, read)
    //   NUMADC_ADDR(0xFD)     : effective ADC count log2 (WRITE only; read 0xFD = live low byte)
    //   CTRL_ADDR(0xFE)       : acquisition control (write: 0x1=arm, 0x0=stop)
    //   STAT_ADDR(0xFF)       : status byte (read) / adc_sel (write)
    localparam [7:0] LIVE_BASE   = 8'hFD;   // live value at 0xFD,0xFE (read)
    localparam [7:0] CTRL_ADDR   = 8'hFE;   // acquisition control (write): 0x1=arm, 0x0=stop
    localparam [7:0] STAT_ADDR   = 8'hFF;   // status (read) / adc_sel (write)
    localparam [7:0] NUMADC_ADDR = 8'hFD;   // effective ADC count log2 (WRITE only; read 0xFD = live low byte)

    // ---------------------------------------------------------------
    // Address phase: transparent latch while NADV is low; frozen on
    // the rising edge of NADV. All 8 address lines are routed.
    // ---------------------------------------------------------------
    reg [7:0] latch_addr;

    always @(*) begin
        if (!fsmc_nadv)
            latch_addr = fsmc_ad;
    end

    reg [7:0] burst_start_addr;

    always @(posedge fsmc_nadv or negedge reset_n) begin
        if (!reset_n)
            burst_start_addr <= 8'h00;
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

    // ---- Two fsmc_nwe->sys_clk crossings share one synchronizer block ----
    //   * adc_sel        (STAT_ADDR write) : plain 2-FF value sync
    //   * acquisition cmd (CTRL_ADDR write): toggle (edge=new cmd) + data bit
    reg [7:0] adc_sel;                       // fsmc_nwe domain (write decode below)
    reg [7:0] adc_sel_sync1, adc_sel_sync2;
    reg [1:0] ctrl_cmd_sync;
    reg       ctrl_cmd_sync_prev;
    reg       ctrl_val_sync1, ctrl_val_sync2;
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            adc_sel_sync1      <= 8'h00;
            adc_sel_sync2      <= 8'h00;
            ctrl_cmd_sync      <= 2'b00;
            ctrl_cmd_sync_prev <= 1'b0;
            ctrl_val_sync1     <= 1'b0;
            ctrl_val_sync2     <= 1'b0;
        end else begin
            adc_sel_sync1      <= adc_sel;
            adc_sel_sync2      <= adc_sel_sync1;
            ctrl_cmd_sync      <= {ctrl_cmd_sync[0], ctrl_cmd_tog_fsmc};
            ctrl_cmd_sync_prev <= ctrl_cmd_sync[1];
            ctrl_val_sync1     <= ctrl_cmd_val;
            ctrl_val_sync2     <= ctrl_val_sync1;
        end
    end
    wire ctrl_cmd_edge = (ctrl_cmd_sync[1] != ctrl_cmd_sync_prev);
    wire start_pulse   = ctrl_cmd_edge &  ctrl_val_sync2;   // write 0x1 to CTRL_ADDR
    wire stop_pulse    = ctrl_cmd_edge & ~ctrl_val_sync2;   // write 0x0 to CTRL_ADDR

    // =================================================================
    // sys_clk WRITE ARBITER + live-value register + ACQUISITION CONTROL
    //
    // Write sources feeding the single PSRAM write port:
    //   * ADC samples (adc_rdy pulse, data = adc_value) - the real source,
    //     pushed ONLY while a capture is armed (polling_enabled) and the FIFO
    //     is not full.
    //   * STM32 debug writes (stm_wr_edge, data = wr_accum) - occasional.
    // ADC has priority; on a same-cycle collision the debug write is dropped.
    // Both psram_wr_toggle and psram_wr_data are sys_clk - no CDC.
    //
    // live_val tracks the adc_sel-selected channel, refreshed every adc_rdy
    // REGARDLESS of capture state, and is read back at LIVE_BASE..+3.
    //
    // Acquisition control (same block, no extra sys_clk process):
    //   - Disabled out of reset (polling_enabled=0). STM32 writes 0x1 to
    //     CTRL_ADDR to ARM: once the PSRAM self-test has passed (is_valid,
    //     checked ONCE - it never clears afterwards, so re-arm is immediate),
    //     it pulses psram_fifo_clear (write pointer -> 0, stale contents +
    //     prefetch discarded) then enables pushes.
    //   - On FIFO full: pushes stop (unread data preserved) and acq_full_sticky
    //     latches (status bit1). is_valid is untouched - ready for a hot re-arm.
    //   - STM32 writes 0x0 to CTRL_ADDR to stop early (no sticky flag).
    //   - Reading may begin as soon as the first entry is available (see the
    //     prefetch engine / data-ready bit3); waiting for full is optional.
    // =================================================================
    reg                  psram_wr_toggle;
    reg [ENTRY_BITS-1:0] psram_wr_data;
    reg [15:0]           live_val;
    reg                  adc_rdy_d;
    wire                 adc_rdy_edge = adc_rdy & ~adc_rdy_d;

    reg       polling_enabled;   // 1 while a capture is armed (gates ADC pushes)
    reg       acq_full_sticky;   // latched: FIFO filled, capture auto-stopped
    reg       psram_fifo_clear;  // -> PSRAM.fifo_clear (same sys_clk domain)
    reg [1:0] acq_state;
    reg       arm_pending;       // arm requested, waiting on first self-test
    reg [3:0] clear_hold;        // min hold so PSRAM samples fifo_clear in S_IDLE
    localparam ACQ_OFF   = 2'd0,
               ACQ_CLEAR = 2'd1,
               ACQ_RUN   = 2'd2;

    integer ch;
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            psram_wr_toggle  <= 1'b0;
            psram_wr_data    <= {ENTRY_BITS{1'b0}};
            live_val         <= 16'h0000;
            adc_rdy_d        <= 1'b0;
            polling_enabled  <= 1'b0;
            acq_full_sticky  <= 1'b0;
            psram_fifo_clear <= 1'b0;
            acq_state        <= ACQ_OFF;
            arm_pending      <= 1'b0;
            clear_hold       <= 4'd0;
        end else begin
            adc_rdy_d <= adc_rdy;

            // ---- ADC push + live value ----
            if (adc_rdy_edge) begin
                for (ch = 0; ch < NUM_ADC; ch = ch + 1)
                    if (adc_sel_sync2 == ch)
                        live_val <= adc_value[16*ch +: 16];
                if (polling_enabled && !psram_fifo_full) begin
                    psram_wr_data   <= adc_value;
                    psram_wr_toggle <= ~psram_wr_toggle;
                end
            end else if (stm_wr_edge) begin
                // debug: low 16 bits = the word the STM32 assembled, rest 0
                psram_wr_data   <= {{(ENTRY_BITS-16){1'b0}}, wr_accum};
                psram_wr_toggle <= ~psram_wr_toggle;
            end

            // ---- acquisition control FSM ----
            case (acq_state)
                ACQ_OFF: begin
                    polling_enabled  <= 1'b0;
                    psram_fifo_clear <= 1'b0;
                    if (start_pulse) begin
                        acq_full_sticky <= 1'b0;   // starting fresh
                        arm_pending     <= 1'b1;
                    end
                    // is_valid is checked only here and never clears once set,
                    // so a re-arm after the first startup proceeds immediately.
                    if (arm_pending && psram_valid_int) begin
                        arm_pending      <= 1'b0;
                        psram_fifo_clear <= 1'b1;
                        clear_hold       <= 4'd3;
                        acq_state        <= ACQ_CLEAR;
                    end
                end
                ACQ_CLEAR: begin
                    psram_fifo_clear <= 1'b1;      // hold clear asserted
                    if (clear_hold != 4'd0) begin
                        clear_hold <= clear_hold - 4'd1;
                    end else if (fifo_empty_pre && !pf_inflight) begin
                        // buffer emptied and no pop in flight -> capture window open
                        psram_fifo_clear <= 1'b0;
                        polling_enabled  <= 1'b1;
                        acq_state        <= ACQ_RUN;
                    end
                end
                ACQ_RUN: begin
                    polling_enabled <= 1'b1;
                    if (stop_pulse) begin
                        polling_enabled <= 1'b0;
                        acq_state       <= ACQ_OFF;
                    end else if (fifo_full_pre) begin
                        // buffer full: stop capturing, latch sticky flag
                        polling_enabled <= 1'b0;
                        acq_full_sticky <= 1'b1;
                        acq_state       <= ACQ_OFF;
                    end
                end
                default: acq_state <= ACQ_OFF;
            endcase
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

            if (psram_fifo_clear) begin
                // Acquisition (re)start: throw away any prefetched/held word so
                // a stale entry from a previous capture can't be read as the
                // first entry of the new one. Let an in-flight pop retire (its
                // psram_data_valid) but discard the result.
                pf_valid <= 1'b0;
                if (pf_inflight && psram_data_valid)
                    pf_inflight <= 1'b0;
            end else if (pf_inflight && psram_data_valid) begin
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
    reg fifo_empty_pre, fifo_full_pre, is_valid_pre, acq_full_pre, adc_valid_s1;
    reg [3:0] cam_red_pre, cam_green_pre;   // camera averages, sys_clk pre-register
    always @(posedge sys_clk or negedge reset_n) begin
        if (!reset_n) begin
            fifo_empty_pre <= 1'b1;
            fifo_full_pre  <= 1'b0;
            is_valid_pre   <= 1'b0;
            adc_valid_s1   <= 1'b0;
            acq_full_pre   <= 1'b0;
            cam_red_pre    <= 4'h0;
            cam_green_pre  <= 4'h0;
        end else begin
            fifo_empty_pre <= psram_fifo_empty;
            fifo_full_pre  <= psram_fifo_full;
            // status bit2 now reports ADC address-ack validity (not PSRAM self-test,
            // which stays on the psram_is_valid pin / LED). 2-FF sync i_CLK50->sys_clk.
            adc_valid_s1   <= i_adc_valid;
            is_valid_pre   <= adc_valid_s1;
            acq_full_pre   <= acq_full_sticky;
            cam_red_pre    <= cam_red;
            cam_green_pre  <= cam_green;
        end
    end

    reg       fifo_empty_sync1;   // single fsmc_clk FF — source already sys_clk-stable
    reg       fifo_full_sync1;
    reg       is_valid_sync1;
    reg       acq_full_sync1;     // sticky "capture full / stopped" flag
    reg       pf_valid_sync1;     // data-ready (pf_valid) crossed into fsmc_clk
    reg [3:0] cam_red_sync1, cam_green_sync1;

    always @(posedge fsmc_clk or negedge reset_n) begin
        if (!reset_n) begin
            fifo_empty_sync1 <= 1'b1;
            fifo_full_sync1  <= 1'b0;
            is_valid_sync1   <= 1'b0;
            acq_full_sync1   <= 1'b0;
            pf_valid_sync1   <= 1'b0;
            cam_red_sync1    <= 4'h0;
            cam_green_sync1  <= 4'h0;
        end else begin
            fifo_empty_sync1 <= fifo_empty_pre;
            fifo_full_sync1  <= fifo_full_pre;
            is_valid_sync1   <= is_valid_pre;
            acq_full_sync1   <= acq_full_pre;
            pf_valid_sync1   <= pf_valid;
            cam_red_sync1    <= cam_red_pre;
            cam_green_sync1  <= cam_green_pre;
        end
    end

    wire fifo_empty_fsmc = fifo_empty_sync1;
    wire fifo_full_fsmc  = fifo_full_sync1;   // (kept for debug; not in status word)
    wire is_valid_fsmc   = is_valid_sync1;
    wire acq_full_fsmc   = acq_full_sync1;
    wire pf_valid_fsmc   = pf_valid_sync1;

    // Status byte @STAT_ADDR (0xFF):
    //   bit0=fifo_empty  bit1=acq_full(sticky)  bit2=adc_valid  bit3=data_ready
    //   bit2 = combined ADC address-ack validity across the EFF active channels
    //   (PSRAM self-test valid is no longer here - it stays on psram_is_valid / LED).
    //   Bit layout is unchanged from the old 4-bit status nibble; upper bits read 0.
    wire [7:0] status_word = {4'b0, pf_valid_fsmc, is_valid_fsmc, acq_full_fsmc, fifo_empty_fsmc};

    // =================================================================
    // WRITE path (fsmc_nwe domain)
    //   STAT_ADDR (0xFF) : write adc_sel (selected live channel)
    //   CTRL_ADDR (0xFE) : acquisition control (bit0: 1=arm, 0=stop)
    //   NUMADC_ADDR(0xFD): effective ADC-count log2
    //   addr 0x00..0x01  : debug FIFO write - accumulate a 16-bit word, push on 0x01
    //                      (pushed as the low word of an ENTRY_BITS entry, rest 0)
    // =================================================================
    reg [15:0] wr_accum;
    reg [2:0]  num_adc_log2;                // EFF channel-count log2, written by STM32 at 0xFD
    assign o_num_adc_log2 = num_adc_log2;

    // acquisition-control command crossed to sys_clk as a toggle + data bit
    reg ctrl_cmd_tog_fsmc;
    reg ctrl_cmd_val;                              // 1 = arm/start, 0 = stop

    always @(posedge fsmc_nwe or negedge reset_n) begin
        if (!reset_n) begin
            wr_accum          <= 16'h0000;
            wr_req_tog_fsmc   <= 1'b0;
            adc_sel           <= 8'h00;
            ctrl_cmd_tog_fsmc <= 1'b0;
            ctrl_cmd_val      <= 1'b0;
            num_adc_log2      <= 3'd1;             // default EFF = 2
        end else if (~fsmc_ne) begin
            if (burst_start_addr == STAT_ADDR) begin
                adc_sel <= fsmc_ad;                // select live channel (full byte index)
            end else if (burst_start_addr == CTRL_ADDR) begin
                // acquisition control: bit0 = 1 arm, 0 stop
                ctrl_cmd_val      <= fsmc_ad[0];
                ctrl_cmd_tog_fsmc <= ~ctrl_cmd_tog_fsmc;
            end else if (burst_start_addr == NUMADC_ADDR) begin
                num_adc_log2      <= fsmc_ad[2:0]; // EFF = 1<<val (0->1 .. 5->32)
            end else if (burst_start_addr < 8'h02) begin
                case (burst_start_addr[0])
                    1'b0: wr_accum[7:0]  <= fsmc_ad;
                    1'b1: begin
                        wr_accum[15:8]  <= fsmc_ad;
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
    reg  [7:0]            cur_addr;
    reg  [7:0]            byte_base;   // first FSMC address of the active region
    reg  [7:0]            lat_cnt;
    reg  [ENTRY_BITS-1:0] rd_holding;  // right-aligned: entry / live(16b) / status(byte)
    reg                   rd_consume_tog_fsmc;   // toggled when a prefetched word is taken

    wire read_selected = (~fsmc_ne) & (~fsmc_noe);

    initial begin
        state               = ST_IDLE;
        cur_addr            = 8'h00;
        byte_base           = 8'h00;
        lat_cnt             = 8'h00;
        rd_holding          = {ENTRY_BITS{1'b0}};
        rd_consume_tog_fsmc = 1'b0;
        burst_start_addr    = 8'h00;
        latch_addr          = 8'h00;
    end

    always @(posedge fsmc_clk or posedge fsmc_ne or negedge reset_n) begin
        if (!reset_n) begin
            state               <= ST_IDLE;
            cur_addr            <= 8'h00;
            byte_base           <= 8'h00;
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
                    if (burst_start_addr < READ_ENTRY_BYTES) begin
                        // FIFO entry region (0x00 .. ENTRY_BYTES-1)
                        byte_base <= 8'h00;
                        if (burst_start_addr == 8'h00 && pf_valid_fsmc) begin
                            // take the prefetched entry; addr 1.. just replay it
                            rd_holding          <= pf_data;
                            rd_consume_tog_fsmc <= ~rd_consume_tog_fsmc;  // fetch next
                        end
                    end else if (burst_start_addr >= LIVE_BASE &&
                                 burst_start_addr <  LIVE_BASE + 8'h02) begin
                        // live selected-channel value (16 bits, 2 bytes: 0xFD,0xFE)
                        byte_base <= LIVE_BASE;
                        if (burst_start_addr == LIVE_BASE)
                            rd_holding <= {{(ENTRY_BITS-16){1'b0}}, live_val};
                    end else if (burst_start_addr == STAT_ADDR) begin
                        // status byte (0xFF)
                        byte_base  <= STAT_ADDR;
                        rd_holding <= {{(ENTRY_BITS-8){1'b0}}, status_word};
                    end else begin
                        // unused addresses - replay whatever is in rd_holding
                        byte_base <= 8'h00;
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
                    cur_addr <= cur_addr + 8'd1;  // advances through the region's bytes
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
    // Select byte `sel` (region-relative) of the ENTRY_BITS holding reg
    // ---------------------------------------------------------------
    function [7:0] select_byte;
        input [ENTRY_BITS-1:0] word;
        input [5:0]            sel;     // 0 .. ENTRY_BYTES-1 (<=63)
        begin
            select_byte = word[sel*8 +: 8];
        end
    endfunction

    // byte index within the active region = absolute address - region base
    wire [7:0] byte_idx = cur_addr - byte_base;

    // ---------------------------------------------------------------
    // Drive AD bus with a holding-register byte only while streaming
    // (index bounded to 6 bits: the entry is at most ENTRY_BYTES=64 bytes)
    // ---------------------------------------------------------------
    assign #(ACCESS_DELAY) fsmc_ad =
        (read_selected && state == ST_STREAM) ? select_byte(rd_holding, byte_idx[5:0]) : 8'bz;

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
        .fifo_clear  (psram_fifo_clear),    // acquisition (re)start: rewind pointers
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