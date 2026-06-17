// =============================================================================
// psram_fifo_tb.v
// Testbench for psram_fifo.v
//
// Includes a simple behavioral model of the APS6404L that:
//   - Responds to Write (0x02)  : stores bytes at the addressed location
//   - Responds to Fast Read (0x0B): returns stored bytes after 8 dummy clocks
//   - Responds to Reset-Enable + Reset sequence
//   - The model ignores SPI commands while CE# is HIGH (standby)
//
// Test sequence:
//   1. Wait for power-up + hardware reset to complete
//   2. Write 4 entries into the FIFO
//   3. Read back all 4 entries and verify they match
//   4. Test FIFO full detection (write past depth limit)
//   5. Test reset clears FIFO pointers
// =============================================================================

`timescale 1ns/1ps

module psram_fifo_tb;

// ---------------------------------------------------------------------------
// Parameters – must match DUT
// ---------------------------------------------------------------------------
parameter nADC        = 4;
parameter CLK_DIV     = 4;
parameter SYS_CLK_MHZ = 50;
parameter FIFO_DEPTH  = 8;    // small for fast simulation
parameter ENTRY_BITS  = nADC * 16;

// ---------------------------------------------------------------------------
// Clock & reset
// ---------------------------------------------------------------------------
reg sys_clk = 0;
reg reset_n = 0;

localparam CLK_PERIOD = 1000 / SYS_CLK_MHZ; // ns  (20 ns for 50 MHz)
always #(CLK_PERIOD/2) sys_clk = ~sys_clk;

// ---------------------------------------------------------------------------
// DUT signals
// ---------------------------------------------------------------------------
reg  [ENTRY_BITS-1:0] data_in;
reg                   wr_toggle;
reg                   rd_toggle;
wire [ENTRY_BITS-1:0] data_out;
wire                  data_valid;
wire                  fifo_full;
wire                  fifo_empty;
wire                  psram_sclk;
wire                  psram_ce_n;
wire                  psram_si;
wire                  psram_so;

// ---------------------------------------------------------------------------
// DUT instantiation
// ---------------------------------------------------------------------------
psram_fifo #(
    .nADC        (nADC),
    .CLK_DIV     (CLK_DIV),
    .SYS_CLK_MHZ (SYS_CLK_MHZ),
    .FIFO_DEPTH  (FIFO_DEPTH)
) dut (
    .sys_clk   (sys_clk),
    .reset_n   (reset_n),
    .data_in   (data_in),
    .wr_toggle (wr_toggle),
    .rd_toggle (rd_toggle),
    .data_out  (data_out),
    .data_valid(data_valid),
    .fifo_full (fifo_full),
    .fifo_empty(fifo_empty),
    .psram_sclk(psram_sclk),
    .psram_ce_n(psram_ce_n),
    .psram_si  (psram_si),
    .psram_so  (psram_so)
);

// ---------------------------------------------------------------------------
// Behavioral PSRAM Model (APS6404L – SPI mode subset)
// ---------------------------------------------------------------------------
// 64 KB of RAM for the model (enough for small FIFO_DEPTH tests)
reg [7:0] psram_mem [0:65535];

// SPI receiver state machine
reg [7:0]  rx_byte;
reg [4:0]  rx_bit_cnt;
reg [2:0]  byte_cnt;       // how many bytes received this CE# cycle
reg [7:0]  rx_cmd;
reg [23:0] rx_addr;
reg        rsten_received;  // Reset-Enable received flag

// ---------------------------------------------------------------------------
// Single unambiguous bit-position counter for the whole transaction.
// bit_pos counts every bit-period from CE# low:
//   bits 0..7    : command byte      (sampled on rising edges by rx block)
//   bits 8..31   : 24-bit address    (sampled on rising edges by rx block)
//   bits 32..39  : 8 dummy clocks (Fast Read 'h0B only)
//   bits 40..    : data bits, MSB first, 8 bits per byte
// This single counter is incremented on every RISING edge of sclk (the same
// edge convention the DUT itself uses for its own bit/dummy counters), so
// there is no risk of the rx-side and tx-side getting out of step with each
// other or with the DUT.
// ---------------------------------------------------------------------------
integer bit_pos;
localparam CMD_BITS    = 8;
localparam ADDR_BITS_M = 24;
localparam DUMMY_BITS  = 8;
localparam HDR_BITS    = CMD_BITS + ADDR_BITS_M;            // 32
localparam DATA_START  = HDR_BITS + DUMMY_BITS;             // 40 (Fast Read only)

// SO driven by model
reg psram_so_reg;
assign psram_so = (psram_ce_n) ? 1'bz : psram_so_reg;

// SPI model: shift on falling edge, sample on rising edge (mode 0)
integer i;
initial begin
    psram_so_reg   = 1'b0;
    rx_bit_cnt     = 0;
    byte_cnt       = 0;
    rsten_received = 0;
    bit_pos        = 0;
    // Pre-fill memory with 0
    for (i = 0; i < 65536; i = i + 1)
        psram_mem[i] = 8'hA5;   // recognisable pattern before any write
end

// CE# rising edge: end of transaction
always @(posedge psram_ce_n) begin
    rx_bit_cnt   <= 0;
    byte_cnt     <= 0;
    bit_pos      <= 0;
    psram_so_reg <= 1'b0;
end

// CE# falling edge: start of transaction - reset counters
always @(negedge psram_ce_n) begin
    rx_bit_cnt <= 0;
    byte_cnt   <= 0;
    bit_pos    <= 0;
end

// Rising sclk: sample SI (command + address phase), and advance bit_pos.
// bit_pos is advanced here (rising edge) for every bit of the transaction,
// command/address/dummy/data alike, so it always reflects "how many rising
// edges have occurred since CE# went low", matching the DUT's own counters
// bit-for-bit.
always @(posedge psram_sclk) begin
    if (!psram_ce_n) begin
        bit_pos <= bit_pos + 1;

        if (bit_pos < HDR_BITS) begin
            // Command or address phase: shift SI into rx_byte
            rx_byte    <= {rx_byte[6:0], psram_si};
            rx_bit_cnt <= rx_bit_cnt + 1;

            if (rx_bit_cnt == 7) begin
                rx_bit_cnt <= 0;

                case (byte_cnt)
                0: begin // Command byte
                    rx_cmd   <= {rx_byte[6:0], psram_si};
                    byte_cnt <= byte_cnt + 1;

                    if ({rx_byte[6:0], psram_si} == 8'h99 && rsten_received) begin
                        $display("[PSRAM MODEL] Reset command received at t=%0t", $time);
                        rsten_received <= 0;
                    end else if ({rx_byte[6:0], psram_si} == 8'h66) begin
                        rsten_received <= 1;
                        $display("[PSRAM MODEL] Reset-Enable received at t=%0t", $time);
                    end else begin
                        rsten_received <= 0;
                    end
                end
                1: begin // Address byte 2 (MSB)
                    rx_addr[23:16] <= {rx_byte[6:0], psram_si};
                    byte_cnt       <= byte_cnt + 1;
                end
                2: begin // Address byte 1
                    rx_addr[15:8] <= {rx_byte[6:0], psram_si};
                    byte_cnt      <= byte_cnt + 1;
                end
                3: begin // Address byte 0 (LSB)
                    rx_addr[7:0] <= {rx_byte[6:0], psram_si};
                    byte_cnt     <= byte_cnt + 1;
                    if (rx_cmd == 8'h02)
                        $display("[PSRAM MODEL] Write cmd to addr 0x%06X at t=%0t",
                                 {rx_addr[23:8], {rx_byte[6:0], psram_si}}, $time);
                    else if (rx_cmd == 8'h0B)
                        $display("[PSRAM MODEL] Fast Read cmd to addr 0x%06X at t=%0t",
                                 {rx_addr[23:8], {rx_byte[6:0], psram_si}}, $time);
                end
                default: ; // unreachable while bit_pos < HDR_BITS
                endcase
            end
        end else if (rx_cmd == 8'h02) begin
            // Write data phase: every 8 rising edges, latch one byte and
            // advance the write address. byte_cnt keeps counting here purely
            // for bookkeeping / readability; the actual byte boundary is
            // derived from bit_pos so it can't drift out of sync with the
            // header phase above.
            rx_byte <= {rx_byte[6:0], psram_si};
            if ((bit_pos - HDR_BITS) % 8 == 7) begin
                psram_mem[rx_addr] <= {rx_byte[6:0], psram_si};
                rx_addr <= rx_addr + 1;
            end
        end
        // For Fast Read (0x0B), bits at/after HDR_BITS are dummy clocks and
        // then data - SI is don't-care and SO is driven by the falling-edge
        // block below, keyed off the same bit_pos counter.
    end
end

// Falling sclk: drive SO for reads. SO must be valid *before* the next
// rising edge so the DUT can sample it there - so on each falling edge we
// pre-compute the value for bit_pos (which has already been incremented to
// reflect the upcoming rising edge's index).
always @(negedge psram_sclk) begin
    if (!psram_ce_n && rx_cmd == 8'h0B && bit_pos >= DATA_START) begin
        // Which data bit (0 = MSB of first output byte) are we about to
        // present for the next rising edge?
        psram_so_reg <= read_bit(rx_addr, bit_pos - DATA_START);
    end else begin
        psram_so_reg <= 1'b0;
    end
end

// Returns bit 'bitnum' (0 = MSB) of the byte stream starting at psram_mem[base_addr],
// reading sequentially through memory (MSB-first per byte, byte address increasing).
function read_bit;
    input [23:0] base_addr;
    input integer bitnum;
    reg [23:0] byte_offset;
    reg [2:0]  bit_in_byte;
    begin
        byte_offset = bitnum >> 3;          // which byte (0,1,2,...)
        bit_in_byte = 3'd7 - (bitnum & 3'h7); // 0=>bit7 (MSB) ... 7=>bit0 (LSB)
        read_bit = psram_mem[base_addr + byte_offset][bit_in_byte];
    end
endfunction

// ---------------------------------------------------------------------------
// Helper task: toggle write
// ---------------------------------------------------------------------------
task do_write;
    input [ENTRY_BITS-1:0] wdata;
    integer timeout;
    begin
        @(posedge sys_clk);
        data_in   <= wdata;
        wr_toggle <= ~wr_toggle;
        @(posedge sys_clk);

        // Wait for the transaction to actually start (CE# goes low).
        // Use a timeout so a real DUT bug shows up as an error, not a hang.
        timeout = 0;
        while (psram_ce_n !== 1'b0 && timeout < 2000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 2000)
            $display("  *** TIMEOUT waiting for write CE# low at t=%0t ***", $time);

        // Wait for the transaction to finish (CE# goes back high).
        timeout = 0;
        while (psram_ce_n !== 1'b1 && timeout < 2000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 2000)
            $display("  *** TIMEOUT waiting for write CE# high at t=%0t ***", $time);

        // Extra settling time
        repeat(10) @(posedge sys_clk);
    end
endtask

// ---------------------------------------------------------------------------
// Helper task: toggle read and capture data
// ---------------------------------------------------------------------------
task do_read;
    output [ENTRY_BITS-1:0] rdata;
    integer timeout;
    begin
        @(posedge sys_clk);
        rd_toggle <= ~rd_toggle;
        @(posedge sys_clk);

        // Wait for the transaction to actually start (CE# goes low).
        timeout = 0;
        while (psram_ce_n !== 1'b0 && timeout < 2000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 2000)
            $display("  *** TIMEOUT waiting for read CE# low at t=%0t ***", $time);

        // Wait for the transaction to finish (CE# goes back high) AND
        // for data_valid to assert. Poll level, don't wait on an edge that
        // may have already passed.
        timeout = 0;
        while (!(psram_ce_n === 1'b1 && data_valid === 1'b1) && timeout < 2000) begin
            @(posedge sys_clk);
            timeout = timeout + 1;
        end
        if (timeout >= 2000)
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
    $dumpfile("psram_fifo_tb.vcd");
    $dumpvars(0, psram_fifo_tb);

    // Initialise control signals
    data_in   = 0;
    wr_toggle = 0;
    rd_toggle = 0;

    // Fill test vectors with recognisable patterns
    for (k = 0; k < 8; k = k + 1)
        test_vectors[k] = { {nADC{16'h0}} } | (k * {nADC{16'h1111}});
    // e.g. k=0 → 0x0000_0000_0000_0000
    //      k=1 → 0x1111_1111_1111_1111
    //      k=2 → 0x2222_2222_2222_2222  etc.

    // ----------------------------------------------------------------
    // Apply reset
    // ----------------------------------------------------------------
    $display("\n=== Applying reset ===");
    reset_n = 0;
    repeat(10) @(posedge sys_clk);
    reset_n = 1;

    // ----------------------------------------------------------------
    // Wait for power-up sequence (150 µs + reset + idle)
    // The DUT does S_PU_WAIT → S_RST_EN → S_RST_CMD → S_RST_WAIT → S_IDLE
    // At 50 MHz: 150 µs = 7500 cycles.  Allow some margin.
    // ----------------------------------------------------------------
    $display("=== Waiting for PSRAM power-up sequence ... ===");
    // Wait until DUT asserts CE# high after the reset sequence
    // (After S_RST_WAIT it goes to S_IDLE where CE# stays high)
    // A safe upper bound: 8000 cycles @ 50 MHz
    repeat (8200) @(posedge sys_clk);
    $display("=== Power-up done, starting tests at t=%0t ===", $time);

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
        $display("  Read entry %0d: got=0x%H  exp=0x%H  %s",
                 k, read_back, test_vectors[k],
                 (read_back === test_vectors[k]) ? "PASS" : "FAIL");
        if (read_back !== test_vectors[k]) test_fail = test_fail + 1;
    end
    $display("  fifo_empty=%b", fifo_empty);

    // ----------------------------------------------------------------
    // TEST 3: Write until FIFO full
    // ----------------------------------------------------------------
    $display("\n--- TEST 3: Fill FIFO to capacity (%0d entries) ---", FIFO_DEPTH);
    for (k = 0; k < FIFO_DEPTH; k = k + 1) begin
        if (!fifo_full) begin
            do_write(test_vectors[k % 8]);
            $display("  Wrote entry %0d, count OK", k);
        end else begin
            $display("  FIFO reported full at entry %0d (expected at %0d) - %s",
                     k, FIFO_DEPTH,
                     (k == FIFO_DEPTH) ? "PASS" : "FAIL");
        end
    end
    $display("  fifo_full=%b (expect 1)", fifo_full);
    if (!fifo_full) test_fail = test_fail + 1;

    // ----------------------------------------------------------------
    // TEST 4: Attempt write when full – wr_pending should be ignored
    // ----------------------------------------------------------------
    $display("\n--- TEST 4: Write when full (should be ignored) ---");
    data_in   <= {ENTRY_BITS{1'b1}};
    wr_toggle <= ~wr_toggle;
    repeat(20) @(posedge sys_clk);
    $display("  fifo_full still = %b (expect 1)", fifo_full);

    // ----------------------------------------------------------------
    // TEST 5: Reset clears FIFO
    // ----------------------------------------------------------------
    $display("\n--- TEST 5: Reset clears FIFO ---");
    reset_n = 0;
    repeat(5) @(posedge sys_clk);
    reset_n = 1;
    repeat(3) @(posedge sys_clk);
    $display("  After reset: fifo_empty=%b (expect 1)  fifo_full=%b (expect 0)",
             fifo_empty, fifo_full);
    if (!fifo_empty) test_fail = test_fail + 1;

    // Re-run power-up wait
    repeat(8200) @(posedge sys_clk);

    // ----------------------------------------------------------------
    // TEST 6: Single write + read after reset
    // ----------------------------------------------------------------
    $display("\n--- TEST 6: Single write/read after reset ---");
    do_write(64'hDEADBEEFCAFEBABE);
    do_read(read_back);
    $display("  Read: 0x%H  (exp 0xDEADBEEFCAFEBABE)  %s",
             read_back,
             (read_back === 64'hDEADBEEFCAFEBABE) ? "PASS" : "FAIL");
    if (read_back !== 64'hDEADBEEFCAFEBABE) test_fail = test_fail + 1;

    // ----------------------------------------------------------------
    // Result summary
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
    #200_000_000; // 200 ms sim limit
    $display("WATCHDOG TIMEOUT");
    $finish;
end

endmodule