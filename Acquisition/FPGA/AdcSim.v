`timescale 1ns/1ps
// =====================================================================
// AdcSim.v - simulated multi-channel ADC feed for bench / pipeline tests.
//
// Replays 4-channel sample data from a hex file (default sine.hex, made by
// generate_memory.py) as if it were a live ADC. Each hex line is one
// 64-bit word packed MSB-first as:
//     {ch1[15:0], ch2[15:0], ch3[15:0], ch4[15:0]}
//
// The 4 file channels are shared across the NUM_ADC output channels by
// wrapping mod 4: output channel k <- file channel (k % 4). So NUM_ADC=1
// feeds only channel 1; NUM_ADC=6 feeds file channels 1,2,3,4,1,2.
//
// While i_EN is high a fresh sample is emitted every SINE_DIV clocks
// (o_RDY pulses one cycle; o_VALUE holds the current sample). The read
// address wraps back to 0 after SINE_SAMPLES samples, so a file SHORTER
// than the downstream buffer just repeats from the beginning. While i_EN
// is low the feed holds at sample 0 and emits nothing.
//
// This is the exact module wired behind SW1 in main.v, so a testbench that
// instantiates it exercises the real feed - not a stand-in.
// =====================================================================
module AdcSim #(
    parameter NUM_ADC      = 2,
    parameter SINE_SAMPLES = 2560,       // number of samples (lines) in HEX_FILE
    parameter SINE_DIV     = 1024,       // i_CLK cycles between samples
    parameter HEX_FILE     = "sine.hex"
)(
    input  wire                    i_CLK,
    input  wire                    i_EN,     // high = run the feed
    output wire [16*NUM_ADC-1:0]   o_VALUE,  // current multi-channel sample
    output reg                     o_RDY,    // one-cycle pulse per new sample
    output reg  [15:0]             o_ADDR    // current sample index (observability)
);
    reg [63:0] rom [0:SINE_SAMPLES-1];
    initial $readmemh(HEX_FILE, rom);        // path relative to sim/synth cwd

    reg [15:0] div_cnt = 16'd0;
    initial begin o_ADDR = 16'd0; o_RDY = 1'b0; end

    always @(posedge i_CLK) begin
        o_RDY <= 1'b0;                       // default: one-cycle pulse
        if (!i_EN) begin
            div_cnt <= 16'd0;
            o_ADDR  <= 16'd0;                // hold at start while disabled
        end else if (div_cnt == SINE_DIV - 1) begin
            div_cnt <= 16'd0;
            o_RDY   <= 1'b1;                 // sample tick (value = current word)
            o_ADDR  <= (o_ADDR == SINE_SAMPLES-1) ? 16'd0 : o_ADDR + 16'd1; // wrap
        end else begin
            div_cnt <= div_cnt + 16'd1;
        end
    end

    // Expand the current 64-bit word into NUM_ADC 16-bit channels (mod-4 share).
    // Output ch k occupies o_VALUE[16*k +: 16]; file ch c=k%4 lives at
    // word[16*(4-c)-1 -: 16] (ch1 is the top 16-bit group).
    wire [63:0] word = rom[o_ADDR];
    genvar gi;
    generate
        for (gi = 0; gi < NUM_ADC; gi = gi + 1) begin : MAP
            assign o_VALUE[16*gi +: 16] = word[16*(4-(gi%4))-1 -: 16];
        end
    endgenerate
endmodule
