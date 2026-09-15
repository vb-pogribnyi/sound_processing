`timescale 1ns / 1ps

`include "src/outputter.v"

////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer:
//
// Create Date:   23:07:44 12/17/2025
// Design Name:   outputter
// Module Name:   C:/Users/ise_user/Documents/ISE_Projects/test2/outputter_test.v
// Project Name:  test2
// Target Device:  
// Tool versions:  
// Description: 
//
// Verilog Test Fixture created by ISE for module: outputter
//
// Dependencies:
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
////////////////////////////////////////////////////////////////////////////////

module outputter_test;

	// Inputs
	reg [15:0] i_OUT1;
	reg [15:0] i_OUT2;
	reg [15:0] i_OUT3;
	reg [15:0] i_OUT4;
	reg i_OCLK;
	reg i_RDY;
	reg i_CLK;
	wire o_RDY;
	always #5 i_CLK = ~i_CLK;

	// Outputs
	wire [7:0] o_OUTPUT;

	// Instantiate the Unit Under Test (UUT)
	Outputter uut (
		.i_OUT1(i_OUT1), 
		.i_OUT2(i_OUT2), 
		.i_OUT3(i_OUT3), 
		.i_OUT4(i_OUT4), 
		.i_OCLK(i_OCLK), 
		.i_CLK(i_CLK), 
		.i_RDY(i_RDY), 
		.o_OUTPUT(o_OUTPUT), 
		.o_RDY(o_RDY)
	);
	
	integer i;

	initial begin
		// Initialize Inputs
		i_OUT1 = 0;
		i_OUT2 = 0;
		i_OUT3 = 0;
		i_OUT4 = 0;
		i_OCLK = 0;
		i_CLK = 0;
		i_RDY = 0;

		// Wait 100 ns for global reset to finish
		#100;
        
		// Add stimulus here
		i_OUT1 = 16'h8181;
		i_OUT2 = 16'hc3c3;
		i_OUT3 = 16'ha5a5;
		i_OUT4 = 16'he7e7;
		i_RDY = 1;
		for (i = 7; i >= 0; i = i - 1)
		begin
			#5 i_OCLK = ~i_OCLK;
			#5 i_OCLK = ~i_OCLK;
			i_RDY = 0;
			//if (o_RDY) begin
			//	i_RDY = 0;
			//end
		end
		#8 i_RDY = 0;
		
		#15
		i_OUT1 = 16'h8181;
		i_OUT2 = 16'hc3c3;
		i_OUT3 = 16'ha5a5;
		i_OUT4 = 16'he7e7;
		i_RDY = 1;
		#3
		for (i = 7; i >= 0; i = i - 1)
		begin
			#5 i_OCLK = ~i_OCLK;
			#5 i_OCLK = ~i_OCLK;
			i_RDY = 0;
		end
		#8 i_RDY = 0;
		
		
		#17
		i_OUT1 = 16'h8181;
		i_OUT2 = 16'hc3c3;
		i_OUT3 = 16'ha5a5;
		i_OUT4 = 16'he7e7;
		#9
		i_RDY = 1;
		#22	i_RDY = 0;
		#15
		for (i = 15; i >= 0; i = i - 1)
		begin
			#5 i_OCLK = ~i_OCLK;
			#5 i_OCLK = ~i_OCLK;
		end
		#8 i_RDY = 0;
		
		#17
		i_OUT1 = 16'h8181;
		i_OUT2 = 16'hc3c3;
		i_OUT3 = 16'ha5a5;
		i_OUT4 = 16'he7e7;
		#9
		i_RDY = 1;
		#11
		for (i = 15; i >= 0; i = i - 1)
		begin
			#5 i_OCLK = ~i_OCLK;
			#5 i_OCLK = ~i_OCLK;
		end
		#8 i_RDY = 0;
	end
      
endmodule

