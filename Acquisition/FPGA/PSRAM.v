// =============================================================================
// PSRAM.v
// FIFO controller for AP Memory APS6404L-3SQR QSPI PSRAM
//
// Startup (SPI, single-bit):
//   0x66  Reset-Enable
//   0x99  Reset
//   0x35  Enter Quad Mode  ← chip switches to QPI after CE# rises
//
// Normal operation (QPI, 4-bit):
//   0x02  Write     : CMD(2) + ADDR(6) + DATA(ENTRY_BITS/4) nibble-clocks
//   0x0B  Fast Read : CMD(2) + ADDR(6) + 4 dummy + DATA(ENTRY_BITS/4) nibble-clocks
//
// SIO bus ports (connect to external tristate buffer on real FPGA):
//   psram_sio_out  – nibble FPGA drives onto SIO[3:0]
//   psram_sio_in   – nibble FPGA samples from SIO[3:0]
//   psram_sio_oe   – 1 = FPGA is driving, 0 = chip is driving (read data phase)
// =============================================================================

`timescale 1ns/1ps

module PSRAM #(
    parameter nADC        = 4,
    parameter CLK_DIV     = 4,
    parameter SYS_CLK_MHZ = 50,
    parameter FIFO_DEPTH  = 256
)(
    input  wire                   sys_clk,
    input  wire                   reset_n,

    input  wire [nADC*16-1:0]     data_in,
    input  wire                   wr_toggle,
    input  wire                   rd_toggle,
    output reg  [nADC*16-1:0]     data_out,
    output reg                    data_valid,
    output wire                   fifo_full,
    output wire                   fifo_empty,
    output reg                    is_valid,    // 1 after startup self-test passes

    output reg                    psram_sclk,
    output reg                    psram_ce_n,
    output reg  [3:0]             psram_sio_out,
    input  wire [3:0]             psram_sio_in,
    output reg                    psram_sio_oe
);

// ---------------------------------------------------------------------------
// Derived parameters
// ---------------------------------------------------------------------------
localparam ENTRY_BYTES   = nADC * 2;
localparam ENTRY_BITS    = nADC * 16;
localparam ENTRY_NIBS    = ENTRY_BITS / 4;   // nibble-clocks for QPI data phase
localparam ADDR_BITS     = 23;
localparam PU_CYCLES     = 150 * SYS_CLK_MHZ;
localparam PU_CNT_W      = $clog2(PU_CYCLES + 1);
localparam PTR_W         = $clog2(FIFO_DEPTH + 1);

// bit_cnt is reused for both bit-counts (SPI startup, max 24) and
// nibble-counts (QPI data, max ENTRY_NIBS).  Size for the larger.
localparam CNT_MAX = (ENTRY_NIBS > 24) ? ENTRY_NIBS : 24;
localparam CNT_W   = $clog2(CNT_MAX + 1);

// tRST = 50 ns min
localparam RST_WAIT   = (SYS_CLK_MHZ / 20 < 3) ? 3 : SYS_CLK_MHZ / 20;
localparam RST_WAIT_W = $clog2(RST_WAIT + 1);

// Self-test: write/read a fixed pattern at an address beyond the FIFO region
localparam [ENTRY_BITS-1:0] ST_PATTERN = {(ENTRY_BITS/8){8'hA5}};
localparam [23:0]           ST_ADDR    = FIFO_DEPTH * ENTRY_BYTES;

// ---------------------------------------------------------------------------
// FSM states
// ---------------------------------------------------------------------------
localparam [4:0]
    S_PU_WAIT  = 5'd0,
    S_RST_EN   = 5'd1,   // SPI: send 0x66
    S_RST_CMD  = 5'd2,   // SPI: send 0x99
    S_RST_WAIT = 5'd3,   // tRST hold
    S_QPI_EN   = 5'd4,   // SPI: send 0x35 → chip enters QPI
    S_IDLE     = 5'd5,
    S_WR_CMD   = 5'd6,   // QPI: 2 nibble-clocks for 0x02
    S_WR_ADDR  = 5'd7,   // QPI: 6 nibble-clocks for 24-bit addr
    S_WR_DATA  = 5'd8,   // QPI: ENTRY_NIBS nibble-clocks
    S_WR_DONE  = 5'd9,
    S_RD_CMD   = 5'd10,  // QPI: 2 nibble-clocks for 0x0B
    S_RD_ADDR  = 5'd11,  // QPI: 6 nibble-clocks
    S_RD_WAIT  = 5'd12,  // QPI: 4 dummy nibble-clocks
    S_RD_DATA  = 5'd13,  // QPI: ENTRY_NIBS nibble-clocks
    S_RD_DONE  = 5'd14;

// ---------------------------------------------------------------------------
// Registers
// ---------------------------------------------------------------------------
reg [4:0]          state;
reg                qpi_mode;

reg [PTR_W-1:0]    wr_ptr, rd_ptr, count;
assign fifo_full  = (count == FIFO_DEPTH);
assign fifo_empty = (count == 0);

reg wr_prev, rd_prev;
wire wr_req = (wr_toggle != wr_prev);
wire rd_req = (rd_toggle != rd_prev);

reg                  wr_pending, rd_pending;
reg [ENTRY_BITS-1:0] wr_data_latch;

reg [PU_CNT_W-1:0]   pu_cnt;
reg [CNT_W-1:0]      bit_cnt;
reg [7:0]            cmd_sr;
reg [23:0]           addr_sr;
reg [ENTRY_BITS-1:0] data_sr;
reg [3:0]            dummy_cnt;

reg [$clog2(CLK_DIV)-1:0] div_cnt;
reg sclk_en;
reg sclk_phase;

reg [RST_WAIT_W-1:0] rst_wait_cnt;
reg                  st_mode;   // 1 while startup self-test is running

// ---------------------------------------------------------------------------
// Address from FIFO pointer
// ---------------------------------------------------------------------------
function [ADDR_BITS-1:0] fifo_addr;
    input [PTR_W-1:0] ptr;
    begin fifo_addr = ptr * ENTRY_BYTES; end
endfunction

// ---------------------------------------------------------------------------
// Sequential logic
// ---------------------------------------------------------------------------
always @(posedge sys_clk or negedge reset_n) begin
    if (!reset_n) begin
        wr_ptr        <= 0;
        rd_ptr        <= 0;
        count         <= 0;
        data_out      <= 0;
        data_valid    <= 0;
        wr_prev       <= wr_toggle;
        rd_prev       <= rd_toggle;
        wr_pending    <= 0;
        rd_pending    <= 0;
        wr_data_latch <= 0;
        psram_sclk    <= 0;
        psram_ce_n    <= 1;
        psram_sio_out <= 0;
        psram_sio_oe  <= 1;
        pu_cnt        <= 0;
        bit_cnt       <= 0;
        cmd_sr        <= 0;
        addr_sr       <= 0;
        data_sr       <= 0;
        dummy_cnt     <= 0;
        div_cnt       <= 0;
        sclk_en       <= 0;
        sclk_phase    <= 0;
        rst_wait_cnt  <= 0;
        qpi_mode      <= 0;
        is_valid      <= 0;
        st_mode       <= 0;
        state         <= S_PU_WAIT;
    end else begin
        data_valid <= 0;

        wr_prev <= wr_toggle;
        rd_prev <= rd_toggle;

        if (wr_req && !fifo_full) begin
            wr_pending    <= 1;
            wr_data_latch <= data_in;
        end
        if (rd_req && !fifo_empty)
            rd_pending <= 1;

        // SPI clock divider
        sclk_en <= 0;
        if (div_cnt == CLK_DIV - 1) begin
            div_cnt <= 0;
            sclk_en <= 1;
        end else
            div_cnt <= div_cnt + 1;

        case (state)

        // ----------------------------------------------------------------
        // Power-up delay (150 µs)
        // ----------------------------------------------------------------
        S_PU_WAIT: begin
            psram_ce_n   <= 1;
            psram_sclk   <= 0;
            psram_sio_oe <= 1;
            if (pu_cnt < PU_CYCLES - 1)
                pu_cnt <= pu_cnt + 1;
            else begin
                pu_cnt <= 0;
                state  <= S_RST_EN;
            end
        end

        // ----------------------------------------------------------------
        // SPI startup helper macro: shifts cmd_sr MSB-first on SIO[0]
        // Reused by S_RST_EN, S_RST_CMD, S_QPI_EN
        // ----------------------------------------------------------------
        S_RST_EN: begin
            if (bit_cnt == 0) begin
                cmd_sr       <= 8'h66;
                psram_ce_n   <= 0;
                psram_sio_oe <= 1;
                bit_cnt      <= 8;
            end
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    psram_sio_out <= {3'b0, cmd_sr[7]};
                    cmd_sr        <= {cmd_sr[6:0], 1'b0};
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        psram_ce_n <= 1;
                        psram_sclk <= 0;
                        state      <= S_RST_CMD;
                        bit_cnt    <= 0;
                    end
                end
            end
        end

        S_RST_CMD: begin
            if (bit_cnt == 0) begin
                cmd_sr       <= 8'h99;
                psram_ce_n   <= 0;
                psram_sio_oe <= 1;
                bit_cnt      <= 8;
            end
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    psram_sio_out <= {3'b0, cmd_sr[7]};
                    cmd_sr        <= {cmd_sr[6:0], 1'b0};
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        psram_ce_n   <= 1;
                        psram_sclk   <= 0;
                        rst_wait_cnt <= RST_WAIT;
                        state        <= S_RST_WAIT;
                        bit_cnt      <= 0;
                    end
                end
            end
        end

        S_RST_WAIT: begin
            if (rst_wait_cnt > 0)
                rst_wait_cnt <= rst_wait_cnt - 1;
            else
                state <= S_QPI_EN;
        end

        S_QPI_EN: begin
            psram_sio_oe <= 1;
            if (bit_cnt == 0 && !psram_ce_n) begin
                // 8th rising edge just completed with sclk=1, ce_n=0.
                // De-assert CE# now (sclk stays high; S_IDLE will pull it low).
                // This guarantees the model saw the genuine posedge and set qpi_mode.
                psram_ce_n    <= 1;
                qpi_mode      <= 1;
                // Kick off startup self-test: write ST_PATTERN, then read back.
                st_mode       <= 1;
                wr_pending    <= 1;
                wr_data_latch <= ST_PATTERN;
                state         <= S_IDLE;
            end else begin
                if (bit_cnt == 0) begin   // initial entry
                    cmd_sr     <= 8'h35;
                    psram_ce_n <= 0;
                    bit_cnt    <= 8;
                end
                if (sclk_en) begin
                    if (!sclk_phase) begin
                        psram_sclk    <= 0;
                        psram_sio_out <= {3'b0, cmd_sr[7]};
                        cmd_sr        <= {cmd_sr[6:0], 1'b0};
                        sclk_phase    <= 1;
                    end else begin
                        psram_sclk <= 1;   // genuine rising edge - no override
                        sclk_phase <= 0;
                        bit_cnt    <= bit_cnt - 1;
                        // Do NOT touch psram_sclk or psram_ce_n here;
                        // when bit_cnt reaches 0 the top branch fires next clock.
                    end
                end
            end
        end

        // ----------------------------------------------------------------
        // Idle
        // ----------------------------------------------------------------
        S_IDLE: begin
            psram_ce_n   <= 1;
            psram_sclk   <= 0;
            psram_sio_oe <= 1;
            if (wr_pending && (st_mode || !fifo_full)) begin
                wr_pending <= 0;
                cmd_sr     <= 8'h02;
                addr_sr    <= st_mode ? ST_ADDR : fifo_addr(wr_ptr);
                data_sr    <= wr_data_latch;
                bit_cnt    <= 2;
                psram_ce_n <= 0;
                state      <= S_WR_CMD;
            end else if (rd_pending && (st_mode || !fifo_empty)) begin
                rd_pending <= 0;
                cmd_sr     <= 8'h0B;
                addr_sr    <= st_mode ? ST_ADDR : fifo_addr(rd_ptr);
                data_sr    <= 0;
                bit_cnt    <= 2;
                psram_ce_n <= 0;
                state      <= S_RD_CMD;
            end
        end

        // ----------------------------------------------------------------
        // QPI WRITE path
        // bit_cnt counts nibble-clocks remaining in each phase
        // ----------------------------------------------------------------
        S_WR_CMD: begin
            psram_sio_oe <= 1;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    // high nibble first (bit_cnt==2), then low nibble (bit_cnt==1)
                    psram_sio_out <= (bit_cnt == 2) ? cmd_sr[7:4] : cmd_sr[3:0];
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        bit_cnt <= 6;    // 6 nibble-clocks for 24-bit addr
                        state   <= S_WR_ADDR;
                    end
                end
            end
        end

        S_WR_ADDR: begin
            psram_sio_oe <= 1;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    psram_sio_out <= addr_sr[23:20];
                    addr_sr       <= {addr_sr[19:0], 4'b0};
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        bit_cnt <= ENTRY_NIBS;
                        state   <= S_WR_DATA;
                    end
                end
            end
        end

        S_WR_DATA: begin
            psram_sio_oe <= 1;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    psram_sio_out <= data_sr[ENTRY_BITS-1:ENTRY_BITS-4];
                    data_sr       <= {data_sr[ENTRY_BITS-5:0], 4'b0};
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1)
                        state <= S_WR_DONE;
                end
            end
        end

        S_WR_DONE: begin
            psram_sclk    <= 0;
            psram_ce_n    <= 1;
            psram_sio_out <= 0;
            if (st_mode) begin
                rd_pending <= 1;   // self-test: read back what we just wrote
            end else begin
                if (wr_ptr == FIFO_DEPTH - 1)
                    wr_ptr <= 0;
                else
                    wr_ptr <= wr_ptr + 1;
                count <= count + 1;
            end
            state <= S_IDLE;
        end

        // ----------------------------------------------------------------
        // QPI READ path
        // ----------------------------------------------------------------
        S_RD_CMD: begin
            psram_sio_oe <= 1;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    psram_sio_out <= (bit_cnt == 2) ? cmd_sr[7:4] : cmd_sr[3:0];
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        bit_cnt <= 6;
                        state   <= S_RD_ADDR;
                    end
                end
            end
        end

        S_RD_ADDR: begin
            psram_sio_oe <= 1;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk    <= 0;
                    psram_sio_out <= addr_sr[23:20];
                    addr_sr       <= {addr_sr[19:0], 4'b0};
                    sclk_phase    <= 1;
                end else begin
                    psram_sclk <= 1;
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        dummy_cnt <= 4;   // 0x0B: 4 dummy nibble-clocks
                        state     <= S_RD_WAIT;
                    end
                end
            end
        end

        S_RD_WAIT: begin
            psram_sio_oe <= 1;   // still driving during dummy
            psram_sio_out <= 0;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 0;
                    sclk_phase <= 1;
                end else begin
                    psram_sclk   <= 1;
                    sclk_phase   <= 0;
                    dummy_cnt    <= dummy_cnt - 1;
                    if (dummy_cnt == 1) begin
                        psram_sio_oe <= 0;   // release bus for chip to drive
                        bit_cnt      <= ENTRY_NIBS;
                        data_sr      <= 0;
                        state        <= S_RD_DATA;
                    end
                end
            end
        end

        S_RD_DATA: begin
            psram_sio_oe <= 0;
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 0;
                    sclk_phase <= 1;
                end else begin
                    psram_sclk <= 1;
                    data_sr    <= {data_sr[ENTRY_BITS-5:0], psram_sio_in};
                    sclk_phase <= 0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1)
                        state <= S_RD_DONE;
                end
            end
        end

        S_RD_DONE: begin
            psram_sclk   <= 0;
            psram_ce_n   <= 1;
            psram_sio_oe <= 1;
            if (st_mode) begin
                is_valid <= (data_sr == ST_PATTERN);
                st_mode  <= 0;
            end else begin
                data_out   <= data_sr;
                data_valid <= 1;
                if (rd_ptr == FIFO_DEPTH - 1)
                    rd_ptr <= 0;
                else
                    rd_ptr <= rd_ptr + 1;
                count <= count - 1;
            end
            state <= S_IDLE;
        end

        default: state <= S_IDLE;
        endcase
    end
end

endmodule
