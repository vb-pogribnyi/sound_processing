// =====================================================================
// aps6404l_behavioral_model.v
//
// Behavioral simulation model of the AP Memory APS6404L-3SQR QSPI PSRAM.
// Implements only the SPI-mode subset used by PSRAM.v:
//
//   0x66 / 0x99  Reset-Enable / Reset  (single-byte, no data phase)
//   0x02         Write:     CMD(8) + ADDR(24) + DATA bytes until CE# rises
//   0x0B         Fast Read: CMD(8) + ADDR(24) + 8 dummy clks + DATA bytes
//
// SPI Mode 0 (CPOL=0, CPHA=0): slave drives SO on falling SCLK,
// master samples SO on rising SCLK.  All transfers are MSB-first.
//
// Verified against APS6404L-3SQR datasheet Rev 2.3, sections 8.5, 10.1, 10.2.
// =====================================================================

`timescale 1ns/1ps

module aps6404l_behavioral_model #(
    parameter MEM_BYTES = 4096   // simulated memory (real chip is 8 MB)
)(
    input  wire sclk,
    input  wire ce_n,
    input  wire si,     // MOSI
    output reg  so      // MISO  (1'bz when not selected)
);

    reg [7:0] mem [0:MEM_BYTES-1];

    localparam S_IDLE  = 3'd0,
               S_CMD   = 3'd1,
               S_ADDR  = 3'd2,
               S_DUMMY = 3'd3,
               S_WDATA = 3'd4,
               S_RDATA = 3'd5;

    reg [2:0]  state;
    reg [7:0]  cmd_sr;      // command shift register
    reg [23:0] addr_sr;     // address shift register (accumulates incoming bits)
    reg [23:0] cur_addr;    // latched byte address for current transaction
    reg [4:0]  bitcnt;      // down-counter: bits remaining in current phase (max 24)
    reg [7:0]  wbyte_sr;    // write-data shift register
    reg [7:0]  rdata_byte;  // output byte currently being serialised on SO
    reg        is_read;     // 1 = Fast Read (0x0B), 0 = Write (0x02)

    integer i;
    initial begin
        for (i = 0; i < MEM_BYTES; i = i + 1)
            mem[i] = 8'h00;
        state      = S_IDLE;
        so         = 1'bz;
        is_read    = 1'b0;
        cmd_sr     = 8'h00;
        addr_sr    = 24'h0;
        cur_addr   = 24'h0;
        bitcnt     = 5'd0;
        wbyte_sr   = 8'h00;
        rdata_byte = 8'h00;
    end

    // ---------------------------------------------------------------
    // CE# falling: start of a new transaction
    // ---------------------------------------------------------------
    always @(negedge ce_n) begin
        state  <= S_CMD;
        bitcnt <= 5'd8;
        cmd_sr <= 8'h00;
    end

    // ---------------------------------------------------------------
    // CE# rising: end of transaction, release SO (High-Z)
    // ---------------------------------------------------------------
    always @(posedge ce_n) begin
        state <= S_IDLE;
        so    <= 1'bz;
    end

    // ---------------------------------------------------------------
    // SO output: driven on falling SCLK so the master can latch it on
    // the next rising SCLK.
    //
    // bitcnt counts 8..1 within each output byte, so rdata_byte[bitcnt-1]
    // maps to bit7 (MSB) .. bit0 (LSB) — MSB-first per the datasheet.
    // ---------------------------------------------------------------
    always @(negedge sclk) begin
        if (!ce_n && state == S_RDATA)
            so <= rdata_byte[bitcnt - 1];
    end

    // ---------------------------------------------------------------
    // Main receive / protocol FSM: advances on rising SCLK
    // ---------------------------------------------------------------
    always @(posedge sclk) begin
        if (!ce_n) begin
            case (state)

                // ---- Command byte (8 bits, MSB first) ---------------
                S_CMD: begin
                    cmd_sr <= {cmd_sr[6:0], si};
                    if (bitcnt == 5'd1) begin
                        case ({cmd_sr[6:0], si})
                            8'h02: begin
                                is_read <= 1'b0;
                                state   <= S_ADDR;
                                bitcnt  <= 5'd24;
                            end
                            8'h0B: begin
                                is_read <= 1'b1;
                                state   <= S_ADDR;
                                bitcnt  <= 5'd24;
                            end
                            default: begin
                                // 0x66 / 0x99 / others: single-byte command,
                                // CE# will go high to end it; nothing more to do.
                                state <= S_IDLE;
                            end
                        endcase
                    end else
                        bitcnt <= bitcnt - 5'd1;
                end

                // ---- Address (24 bits, MSB first) -------------------
                S_ADDR: begin
                    addr_sr <= {addr_sr[22:0], si};
                    if (bitcnt == 5'd1) begin
                        // Latch the complete 24-bit address.
                        // addr_sr holds bits[23:1] from previous posedges;
                        // si is bit[0] on this (the 24th) posedge.
                        cur_addr <= {addr_sr[22:0], si};
                        if (is_read) begin
                            state  <= S_DUMMY;
                            bitcnt <= 5'd8;    // 8 wait cycles per datasheet §10.1
                        end else begin
                            state    <= S_WDATA;
                            bitcnt   <= 5'd8;
                            wbyte_sr <= 8'h00;
                        end
                    end else
                        bitcnt <= bitcnt - 5'd1;
                end

                // ---- 8 dummy clock cycles (Fast Read only) ----------
                // Datasheet §10.1 Fig.7: 8 wait cycles before data out.
                // During this phase SI is don't-care; SO is not yet driven.
                S_DUMMY: begin
                    if (bitcnt == 5'd1) begin
                        rdata_byte <= mem[cur_addr];   // pre-load first output byte
                        state      <= S_RDATA;
                        bitcnt     <= 5'd8;
                    end else
                        bitcnt <= bitcnt - 5'd1;
                end

                // ---- Write data: bytes in, address auto-increments ---
                S_WDATA: begin
                    wbyte_sr <= {wbyte_sr[6:0], si};
                    if (bitcnt == 5'd1) begin
                        mem[cur_addr] <= {wbyte_sr[6:0], si};
                        cur_addr      <= cur_addr + 24'd1;
                        bitcnt        <= 5'd8;
                        wbyte_sr      <= 8'h00;
                    end else
                        bitcnt <= bitcnt - 5'd1;
                end

                // ---- Read data: SO driven by the negedge block above -
                // On each byte boundary: advance address, pre-load next byte.
                S_RDATA: begin
                    if (bitcnt == 5'd1) begin
                        cur_addr   <= cur_addr + 24'd1;
                        // cur_addr hasn't updated yet (non-blocking), so
                        // cur_addr+1 is the next byte address.
                        rdata_byte <= mem[cur_addr + 24'd1];
                        bitcnt     <= 5'd8;
                    end else
                        bitcnt <= bitcnt - 5'd1;
                end

                default: ;   // S_IDLE: no action
            endcase
        end
    end

endmodule
