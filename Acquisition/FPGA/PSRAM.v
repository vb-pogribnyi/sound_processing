// =============================================================================
// psram_fifo.v
// FIFO controller for AP Memory APS6404L-3SQR QSPI PSRAM
//
// Interface: SPI mode (powers up in SPI, single-bit SI/SO).
// Commands used:
//   Write  : 0x02  – Serial CMD, Serial Addr, Serial Data, no wait cycles
//   Fast Read : 0x0B – Serial CMD, Serial Addr, 8 dummy clocks, Serial Data
//   Reset-Enable : 0x66
//   Reset        : 0x99
//
// FIFO semantics
//   - Each "entry" is nADC * 16 bits wide.
//   - On the rising edge of wr_toggle the current data_in is appended.
//   - On the rising edge of rd_toggle the oldest unread entry appears on data_out
//     and is consumed.
//   - reset_n (active-low async reset) clears head/tail pointers; PSRAM data is
//     not erased but will be overwritten on the next write cycle.
//
// PSRAM memory map
//   Each entry occupies  nADC * 2  bytes (nADC 16-bit words).
//   Entry i starts at byte address  i * (nADC * 2).
//   Maximum FIFO depth = 8 MB / (nADC * 2 bytes).
//
// SPI clock: sclk is generated internally; it toggles only during an active
// transaction (CE# low).  The ratio is set by CLK_DIV (system clocks per
// half-period of sclk).  For a 50 MHz sys_clk and CLK_DIV=2 you get ~12.5 MHz
// sclk, comfortably within the 84 MHz (linear-burst) limit.
//
// NOTE: tPU >= 150 µs after power-on before the first command. The module
// handles this with a startup counter.  Adjust SYS_CLK_MHZ to match your
// actual system clock frequency.
// =============================================================================

module PSRAM #(
    parameter nADC        = 4,          // number of 16-bit ADC channels
    parameter CLK_DIV     = 4,          // sys_clk half-periods per sclk half-period
    parameter SYS_CLK_MHZ = 50,        // system clock in MHz (for tPU calculation)
    parameter FIFO_DEPTH  = 256         // maximum number of entries
)(
    // System
    input  wire                   sys_clk,
    input  wire                   reset_n,       // async active-low reset

    // User interface
    input  wire [nADC*16-1:0]     data_in,       // data to write
    input  wire                   wr_toggle,     // write request (edge-detected)
    input  wire                   rd_toggle,     // read  request (edge-detected)
    output reg  [nADC*16-1:0]     data_out,      // data read back
    output reg                    data_valid,    // data_out is valid for one cycle
    output wire                   fifo_full,
    output wire                   fifo_empty,

    // APS6404L SPI pins
    output reg                    psram_sclk,
    output reg                    psram_ce_n,
    output reg                    psram_si,      // SI / SIO[0]
    input  wire                   psram_so       // SO / SIO[1]
);

// ---------------------------------------------------------------------------
// Derived parameters
// ---------------------------------------------------------------------------
localparam ENTRY_BYTES  = nADC * 2;             // bytes per FIFO entry
localparam ENTRY_BITS   = nADC * 16;
localparam ADDR_BITS    = 23;                   // A[22:0]
// Power-up delay: 150 µs → cycles = 150 * SYS_CLK_MHZ
localparam PU_CYCLES    = 150 * SYS_CLK_MHZ;
localparam PU_CNT_W     = $clog2(PU_CYCLES + 1);

// Pointer width
localparam PTR_W        = $clog2(FIFO_DEPTH + 1);

// ---------------------------------------------------------------------------
// FSM states
// ---------------------------------------------------------------------------
localparam [3:0]
    S_PU_WAIT   = 4'd0,   // power-up delay
    S_RST_EN    = 4'd1,   // send Reset-Enable (0x66)
    S_RST_CMD   = 4'd2,   // send Reset (0x99)
    S_RST_WAIT  = 4'd3,   // tRST = 50 ns min
    S_IDLE      = 4'd4,   // wait for wr/rd request
    S_WR_CMD    = 4'd5,   // send Write command byte
    S_WR_ADDR   = 4'd6,   // send 24-bit address
    S_WR_DATA   = 4'd7,   // send nADC*16 data bits
    S_WR_DONE   = 4'd8,   // de-assert CE#, advance write pointer
    S_RD_CMD    = 4'd9,   // send Fast-Read command byte
    S_RD_ADDR   = 4'd10,  // send 24-bit address
    S_RD_WAIT   = 4'd11,  // 8 dummy clock cycles
    S_RD_DATA   = 4'd12,  // receive nADC*16 data bits
    S_RD_DONE   = 4'd13;  // de-assert CE#, advance read pointer

// ---------------------------------------------------------------------------
// FIFO pointers & flags
// ---------------------------------------------------------------------------
reg [PTR_W-1:0] wr_ptr, rd_ptr, count;

assign fifo_full  = (count == FIFO_DEPTH);
assign fifo_empty = (count == 0);

// ---------------------------------------------------------------------------
// Edge detection for wr_toggle / rd_toggle
// ---------------------------------------------------------------------------
// "Toggle" semantics: a request is signalled by data_in/_out's associated
// control bit *changing value*, in either direction (0->1 or 1->0). A
// simple rising-edge detector would silently drop every other request
// from a strict toggle (0,1,0,1,...) sequence, so we compare against the
// previous sampled value instead.
reg wr_prev, rd_prev;
wire wr_req = (wr_toggle != wr_prev);
wire rd_req = (rd_toggle != rd_prev);

// ---------------------------------------------------------------------------
// Pending request latches (decouple from FSM)
// ---------------------------------------------------------------------------
reg wr_pending, rd_pending;
reg [ENTRY_BITS-1:0] wr_data_latch;

// ---------------------------------------------------------------------------
// Power-up counter
// ---------------------------------------------------------------------------
reg [PU_CNT_W-1:0] pu_cnt;

// ---------------------------------------------------------------------------
// SPI bit counter & shift registers
// ---------------------------------------------------------------------------
// bit_cnt must be able to hold the largest count it is ever loaded with:
// 8 (command byte), 24 (address), or ENTRY_BITS (data phase) - whichever is
// largest. A fixed-width field here is a real hazard: for nADC>=2,
// ENTRY_BITS exceeds what a 5-bit register can represent, and
// bit_cnt <= ENTRY_BITS would silently truncate (e.g. 64 -> 0 in 5 bits),
// causing the data phase to terminate after only 32 bits instead of 64.
// Sizing the field from BIT_CNT_MAX avoids this for any nADC.
localparam BIT_CNT_MAX  = (ENTRY_BITS > 24) ? ENTRY_BITS : 24;
localparam BIT_CNT_W    = $clog2(BIT_CNT_MAX + 1);

reg [BIT_CNT_W-1:0]  bit_cnt;          // counts down within each SPI phase
reg [7:0]            cmd_sr;           // command shift register
reg [23:0]           addr_sr;          // address shift register
reg [ENTRY_BITS-1:0] data_sr;          // data shift register
reg [5:0]            dummy_cnt;        // dummy clock counter (max 8, 6 bits is ample)

// ---------------------------------------------------------------------------
// CLK_DIV counter for sclk generation
// ---------------------------------------------------------------------------
reg [$clog2(CLK_DIV)-1:0] div_cnt;
reg sclk_en;          // tick every half-period of sclk
reg sclk_phase;       // 0=high-half, 1=low-half  (sclk starts HIGH per SPI mode 0)

// current sclk
// data is shifted on falling edge of sclk (mode 0: CPOL=0, CPHA=0)
// data is sampled on rising edge

// ---------------------------------------------------------------------------
// FSM register
// ---------------------------------------------------------------------------
reg [3:0] state;

// tRST counter (50 ns = SYS_CLK_MHZ/20 cycles, minimum 3)
localparam RST_WAIT   = (SYS_CLK_MHZ / 20 < 3) ? 3 : SYS_CLK_MHZ / 20;
localparam RST_WAIT_W = $clog2(RST_WAIT + 1);
reg [RST_WAIT_W-1:0] rst_wait_cnt;

// ---------------------------------------------------------------------------
// Compute PSRAM byte address from FIFO pointer
// ---------------------------------------------------------------------------
function [ADDR_BITS-1:0] fifo_addr;
    input [PTR_W-1:0] ptr;
    begin
        fifo_addr = ptr * ENTRY_BYTES;
    end
endfunction

// ---------------------------------------------------------------------------
// Sequential logic
// ---------------------------------------------------------------------------
always @(posedge sys_clk or negedge reset_n) begin
    if (!reset_n) begin
        // FIFO pointers
        wr_ptr        <= 0;
        rd_ptr        <= 0;
        count         <= 0;
        // User outputs
        data_out      <= 0;
        data_valid    <= 0;
        // Edge detectors: seed with the *current* toggle-line value rather
        // than a fixed 0. If a reset happens while wr_toggle/rd_toggle is
        // sitting at '1' (e.g. an odd number of toggles occurred before
        // reset), seeding wr_prev/rd_prev to 0 would make the very next
        // sys_clk edge after reset look like a toggle event (1 != 0) and
        // spawn a phantom write/read that the caller never asked for.
        // Seeding from the live signal guarantees no edge is detected
        // until the user actually toggles the line again post-reset.
        wr_prev       <= wr_toggle;
        rd_prev       <= rd_toggle;
        wr_pending    <= 0;
        rd_pending    <= 0;
        wr_data_latch <= 0;
        // SPI outputs
        psram_sclk    <= 1'b0;
        psram_ce_n    <= 1'b1;
        psram_si      <= 1'b0;
        // Internal
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
        state         <= S_PU_WAIT;
    end else begin
        // Default: clear data_valid after one cycle
        data_valid <= 1'b0;

        // Edge detectors
        wr_prev <= wr_toggle;
        rd_prev <= rd_toggle;

        // Latch a toggle into a pending request. NOTE: this assumes the
        // caller waits for the previous write/read to fully complete
        // (i.e. data_valid observed / enough cycles elapsed) before
        // toggling again - wr_pending/rd_pending hold only one
        // outstanding request each, mirroring a single in-flight
        // command at a time on the SPI bus.
        if (wr_req && !fifo_full) begin
            wr_pending    <= 1'b1;
            wr_data_latch <= data_in;
        end
        if (rd_req && !fifo_empty) begin
            rd_pending <= 1'b1;
        end

        // SPI clock divider tick
        sclk_en <= 1'b0;
        if (div_cnt == CLK_DIV - 1) begin
            div_cnt <= 0;
            sclk_en <= 1'b1;
        end else begin
            div_cnt <= div_cnt + 1;
        end

        // ----------------------------------------------------------------
        // FSM
        // ----------------------------------------------------------------
        case (state)

        // ------------------------------------------------------------------
        // S_PU_WAIT : wait 150 µs after reset before issuing any command
        // ------------------------------------------------------------------
        S_PU_WAIT: begin
            psram_ce_n <= 1'b1;
            psram_sclk <= 1'b0;
            if (pu_cnt < PU_CYCLES - 1)
                pu_cnt <= pu_cnt + 1;
            else begin
                pu_cnt <= 0;
                state  <= S_RST_EN;
            end
        end

        // ------------------------------------------------------------------
        // S_RST_EN : send 0x66 (Reset-Enable) over SPI
        // ------------------------------------------------------------------
        S_RST_EN: begin
            if (bit_cnt == 0) begin
                // First entry: set up shift register, assert CE#
                cmd_sr     <= 8'h66;
                psram_ce_n <= 1'b0;
                bit_cnt    <= 8;
            end
            if (sclk_en) begin
                if (!sclk_phase) begin
                    // Falling edge (sclk goes low) – shift out MSB
                    psram_sclk <= 1'b0;
                    psram_si   <= cmd_sr[7];
                    cmd_sr     <= {cmd_sr[6:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    // Rising edge
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        psram_ce_n <= 1'b1;
                        psram_sclk <= 1'b0;
                        state      <= S_RST_CMD;
                        bit_cnt    <= 0;
                    end
                end
            end
        end

        // ------------------------------------------------------------------
        // S_RST_CMD : send 0x99 (Reset)
        // ------------------------------------------------------------------
        S_RST_CMD: begin
            if (bit_cnt == 0) begin
                cmd_sr     <= 8'h99;
                psram_ce_n <= 1'b0;
                bit_cnt    <= 8;
            end
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= cmd_sr[7];
                    cmd_sr     <= {cmd_sr[6:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        psram_ce_n   <= 1'b1;
                        psram_sclk   <= 1'b0;
                        rst_wait_cnt <= RST_WAIT;
                        state        <= S_RST_WAIT;
                        bit_cnt      <= 0;
                    end
                end
            end
        end

        // ------------------------------------------------------------------
        // S_RST_WAIT : tRST hold (50 ns min)
        // ------------------------------------------------------------------
        S_RST_WAIT: begin
            if (rst_wait_cnt > 0)
                rst_wait_cnt <= rst_wait_cnt - 1;
            else
                state <= S_IDLE;
        end

        // ------------------------------------------------------------------
        // S_IDLE : wait for pending r/w requests
        // ------------------------------------------------------------------
        S_IDLE: begin
            psram_ce_n <= 1'b1;
            psram_sclk <= 1'b0;
            if (wr_pending && !fifo_full) begin
                wr_pending <= 1'b0;
                // Load shift register with Write command
                cmd_sr  <= 8'h02;
                addr_sr <= fifo_addr(wr_ptr);
                data_sr <= wr_data_latch;
                bit_cnt <= 8;
                psram_ce_n <= 1'b0;
                state   <= S_WR_CMD;
            end else if (rd_pending && !fifo_empty) begin
                rd_pending <= 1'b0;
                // Load shift register with Fast-Read command
                cmd_sr  <= 8'h0B;
                addr_sr <= fifo_addr(rd_ptr);
                data_sr <= 0;
                bit_cnt <= 8;
                psram_ce_n <= 1'b0;
                state   <= S_RD_CMD;
            end
        end

        // ------------------------------------------------------------------
        // WRITE path
        // ------------------------------------------------------------------
        S_WR_CMD: begin
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= cmd_sr[7];
                    cmd_sr     <= {cmd_sr[6:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        bit_cnt <= 24;
                        state   <= S_WR_ADDR;
                    end
                end
            end
        end

        S_WR_ADDR: begin
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= addr_sr[23];
                    addr_sr    <= {addr_sr[22:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        bit_cnt <= ENTRY_BITS;
                        state   <= S_WR_DATA;
                    end
                end
            end
        end

        S_WR_DATA: begin
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= data_sr[ENTRY_BITS-1];
                    data_sr    <= {data_sr[ENTRY_BITS-2:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        state <= S_WR_DONE;
                    end
                end
            end
        end

        S_WR_DONE: begin
            // Deassert CE# to commit the write, advance write pointer
            psram_sclk <= 1'b0;
            psram_ce_n <= 1'b1;
            psram_si   <= 1'b0;
            if (wr_ptr == FIFO_DEPTH - 1)
                wr_ptr <= 0;
            else
                wr_ptr <= wr_ptr + 1;
            count <= count + 1;
            state <= S_IDLE;
        end

        // ------------------------------------------------------------------
        // READ path
        // ------------------------------------------------------------------
        S_RD_CMD: begin
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= cmd_sr[7];
                    cmd_sr     <= {cmd_sr[6:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        bit_cnt <= 24;
                        state   <= S_RD_ADDR;
                    end
                end
            end
        end

        S_RD_ADDR: begin
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= addr_sr[23];
                    addr_sr    <= {addr_sr[22:0], 1'b0};
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        dummy_cnt <= 8;
                        state     <= S_RD_WAIT;
                    end
                end
            end
        end

        S_RD_WAIT: begin
            // 8 dummy clocks (MOSI don't-care, we just clock)
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    psram_si   <= 1'b0;
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    sclk_phase <= 1'b0;
                    dummy_cnt  <= dummy_cnt - 1;
                    if (dummy_cnt == 1) begin
                        bit_cnt <= ENTRY_BITS;
                        data_sr <= 0;
                        state   <= S_RD_DATA;
                    end
                end
            end
        end

        S_RD_DATA: begin
            // Sample SO on the rising edge of sclk
            if (sclk_en) begin
                if (!sclk_phase) begin
                    psram_sclk <= 1'b0;
                    sclk_phase <= 1'b1;
                end else begin
                    psram_sclk <= 1'b1;
                    // Shift in MSB-first
                    data_sr    <= {data_sr[ENTRY_BITS-2:0], psram_so};
                    sclk_phase <= 1'b0;
                    bit_cnt    <= bit_cnt - 1;
                    if (bit_cnt == 1) begin
                        state <= S_RD_DONE;
                    end
                end
            end
        end

        S_RD_DONE: begin
            psram_sclk <= 1'b0;
            psram_ce_n <= 1'b1;
            data_out   <= data_sr;
            data_valid <= 1'b1;
            if (rd_ptr == FIFO_DEPTH - 1)
                rd_ptr <= 0;
            else
                rd_ptr <= rd_ptr + 1;
            count <= count - 1;
            state <= S_IDLE;
        end

        default: state <= S_IDLE;
        endcase
    end
end

endmodule