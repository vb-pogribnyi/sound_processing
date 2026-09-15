`timescale 1ns / 1ps
//////////////////////////////////////////////////////////////////////////////////
// Company: 
// Engineer: 
// 
// Create Date:    23:07:05 12/17/2025 
// Design Name: 
// Module Name:    OutputterBuff
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
module OutputterBuff #(
		parameter BUFF_DEPTH = 1024,
		parameter CHUNK_SIZE = 8) (
    input [15:0] i_OUT1,
    input [15:0] i_OUT2,
    input [15:0] i_OUT3,
    input [15:0] i_OUT4,
    input i_OCLK,
    input i_CLK,
    input i_RDY,
    input wire [1:0] i_STATE,		// 00 - reset; 01 - output chunks; 10 - show status and proceed; 11 - re-send previous chunk
    input [1:0] i_DBG,
    output wire [7:0] o_OUTPUT,
    output wire [7:0] o_OUTPUT2,
    output reg o_RDY
    );
	 reg [63:0] buff [0:BUFF_DEPTH-1];
	 reg [63:0] sine_buff [0:255];
	 initial begin
	   $readmemh("src/sine.hex", sine_buff);
	 end
	 reg [63:0] sine_value = 0;
	 reg [7:0] sine_idx = 0;
	 
	 // Read index will never reach the write index 
	 reg [15:0] write_idx = 0;
	 reg [15:0] read_idx = 0;
	 reg [15:0] next_read_idx = 0;
	 
	 reg is_reading = 0;
	 reg is_available = 0;
	 reg was_rdy_reset = 1;
	 wire [15:0] OUT_1;
	 wire [15:0] OUT_2;
	 wire [15:0] OUT_3;
	 wire [15:0] OUT_4;
	 wire [15:0] dbg_1;
	 wire [15:0] dbg_2;
	 wire [15:0] dbg_3;
	 wire [15:0] dbg_4;
	 reg was_read_reset = 0;
	 
	 assign dbg_1 = (i_DBG[1]) ? sine_value[63:48] : 16'h121F;
	 assign dbg_2 = (i_DBG[1]) ? sine_value[47:32] : 16'h562F;
	 assign dbg_3 = (i_DBG[1]) ? sine_value[31:16] : 16'h893F;
	 assign dbg_4 = (i_DBG[1]) ? sine_value[15:0] : 16'hBC4F;
	 
	 assign OUT_1 = (i_DBG[0]) ? dbg_1 : i_OUT1;
	 assign OUT_2 = (i_DBG[0]) ? dbg_2 : i_OUT2;
	 assign OUT_3 = (i_DBG[0]) ? dbg_3 : i_OUT3;
	 assign OUT_4 = (i_DBG[0]) ? dbg_4 : i_OUT4;
	 
	 wire [63:0] signal;
	 reg [63:0] r_signal;
	 assign signal[63:48] = OUT_1;
	 assign signal[47:32] = OUT_2;
	 assign signal[31:16] = OUT_3;
	 assign signal[15:0] = OUT_4;
	 // assign o_RDY = out_cycle < 3 || is_available;
	 
	 reg [7:0] dbg1 = 0;
	 reg [7:0] dbg2 = 0;
	 reg was_writes_performed = 0;
	 reg [7:0] out_cycle = 0;
	 wire [7:0] out_cycle_w;
	 wire [7:0] out_cycle_i;
	 reg [15:0] out_periodic;
	 
	 always @(negedge i_CLK) begin
	   //o_RDY <= i_STATE[1];
	   case (i_STATE)
		 0: begin
			write_idx <= 0;
			read_idx <= 0;
			o_RDY <= 0;
			was_read_reset <= 1;
			was_writes_performed <= 0;
		 end
		 1: begin
		   read_idx <= next_read_idx;
			r_signal <= buff[next_read_idx + out_cycle_i];
			if ((next_read_idx + CHUNK_SIZE <= write_idx || (write_idx == 0 && was_writes_performed) &&
					next_read_idx + CHUNK_SIZE <= BUFF_DEPTH)) begin
			  o_RDY <= 1;
			end
			else begin
			  o_RDY <= 0;
			end
		 end
		 2: begin
			o_RDY <= 0;
		 end
		 3: begin
			o_RDY <= 0;
		 end
		endcase
		if (i_RDY && was_rdy_reset) begin
		  sine_value <= sine_buff[sine_idx];
		  sine_idx <= sine_idx + 1;
		  out_periodic <= OUT_4;
		  
		  was_rdy_reset <= 0;
		  if (i_STATE != 0) begin
		    //dbg2 = dbg2 + 1;
		    was_read_reset <= 0;
			 
			 if (read_idx < write_idx || was_read_reset) begin // write_idx may be smaller than read_idx if it's zero and no writes performed.
			   was_writes_performed <= 1;
				buff[write_idx] = signal;
			 end
			 if (write_idx + 1 >= BUFF_DEPTH) begin
				write_idx <= 0;
			 end 
			 else if (read_idx < write_idx || was_read_reset) begin
			   write_idx <= write_idx + 1;
				//dbg1 = dbg1 + 1;
			 end
		  end
		end
		if (~i_RDY) begin
		  was_rdy_reset <= 1;
		end
	 end
	 
	 //assign o_OUTPUT = dbg1;
	 //assign o_OUTPUT2 = dbg2;
	 
	 reg is_out_reset = 1;
	 assign out_cycle_w = is_out_reset ? 8'h0 : (out_cycle % 4);
	 assign out_cycle_i = is_out_reset ? 8'h0 : (out_cycle / 4);
	 wire is_reset;
	 assign is_reset = i_STATE == 0 ? 1 : 0;
	 reg [7:0] output_1;
	 reg [7:0] output_2 ;
	 assign o_OUTPUT = is_reset ? out_periodic[15:8] : output_1;
	 assign o_OUTPUT2 = is_reset ? out_periodic[7:0] : output_2;
	 always @(posedge i_OCLK) begin
	   case (i_STATE)
		  0: begin
			 next_read_idx <= 0;
			 out_cycle <= 0;
		  end
        1: begin
		    if (is_out_reset) begin
			   out_cycle <= 1;
				is_out_reset <= 0;
			 end
			 else begin
			   out_cycle <= out_cycle + 1;
			 end
			 if (o_RDY) begin
				 case (out_cycle_w)
					0: begin
						output_1 <= r_signal[63:56];
						output_2 <= r_signal[55:48];
					end
					1: begin
						output_1 <= r_signal[47:40];
						output_2 <= r_signal[39:32];
					end
					2: begin
						output_1 <= r_signal[31:24];
						output_2 <= r_signal[23:16];
					end
					3: begin
						output_1 <= r_signal[15:8];
						output_2 <= r_signal[7:0];
					end
				 endcase
			 end
			 else begin
			   output_1 <= next_read_idx;
			   output_2 <= write_idx;
			 end
		  end
		  2: begin
		    output_1 <= out_cycle;
		    output_2 <= CHUNK_SIZE;
			 is_out_reset <= 1;
			 next_read_idx <= read_idx + CHUNK_SIZE;
		  end
		  3: begin
			 next_read_idx <= read_idx;
		  end
		endcase
	 end

endmodule
