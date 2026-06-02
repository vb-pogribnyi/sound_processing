`timescale 1ns / 1ps

////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer:
//
// Create Date:   07:51:43 03/27/2026
// Design Name:   OutputterBuff
// Module Name:   C:/Users/ise_user/Documents/ISE_Projects/SoundLocatorFPGA/OutputterBuffTest.v
// Project Name:  SoundLocatorFPGA
// Target Device:  
// Tool versions:  
// Description: 
//
// Verilog Test Fixture created by ISE for module: OutputterBuff
//
// Dependencies:
// 
// Revision:
// Revision 0.01 - File Created
// Additional Comments:
// 
////////////////////////////////////////////////////////////////////////////////

module OutputterBuffTest;
	always #5 i_CLK = ~i_CLK;
	
	reg oclk_en = 0;
	always begin
	  #8 
	  if (oclk_en) begin
	    i_OCLK = ~i_OCLK;
	  end
	end

	// Inputs
	reg [15:0] i_OUT1;
	reg [15:0] i_OUT2;
	reg [15:0] i_OUT3;
	reg [15:0] i_OUT4;
	reg i_OCLK;
	reg i_CLK;
	reg i_RDY;
	reg [1:0] i_STATE;
	reg [1:0] i_DBG;

	// Outputs
	wire [7:0] o_OUTPUT;
	wire [7:0] o_OUTPUT2;
	wire o_RDY;
	
	integer i = 0;

	// Instantiate the Unit Under Test (UUT)
	OutputterBuff #(.BUFF_DEPTH(16), .CHUNK_SIZE(8)) uut (
		.i_OUT1(i_OUT1), 
		.i_OUT2(i_OUT2), 
		.i_OUT3(i_OUT3), 
		.i_OUT4(i_OUT4), 
		.i_OCLK(i_OCLK), 
		.i_CLK(i_CLK), 
		.i_RDY(i_RDY), 
		.i_STATE(i_STATE), 
		.i_DBG(i_DBG), 
		.o_OUTPUT(o_OUTPUT), 
		.o_OUTPUT2(o_OUTPUT2), 
		.o_RDY(o_RDY)
	);

	initial begin
		// Initialize Inputs
		i_OUT1 = 16'h1110;
		i_OUT2 = 16'h2220;
		i_OUT3 = 16'h3330;
		i_OUT4 = 16'h4440;
		i_OCLK = 0;
		i_CLK = 0; 
		i_RDY = 0;
		i_STATE = 0;
		i_DBG = 2'h3;

		// Wait 100 ns for global reset to finish
		for (i = 155; i >= 0; i = i - 1) begin
			#10;
			i_RDY = 1;
			#85;
			i_RDY = 0;
			i_OUT1 = i_OUT1 + 1;
			i_OUT2 = i_OUT2 + 1;
			i_OUT3 = i_OUT3 + 1;
			i_OUT4 = i_OUT4 + 1;
		end
   end
	initial begin
		
		#50
		i_STATE = 1;
		#2000
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		// Re-launch right away
		#24
		i_STATE = 3;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		#50
		i_STATE = 1;
		#4
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		
		#2000 // Read then re-lauch
		i_STATE = 1;
		#2000
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		#24
		i_STATE = 3;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		
		#50 // Normal read
		i_STATE = 1;
		#86
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		
		#11 // Normal read
		i_STATE = 1;
		#44
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		
		#11 // Normal read
		i_STATE = 1;
		#44
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		
		// ------- BUFFER ENDED HERE ----------
		#11 // Normal read
		i_STATE = 1;
		#44
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		// Reset
		#24
		i_STATE = 0;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
		
		
		// ------- NEW COMINGS ----------
		#11 // Normal read
		i_STATE = 1;
		#300 // Wait for RDY to come up
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;
	
		#8 // Normal read
		i_STATE = 1;
		#30 // Wait for RDY to come up
		oclk_en = 1;
		#512
		oclk_en = 0;
		#12
		i_STATE = 2;
		#12
		oclk_en = 1;
		#80
		oclk_en = 0;

	end
	initial begin
	  #10000
	  $finish;
	end
      
endmodule

