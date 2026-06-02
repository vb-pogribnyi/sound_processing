`timescale 1ns / 1ps

////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer:
//
// Create Date:   22:23:57 11/26/2025
// Design Name:   ADS8865Reader
// Module Name:   C:/Users/ise_user/Documents/ISE_Projects/test2/ADS8865Tester.v
// Project Name:  test2
// Target Device:  
// Tool versions:  
// Description: 
//
// Verilog Test Fixture created by ISE for module: ADS8865Reader
//
// Dependencies:
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
////////////////////////////////////////////////////////////////////////////////

module ADS8865Tester;

	// Inputs
	reg i_MISO;
	reg i_CLK = 0;
	reg i_EN = 1;
	reg o_SCLK = 0;

	// Outputs
	//wire o_CONVST;
	wire o_RDY;
	wire o_STATE;
	wire o_RST;
	wire o_RESET;
	wire [15:0] o_OUT;
	wire [7:0] o_C;
	
	reg [15:0] value = 16'hACDF;
	integer i;
	integer j;
	always #5 i_CLK = ~i_CLK;

	// Instantiate the Unit Under Test (UUT)
	ADS8865Reader uut (
		.o_SCLK(o_SCLK), 
		//.o_CONVST(o_CONVST), 
		.i_EN(i_EN), 
		.o_OUT(o_OUT), 
		.o_RDY(o_RDY),  
		.i_MISO(i_MISO), 
		.i_CLK(i_CLK),
		
		.o_STATE(o_STATE), 
		.o_RST(o_RST), 
		.o_RESET(o_RESET), 
		.o_C(o_C)
	);
	
	initial begin
		// #115 i_MISO <= 0;
	end

	initial begin
		// Initialize Inputs
		

		// Wait 100 ns for global reset to finish
		//#80;
        
		// Add stimulus here
		for (j = 15; j >= 0; j = j - 1)
		begin
			//@(posedge o_CONVST);
			#20 i_MISO <= 1;
			#20 i_MISO <= 0;
			//@(negedge o_SCLK);
			//i_MISO <= 0;
			//@(negedge o_SCLK);
			//i_MISO <= 1;
			#25 o_SCLK <= 1;
			#5 o_SCLK <= 0;
			for (i = 15; i >= 0; i = i - 1)
			begin
				//@(negedge o_SCLK);
				i_MISO <= value[i];
				#5 o_SCLK <= 1;
				#5 o_SCLK <= 0;
			end
		end
	end
      
endmodule

