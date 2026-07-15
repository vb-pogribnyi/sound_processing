`timescale 1ns / 1ps
`include "src/ADS8865Master.v"
// `include "src/Outputter.v"
`include "src/FSMC.v"
`include "src/PSRAM.v"
`include "src/RunningMean.v"
`include "src/MCP3461MAster.v"
`include "src/OV5640.v"
`include "src/AdcSim.v"

// =====================================================================
// DIP switch map (i_SW1 .. i_SW5)
// ---------------------------------------------------------------------
//   SW1 : Test-signal source select for the PSRAM FIFO.
//         HIGH -> a 4-channel sine pattern replayed from sine.hex is fed
//                 into the FIFO as ADC samples (see "SW1 test feed" below).
//         LOW  -> the live MCP3461 ADC feeds the FIFO (normal operation).
//   SW2 : (unused) wired to Leds.i_SW1; the Leds block that read it is
//         commented out, so it currently has no effect.
//   SW3 : (unused) wired to Leds.i_SW2 and to sw34[1] (sw34 only feeds the
//         commented-out OutputterBuff); no effect at present.
//   SW4 : MCP3461 PGA gain select -> 1x (see adc_gain). Also wired to
//         Leds.i_SW3 / sw34[0] (no effect there).
//   SW5 : MCP3461 PGA gain select -> 2x, takes priority over SW4 (see
//         adc_gain). Also wired to Leds.i_SW4 / commented ADS8865 i_IS_ADS.
// =====================================================================


//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    07:21:52 11/16/2025 
// Design Name: 
// Module Name:    led 
// Project Name: 
// Target Devices: 
// Tool versions: 
// Description: 
//
// Dependencies: 
//
// Revision: 
// Revision 0.01 - File Created
// Additional Comments: 
//
//////////////////////////////////////////////////////////////////////////////////
module led(
    input wire i_BTN,
    input wire i_RST,
    input wire i_CLK,
    // output wire o_CONVST,
    // output wire o_SCLK,
    // input wire i_MISO1,
    // input wire i_MISO2,
    // input wire i_MISO3,
    // input wire i_MISO4,
    input wire i_MCP_SDO1,
    input wire i_MCP_SDO2,
    input wire i_MCP_SDO3,
    input wire i_MCP_SDO4,
    input wire i_MCP_nIRQ,       // ADC data-ready / IRQ (active low) - drives DRDY sync
    output wire o_MCP_nCS,
    output wire o_MCP_SDI,
    output wire o_MCP_SCK,
    output wire o_MCP_MCLK,
     
    // Parallel output
    input wire i_OCLK,
    
    inout wire [3:0] PSRAM_SIO,
    output wire o_PSRAM_CE,
    output wire o_PSRAM_CLK,

    inout wire [3:0] o_FSMC_AD,
    input wire o_FSMC_NE,
    input wire o_FSMC_NOE,
    input wire o_FSMC_NWE,
    input wire o_FSMC_NADV,
    input wire o_FSMC_CLK,
    output wire o_FSMC_NWAIT,
    // output wire [7:0] o_OUTPUT,
    // output wire [7:0] o_OUTPUT2,
    output wire o_RDY,
     
     
    input i_SW1,
    input i_SW2,
    input i_SW3,
    input i_SW4,
    input i_SW5,
    output wire o_LED1P,
    output wire o_LED2P,
    output wire o_LED1N,
    output wire o_LED2N,
    output wire o_LED3N,
    output wire o_LED4N,
     
     // Debugs
    output wire o_MOSI,
    output wire o_GND,
     
    output wire o_DBG6,
    output wire o_DBG5,
    output wire o_DBG12,
    output wire o_DBG13,
    output wire o_DBG14,
    input wire i_AUX1,
    input wire i_AUX2,

    // OV5640 camera (only D3/D6/D7 of the DVP bus are wired).
    // PWDN/RESETB are NOT driven from the FPGA - they are tied on the
    // camera board (PWDN low, RESETB high); the sensor is reset over SCCB
    // (software reset 0x3008=0x82, first entry in the config ROM).
    output wire o_CAM_XCLK,
    output wire o_CAM_SIOC,
    inout  wire o_CAM_SIOD,
    input  wire i_CAM_PCLK,
    input  wire i_CAM_HREF,
    input  wire i_CAM_VSYNC,
    input  wire i_CAM_D7,
    input  wire i_CAM_D6,
    input  wire i_CAM_D3
    );
     parameter CLK_FREQ = 50000000;
     localparam COUNT_MAX = CLK_FREQ / 100;
     reg [31:0] counter;
     wire [15:0] out1;
     wire [15:0] out2;
     wire [15:0] out3;
     wire [15:0] out4;
     wire rdy;
     reg [31:0] counter_rst;
     reg [2:0] counter_presses;
     //reg [15:0] counter_intensity;
     reg is_on;
     wire [31:0] mean;
     wire [16:0] o_CNT;
     
     reg clk_slow;
     reg [15:0] clk_cnt;
     
     
    //  ADS8865Master  adc_master (
    //     .i_CLK(clk_slow), 
    //     .o_CONVST(o_CONVST), 
    //     .o_SCLK(o_SCLK),
    //     .o_RDY(rdy), 
    //     .i_MISO1(i_MISO1), 
    //     .i_MISO2(i_MISO2), 
    //     .i_MISO3(i_MISO3), 
    //     .i_MISO4(i_MISO4), 
    //     .o_OUT1(out1), 
    //     .o_OUT2(out2),
    //     .o_OUT3(out3),
    //     .o_OUT4(out4),
    //     .i_IS_ADS(i_SW5),
        
    //     .o_CNT(o_CNT)
    // );
    // One parameter for the whole chain. Capped at 2 until AD[7:4] are wired:
    // a FIFO entry is 4*NUM_ADC nibbles and must fit below the control
    // registers (live 0xB-0xE, status 0xF) in the 4-bit FSMC address space.
    localparam NUM_ADC = 2;

    wire [3:0] miso;
    wire [2:0] mcp_state;
    assign miso[0] = i_MCP_SDO1;
    assign miso[1] = i_MCP_SDO2;
    assign miso[2] = i_MCP_SDO3;
    assign miso[3] = i_MCP_SDO4;
    wire [16 * NUM_ADC-1:0] outputs;
    assign out1 = outputs[16 * (0+1)-1:16 * 0];
    assign out2 = outputs[16 * (1+1)-1:16 * 1];
    assign out3 = 16'h0000;   // channels 3-4 unused until NUM_ADC is raised
    assign out4 = 16'h0000;
    // SW4 -> ADC PGA gain 1x, SW5 -> 2x (SW5 priority); neither -> baseline.
    // Baseline is GAIN=1/3, so even 1x is a step up from it.
    // Applied live (master re-sends CONFIG on change).
    // Flip the comparisons to 1'b0 if your switches read low when asserted.
    wire [2:0] adc_gain = (i_SW5 == 1'b1) ? 3'b010 :   // 2x
                          (i_SW4 == 1'b1) ? 3'b001 :   // 1x
                                            3'b000;     // baseline = 1/3 (unchanged)
    MCP3461Master #( .NUM_ADC(NUM_ADC), .ADC_ADDR(1) ) adc_master (
        .i_CLK50(i_CLK),
        .i_INTERRUPT(i_MCP_nIRQ),
        .i_GAIN(adc_gain),
        .i_MISO(miso[NUM_ADC-1:0]),
        .o_MOSI(o_MCP_SDI),
        .o_CS(o_MCP_nCS),
        .o_SCLK(o_MCP_SCK),
        .o_MCLK(o_MCP_MCLK),
        .o_STATE(mcp_state),
        .o_VALUE(outputs),
        .o_RDY(rdy)
    );



    reg var_switch = 0;
    wire [1:0] state;
    assign state[0] = i_AUX1;
    assign state[1] = i_AUX2;
    wire [1:0] sw34;
    assign sw34[0] = i_SW4;
    assign sw34[1] = i_SW3;
    assign o_DBG6 = 0;
    // assign o_DBG6 = i_MISO4;
    assign o_DBG14 = var_switch;
    assign o_DBG5 = rdy;
    assign o_DBG12 = 0;
    //assign o_DBG12 = o_OUTPUT[2];
    assign o_DBG13 = 0;
    // assign o_DBG13 = o_OUTPUT[3];
     wire [31:0] var1;
     wire [31:0] mean1;
     wire [31:0] var2;
     wire [31:0] mean2;
     wire [31:0] var3;
     wire [31:0] mean3;
     wire [31:0] var4;
     wire [31:0] mean4;
    RunningMean running_mean1 (
        .i_SIGNAL(out1), 
        .o_VARIANCE(var1), 
        .i_RDY(rdy), 
        .o_MEAN(mean1)
    );
    RunningMean running_mean2 (
        .i_SIGNAL(out2), 
        .o_VARIANCE(var2), 
        .i_RDY(rdy), 
        .o_MEAN(mean2)
    );
    RunningMean running_mean3 (
        .i_SIGNAL(out3), 
        .o_VARIANCE(var3), 
        .i_RDY(rdy), 
        .o_MEAN(mean3)
    );
    RunningMean running_mean4 (
        .i_SIGNAL(out4), 
        .o_VARIANCE(var4), 
        .i_RDY(rdy), 
        .o_MEAN(mean4)
    );
    
     reg [15:0] out_tst = 16'hACDC;
     reg [15:0] out1_tst = 16'h8182;
     reg [15:0] out2_tst = 16'hC3C3;
     reg [15:0] out3_tst = 16'hA5A5;
     reg [15:0] out4_tst = 16'hE7E7;
    /*Outputter out (
        .i_OUT1(out_tst), 
        //.i_OUT2(out2), 
        //.i_OUT3(out3), 
        //.i_OUT4(out4), 
        
        
        .i_OUT2(out4), 
        .i_OUT3(out4), 
        .i_OUT4(out4), 
        
        //.i_OUT1(out1_tst), 
        //.i_OUT2(out2_tst), 
        //.i_OUT3(out3_tst), 
        //.i_OUT4(out4_tst), 
        .i_OCLK(i_OCLK), 
        .i_CLK(i_CLK), 
        .i_RDY(rdy), 
        .i_DBG(i_SW4), 
        .o_OUTPUT(o_OUTPUT),
        .o_OUTPUT2(o_OUTPUT2), 
        .o_RDY(o_RDY)
    );*/
    // OutputterBuff #(.BUFF_DEPTH(4096), .CHUNK_SIZE(8))  out (
    //     .i_OUT1(out_tst), 
        
    //     .i_OUT2(out1), 
    //     .i_OUT3(out1), 
    //     .i_OUT4(out1), 
        
    //     //.i_OUT1(out1_tst), 
    //     //.i_OUT2(out2_tst), 
    //     //.i_OUT3(out3_tst), 
    //     //.i_OUT4(out4_tst), 
    //     .i_OCLK(i_OCLK), 
    //     .i_CLK(clk_slow), 
    //     .i_RDY(rdy), 
    //   .i_STATE(state),
    //     .i_DBG(sw34), 
    //     .o_OUTPUT(o_OUTPUT),
    //     .o_OUTPUT2(o_OUTPUT2), 
    //     .o_RDY(o_RDY)
    // );
	 assign o_RDY = 0;

    wire [3:0] psram_state;
    // wire psram_fifo_empty;
    // wire psram_fifo_full;
    // reg wr_toggle = 0;
    // reg rd_toggle = 0;
    reg fsmc_reset = 1;
    assign psram_state[3:1] = 0;
    localparam nADC        = 1;
    localparam CLK_DIV     = 4;
    localparam SYS_CLK_MHZ = 50;
    // localparam FIFO_DEPTH  = 8;    // small for fast simulation
    localparam PSRAM_CLK_DIV     = 4;
    localparam PSRAM_SYS_CLK_MHZ = 50;
    localparam PSRAM_FIFO_DEPTH  = 256;
    wire [nADC*16-1:0]     data_in;
    wire [nADC*16-1:0]     data_out;
    
    
    // localparam LATENCY_CYCLES  = 2;
    localparam WAIT_ACTIVE_LOW = 0;

    // OV5640 camera front-end: configures the sensor over SCCB and
    // produces a 4-bit per-frame average red/green from the 3 wired DVP bits.
    wire [3:0] cam_red;
    wire [3:0] cam_green;
    wire       cam_cfg_done;
    // Bayer phase for THIS board (confirmed empirically): the true red
    // corner is (EVEN column, odd line). The diagonal opposite (odd,even)
    // is blue, the other two corners are green. (Picking (odd,even) made
    // "red" read blue - high on white, low on red & green - so it's the
    // mate, (even,odd).)
    OV5640 #(
        .RED_COL_PAR (1'b0),
        .RED_LINE_PAR(1'b1)
    ) camera (
        .i_CLK    (i_CLK),
        .i_RST_N  (fsmc_reset),
        .o_XCLK   (o_CAM_XCLK),
        .o_SIOC   (o_CAM_SIOC),
        .o_SIOD   (o_CAM_SIOD),
        .o_PWDN   (),               // not wired to FPGA (tied on camera board)
        .o_RESETB (),               // not wired to FPGA (tied on camera board)
        .i_PCLK   (i_CAM_PCLK),
        .i_HREF   (i_CAM_HREF),
        .i_VSYNC  (i_CAM_VSYNC),
        .i_D7     (i_CAM_D7),
        .i_D6     (i_CAM_D6),
        .i_D3     (i_CAM_D3),
        .o_RED    (cam_red),
        .o_GREEN  (cam_green),
        .o_CFG_DONE(cam_cfg_done)
    );

    // =====================================================================
    // SW1 test feed: an AdcSim instance replays 4-channel sine data from
    // sine.hex and (when SW1 is high) is muxed into the FSMC ADC input in
    // place of the live MCP3461. The same data path (FSMC -> PSRAM FIFO ->
    // APS6404L) is exercised as in normal operation; only the sample source
    // changes. See SW1PipelineTest.v for a full end-to-end simulation.
    //
    // Channel sharing: the 4 file channels wrap mod 4 across NUM_ADC (ch k
    // <- file ch k%4), and the read address wraps so a file shorter than the
    // FIFO just repeats from the beginning.
    // =====================================================================
    wire [16*NUM_ADC-1:0] sine_value;
    wire                  sine_rdy;
    wire [15:0]           sine_addr;         // current sample index (debug)
    AdcSim #(
        .NUM_ADC      (NUM_ADC),
        .SINE_SAMPLES (2560),
        .SINE_DIV     (1024),               // ~48.8 kHz @ 50 MHz (spaced > 1 PSRAM write)
        .HEX_FILE     ("sine.hex")
    ) adc_sim (
        .i_CLK   (i_CLK),
        .i_EN    (i_SW1),
        .o_VALUE (sine_value),
        .o_RDY   (sine_rdy),
        .o_ADDR  (sine_addr)
    );

    // Source select: SW1 high -> sine test feed, low -> live MCP3461 ADC.
    wire [16*NUM_ADC-1:0] fsmc_adc_value = i_SW1 ? sine_value : outputs;
    wire                  fsmc_adc_rdy   = i_SW1 ? sine_rdy   : rdy;

    FSMC #(
        .NUM_ADC           (NUM_ADC),
        .WAIT_ACTIVE_LOW(WAIT_ACTIVE_LOW),
        .PSRAM_CLK_DIV     (PSRAM_CLK_DIV),
        .PSRAM_SYS_CLK_MHZ (PSRAM_SYS_CLK_MHZ),
        .PSRAM_FIFO_DEPTH  (PSRAM_FIFO_DEPTH)
    ) outputter (
        .fsmc_ad   (o_FSMC_AD),
        .fsmc_ne   (o_FSMC_NE),
        .fsmc_nadv (o_FSMC_NADV),
        .fsmc_noe  (o_FSMC_NOE),
        .fsmc_nwe  (o_FSMC_NWE),
        .fsmc_clk  (o_FSMC_CLK),
        .fsmc_nwait(o_FSMC_NWAIT),
        .sys_clk       (i_CLK),
        .reset_n       (fsmc_reset),
        .adc_value     (fsmc_adc_value),   // SW1: sine test feed, else MCP3461 sample
        .adc_rdy       (fsmc_adc_rdy),     // SW1: sine sample tick, else ADC fresh-sample
        .cam_red       (cam_red),       // camera frame-average red   (FSMC 0x9)
        .cam_green     (cam_green),     // camera frame-average green (FSMC 0xA)
        .psram_sclk    (o_PSRAM_CLK),
        .psram_ce_n    (o_PSRAM_CE),
        .psram_sio     (PSRAM_SIO),
        .psram_is_valid(psram_state[0])
    );
    // PSRAM #(
    //     .nADC        (nADC),
    //     .CLK_DIV     (CLK_DIV),
    //     .SYS_CLK_MHZ (SYS_CLK_MHZ),
    //     .FIFO_DEPTH  (FIFO_DEPTH)
    // ) psram (
    //     .sys_clk     (i_CLK),
    //     .reset_n     (psram_reset),
    //     .data_in     (data_in),
    //     .wr_toggle   (wr_toggle),
    //     .rd_toggle   (rd_toggle),
    //     .data_out    (data_out),
    //     .data_valid  (data_valid),
    //     .fifo_full   (psram_fifo_full),
    //     .fifo_empty  (psram_fifo_empty),
    //     .is_valid    (psram_state[0]),
    //     .psram_sclk  (o_PSRAM_CLK),
    //     .psram_ce_n  (o_PSRAM_CE),
    //     .psram_sio   (PSRAM_SIO)
    // );

    Leds leds (
        .i_CLK(i_CLK),
        .i_SW1(i_SW2),
        .i_SW2(i_SW3),
        .i_SW3(i_SW4),
        .i_SW4(i_SW5),
        .i_VAR1(var1),
        .i_VAR2(var2),
        .i_VAR3(var3),
        .i_VAR4(var4),
        // .i_STATE(mcp_state),
        .i_STATE(psram_state),
        .o_LED1P(o_LED1P),
        .o_LED2P(o_LED2P),
        .o_LED1N(o_LED1N),
        .o_LED2N(o_LED2N),
        .o_LED3N(o_LED3N),
        .o_LED4N(o_LED4N)
    );
    
    assign o_MOSI = 1;
    assign o_GND = 0;
     
     
     always @(posedge i_CLK) begin
       if (out4 < 35000) begin
          var_switch <= var_switch + 1;
        end
       // o_DBG <= i_RST;
       // o_DBG <= clk_slow;
        //counter_intensity <= counter_intensity + 1;
        
        
        if (clk_cnt == 0) begin
            clk_slow <= ~clk_slow;
        end
        clk_cnt <= clk_cnt + 1;
        if (clk_cnt == 3) begin
            clk_cnt <= 0;
        end
        /*
        // PWM led indication
        if (counter_intensity < var1) begin
          o_LED <= 1'b1;
          o_DBG <= 1'b1;
        end else begin
          o_LED <= 1'b0;
          o_DBG <= 1'b0;
        end
        */
        /*
        if (counter_intensity < var1) begin
          o_LED0 <= 1'b0;
          //o_DBG <= 1'b1;
        end else begin
          o_LED0 <= 1'b1;
          //o_DBG <= 1'b0;
        end
        if (counter_intensity < var2) begin
          o_LED1 <= 1'b0;
          //o_DBG <= 1'b1;
        end else begin
          o_LED1 <= 1'b1;
          //o_DBG <= 1'b0;
        end
        if (counter_intensity < var3) begin
          o_LED2 <= 1'b0;
          //o_DBG <= 1'b1;
        end else begin
          o_LED2 <= 1'b1;
          //o_DBG <= 1'b0;
        end
        if (counter_intensity < var4) begin
          o_LED3 <= 1'b1;
          //o_DBG <= 1'b1;
        end else begin
          o_LED3 <= 1'b0;
          //o_DBG <= 1'b0;
        end*/
        
        
        /*
        if (o_CNT < 5) begin
          o_LED <= 1'b0;
        end else begin
          o_LED <= 1'b1;
        end
        */
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        // Detect clock button press
        // if is_on was not set and button remains pressed for 10 ms
        // then set is_on.
       if (!is_on) begin
            if (!i_BTN) begin
                counter <= counter + 1;
                if (counter >= COUNT_MAX) begin
                    is_on <= 1'b1;
                    counter <= 0;
                    counter_presses <= counter_presses + 1;
                end
            end else begin
                counter <= 0;
            end
        // if is_on was set then wait until the button is not pressed
        // for at least 10 ms
        end else begin
            if (i_BTN) begin
                counter <= counter + 1;
                if (counter >= COUNT_MAX) begin
                    is_on <= 1'b0;
                    counter <= 0;
                end
            end else begin
                counter <= 0;
            end
        end
        
        
        // Detect reset button press in the same way
        if (!i_RST) begin // it turns out to be active low...
            counter_rst <= counter_rst + 1;
            if (counter_rst >= COUNT_MAX) begin
                counter_rst <= 0;
                counter_presses <= 0;
            end
        end else begin
            counter_rst <= 0;
        end
        
    end
     
        assign mean = mean1 + 10000 < 30000 ? mean1 + 10000 : 0;
 endmodule
