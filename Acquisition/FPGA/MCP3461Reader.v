module MCP3461Reader (
    input wire i_CLK50,
    input wire i_MISO,
    input wire i_SCLK,
    input wire i_CS,
    output reg o_RDY,
    output reg [15:0] o_VALUE,
    output wire o_VALID          // address-ack validity of the latest STATUS byte
);

reg [7:0] bit_idx = 0;
reg [31:0] rx_shift_reg = 0;
reg is_valid = 0;

always @(posedge i_SCLK) begin
    if (!i_CS) begin
        // Read from MISO
        if (bit_idx == 0) begin
            is_valid <= 0;
        end
        if (bit_idx > 1) begin  // First 2 bits are always invalid
            if (bit_idx < 24) begin
                rx_shift_reg <= {rx_shift_reg[30:0], i_MISO};
                o_RDY <= 0;
            end
            if (bit_idx == 7) begin
                is_valid <= rx_shift_reg[0] == !i_MISO;
            end
        end
        bit_idx <= bit_idx + 1;
    end
    else begin
        // Reset reading
        bit_idx <= 0;
        rx_shift_reg <= 0;
    end
    if (bit_idx == 24) begin
        o_VALUE <= rx_shift_reg[15:0];
        // Assert RDY only when the ADC's STATUS byte reported fresh data.
        // The read clocks STATUS(8b) + DATA(16b); the STATUS byte's
        // DR_STATUS bit (STAT[2], active-low: 0 = new data) was shifted into
        // rx_shift_reg[18] (4th of the 22 captured bits). Suppress RDY on
        // stale reads so duplicate samples are not pushed downstream.
        o_RDY <= ~rx_shift_reg[18];
    end
end

// Expose the address-ack check (2 device-address bits + 1 inverted bit) so the
// master can enforce it: a floating/unpopulated channel cannot reproduce the
// complementary pattern, so its is_valid stays low.
assign o_VALID = is_valid;

endmodule