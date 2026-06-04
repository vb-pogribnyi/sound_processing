module MCP3461Master #(
    parameter NUM_ADC   = 4
) (
    input wire i_CLK50,
    input wire i_INTERRUPT,
    input wire [NUM_ADC-1:0] i_MISO,
    // output wire sel_interrupt,
    output wire o_MOSI,
    output wire o_CS,
    output wire o_SCLK,
    output wire o_MCLK
);
reg [1:0] cnt = 0;
assign o_MCLK = (cnt >= 2);
always @(posedge i_CLK50) begin
    cnt <= cnt + 1;
end
endmodule