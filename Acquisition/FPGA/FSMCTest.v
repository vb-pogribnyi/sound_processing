// =============================================================================
// FSMCTest.v  –  Testbench for FSMC.v + PSRAM.v + aps6404l_behavioral_model.v
//
// Simulates STM32 FSMC burst writes (address 0→3, one nibble each) and reads
// (address 0 triggers FIFO pop + NWAIT stall, addresses 1-3 replay nibbles).
//
// Run:
//   iverilog -g2005 -o FSMCTest.vvp FSMCTest.v FSMC.v PSRAM.v aps6404l_behavioral_model.v
//   vvp FSMCTest.vvp
//   gtkwave FSMCTest.vcd
// =============================================================================
`timescale 1ns/1ps

module FSMCTest;

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------
localparam FSMC_CLK_HALF  = 12;   // ~83 MHz
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
// FSMC bus signals
// ---------------------------------------------------------------------------
reg        fsmc_ne   = 1;
reg        fsmc_nadv = 1;
reg        fsmc_noe  = 1;
reg        fsmc_nwe  = 1;
reg  [3:0] ad_drive  = 4'h0;
reg        ad_oe     = 0;

wire [3:0] fsmc_ad  = ad_oe ? ad_drive : 4'bz;
wire       fsmc_nwait;

// ---------------------------------------------------------------------------
// PSRAM physical bus
// ---------------------------------------------------------------------------
wire        psram_sclk;
wire        psram_ce_n;
wire [3:0]  psram_sio;   // shared bidirectional
wire        psram_is_valid;

// ---------------------------------------------------------------------------
// DUT: FSMC bridge
// ---------------------------------------------------------------------------
FSMC #(
    .WAIT_ACTIVE_LOW   (0),
    .PSRAM_CLK_DIV     (PSRAM_CLK_DIV),
    .PSRAM_SYS_CLK_MHZ (PSRAM_SYS_CLK_MHZ),
    .PSRAM_FIFO_DEPTH  (PSRAM_FIFO_DEPTH),
    .MAX_WAIT_CYCLES   (MAX_WAIT)
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
    .psram_sclk    (psram_sclk),
    .psram_ce_n    (psram_ce_n),
    .psram_sio     (psram_sio),
    .psram_is_valid(psram_is_valid)
);

// ---------------------------------------------------------------------------
// Behavioral PSRAM chip model
// ---------------------------------------------------------------------------
aps6404l_behavioral_model #(
    .MEM_BYTES (4096)
) chip (
    .sclk (psram_sclk),
    .ce_n (psram_ce_n),
    .sio  (psram_sio)
);

// ---------------------------------------------------------------------------
// Task: wait for the current PSRAM transaction (write) to finish.
// Waits for CE# to go low (transaction starts) then high (done).
// A PSRAM write triggered via CDC may not start immediately, so we wait up
// to 500 sys_clk cycles for CE# to assert first.
// ---------------------------------------------------------------------------
task wait_psram_idle;
    integer tout;
    begin
        // wait for CE# to assert (write starts)
        tout = 0;
        while (psram_ce_n !== 1'b0 && tout < 500) begin
            @(posedge sys_clk);
            tout = tout + 1;
        end
        // wait for CE# to deassert (write done)
        tout = 0;
        while (psram_ce_n !== 1'b1 && tout < 2000) begin
            @(posedge sys_clk);
            tout = tout + 1;
        end
        // extra cycles for count register and fifo_empty CDC to settle
        repeat(10) @(posedge sys_clk);
        repeat(5)  @(posedge fsmc_clk);
    end
endtask

// ---------------------------------------------------------------------------
// Task: write one 16-bit word via 4 separate FSMC nibble transactions.
// FSMC.v write path uses burst_start_addr (static per transaction) to
// select which nibble slot to fill, so each nibble must be a distinct
// transaction with its own NADV address phase (addr 0-3).
// Address 3 write triggers the FIFO push.
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

        // Assert NE once; keep it low for all 4 nibbles (burst behaviour).
        // NE must be low BEFORE posedge NWE fires so the always block sees ~ne=1.
        @(posedge fsmc_clk); #1;
        fsmc_ne  = 0;
        ad_oe    = 1;

        for (n = 0; n < 4; n = n + 1) begin
            // NADV phase: latch address n
            ad_drive  = n[3:0];
            fsmc_nadv = 0;
            @(posedge fsmc_clk); #1;
            fsmc_nadv = 1;   // burst_start_addr latches address n here

            // Write nibble: NWE rises with NE already low
            ad_drive = nibbles[n];
            fsmc_nwe = 0;
            @(posedge fsmc_clk); #1;
            fsmc_nwe = 1;    // posedge NWE: ~fsmc_ne=1, processes nibble n
            @(posedge fsmc_clk); #1;
        end

        fsmc_ne = 1;   // release after all nibbles committed
        ad_oe   = 0;
        @(posedge fsmc_clk); #1;
    end
endtask

// ---------------------------------------------------------------------------
// Task: read one 16-bit word via 4 FSMC nibble reads (addr 0-3)
// Stalls on NWAIT while PSRAM pop completes, then collects nibbles.
// ---------------------------------------------------------------------------
task fsmc_read_word;
    output [15:0] rdata;
    integer timeout;
    reg [3:0] nibs [0:3];
    integer n;
    begin
        // NADV phase: latch address 0x0
        @(posedge fsmc_clk); #1;
        fsmc_ne   = 0;
        ad_drive  = 4'h0;
        ad_oe     = 1;
        fsmc_nadv = 0;
        @(posedge fsmc_clk); #1;
        fsmc_nadv = 1;
        ad_oe     = 0;

        // NOE asserted – start read burst, stall while NWAIT=1
        fsmc_noe = 0;
        timeout  = 0;
        // Let FSM react to NOE assertion before checking NWAIT
        @(posedge fsmc_clk); #2;
        while (fsmc_nwait === 1'b1 && timeout < MAX_WAIT) begin
            @(posedge fsmc_clk); #2;
            timeout = timeout + 1;
        end
        if (timeout >= MAX_WAIT)
            $display("  *** NWAIT TIMEOUT in read at t=%0t ***", $time);

        // NWAIT deasserted. Wait ACCESS_DELAY+1 ns for fsmc_ad to propagate
        // through the inertial #5 delay in the FSMC assign before sampling.
        // Each subsequent nibble: posedge advances cur_addr, then wait same margin.
        #6;
        for (n = 0; n < 4; n = n + 1) begin
            nibs[n] = fsmc_ad;
            @(posedge fsmc_clk); #6;
        end

        fsmc_noe = 1;
        fsmc_ne  = 1;
        @(posedge fsmc_clk); #1;

        rdata = {nibs[3], nibs[2], nibs[1], nibs[0]};
    end
endtask

// ---------------------------------------------------------------------------
// Task: read the status nibble from address 0x4 (no NWAIT stall).
// Returns the raw 4-bit nibble: bit0=fifo_empty, bit1=fifo_full, bit2=is_valid.
// ---------------------------------------------------------------------------
task fsmc_read_status;
    output [3:0] stat;
    begin
        // NADV phase: latch address 0x4
        @(posedge fsmc_clk); #1;
        fsmc_ne   = 0;
        ad_drive  = 4'h4;
        ad_oe     = 1;
        fsmc_nadv = 0;
        @(posedge fsmc_clk); #1;
        fsmc_nadv = 1;
        ad_oe     = 0;

        // NOE: status has no stall (NWAIT never asserted)
        fsmc_noe = 0;
        @(posedge fsmc_clk); #6;   // one cycle for FSM + ACCESS_DELAY
        stat = fsmc_ad;

        fsmc_noe = 1;
        fsmc_ne  = 1;
        @(posedge fsmc_clk); #1;
    end
endtask

// ---------------------------------------------------------------------------
// Stimulus
// ---------------------------------------------------------------------------
integer test_fail = 0;
reg [15:0] rbuf;
reg  [3:0] stat;
integer k;

initial begin
    $dumpfile("FSMCTest.vcd");
    $dumpvars(0, FSMCTest);

    // Reset
    reset_n = 0;
    repeat(10) @(posedge fsmc_clk);
    reset_n = 1;

    // Wait for PSRAM power-up + self-test (~150 µs at 50 MHz = 7500 sys_clk cycles)
    $display("=== Waiting for PSRAM self-test ===");
    repeat(8500) @(posedge sys_clk);
    $display("  psram_is_valid=%b (expect 1)", psram_is_valid);
    if (!psram_is_valid) begin
        $display("  *** SELF-TEST FAILED ***");
        test_fail = test_fail + 1;
    end

    // ------------------------------------------------------------------
    // TEST 1: Write two words, read them back
    // ------------------------------------------------------------------
    $display("\n--- TEST 1: write 0xA5C3, 0x1234 ---");
    fsmc_write_word(16'hA5C3);
    wait_psram_idle;
    fsmc_write_word(16'h1234);
    wait_psram_idle;

    $display("--- TEST 1: read back ---");
    fsmc_read_word(rbuf);
    $display("  Word 0: got=0x%04H  exp=0xA5C3  %s", rbuf,
             (rbuf === 16'hA5C3) ? "PASS" : "FAIL");
    if (rbuf !== 16'hA5C3) test_fail = test_fail + 1;

    fsmc_read_word(rbuf);
    $display("  Word 1: got=0x%04H  exp=0x1234  %s", rbuf,
             (rbuf === 16'h1234) ? "PASS" : "FAIL");
    if (rbuf !== 16'h1234) test_fail = test_fail + 1;

    // ------------------------------------------------------------------
    // TEST 2: Fill FIFO then read all back
    // ------------------------------------------------------------------
    $display("\n--- TEST 2: fill FIFO (%0d words) ---", PSRAM_FIFO_DEPTH);
    for (k = 0; k < PSRAM_FIFO_DEPTH; k = k + 1) begin
        fsmc_write_word(k * 16'h0101);
        wait_psram_idle;
    end
    for (k = 0; k < PSRAM_FIFO_DEPTH; k = k + 1) begin
        fsmc_read_word(rbuf);
        $display("  [%0d] got=0x%04H  exp=0x%04H  %s",
                 k, rbuf, k * 16'h0101,
                 (rbuf === k * 16'h0101) ? "PASS" : "FAIL");
        if (rbuf !== k * 16'h0101) test_fail = test_fail + 1;
    end

    // ------------------------------------------------------------------
    // TEST 3: Status register (address 0x4)
    //   After FIFO drained: empty=1, full=0, is_valid=1  → nibble = 4'b0101
    //   Write one word:     empty=0, full=0, is_valid=1  → nibble = 4'b0100
    // ------------------------------------------------------------------
    $display("\n--- TEST 3: status register ---");

    // FIFO is empty after TEST 2 - check status
    repeat(5) @(posedge fsmc_clk);  // let CDC settle
    fsmc_read_status(stat);
    $display("  After drain:  stat=%b  empty=%b full=%b valid=%b  (exp 1 0 1)",
             stat, stat[0], stat[1], stat[2]);
    if (stat[0] !== 1'b1 || stat[1] !== 1'b0 || stat[2] !== 1'b1)
        test_fail = test_fail + 1;

    // Write one word then check again
    fsmc_write_word(16'hBEEF);
    wait_psram_idle;
    fsmc_read_status(stat);
    $display("  After 1 write: stat=%b  empty=%b full=%b valid=%b  (exp 0 0 1)",
             stat, stat[0], stat[1], stat[2]);
    if (stat[0] !== 1'b0 || stat[1] !== 1'b0 || stat[2] !== 1'b1)
        test_fail = test_fail + 1;

    // Drain and verify
    fsmc_read_word(rbuf);
    $display("  Drained word: 0x%04H  exp=0xBEEF  %s", rbuf,
             (rbuf === 16'hBEEF) ? "PASS" : "FAIL");
    if (rbuf !== 16'hBEEF) test_fail = test_fail + 1;

    // ------------------------------------------------------------------
    // Summary
    // ------------------------------------------------------------------
    $display("\n========================================");
    if (test_fail == 0)
        $display("  ALL TESTS PASSED");
    else
        $display("  FAILURES: %0d", test_fail);
    $display("========================================\n");
    $finish;
end

// Watchdog
initial begin
    #500_000_000;
    $display("WATCHDOG TIMEOUT");
    $finish;
end

endmodule
