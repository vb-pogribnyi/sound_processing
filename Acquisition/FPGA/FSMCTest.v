// =============================================================================
// FSMCTest.v  –  Testbench for FSMC.v + PSRAM.v + aps6404l_behavioral_model.v
//
// Covers the NUM_ADC=2 design:
//   * ADC samples pushed via adc_value/adc_rdy -> FIFO (8-nibble entries)
//   * buffered read at 0x0-0x7 (poll status 0xF bit3 first)
//   * live selected-channel value at 0xB-0xE (write adc_sel @0xF, no poll)
//   * status nibble at 0xF
//   * STM32 debug write at 0x0-0x3
//
// Run:
//   iverilog -g2005 -o FSMCTest.vvp FSMCTest.v FSMC.v PSRAM.v aps6404l_behavioral_model.v
//   vvp FSMCTest.vvp
// =============================================================================
`timescale 1ns/1ps

module FSMCTest;

localparam NUM_ADC        = 2;
localparam ENTRY_BITS     = 16 * NUM_ADC;   // 32
localparam ENTRY_NIBS     = 4  * NUM_ADC;   // 8
localparam LIVE_BASE      = 11;
localparam STAT_ADDR      = 15;

localparam FSMC_CLK_HALF  = 12;   // ~42 MHz half-period
localparam SYS_CLK_HALF   = 10;   // 50 MHz
localparam PSRAM_CLK_DIV     = 4;
localparam PSRAM_SYS_CLK_MHZ = 50;
localparam PSRAM_FIFO_DEPTH  = 8;
localparam MAX_WAIT          = 8000;

// ---------------------------------------------------------------------------
// Clocks & reset
// ---------------------------------------------------------------------------
reg sys_clk  = 0;
reg fsmc_clk = 0;
reg reset_n  = 0;
always #(SYS_CLK_HALF)  sys_clk  = ~sys_clk;
always #(FSMC_CLK_HALF) fsmc_clk = ~fsmc_clk;

// ---------------------------------------------------------------------------
// FSMC bus
// ---------------------------------------------------------------------------
reg        fsmc_ne   = 1;
reg        fsmc_nadv = 1;
reg        fsmc_noe  = 1;
reg        fsmc_nwe  = 1;
reg  [3:0] ad_drive  = 4'h0;
reg        ad_oe     = 0;
wire [3:0] fsmc_ad   = ad_oe ? ad_drive : 4'bz;
wire       fsmc_nwait;

// ---------------------------------------------------------------------------
// ADC source
// ---------------------------------------------------------------------------
reg [ENTRY_BITS-1:0] adc_value = 0;
reg                  adc_rdy   = 0;

// ---------------------------------------------------------------------------
// PSRAM physical bus
// ---------------------------------------------------------------------------
wire        psram_sclk;
wire        psram_ce_n;
wire [3:0]  psram_sio;
wire        psram_is_valid;

// ---------------------------------------------------------------------------
// DUT
// ---------------------------------------------------------------------------
FSMC #(
    .NUM_ADC           (NUM_ADC),
    .WAIT_ACTIVE_LOW   (0),
    .PSRAM_CLK_DIV     (PSRAM_CLK_DIV),
    .PSRAM_SYS_CLK_MHZ (PSRAM_SYS_CLK_MHZ),
    .PSRAM_FIFO_DEPTH  (PSRAM_FIFO_DEPTH)
) dut (
    .fsmc_ad       (fsmc_ad),
    .fsmc_ne       (fsmc_ne),
    .fsmc_nadv     (fsmc_nadv),
    .fsmc_noe      (fsmc_noe),
    .fsmc_nwe      (fsmc_nwe),
    .fsmc_clk      (fsmc_clk),
    .fsmc_nwait    (fsmc_nwait),
    .sys_clk       (sys_clk),
    .reset_n       (reset_n),
    .adc_value     (adc_value),
    .adc_rdy       (adc_rdy),
    .psram_sclk    (psram_sclk),
    .psram_ce_n    (psram_ce_n),
    .psram_sio     (psram_sio),
    .psram_is_valid(psram_is_valid)
);

aps6404l_behavioral_model #(.MEM_BYTES(4096)) chip (
    .sclk (psram_sclk),
    .ce_n (psram_ce_n),
    .sio  (psram_sio)
);

// ---------------------------------------------------------------------------
// Wait for the current PSRAM transaction (CE# low then high) to finish.
// ---------------------------------------------------------------------------
task wait_psram_idle;
    integer tout;
    begin
        tout = 0;
        while (psram_ce_n !== 1'b0 && tout < 500) begin
            @(posedge sys_clk); tout = tout + 1;
        end
        tout = 0;
        while (psram_ce_n !== 1'b1 && tout < 2000) begin
            @(posedge sys_clk); tout = tout + 1;
        end
        repeat(10) @(posedge sys_clk);
        repeat(5)  @(posedge fsmc_clk);
    end
endtask

// ---------------------------------------------------------------------------
// Push one ADC sample (drive adc_value, pulse adc_rdy in sys_clk).
// ---------------------------------------------------------------------------
task push_adc_sample;
    input [ENTRY_BITS-1:0] val;
    begin
        @(posedge sys_clk); #1;
        adc_value = val;
        adc_rdy   = 1;
        @(posedge sys_clk);
        @(posedge sys_clk); #1;
        adc_rdy   = 0;
        wait_psram_idle;
    end
endtask

// ---------------------------------------------------------------------------
// STM32 debug write: one 16-bit word via 4 nibble transactions (addr 0-3).
// Pushed as the low word of a 32-bit entry (high word 0).
// ---------------------------------------------------------------------------
task fsmc_write_word;
    input [15:0] wdata;
    reg [3:0] nibbles [0:3];
    integer n;
    begin
        nibbles[0] = wdata[3:0];
        nibbles[1] = wdata[7:4];
        nibbles[2] = wdata[11:8];
        nibbles[3] = wdata[15:12];
        @(posedge fsmc_clk); #1;
        fsmc_ne = 0; ad_oe = 1;
        for (n = 0; n < 4; n = n + 1) begin
            ad_drive  = n[3:0];
            fsmc_nadv = 0;
            @(posedge fsmc_clk); #1;
            fsmc_nadv = 1;
            ad_drive  = nibbles[n];
            fsmc_nwe  = 0;
            @(posedge fsmc_clk); #1;
            fsmc_nwe  = 1;
            @(posedge fsmc_clk); #1;
        end
        fsmc_ne = 1; ad_oe = 0;
        @(posedge fsmc_clk); #1;
        wait_psram_idle;
    end
endtask

// ---------------------------------------------------------------------------
// Write adc_sel (live channel index) at STAT_ADDR.
// ---------------------------------------------------------------------------
task fsmc_write_adc_sel;
    input [3:0] idx;
    begin
        @(posedge fsmc_clk); #1;
        fsmc_ne = 0; ad_oe = 1;
        ad_drive  = STAT_ADDR;
        fsmc_nadv = 0;
        @(posedge fsmc_clk); #1;
        fsmc_nadv = 1;
        ad_drive  = idx;
        fsmc_nwe  = 0;
        @(posedge fsmc_clk); #1;
        fsmc_nwe  = 1;
        @(posedge fsmc_clk); #1;
        fsmc_ne = 1; ad_oe = 0;
        @(posedge fsmc_clk); #1;
        repeat(4) @(posedge sys_clk);   // let adc_sel sync into sys_clk
    end
endtask

// ---------------------------------------------------------------------------
// Read the status nibble at STAT_ADDR (no stall on data, short latency).
//   bit0=fifo_empty, bit1=fifo_full, bit2=is_valid, bit3=data_ready
// ---------------------------------------------------------------------------
task fsmc_read_status;
    output [3:0] stat;
    integer timeout;
    begin
        @(posedge fsmc_clk); #1;
        fsmc_ne = 0; ad_oe = 1;
        ad_drive  = STAT_ADDR;
        fsmc_nadv = 0;
        @(posedge fsmc_clk); #1;
        fsmc_nadv = 1;
        ad_oe     = 0;
        fsmc_noe  = 0;
        @(posedge fsmc_clk); #2;
        timeout = 0;
        while (fsmc_nwait === 1'b1 && timeout < MAX_WAIT) begin
            @(posedge fsmc_clk); #2; timeout = timeout + 1;
        end
        #6;
        stat = fsmc_ad;
        fsmc_noe = 1; fsmc_ne = 1;
        @(posedge fsmc_clk); #1;
    end
endtask

// ---------------------------------------------------------------------------
// Generic region read: NADV at `base`, collect `nnib` nibbles, LSnibble first.
// ---------------------------------------------------------------------------
task fsmc_read_region;
    input  [3:0]  base;
    input  integer nnib;
    output [ENTRY_BITS-1:0] rdata;
    integer timeout, n;
    reg [3:0] nibs [0:7];
    begin
        @(posedge fsmc_clk); #1;
        fsmc_ne = 0; ad_oe = 1;
        ad_drive  = base;
        fsmc_nadv = 0;
        @(posedge fsmc_clk); #1;
        fsmc_nadv = 1;
        ad_oe     = 0;
        fsmc_noe  = 0;
        @(posedge fsmc_clk); #2;
        timeout = 0;
        while (fsmc_nwait === 1'b1 && timeout < MAX_WAIT) begin
            @(posedge fsmc_clk); #2; timeout = timeout + 1;
        end
        if (timeout >= MAX_WAIT)
            $display("  *** NWAIT TIMEOUT (base=%0d) at t=%0t ***", base, $time);
        #6;
        rdata = 0;
        for (n = 0; n < nnib; n = n + 1) begin
            nibs[n] = fsmc_ad;
            rdata[4*n +: 4] = fsmc_ad;
            @(posedge fsmc_clk); #6;
        end
        fsmc_noe = 1; fsmc_ne = 1;
        @(posedge fsmc_clk); #1;
    end
endtask

// ---------------------------------------------------------------------------
// Buffered FIFO entry read: poll data-ready (0xF bit3), then read 8 nibbles.
// ---------------------------------------------------------------------------
task fsmc_read_entry;
    output [ENTRY_BITS-1:0] rdata;
    integer timeout;
    reg [3:0] st;
    begin
        st = 0; timeout = 0;
        while (st[3] !== 1'b1 && timeout < MAX_WAIT) begin
            fsmc_read_status(st); timeout = timeout + 1;
        end
        if (timeout >= MAX_WAIT)
            $display("  *** DATA-READY TIMEOUT at t=%0t ***", $time);
        fsmc_read_region(4'd0, ENTRY_NIBS, rdata);
    end
endtask

// ---------------------------------------------------------------------------
// Stimulus
// ---------------------------------------------------------------------------
integer test_fail = 0;
reg [ENTRY_BITS-1:0] ebuf;
reg [ENTRY_BITS-1:0] lbuf;
reg [3:0] stat;
integer k;

initial begin
    $dumpfile("FSMCTest.vcd");
    $dumpvars(0, FSMCTest);

    reset_n = 0;
    repeat(10) @(posedge fsmc_clk);
    reset_n = 1;

    $display("=== Waiting for PSRAM self-test ===");
    repeat(8500) @(posedge sys_clk);
    $display("  psram_is_valid=%b (expect 1)", psram_is_valid);
    if (!psram_is_valid) begin
        $display("  *** SELF-TEST FAILED ***"); test_fail = test_fail + 1;
    end

    // ------------------------------------------------------------------
    // TEST 1: push 2 ADC samples, read back as 32-bit entries
    // ------------------------------------------------------------------
    $display("\n--- TEST 1: ADC push 0xAAAA5555, 0x12345678 ---");
    push_adc_sample(32'hAAAA5555);
    push_adc_sample(32'h12345678);

    fsmc_read_entry(ebuf);
    $display("  Entry 0: got=0x%08H  exp=0xAAAA5555  %s", ebuf,
             (ebuf === 32'hAAAA5555) ? "PASS" : "FAIL");
    if (ebuf !== 32'hAAAA5555) test_fail = test_fail + 1;

    fsmc_read_entry(ebuf);
    $display("  Entry 1: got=0x%08H  exp=0x12345678  %s", ebuf,
             (ebuf === 32'h12345678) ? "PASS" : "FAIL");
    if (ebuf !== 32'h12345678) test_fail = test_fail + 1;

    // ------------------------------------------------------------------
    // TEST 2: fill FIFO via ADC push, read all back
    // ------------------------------------------------------------------
    $display("\n--- TEST 2: fill FIFO (%0d entries) ---", PSRAM_FIFO_DEPTH);
    for (k = 0; k < PSRAM_FIFO_DEPTH; k = k + 1)
        push_adc_sample(k * 32'h11110001);
    for (k = 0; k < PSRAM_FIFO_DEPTH; k = k + 1) begin
        fsmc_read_entry(ebuf);
        $display("  [%0d] got=0x%08H  exp=0x%08H  %s",
                 k, ebuf, k * 32'h11110001,
                 (ebuf === k * 32'h11110001) ? "PASS" : "FAIL");
        if (ebuf !== k * 32'h11110001) test_fail = test_fail + 1;
    end

    // ------------------------------------------------------------------
    // TEST 3: STM32 debug write -> entry low word
    // ------------------------------------------------------------------
    $display("\n--- TEST 3: debug write 0xBEEF ---");
    fsmc_write_word(16'hBEEF);
    fsmc_read_entry(ebuf);
    $display("  got=0x%08H  exp=0x0000BEEF  %s", ebuf,
             (ebuf === 32'h0000BEEF) ? "PASS" : "FAIL");
    if (ebuf !== 32'h0000BEEF) test_fail = test_fail + 1;

    // ------------------------------------------------------------------
    // TEST 4: live value (0xB-0xE), channel select via 0xF write
    //   adc_value = {ch1=0xBBBB, ch0=0xAAAA} = 0xBBBBAAAA
    // ------------------------------------------------------------------
    $display("\n--- TEST 4: live value ---");
    fsmc_write_adc_sel(4'd0);
    push_adc_sample(32'hBBBBAAAA);     // refresh live_val with sel=0
    fsmc_read_region(LIVE_BASE, 4, lbuf);
    $display("  sel=0 live=0x%04H  exp=0xAAAA  %s", lbuf[15:0],
             (lbuf[15:0] === 16'hAAAA) ? "PASS" : "FAIL");
    if (lbuf[15:0] !== 16'hAAAA) test_fail = test_fail + 1;

    fsmc_write_adc_sel(4'd1);
    push_adc_sample(32'hBBBBAAAA);     // refresh live_val with sel=1
    fsmc_read_region(LIVE_BASE, 4, lbuf);
    $display("  sel=1 live=0x%04H  exp=0xBBBB  %s", lbuf[15:0],
             (lbuf[15:0] === 16'hBBBB) ? "PASS" : "FAIL");
    if (lbuf[15:0] !== 16'hBBBB) test_fail = test_fail + 1;

    // drain the two entries TEST 4 pushed so status is clean
    fsmc_read_entry(ebuf);
    fsmc_read_entry(ebuf);

    // ------------------------------------------------------------------
    // TEST 5: status nibble at 0xF
    // ------------------------------------------------------------------
    $display("\n--- TEST 5: status register (0xF) ---");
    repeat(5) @(posedge fsmc_clk);
    fsmc_read_status(stat);
    $display("  After drain:  stat=%b  empty=%b full=%b valid=%b  (exp 1 0 1)",
             stat, stat[0], stat[1], stat[2]);
    if (stat[0] !== 1'b1 || stat[1] !== 1'b0 || stat[2] !== 1'b1)
        test_fail = test_fail + 1;

    push_adc_sample(32'hCAFEF00D);
    fsmc_read_status(stat);
    $display("  After push:   stat=%b  empty=%b full=%b valid=%b  (exp 0 0 1)",
             stat, stat[0], stat[1], stat[2]);
    if (stat[1] !== 1'b0 || stat[2] !== 1'b1)
        test_fail = test_fail + 1;

    fsmc_read_entry(ebuf);
    $display("  Drained: 0x%08H  exp=0xCAFEF00D  %s", ebuf,
             (ebuf === 32'hCAFEF00D) ? "PASS" : "FAIL");
    if (ebuf !== 32'hCAFEF00D) test_fail = test_fail + 1;

    // ------------------------------------------------------------------
    $display("\n========================================");
    if (test_fail == 0) $display("  ALL TESTS PASSED");
    else                $display("  FAILURES: %0d", test_fail);
    $display("========================================\n");
    $finish;
end

initial begin
    #500_000_000;
    $display("WATCHDOG TIMEOUT");
    $finish;
end

endmodule
