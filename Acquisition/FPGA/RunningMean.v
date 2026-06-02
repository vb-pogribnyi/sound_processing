`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    22:29:14 11/27/2025 
// Design Name: 
// Module Name:    RunningMean 
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
module RunningMean(
    input signed [15:0] i_SIGNAL,
    input i_RDY,
    output reg [31:0] o_VARIANCE,
    output reg [31:0] o_MEAN
    );
	reg signed [31:0] mean = 0;
	reg signed [31:0] variance = 0;
	wire signed [31:0] sig32 = $signed(i_SIGNAL);
	parameter K = 4;
	
	wire signed [31:0] diff = sig32 - (mean >>> K);
	wire signed [31:0] diff2 = diff * diff;
	
	always @(posedge i_RDY) begin
		mean <= mean + (diff >>> K);
		variance <= variance + ((diff2 - variance) >>> K);
		o_VARIANCE <= variance >> 4;
		o_MEAN <= mean >>> K;
	end

endmodule
