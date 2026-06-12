`timescale 1ns / 1ps
`include "src/ADS8865Master.v"
`include "src/Outputter.v"
`include "src/RunningMean.v"
`include "src/MCP3461MAster.v"


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
    output wire o_MCP_nCS,
    output wire o_MCP_SDI,
    output wire o_MCP_SCK,
    output wire o_MCP_MCLK,
     
    // Parallel output
    input wire i_OCLK,
    output wire [7:0] o_OUTPUT,
    output wire [7:0] o_OUTPUT2,
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
    input wire i_AUX2
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
    localparam NUM_ADC = 4;
    
    reg interrupt = 0;
    wire [3:0] miso;
    wire [2:0] mcp_state;
    assign miso[0] = i_MCP_SDO1;
    assign miso[1] = i_MCP_SDO2;
    assign miso[2] = i_MCP_SDO3;
    assign miso[3] = i_MCP_SDO4;
    wire [16 * NUM_ADC-1:0] outputs;
    assign out1 = outputs[16 * (0+1)-1:16 * 0];
    assign out2 = outputs[16 * (1+1)-1:16 * 1];
    assign out3 = outputs[16 * (2+1)-1:16 * 2];
    assign out4 = outputs[16 * (3+1)-1:16 * 3];
    MCP3461Master #( .NUM_ADC(NUM_ADC), .ADC_ADDR(1) ) adc_master (
        .i_CLK50(i_CLK),
        .i_INTERRUPT(interrupt),
        .i_MISO(miso),
        .o_MOSI(o_MCP_SDI),
        .o_CS(o_MCP_nCS),
        .o_SCLK(o_MCP_SCK),
        .o_MCLK(o_MCP_MCLK),
        .o_STATE(mcp_state),
        .o_VALUE(outputs)
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
    assign o_DBG13 = o_OUTPUT[3];
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
    OutputterBuff #(.BUFF_DEPTH(4096), .CHUNK_SIZE(8))  out (
        .i_OUT1(out_tst), 
        
        .i_OUT2(out4), 
        .i_OUT3(out4), 
        .i_OUT4(out4), 
        
        //.i_OUT1(out1_tst), 
        //.i_OUT2(out2_tst), 
        //.i_OUT3(out3_tst), 
        //.i_OUT4(out4_tst), 
        .i_OCLK(i_OCLK), 
        .i_CLK(clk_slow), 
        .i_RDY(rdy), 
      .i_STATE(state),
        .i_DBG(sw34), 
        .o_OUTPUT(o_OUTPUT),
        .o_OUTPUT2(o_OUTPUT2), 
        .o_RDY(o_RDY)
    );
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
        .i_STATE(mcp_state),
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
