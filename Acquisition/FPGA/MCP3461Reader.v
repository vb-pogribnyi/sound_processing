module MCP3461Reader (
    input wire i_CLK50,
    input wire i_MISO,
    input wire i_SCLK,
    input wire i_CS,
    output reg o_RDY,
    output reg [15:0] o_VALUE
);

reg [7:0] bit_idx = 0;
reg [31:0] rx_shift_reg = 0;
reg is_valid = 0;

always @(posedge i_SCLK) begin
    if (!i_CS) begin
        // Read from MISO
        if (bit_idx > 1) begin  // First 2 bits are always invalid
            if (bit_idx < 24) begin
                rx_shift_reg <= {rx_shift_reg[30:0], i_MISO};
                o_RDY <= 0;
            end
            if (bit_idx == 7) begin
                is_valid <= rx_shift_reg[0] == !rx_shift_reg[1];
            end
        end
        bit_idx <= bit_idx + 1;
    end
    else begin
        // Reset reading
        bit_idx <= 0;
        is_valid <= 0;
        rx_shift_reg <= 0;
    end
    if (bit_idx == 24) begin
        o_VALUE <= rx_shift_reg[15:0];
        o_RDY <= 1;
    end
end

endmodule