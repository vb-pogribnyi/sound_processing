`timescale 1ns / 1ps

// iverilog .\Acquisition\FPGA\MCP3461Master.v .\Acquisition\FPGA\MCP3461MasterTester.v
// vvp a.out  
// gtkwave .\mcp3461.vcd

// `include "Acquisition/FPGA/MCP3461Master.v"

module MCP3461MasterTester;

    // Inputs
    reg i_CLK;
    reg [1:0] miso;
    reg interrupt;

    // Outputs
    wire o_MOSI;
    wire o_MCLK;
    wire o_SCLK;
    wire o_RDY;
    wire o_CS;
    
    wire [15:0] o_OUT1;
    wire [15:0] o_OUT2;
    
    // Output simulation. 8 bits status + 16 bit ADC value
    reg [23:0] value1 = 24'hF0ACDC;
    reg [23:0] value2 = 24'hF1BBDF;
    reg [7:0] data_in = 8'h00;
    reg [2:0] idx_in = 0;
    always @(posedge o_SCLK) begin
        if (idx_in == 0) begin
            data_in <= 8'h00;
        end
        data_in[idx_in] <= o_MOSI;
        idx_in <= idx_in + 1;
    end
    
    
    integer i;
    integer j;
    always #5 i_CLK = ~i_CLK;

    // Instantiate the Unit Under Test (UUT)
    MCP3461Master #( .NUM_ADC(2) ) uut (
        .i_CLK50(i_CLK),
        .i_INTERRUPT(interrupt),
        .i_MISO(miso),
        .o_MOSI(o_MOSI),
        .o_CS(o_CS),
        .o_SCLK(o_SCLK),
        .o_MCLK(o_MCLK)
    );

    // input wire i_CLK50,
    // input wire i_INTERRUPT,
    // input wire [NUM_ADC-1:0] i_MISO,
    // // output wire sel_interrupt,
    // output wire o_MOSI,
    // output wire o_CS,
    // output wire o_SCLK,
    // output wire o_MCLK

    initial begin
        $dumpfile("mcp3461.vcd");
        $dumpvars(0, MCP3461MasterTester);
        // Initialize Inputs
        i_CLK = 0;
        interrupt = 1;
        #50;
        
        // Add stimulus here
        for (j = 15; j >= 0; j = j - 1)
        begin
            for (i = 0; i < 25; i = i + 1) begin
                @(negedge o_SCLK);
                miso[0] <= value1[23 - i-1];
                miso[1] <= value2[23 - i-1];
                if (o_CS) begin
                    i <= 0;
                    j <= j - 1;
                    if (j == 0) begin
                        $finish;
                    end
                end
            end
        end

        $finish;

    end
      
endmodule

