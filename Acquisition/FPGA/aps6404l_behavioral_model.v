// =====================================================================
// aps6404l_behavioral_model.v
//
// Behavioral model of APS6404L-3SQR QSPI PSRAM.
// Supports:
//   SPI mode (power-on default):
//     0x66  Reset-Enable
//     0x99  Reset
//     0x35  Enter Quad Mode  → switches to QPI
//   QPI mode (after 0x35):
//     0x02  Write     : CMD(2) + ADDR(6) + DATA nibble-clocks
//     0x0B  Fast Read : CMD(2) + ADDR(6) + 4 dummy + DATA nibble-clocks
//
// SIO bus: driven/sampled 4 bits per clock in QPI, 1 bit (SIO[0]) in SPI.
// SPI mode 0: FPGA drives on falling SCLK, samples on rising SCLK.
// =====================================================================

`timescale 1ns/1ps

module aps6404l_behavioral_model #(
    parameter MEM_BYTES = 4096
)(
    input  wire       sclk,
    input  wire       ce_n,
    input  wire [3:0] sio_in,    // what the FPGA is driving onto SIO
    output reg  [3:0] sio_out    // what the chip drives onto SIO (High-Z when not reading)
);

    reg [7:0] mem [0:MEM_BYTES-1];

    // FSM states (shared SPI/QPI)
    localparam S_IDLE  = 3'd0,
               S_CMD   = 3'd1,
               S_ADDR  = 3'd2,
               S_DUMMY = 3'd3,
               S_WDATA = 3'd4,
               S_RDATA = 3'd5;

    reg [2:0]  state;
    reg        qpi_mode;     // 0 = SPI, 1 = QPI

    // Command / address accumulation
    reg [7:0]  cmd_sr;
    reg [23:0] addr_sr;
    reg [23:0] cur_addr;
    reg [4:0]  bitcnt;       // bits remaining (SPI CMD/ADDR phases)
    reg [2:0]  nibcnt;       // nibbles remaining (QPI phases)

    // Write data
    reg [7:0]  wbyte_sr;
    reg [2:0]  wbit;         // bits accumulated in current write byte (SPI)

    // Read data
    reg [7:0]  rdata_byte;
    reg [1:0]  rnibble;      // nibbles output in current byte (0..1, QPI)

    integer i;
    initial begin
        for (i = 0; i < MEM_BYTES; i = i + 1)
            mem[i] = 8'h00;
        state      = S_IDLE;
        qpi_mode   = 1'b0;
        sio_out    = 4'bz;
        cmd_sr     = 8'h00;
        addr_sr    = 24'h0;
        cur_addr   = 24'h0;
        bitcnt     = 5'd0;
        nibcnt     = 3'd0;
        wbyte_sr   = 8'h00;
        wbit       = 3'd0;
        rdata_byte = 8'h00;
        rnibble    = 2'd0;
    end

    // ---------------------------------------------------------------
    // CE# falling: start of transaction
    // ---------------------------------------------------------------
    always @(negedge ce_n) begin
        state   <= S_CMD;
        cmd_sr  <= 8'h00;
        addr_sr <= 24'h0;
        if (qpi_mode)
            nibcnt <= 3'd2;   // 2 nibble-clocks for 8-bit cmd
        else
            bitcnt <= 5'd8;
    end

    // ---------------------------------------------------------------
    // CE# rising: end of transaction
    // ---------------------------------------------------------------
    always @(posedge ce_n) begin
        state   <= S_IDLE;
        sio_out <= 4'bz;
    end

    // ---------------------------------------------------------------
    // Drive SIO on falling SCLK (read data phase only)
    // ---------------------------------------------------------------
    always @(negedge sclk) begin
        if (!ce_n && state == S_RDATA) begin
            if (qpi_mode)
                sio_out <= (rnibble == 0) ? rdata_byte[7:4] : rdata_byte[3:0];
            else
                sio_out <= {3'b0, rdata_byte[bitcnt - 1]};
        end
    end

    // ---------------------------------------------------------------
    // Main FSM: advances on rising SCLK
    // ---------------------------------------------------------------
    always @(posedge sclk) begin
        if (!ce_n) begin
            if (qpi_mode) begin
                // ---- QPI mode: 4 bits per clock ------------------
                case (state)

                    S_CMD: begin
                        cmd_sr <= {cmd_sr[3:0], sio_in};
                        nibcnt <= nibcnt - 1;
                        if (nibcnt == 1) begin
                            // command is complete: {cmd_sr[3:0], sio_in}
                            case ({cmd_sr[3:0], sio_in})
                                8'h02: begin
                                    state  <= S_ADDR;
                                    nibcnt <= 3'd6;
                                    wbyte_sr <= 8'h00;
                                end
                                8'h0B: begin
                                    state  <= S_ADDR;
                                    nibcnt <= 3'd6;
                                end
                                default: state <= S_IDLE;
                            endcase
                            cmd_sr <= {cmd_sr[3:0], sio_in};
                        end
                    end

                    S_ADDR: begin
                        addr_sr <= {addr_sr[19:0], sio_in};
                        nibcnt  <= nibcnt - 1;
                        if (nibcnt == 1) begin
                            cur_addr <= {addr_sr[19:0], sio_in};
                            if (cmd_sr == 8'h0B) begin
                                state  <= S_DUMMY;
                                nibcnt <= 3'd4;   // 4 dummy nibble-clocks
                            end else begin
                                state  <= S_WDATA;
                                nibcnt <= 3'd2;
                                wbyte_sr <= 8'h00;
                            end
                        end
                    end

                    S_DUMMY: begin
                        nibcnt <= nibcnt - 1;
                        if (nibcnt == 1) begin
                            rdata_byte <= mem[cur_addr];
                            rnibble    <= 2'd0;
                            state      <= S_RDATA;
                            nibcnt     <= 3'd2;
                        end
                    end

                    S_WDATA: begin
                        // Each clock = one nibble; two nibbles = one byte
                        if (nibcnt == 2) begin
                            wbyte_sr <= {sio_in, 4'h0};
                            nibcnt   <= 3'd1;
                        end else begin
                            mem[cur_addr] <= {wbyte_sr[7:4], sio_in};
                            cur_addr <= cur_addr + 1;
                            wbyte_sr <= 8'h00;
                            nibcnt   <= 3'd2;
                        end
                    end

                    S_RDATA: begin
                        // rnibble tracks which nibble of rdata_byte we just drove
                        if (rnibble == 1) begin
                            // finished this byte
                            cur_addr   <= cur_addr + 1;
                            rdata_byte <= mem[cur_addr + 1];
                            rnibble    <= 2'd0;
                        end else begin
                            rnibble <= rnibble + 1;
                        end
                    end

                    default: ;
                endcase

            end else begin
                // ---- SPI mode: 1 bit per clock (SIO[0]) ----------
                case (state)

                    S_CMD: begin
                        cmd_sr <= {cmd_sr[6:0], sio_in[0]};
                        if (bitcnt == 5'd1) begin
                            case ({cmd_sr[6:0], sio_in[0]})
                                8'h35: begin
                                    // Enter Quad Mode – CE# will go high, nothing more
                                    qpi_mode <= 1'b1;
                                    state    <= S_IDLE;
                                end
                                8'h66, 8'h99: state <= S_IDLE;  // single-byte cmds
                                default:      state <= S_IDLE;
                            endcase
                        end else
                            bitcnt <= bitcnt - 5'd1;
                    end

                    default: ;  // SPI data ops not used after QPI enable
                endcase
            end
        end
    end

endmodule
