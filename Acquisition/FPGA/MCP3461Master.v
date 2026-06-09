module MCP3461Master #(
    parameter NUM_ADC   = 4
) (
    input wire i_CLK50,
    input wire i_INTERRUPT,
    input wire [NUM_ADC-1:0] i_MISO,
    // output wire sel_interrupt,
    output reg o_MOSI,
    output reg o_CS,
    output wire o_SCLK,
    output wire o_MCLK,
    output wire [16 * NUM_ADC-1:0] o_VALUE
);
reg [7:0] tx_buff [0:16];
reg [7:0] tx_len = 0;
reg [7:0] cfg [0:4];
reg [3:0] byte_idx;
reg [2:0] bit_idx;
reg [7:0] tx_shift_reg;

reg transmitting = 0;
reg trigger = 0;
reg sclk = 0;
integer i;
assign o_SCLK = sclk & !o_CS;
localparam cmd_read_int = 8'h15;
localparam cmd_read_val = 8'h10;
localparam	TIMEOUT = 4;
localparam	FRESH       = 3'h0,
            ALIVE       = 3'h1,
            // CONFIGURING = 3'h2,
            READING     = 3'h3,
            ERROR       = 3'h4;
reg [2:0] state = FRESH;
reg [1:0] cnt = 0;
reg [16:0] to_cnt = TIMEOUT;
wire [NUM_ADC-1:0] reader_rdy;
genvar gi;
generate
for (gi = 0; gi < NUM_ADC ; gi = gi + 1) begin: readers
    MCP3461Reader reader ( 
        .i_CLK50(i_CLK50),
        .i_MISO(i_MISO[gi]),
        .i_SCLK(sclk),
        .i_CS(o_CS),
        .o_RDY(reader_rdy[gi]),
        .o_VALUE(o_VALUE[16 * (gi+1)-1:16 * gi])
    );
end
endgenerate;
initial begin
    o_CS = 1;
    cfg[0] = 8'hC3;  // CONFIG0. Internal ref, external MCLK, no current, conv mode
    cfg[1] = 8'h00;  // CONFIG1. No prescaler, smallest oversampling
    cfg[2] = 8'h45;  // CONFIG2. No current scale, no gain, no input chopping, yes ref chopping
    cfg[3] = 8'hC0;  // CONFIG3. Continuous conversion, 16-bit coding, no CRC, no calibration
    cfg[4] = 8'h00;  // IRQ. Enabled, no "start" interrupt
    // Actually from this point on the default configuration is OK.
    // cfg[5] = 8'h01;  // MUX. Measuring CH0 vs CH1
    // cfg[6] = 8'h45;  // SCAN. 
    // Fill configuration...
    
end
// SDI (MOSI) clocked on rising edge, update should be on falling edge
// SDO (MISO) clocked out on falling edge, read should be on rising edge.
assign o_MCLK = (cnt >= 2);
always @(posedge i_CLK50) begin
    cnt <= cnt + 1;
    if (cnt == 0) begin // 6 MHZ clock
        sclk <= !sclk;

        // The state-machine sets transmission data and trigger, if required.
        case(state)
            FRESH: begin    // Just powered up, maybe not yet initialized
                if (to_cnt > 0) begin  // HOOLD
                    to_cnt <= to_cnt - 1;
                end
                else begin
                    if (!trigger && !transmitting && tx_len == 0) begin
                        tx_len <= 1;
                        tx_buff[0] <= cmd_read_int;
                        trigger <= 1;
                    end
                    if (!trigger && !transmitting && tx_len > 0) begin
                        // TODO: Check if the answer is valid
                        // That would mean the ADC is ready to talk.
                        tx_len <= 0;
                        state <= ALIVE;
                    end
                end
            end
            ALIVE: begin    // The ADC is ready to be configured
                if (!trigger && !transmitting && o_CS && tx_len == 0) begin
                    tx_len <= 5;
                    tx_buff[0] <= cfg[0];
                    tx_buff[1] <= cfg[1];
                    tx_buff[2] <= cfg[2];
                    tx_buff[3] <= cfg[3];
                    tx_buff[4] <= cfg[4];
                    trigger <= 1;
                end
                if (!trigger && !transmitting && tx_len > 0) begin
                    // TODO: Check if the answer is valid
                    // That would mean the ADC is configured.
                    tx_len <= 0;
                    state <= READING;

                    to_cnt <= TIMEOUT;
                end
            end
            READING: begin    // Main operation loop
                if (to_cnt > 0) begin  // TODO: Wait for the interrupt to go low
                    to_cnt <= to_cnt - 1;
                end
                else begin
                    if (!trigger && !transmitting && o_CS && tx_len == 0) begin
                        tx_len <= 3;    // 1 byte status 2 bytes ADC value
                        tx_buff[0] <= cmd_read_val;
                        tx_buff[1] <= 0;
                        tx_buff[2] <= 0;
                        trigger <= 1;
                    end
                    if (!trigger && !transmitting && o_CS && tx_len > 0) begin
                        // TODO: Output the ADC value
                        tx_len <= 0;
                        to_cnt <= TIMEOUT;
                    end
                end
            end
        endcase
        if (trigger && !transmitting) begin
            transmitting <= 1;
            trigger <= 0;
            byte_idx <= 0;
            bit_idx <= 7;
            tx_shift_reg <= tx_buff[0];
        end
        if (transmitting) begin
            if (sclk) begin // Falling edge; sclk will update to low at the end of posedge handler
                // if (read_offset > 1) begin
                //     read_offset <= 2;
                // end
                tx_shift_reg <= {tx_shift_reg[6:0], 1'b0};
                o_MOSI <= tx_shift_reg[7];
                o_CS <= 0;
                if (bit_idx == 0) begin
                    byte_idx <= byte_idx + 1;
                    tx_shift_reg <= tx_buff[byte_idx + 1];
                    bit_idx <= 7;
                end
                else begin
                    bit_idx <= bit_idx - 1;
                end
                if (bit_idx == 7) begin
                    if (byte_idx == tx_len) begin
                        transmitting <= 0;
                    end
                end
            end
        end
        else begin
            o_CS <= 1;
        end
    end
end
endmodule