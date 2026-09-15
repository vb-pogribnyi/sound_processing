// =====================================================================
// SW1PipelineTest.v
//
// Whole-pipeline simulation of the SW1 test feed:
//
//     AdcSim (sine.hex)  ->  FSMC  ->  PSRAM FIFO  ->  aps6404l model
//
// This drives the REAL modules end to end (no forcing of FSMC's output):
//   1. Wait for the PSRAM power-up self-test to pass (is_valid).
//   2. Turn the AdcSim feed on (SW1) and ARM the capture by writing 0x1 to
//      control address 0xE over the FSMC bus - exactly what the STM32 does.
//   3. The sine samples flow through FSMC into the PSRAM FIFO (and out to the
//      APS6404L behavioral model over QPI) until the FIFO fills.
//   4. On full, capture stops automatically (acq_full latches, pushes stop) -
//      unread data is preserved.
//
// To exercise the "wrap when the file is smaller than the FIFO" path, the
// AdcSim here is told SINE_SAMPLES=4 while the FIFO is 8 deep, so the feed
// wraps back to sample 0 partway through filling the buffer.
//
// Self-checks (hierarchical) confirm the data that reached the APS6404L chip
// equals, in FIFO order, exactly the samples the feed emitted. A VCD is
// written for GTKWave.
//
// Run:
//   iverilog -g2012 -o sim_sw1 SW1PipelineTest.v AdcSim.v FSMC.v PSRAM.v \
//            aps6404l_behavioral_model.v
//   vvp sim_sw1
//   gtkwave wave_sw1_pipeline.vcd
// =====================================================================
`timescale 1ns/1ps

module SW1PipelineTest;

    // ---- geometry ----
    localparam NUM_ADC     = 2;
    localparam FIFO_DEPTH  = 8;               // small -> fills quickly
    localparam SINE_SAMPLES= 4;               // < FIFO_DEPTH -> feed must wrap
    localparam SINE_DIV    = 300;             // sys_clk cycles/sample (> 1 PSRAM op)
    localparam ENTRY_BITS  = 16*NUM_ADC;
    localparam ENTRY_BYTES = NUM_ADC*2;

    // ---- clocks / reset ----
    reg sys_clk  = 0;  always #10 sys_clk  = ~sys_clk;   // 50 MHz
    reg fsmc_clk = 0;  always #7  fsmc_clk = ~fsmc_clk;  // async burst clock
    reg reset_n  = 0;
    reg sw1      = 0;

    // ---- FSMC bus ----
    wire [3:0] fsmc_ad;
    reg  [3:0] ad_drive; reg ad_oe;
    assign fsmc_ad = ad_oe ? ad_drive : 4'bz;
    reg  ne = 1, nadv = 1, noe = 1, nwe = 1;
    wire nwait;

    // ---- AdcSim feed ----
    wire [ENTRY_BITS-1:0] adc_value;
    wire                  adc_rdy;
    wire [15:0]           adc_addr;
    AdcSim #(
        .NUM_ADC     (NUM_ADC),
        .SINE_SAMPLES(SINE_SAMPLES),
        .SINE_DIV    (SINE_DIV),
        .HEX_FILE    ("sine.hex")
    ) feed (
        .i_CLK  (sys_clk),
        .i_EN   (sw1),
        .o_VALUE(adc_value),
        .o_RDY  (adc_rdy),
        .o_ADDR (adc_addr)
    );

    // ---- PSRAM pins ----
    wire        psram_sclk, psram_ce_n;
    wire [3:0]  psram_sio;

    // ---- DUT: FSMC (contains the PSRAM FIFO controller) ----
    FSMC #(
        .NUM_ADC          (NUM_ADC),
        .WAIT_ACTIVE_LOW  (0),
        .PSRAM_CLK_DIV    (2),
        .PSRAM_SYS_CLK_MHZ(1),                // short power-up for sim
        .PSRAM_FIFO_DEPTH (FIFO_DEPTH)
    ) dut (
        .fsmc_ad   (fsmc_ad),
        .fsmc_ne   (ne),
        .fsmc_nadv (nadv),
        .fsmc_noe  (noe),
        .fsmc_nwe  (nwe),
        .fsmc_clk  (fsmc_clk),
        .fsmc_nwait(nwait),
        .sys_clk   (sys_clk),
        .reset_n   (reset_n),
        .adc_value (adc_value),
        .adc_rdy   (adc_rdy),
        .cam_red   (4'h0),
        .cam_green (4'h0),
        .psram_sclk(psram_sclk),
        .psram_ce_n(psram_ce_n),
        .psram_sio (psram_sio),
        .psram_is_valid()
    );

    // ---- APS6404L behavioral chip ----
    aps6404l_behavioral_model chip (
        .sclk(psram_sclk),
        .ce_n(psram_ce_n),
        .sio (psram_sio)
    );

    // =================================================================
    // Record every committed push (FSMC only toggles psram_wr_toggle when it
    // actually accepts a sample), so we know the exact sequence of samples
    // that entered the FIFO.
    // =================================================================
    reg [ENTRY_BITS-1:0] pushed [0:255];
    integer npush = 0;
    reg     last_tog = 0;
    reg     rec_en   = 0;      // enabled by the stimulus once reset is complete
    always @(posedge sys_clk) begin
        if (!rec_en) begin
            last_tog <= dut.psram_wr_toggle;   // track (seed) until recording starts
        end else if (dut.psram_wr_toggle !== last_tog) begin
            pushed[npush] = dut.psram_wr_data;
            npush = npush + 1;
            last_tog <= dut.psram_wr_toggle;
        end
    end

    // Track whether the feed wrapped (o_ADDR decreased) during the run.
    reg        saw_wrap = 0;
    reg [15:0] prev_addr = 0;
    always @(posedge sys_clk) begin
        if (adc_rdy && adc_addr < prev_addr) saw_wrap <= 1'b1;
        if (adc_rdy) prev_addr <= adc_addr;
    end

    // Reconstruct FIFO entry stored at PSRAM entry index e from the chip's
    // byte memory (first byte written is the MSB byte).
    function [ENTRY_BITS-1:0] mem_entry;
        input integer e;
        integer b;
        reg [ENTRY_BITS-1:0] v;
        begin
            v = 0;
            for (b = 0; b < ENTRY_BYTES; b = b + 1)
                v[ENTRY_BITS-1-8*b -: 8] = chip.mem[e*ENTRY_BYTES + b];
            mem_entry = v;
        end
    endfunction

    // ---- FSMC single-beat write (used to arm at control address 0xE) ----
    task fsmc_write;
        input [3:0] addr;
        input [3:0] data;
        begin
            ne = 1'b0;
            ad_drive = addr; ad_oe = 1'b1;    // address phase
            nadv = 1'b0; #20;
            nadv = 1'b1; #20;                 // rising NADV latches the address
            ad_drive = data;                  // data phase
            nwe = 1'b0; #20;
            nwe = 1'b1; #20;                  // rising NWE captures the write
            ad_oe = 1'b0;
            ne = 1'b1; #20;
        end
    endtask

    // =================================================================
    // Stimulus
    // =================================================================
    integer i, fails, expect_n, npush_at_full;
    reg [ENTRY_BITS-1:0] exp_read;
    integer rp, cnt, rd_idx;

    initial begin
        $dumpfile("wave_sw1_pipeline.vcd");
        $dumpvars(0, SW1PipelineTest);

        fails = 0;
        ad_oe = 0; ne = 1; nadv = 1; noe = 1; nwe = 1; sw1 = 0;
        // Proper reset EDGE: 1 -> 0 -> 1. The FSMC regs clocked by fsmc_nwe /
        // fsmc_nadv only async-reset on a negedge of reset_n (on real silicon
        // Xilinx GSR inits them to 0); without a negedge they stay X in sim.
        reset_n = 1;
        #30;
        reset_n = 0;
        #200;
        reset_n = 1;

        $display("=====================================================");
        $display(" SW1 pipeline: AdcSim -> FSMC -> PSRAM -> APS6404L");
        $display("   FIFO_DEPTH=%0d  SINE_SAMPLES=%0d (feed must wrap)", FIFO_DEPTH, SINE_SAMPLES);
        $display("=====================================================");

        // 1) wait for PSRAM self-test
        wait (dut.u_psram_fifo.is_valid === 1'b1);
        $display("[%0t] PSRAM self-test passed (is_valid=1)", $time);

        // 2) turn on SW1 feed and ARM the capture (write 0x1 -> 0xE)
        rec_en = 1'b1;                 // start recording committed pushes
        sw1 = 1'b1;
        fsmc_write(4'hE, 4'h1);
        $display("[%0t] SW1 on, armed capture (0x1 -> 0xE)", $time);

        // 3) run until the FIFO fills and capture auto-stops
        wait (dut.acq_full_sticky === 1'b1);
        npush_at_full = npush;
        $display("[%0t] acq_full latched: count=%0d  pushes=%0d  fifo_full=%b",
                 $time, dut.u_psram_fifo.count, npush, dut.u_psram_fifo.fifo_full);

        // 4) confirm capture really stopped (no further pushes for a while)
        #20000;
        if (npush !== npush_at_full) begin
            $display("  FAIL: pushes kept coming after full (%0d -> %0d)",
                     npush_at_full, npush);
            fails = fails + 1;
        end else
            $display("  OK: pushes stopped at full (%0d total)", npush);

        // 5) the FIFO must be full
        if (dut.u_psram_fifo.count !== FIFO_DEPTH[$clog2(FIFO_DEPTH+1)-1:0]) begin
            $display("  FAIL: count=%0d expected %0d", dut.u_psram_fifo.count, FIFO_DEPTH);
            fails = fails + 1;
        end else
            $display("  OK: FIFO count == FIFO_DEPTH (%0d)", FIFO_DEPTH);

        // 6) the feed must have wrapped (SINE_SAMPLES < entries captured)
        if (!saw_wrap) begin
            $display("  FAIL: feed did not wrap (expected, SINE_SAMPLES<FIFO_DEPTH)");
            fails = fails + 1;
        end else
            $display("  OK: feed wrapped back to sample 0 during fill");

        // 7) data integrity: rebuild the FIFO read order (oldest first) from
        //    the chip memory + prefetch holding reg, and compare to the exact
        //    sequence of samples the feed pushed.
        rp  = dut.u_psram_fifo.rd_ptr;
        cnt = dut.u_psram_fifo.count;
        rd_idx = 0;
        if (dut.pf_valid === 1'b1) begin
            if (dut.pf_data !== pushed[rd_idx]) begin
                $display("  FAIL read[%0d] (prefetch): got %h exp %h",
                         rd_idx, dut.pf_data, pushed[rd_idx]);
                fails = fails + 1;
            end
            rd_idx = rd_idx + 1;
        end
        for (i = 0; i < cnt; i = i + 1) begin
            exp_read = mem_entry((rp + i) % FIFO_DEPTH);
            if (exp_read !== pushed[rd_idx]) begin
                $display("  FAIL read[%0d] (mem entry %0d): got %h exp %h",
                         rd_idx, (rp + i) % FIFO_DEPTH, exp_read, pushed[rd_idx]);
                fails = fails + 1;
            end
            rd_idx = rd_idx + 1;
        end
        expect_n = rd_idx;
        if (expect_n !== npush) begin
            $display("  FAIL: reconstructed %0d entries but %0d were pushed",
                     expect_n, npush);
            fails = fails + 1;
        end else
            $display("  OK: all %0d pushed samples present in FIFO order in the chip", npush);

        // Dump the pushed sequence (ch0=out1 is the low 16 bits) for eyeballing.
        $display("  pushed samples (entry: full / ch0 / ch1):");
        for (i = 0; i < npush; i = i + 1)
            $display("    [%0d] %h  ch0=%h ch1=%h",
                     i, pushed[i], pushed[i][15:0], pushed[i][31:16]);

        $display("=====================================================");
        if (fails == 0) $display("  ALL CHECKS PASSED");
        else            $display("  FAILURES: %0d", fails);
        $display("=====================================================");
        $finish;
    end

    // ---- acquisition-phase trace (OFF->CLEAR->RUN->OFF), for the log ----
    reg [2:0] dbg_acq_prev = 3'd7;
    always @(posedge sys_clk) begin
        if (reset_n && dut.acq_state !== dbg_acq_prev[1:0]) begin
            $display("[%0t] acq_state -> %0d (polling=%b)", $time, dut.acq_state, dut.polling_enabled);
            dbg_acq_prev <= {1'b0, dut.acq_state};
        end
    end

    // watchdog
    initial begin
        #400_000;
        $display("WATCHDOG TIMEOUT at %0t (npush=%0d, acq_full=%b)",
                 $time, npush, dut.acq_full_sticky);
        $finish;
    end

endmodule
