// =============================================================================
// PSRAMTest.v  –  Testbench for PSRAM.v + aps6404l_behavioral_model.v
//
// DUT  : PSRAM  (PSRAM.v)
// Model: aps6404l_behavioral_model  (aps6404l_behavioral_model.v)
//
// Test sequence:
//   1. Power-up + hardware reset (DUT issues Reset-Enable / Reset internally)
//   2. Write 4 entries
//   3. Read back 4 entries and verify
//   4. Fill FIFO to capacity, verify fifo_full
//   5. Reset, verify fifo_empty
//   6. Single write + read after reset
// =============================================================================

`timescale 1ns/1ps

module PSRAMTest;

// ---------------------------------------------------------------------------
// Parameters – must match DUT instantiation below
// ---------------------------------------------------------------------------
parameter nADC        = 4;
parameter CLK_DIV     = 4;
parameter SYS_CLK_MHZ = 50;
parameter FIFO_DEPTH  = 8;    // small for fast simulation

localparam ENTRY_BITS = nADC * 16;
localparam CLK_PERIOD = 1000 / SYS_CLK_MHZ; // ns

// ---------------------------------------------------------------------------
// Clock & reset
// ---------------------------------------------------------------------------
reg sys_clk = 0;
reg reset_n = 0;

always #(CLK_PERIOD/2) sys_clk = ~sys_clk;

// ---------------------------------------------------------------------------
// DUT signals
// ---------------------------------------------------------------------------
reg  [ENTRY_BITS-1:0] data_in   = 0;
reg                   wr_toggle = 0;
reg                   rd_toggle = 0;
wire [ENTRY_BITS-1:0] data_out;
wire                  data_valid;
wire                  fifo_full;
wire                  fifo_empty;
wire                  is_valid;

// QSPI bus wires between DUT and chip model
wire        psram_sclk;
wire        psram_ce_n;
wire [3:0]  psram_sio_out;
wire [3:0]  psram_sio_in;
wire        psram_sio_oe;

// ---------------------------------------------------------------------------
// DUT: PSRAM controller
// ---------------------------------------------------------------------------
PSRAM #(
    .nADC        (nADC),
    .CLK_DIV     (CLK_DIV),
    .SYS_CLK_MHZ (SYS_CLK_MHZ),
    .FIFO_DEPTH  (FIFO_DEPTH)
) dut (
    .sys_clk     (sys_clk),
    .reset_n     (reset_n),
    .data_in     (data_in),
    .wr_toggle   (wr_toggle),
    .rd_toggle   (rd_toggle),
    .data_out    (data_out),
    .data_valid  (data_valid),
    .fifo_full   (fifo_full),
    .fifo_empty  (fifo_empty),
    .is_valid    (is_valid),
    .psram_sclk  (psram_sclk),
    .psram_ce_n  (psram_ce_n),
    .psram_sio_out(psram_sio_out),
    .psram_sio_in (psram_sio_in),
    .psram_sio_oe (psram_sio_oe)
);

// ---------------------------------------------------------------------------
// Chip model: APS6404L behavioral model
// SIO bus: when FPGA drives (oe=1) model sees psram_sio_out,
//          when chip drives (oe=0) FPGA sees model's sio_out.
// ---------------------------------------------------------------------------
wire [3:0] model_sio_out;

aps6404l_behavioral_model #(
    .MEM_BYTES (4096)
) psram_model (
    .sclk    (psram_sclk),
    .ce_n    (psram_ce_n),
    .sio_in  (psram_sio_out),   // model always sees what FPGA drives
    .sio_out (model_sio_out)
);

// FPGA samples model output when chip is driving (oe=0)
assign psram_sio_in = psram_sio_oe ? 4'bz : model_sio_out;

// ---------------------------------------------------------------------------
// Helper task: issue one write and wait for it to complete
// ---------------------------------------------------------------------------
task do_write;
    input [ENTRY_BITS-1:0] wdata;
    integer timeout;
    begin
        @(posedge sys_clk);
        data_in   <= wdata;
        wr_toggle <= ~wr_toggle;
        @(posedge sys_clk);

        timeout = 0;
        while (psram_ce_n !== 1'b0 && timeout < 4000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 4000)
            $display("  *** TIMEOUT waiting for write CE# low at t=%0t ***", $time);

        timeout = 0;
        while (psram_ce_n !== 1'b1 && timeout < 4000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 4000)
            $display("  *** TIMEOUT waiting for write CE# high at t=%0t ***", $time);

        repeat(10) @(posedge sys_clk);
    end
endtask

// ---------------------------------------------------------------------------
// Helper task: issue one read and capture result
// ---------------------------------------------------------------------------
task do_read;
    output [ENTRY_BITS-1:0] rdata;
    integer timeout;
    begin
        @(posedge sys_clk);
        rd_toggle <= ~rd_toggle;
        @(posedge sys_clk);

        timeout = 0;
        while (psram_ce_n !== 1'b0 && timeout < 4000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 4000)
            $display("  *** TIMEOUT waiting for read CE# low at t=%0t ***", $time);

        timeout = 0;
        while (!(psram_ce_n === 1'b1 && data_valid === 1'b1) && timeout < 4000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 4000)
            $display("  *** TIMEOUT waiting for data_valid at t=%0t ***", $time);

        rdata = data_out;
        repeat(5) @(posedge sys_clk);
    end
endtask

// ---------------------------------------------------------------------------
// Test stimulus
// ---------------------------------------------------------------------------
reg [ENTRY_BITS-1:0] test_vectors [0:7];
reg [ENTRY_BITS-1:0] read_back;
integer test_fail = 0;
integer k;

initial begin
    $dumpfile("PSRAMTest.vcd");
    $dumpvars(0, PSRAMTest);

    for (k = 0; k < 8; k = k + 1)
        test_vectors[k] = {nADC{16'h0000}} | (k * {nADC{16'h1111}});

    // ----------------------------------------------------------------
    // Apply reset
    // ----------------------------------------------------------------
    $display("\n=== Applying reset ===");
    reset_n = 0;
    repeat(10) @(posedge sys_clk);
    reset_n = 1;

    // ----------------------------------------------------------------
    // Wait for DUT power-up sequence (150 µs + RSTEN + RST + tRST)
    // 150 µs × 50 MHz = 7500 cycles.  Allow margin.
    // ----------------------------------------------------------------
    $display("=== Waiting for PSRAM power-up + self-test ... ===");
    repeat(8200) @(posedge sys_clk);
    $display("=== Power-up done at t=%0t  is_valid=%b ===", $time, is_valid);
    if (!is_valid) begin
        $display("  *** SELF-TEST FAILED: is_valid=0 ***");
        test_fail = test_fail + 1;
    end else
        $display("  Self-test: PASS");

    // ----------------------------------------------------------------
    // TEST 1: Write 4 entries
    // ----------------------------------------------------------------
    $display("\n--- TEST 1: Write 4 entries ---");
    for (k = 0; k < 4; k = k + 1) begin
        $display("  Writing entry %0d: 0x%H", k, test_vectors[k]);
        do_write(test_vectors[k]);
    end
    $display("  fifo_empty=%b  fifo_full=%b", fifo_empty, fifo_full);

    // ----------------------------------------------------------------
    // TEST 2: Read back and verify
    // ----------------------------------------------------------------
    $display("\n--- TEST 2: Read back 4 entries ---");
    for (k = 0; k < 4; k = k + 1) begin
        do_read(read_back);
        $display("  Entry %0d: got=0x%H  exp=0x%H  %s",
                 k, read_back, test_vectors[k],
                 (read_back === test_vectors[k]) ? "PASS" : "FAIL");
        if (read_back !== test_vectors[k]) test_fail = test_fail + 1;
    end
    $display("  fifo_empty=%b (expect 1)", fifo_empty);

    // ----------------------------------------------------------------
    // TEST 3: Fill FIFO to capacity
    // ----------------------------------------------------------------
    $display("\n--- TEST 3: Fill FIFO (%0d entries) ---", FIFO_DEPTH);
    for (k = 0; k < FIFO_DEPTH; k = k + 1) begin
        if (!fifo_full) begin
            do_write(test_vectors[k % 8]);
            $display("  Wrote entry %0d", k);
        end else begin
            $display("  FIFO full at k=%0d (expected at %0d): %s",
                     k, FIFO_DEPTH,
                     (k == FIFO_DEPTH) ? "PASS" : "FAIL");
        end
    end
    $display("  fifo_full=%b (expect 1)", fifo_full);
    if (!fifo_full) test_fail = test_fail + 1;

    // ----------------------------------------------------------------
    // TEST 4: Write when full – should be silently dropped
    // ----------------------------------------------------------------
    $display("\n--- TEST 4: Write when full (should be ignored) ---");
    data_in   <= {ENTRY_BITS{1'b1}};
    wr_toggle <= ~wr_toggle;
    repeat(20) @(posedge sys_clk);
    $display("  fifo_full=%b (expect 1)", fifo_full);

    // ----------------------------------------------------------------
    // TEST 5: Reset clears FIFO
    // ----------------------------------------------------------------
    $display("\n--- TEST 5: Reset clears FIFO ---");
    reset_n = 0;
    repeat(5) @(posedge sys_clk);
    reset_n = 1;
    repeat(3) @(posedge sys_clk);
    $display("  fifo_empty=%b (expect 1)  fifo_full=%b (expect 0)", fifo_empty, fifo_full);
    if (!fifo_empty) test_fail = test_fail + 1;

    repeat(8200) @(posedge sys_clk);
    $display("  is_valid after re-init=%b (expect 1)", is_valid);
    if (!is_valid) test_fail = test_fail + 1;

    // ----------------------------------------------------------------
    // TEST 6: Single write + read after reset
    // ----------------------------------------------------------------
    $display("\n--- TEST 6: Single write/read after reset ---");
    do_write(64'hDEADBEEFCAFEBABE);
    do_read(read_back);
    $display("  got=0x%H  exp=0xDEADBEEFCAFEBABE  %s",
             read_back,
             (read_back === 64'hDEADBEEFCAFEBABE) ? "PASS" : "FAIL");
    if (read_back !== 64'hDEADBEEFCAFEBABE) test_fail = test_fail + 1;

    // ----------------------------------------------------------------
    // Summary
    // ----------------------------------------------------------------
    $display("\n========================================");
    if (test_fail == 0)
        $display("  ALL TESTS PASSED");
    else
        $display("  FAILURES: %0d", test_fail);
    $display("========================================\n");

    $finish;
end

// Safety watchdog
initial begin
    #200_000_000;
    $display("WATCHDOG TIMEOUT");
    $finish;
end

endmodule
