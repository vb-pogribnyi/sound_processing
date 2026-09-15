`timescale 1ns / 1ps
// =====================================================================
// OV5640Test.v
// Drives a synthetic RAW-Bayer DVP stream (BGGR: even line B G B G,
// odd line G R G R) and checks that OV5640.v bins red vs green by pixel
// position. Verifies a red field reads red>>green, a green field reads
// green>>red, and a white field reads red ~= green.
// =====================================================================
module OV5640Test;

    reg sys_clk = 0;
    reg rst_n   = 0;

    reg pclk  = 0;
    reg href  = 0;
    reg vsync = 0;
    reg d7 = 0, d6 = 0, d3 = 0;

    wire [3:0] red, green;
    wire       cfg_done;
    wire       cam_xclk, cam_sioc, cam_pwdn, cam_resetb;
    tri1       cam_siod;

    // small averaging shifts for a deterministic small frame:
    //   red field  : 8 red px * 7      = 56 ; >>2 = 14
    //   white field: 16 green px * 7   = 112; >>3 = 14  (== red's 14)
    OV5640 #(
        .SCCB_DIV    (2),
        .PWRUP_TICKS (24'd2),
        .RED_SHIFT   (5'd2),
        .GREEN_SHIFT (5'd3),
        .RED_COL_PAR (1'b1),
        .RED_LINE_PAR(1'b1)
    ) dut (
        .i_CLK(sys_clk), .i_RST_N(rst_n),
        .o_XCLK(cam_xclk), .o_SIOC(cam_sioc), .o_SIOD(cam_siod),
        .o_PWDN(cam_pwdn), .o_RESETB(cam_resetb),
        .i_PCLK(pclk), .i_HREF(href), .i_VSYNC(vsync),
        .i_D7(d7), .i_D6(d6), .i_D3(d3),
        .o_RED(red), .o_GREEN(green), .o_CFG_DONE(cfg_done)
    );

    always #10 sys_clk = ~sys_clk;
    always #25 pclk    = ~pclk;

    integer errors = 0;

    localparam NLINES = 4;
    localparam NPIX   = 8;

    task pulse_vsync;
        begin
            vsync = 0; @(posedge pclk);
            vsync = 1; @(posedge pclk); @(posedge pclk);
            vsync = 0; @(posedge pclk);
        end
    endtask

    // Drive one RAW frame. red_on/green_on/blue_on select which Bayer
    // colours are bright (sample=7) vs dark (sample=0).
    task run_raw_frame;
        input red_on, green_on, blue_on;
        integer ln, cl;
        reg is_r, is_b, bright;
        begin
            for (ln = 0; ln < NLINES; ln = ln + 1) begin
                href = 1;
                for (cl = 0; cl < NPIX; cl = cl + 1) begin
                    is_r = (cl[0] == 1'b1) && (ln[0] == 1'b1);
                    is_b = (cl[0] == 1'b0) && (ln[0] == 1'b0);
                    bright = is_r ? red_on : is_b ? blue_on : green_on;
                    d7 = bright; d6 = bright; d3 = bright;
                    @(posedge pclk);
                end
                href = 0; d7 = 0; d6 = 0; d3 = 0;
                @(posedge pclk);   // HREF falling -> line advance
                @(posedge pclk);
            end
            pulse_vsync;           // latch frame averages
        end
    endtask

    task expect_gt;   // check a > b by margin
        input [3:0] a, b;
        input [127:0] name;
        begin
            if (a > b) $display("  %0s: red=%0d green=%0d  PASS", name, red, green);
            else begin
                $display("  %0s: red=%0d green=%0d  FAIL", name, red, green);
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        $dumpfile("OV5640Test.vcd");
        $dumpvars(0, OV5640Test);

        rst_n = 0;
        repeat (4) @(posedge sys_clk);
        rst_n = 1;
        repeat (4) @(posedge pclk);
        pulse_vsync;   // initial clear

        // RED field: only red-position pixels bright -> red >> green
        $display("--- RED field ---");
        run_raw_frame(1, 0, 0);
        repeat (8) @(posedge sys_clk);
        expect_gt(red, green, "red field  (expect red>green)");

        // GREEN field: only green-position pixels bright -> green >> red
        $display("--- GREEN field ---");
        run_raw_frame(0, 1, 0);
        repeat (8) @(posedge sys_clk);
        expect_gt(green, red, "green field (expect green>red)");

        // WHITE field: all bright -> red ~= green (within 1 LSB)
        $display("--- WHITE field ---");
        run_raw_frame(1, 1, 1);
        repeat (8) @(posedge sys_clk);
        if (red == green || (red>green?red-green:green-red) <= 1)
            $display("  white field: red=%0d green=%0d  PASS (balanced)", red, green);
        else begin
            $display("  white field: red=%0d green=%0d  FAIL (unbalanced)", red, green);
            errors = errors + 1;
        end

        $display("========================================");
        if (errors == 0) $display("  ALL TESTS PASSED");
        else             $display("  %0d FAILURES", errors);
        $display("========================================");
        $finish;
    end

    initial begin
        #5000000;
        $display("TIMEOUT");
        $finish;
    end

endmodule
