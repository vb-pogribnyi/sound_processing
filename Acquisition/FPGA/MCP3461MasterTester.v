`timescale 1ns / 1ps

// iverilog .\Acquisition\FPGA\MCP3461Master.v .\Acquisition\FPGA\MCP3461MasterTester.v
// vvp a.out  
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
	
	reg [15:0] value1 = 16'hACDC;
	reg [15:0] value2 = 16'hBBDF;
	
	
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
		miso[0] = 0;
		miso[1] = 0;

		// Wait 100 ns for global reset to finish
		#100;
        
		// Add stimulus here
		for (j = 15; j >= 0; j = j - 1)
		begin
			// @(posedge o_CONVST);
			// i_MISO1 <= 1;
			// i_MISO2 <= 1;
			// #20 i_MISO1 <= 0;
			// #20 i_MISO2 <= 0;
			// //@(negedge o_SCLK);
			// //i_MISO <= 0;
			// //@(negedge o_SCLK);
			// //i_MISO <= 1;
			// for (i = 15; i >= 0; i = i - 1)
			// begin
			// 	@(negedge o_SCLK);
			// 	if (i <= 15) begin
			// 		i_MISO1 <= value1[i];
			// 		i_MISO2 <= value2[i];
			// 	end
			// end
		end

        $finish;

	end
      
endmodule

