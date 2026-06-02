`timescale 1ns / 1ps

////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer:
//
// Create Date:   22:29:37 11/27/2025
// Design Name:   RunningMean
// Module Name:   C:/Users/ise_user/Documents/ISE_Projects/test2/RunningMeanTest.v
// Project Name:  test2
// Target Device:  
// Tool versions:  
// Description: 
//
// Verilog Test Fixture created by ISE for module: RunningMean
//
// Dependencies:
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
////////////////////////////////////////////////////////////////////////////////

module RunningMeanTest;

	// Inputs
	reg signed [15:0] i_SIGNAL;
	reg i_RDY;

	// Outputs
	wire [31:0] o_VARIANCE;
	wire [31:0] o_MEAN;
	integer j;

	// Instantiate the Unit Under Test (UUT)
	RunningMean uut (
		.i_SIGNAL(i_SIGNAL), 
		.o_VARIANCE(o_VARIANCE), 
		.i_RDY(i_RDY), 
		.o_MEAN(o_MEAN)
	);

	initial begin
		// Initialize Inputs
		i_SIGNAL = 0;
		i_RDY = 0;

		// Wait 100 ns for global reset to finish
		#100;
        
		// Add stimulus here
		
		for (j = 55; j >= 0; j = j - 1)
		begin
			#5 i_SIGNAL = 15;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = 12;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = 14;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = 11;
			i_RDY = 1;
			#5 i_RDY = 0;
		end
		
		
		
		for (j = 55; j >= 0; j = j - 1)
		begin
			#5 i_SIGNAL = -122;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = -134;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = -111;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = -125;
			i_RDY = 1;
			#5 i_RDY = 0;
			
			#5 i_SIGNAL = -112;
			i_RDY = 1;
			#5 i_RDY = 0;
		end	

	end
      
endmodule

