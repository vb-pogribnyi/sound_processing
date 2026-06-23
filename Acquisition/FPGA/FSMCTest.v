// =====================================================================
// tb_write_basic.v - basic FSMC write -> FIFO push, two words back-to-back
//
// Writes two 16-bit words via 4 nibble writes each (addr 0,1,2,3), then
// reads both back to confirm they landed in the FIFO in the right order
// with the right values. Focus of this waveform: nibble accumulation
// timing on NWE, and the push trigger on the write to address 3.
//
// Run:
//   iverilog -o sim_write_basic tb_write_basic.v FSMC.v PSRAM.v aps6404l_behavioral_model.v
//   vvp sim_write_basic
//   gtkwave wave_write_basic.vcd
// =====================================================================
`timescale 1ns/1ps

module tb_write_basic;

    localparam FSMC_CLK_HALF_PERIOD = 11;  // ~23 ns period (~43 MHz), arbitrary
    localparam SYS_CLK_HALF_PERIOD  = 5;   // 10 ns period (100 MHz), arbitrary, async to fsmc_clk
    localparam BFM_WAIT_ACTIVE_LOW  = 0;   // must match FSMC's WAIT_ACTIVE_LOW below

    `include "fsmc_tb_common.vh"

    FSMC #(
        .WAIT_ACTIVE_LOW   (BFM_WAIT_ACTIVE_LOW),
        .PSRAM_CLK_DIV     (2),
        .PSRAM_SYS_CLK_MHZ (1)    // shrunk for a fast/clean simulation - see FSMC.v header note
    ) dut_fsmc (
        .fsmc_ad    (fsmc_ad),
        .fsmc_ne    (ne),
        .fsmc_nadv  (nadv),
        .fsmc_noe   (noe),
        .fsmc_nwe   (nwe),
        .fsmc_clk   (fsmc_clk),
        .fsmc_nwait (fsmc_nwait),
        .sys_clk    (sys_clk),
        .reset_n    (reset_n),
        .psram_sclk (psram_sclk),
        .psram_ce_n (psram_ce_n),
        .psram_si   (psram_si),
        .psram_so   (psram_so)
    );

    aps6404l_behavioral_model dut_psram_chip (
        .sclk (psram_sclk),
        .ce_n (psram_ce_n),
        .si   (psram_si),
        .so   (psram_so)
    );

    reg [15:0] result;

    initial begin
        $dumpfile("wave_write_basic.vcd");
        $dumpvars(0, tb_write_basic);

        ad_drive = 0; ad_oe = 0;
        ne = 1; nadv = 1; noe = 1; nwe = 1;
        reset_n = 1'b0;
        #50;
        reset_n = 1'b1;

        $display("=================================================");
        $display(" WRITE BASIC: two words, back to back");
        $display("=================================================");

        write_word(16'hA5C3);
        #6000;   // covers psram_fifo power-up/reset + first push round-trip

        write_word(16'h0F0F);
        #3000;   // covers the second push round-trip

        read_word_burst(result);
        check_word(result, 16'hA5C3, 1);
        #3000;

        read_word_burst(result);
        check_word(result, 16'h0F0F, 2);
        #3000;

        $display("=================================================");
        $display(" done");
        $display("=================================================");
        $finish;
    end

endmodule