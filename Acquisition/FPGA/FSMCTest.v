// =====================================================================
// tb_fsmc_muxed_burst_psram.v
//
// Self-checking testbench for fsmc_muxed_burst_psram.v.
// Acts as the STM32F407 FSMC master: drives the address phase via NADV,
// then either pulses NWE (write) or asserts NOE + clocks FSMC_CLK with
// NWAIT polling (burst read).
//
// Run with Icarus Verilog:
//   iverilog -o sim fsmc_muxed_burst_psram.v tb_fsmc_muxed_burst_psram.v
//   vvp sim
//   gtkwave tb_fsmc_muxed_burst_psram.vcd   (optional waveform)
// =====================================================================

`timescale 1ns/1ps

module tb_fsmc_muxed_burst_psram;

    localparam LATENCY_CYCLES  = 2;
    localparam WAIT_ACTIVE_LOW = 1;
    localparam CLK_PERIOD      = 20;  // ns => 50 MHz FSMC_CLK

    // ---- bus signals (TB is the master) ----
    reg  [7:0] ad_drive;
    reg        ad_oe;      // 1 = TB drives FSMC_AD
    reg        ne, nadv, noe, nwe, clk;

    wire [7:0] fsmc_ad    = ad_oe ? ad_drive : 8'bz;
    wire       fsmc_nwait;

    integer pass_count = 0;
    integer fail_count = 0;

    // ---- DUT ----
    FSMC #(
        .LATENCY_CYCLES (LATENCY_CYCLES),
        .WAIT_ACTIVE_LOW(WAIT_ACTIVE_LOW),
        .ACCESS_DELAY   (5)
    ) dut (
        .fsmc_ad   (fsmc_ad),
        .fsmc_ne   (ne),
        .fsmc_nadv (nadv),
        .fsmc_noe  (noe),
        .fsmc_nwe  (nwe),
        .fsmc_clk  (clk),
        .fsmc_nwait(fsmc_nwait)
    );

    // free-running clock
    initial clk = 0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // ---- reference model ----
    function [7:0] expected_byte;
        input [7:0] a;
        begin
            expected_byte = {a[3:0], a[7:4]};
        end
    endfunction

    // ---- capture buffer ----
    reg [7:0] rd_data [0:63];

    // ---- BFM tasks ----

    // Address phase common to reads and writes
    task drive_address;
        input [7:0] address;
        begin
            ad_drive = address;
            ad_oe    = 1'b1;
            ne       = 1'b0;
            nadv     = 1'b0;
            #15;            // address setup time
            nadv     = 1'b1;
            #2;
        end
    endtask

    // Burst-read `length` bytes from `start_addr` into rd_data[]
    task burst_read;
        input  [7:0]  start_addr;
        input  integer length;
        integer i;
        begin
            drive_address(start_addr);
            ad_oe = 1'b0;   // release bus — DUT drives it from now on
            noe   = 1'b0;

            i = 0;
            while (i < length) begin
                @(posedge clk);
                #7;         // wait past ACCESS_DELAY for signals to settle
                if (fsmc_nwait === (WAIT_ACTIVE_LOW ? 1'b1 : 1'b0)) begin
                    rd_data[i] = fsmc_ad;
                    i = i + 1;
                end
                // NWAIT says "wait" — poll again next clock
            end

            noe = 1'b1;
            ne  = 1'b1;
            #10;
        end
    endtask

    task burst_write;
        input [7:0] address;
        input [7:0] wdata;
        begin
            drive_address(address);
            ad_drive = wdata;
            nwe      = 1'b0;
            #20;
            nwe      = 1'b1;
            #10;
            ad_oe    = 1'b0;
            ne       = 1'b1;
            #10;
        end
    endtask

    task check_burst;
        input [7:0]  start_addr;
        input integer length;
        integer   i;
        reg [7:0] cur, exp;
        reg       ok;
        begin
            burst_read(start_addr, length);
            ok = 1'b1;
            for (i = 0; i < length; i = i + 1) begin
                cur = start_addr + i;           // 8-bit: wraps naturally
                exp = expected_byte(cur);
                if (rd_data[i] !== exp) begin
                    ok = 1'b0;
                    $display("  FAIL beat %0d  addr=0x%02h  expected=0x%02h  got=0x%02h",
                             i, cur, exp, rd_data[i]);
                end
            end
            if (ok) begin
                pass_count = pass_count + 1;
                $display("PASS  start=0x%02h len=%0d", start_addr, length);
            end else begin
                fail_count = fail_count + 1;
                $display("FAIL  start=0x%02h len=%0d", start_addr, length);
            end
        end
    endtask

    integer k;
    reg [7:0] rnd_addr;

    initial begin
        $dumpfile("tb_fsmc_muxed_burst_psram.vcd");
        $dumpvars(0, tb_fsmc_muxed_burst_psram);

        ad_drive = 0; ad_oe = 0;
        ne = 1; nadv = 1; noe = 1; nwe = 1;
        #50;

        $display("=================================================");
        $display(" Single-byte reads");
        $display("=================================================");
        check_burst(8'hAB, 1);   // 0xAB -> expect 0xBA
        check_burst(8'h00, 1);
        check_burst(8'hFF, 1);
        check_burst(8'h12, 1);
        check_burst(8'hCD, 1);

        $display("=================================================");
        $display(" True bursts");
        $display("=================================================");
        check_burst(8'h20, 8);
        check_burst(8'hFC, 8);   // wraps past 0xFF -> 0x00

        $display("=================================================");
        $display(" Randomised burst reads");
        $display("=================================================");
        for (k = 0; k < 10; k = k + 1) begin
            rnd_addr = $random;
            check_burst(rnd_addr, 4);
        end

        $display("=================================================");
        $display(" Write test (read-back must not change)");
        $display("=================================================");
        burst_write(8'hAB, 8'h55);
        check_burst(8'hAB, 1);   // must still return 0xBA

        $display("=================================================");
        $display(" Summary: %0d passed, %0d failed", pass_count, fail_count);
        $display("=================================================");
        if (fail_count == 0)
            $display("ALL TESTS PASSED");
        else
            $display("SOME TESTS FAILED");

        $finish;
    end

endmodule