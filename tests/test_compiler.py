#!/usr/bin/env python3
"""
HP Prime PPL Test Suite
=======================
Run:  py -m pytest test_ppl.py -v
      py -m pytest test_ppl.py -v -k "test_print"   (run one test)

Each test writes PPL code, transpiles it, executes it, and checks:
  - stdout PRINT output  (via captured stdout)
  - no transpile/runtime crashes
  - optionally, pixel colors on the 320x240 screen
"""

import sys, os, io, math, contextlib, tempfile
import pytest  # pyre-ignore

# Ensure project dir is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.ppl_emulator.transpiler import transpile  # pyre-ignore
from src.ppl_emulator.runtime import HPPrimeRuntime, PPLList  # pyre-ignore


# ── Helper ────────────────────────────────────────────────────────

def run_ppl(code, out_png=None):
    """
    Transpile + execute PPL code.
    Returns (stdout_text, runtime_instance, transpiled_python).
    Raises on transpile or execution error.
    """
    if out_png is None:
        out_png = os.path.join(tempfile.gettempdir(), "_ppl_test_screen.png")

    py_code = transpile(code, out_path=out_png)

    # Capture stdout (PRINT output)
    buf = io.StringIO()
    ns = {"__name__": "__main__", "__file__": "<test>"}

    with contextlib.redirect_stdout(buf):
        exec(compile(py_code, "<ppl_test>", "exec"), ns)

    # Fish out the runtime instance for pixel checks
    rt = ns.get("_rt")
    return buf.getvalue(), rt, py_code


def printed_lines(stdout_text):
    """Split captured stdout into non-empty lines, stripping whitespace."""
    return [l.strip() for l in stdout_text.splitlines() if l.strip()]


# ── PRINT / math tests ───────────────────────────────────────────

class TestPrint:

    def test_print_number(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(42);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "42" in out

    def test_print_expression(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(2+3);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "5" in out

    def test_print_string(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT("hello");
        END;
        """
        out, _, _ = run_ppl(code)
        assert "hello" in out

    def test_print_multiple(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(1);
          PRINT(2);
          PRINT(3);
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["1", "2", "3"]

    def test_math_ops(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(10 MOD 3);
          PRINT(10 DIV 3);
          PRINT(2^3);
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["1", "3", "8"]


# ── Variable / assignment tests ───────────────────────────────────

class TestVariables:

    def test_local_var(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 10;
          PRINT(x);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "10" in out

    def test_reassign(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 5;
          x := x + 1;
          PRINT(x);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "6" in out

    def test_multiple_locals(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL a := 1, b := 2;
          PRINT(a + b);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "3" in out


# ── Control flow tests ────────────────────────────────────────────

class TestControlFlow:

    def test_if_true(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 5;
          IF x > 3 THEN
            PRINT("yes");
          END;
        END;
        """
        out, _, _ = run_ppl(code)
        assert "yes" in out

    def test_if_false(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 1;
          IF x > 3 THEN
            PRINT("yes");
          END;
          PRINT("done");
        END;
        """
        out, _, _ = run_ppl(code)
        assert "yes" not in out
        assert "done" in out

    def test_if_else(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 2;
          IF x > 5 THEN
            PRINT("big");
          ELSE
            PRINT("small");
          END;
        END;
        """
        out, _, _ = run_ppl(code)
        assert "small" in out

    def test_for_loop(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL s := 0;
          LOCAL i;
          FOR i FROM 1 TO 5 DO
            s := s + i;
          END;
          PRINT(s);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "15" in out

    def test_for_step(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL i;
          FOR i FROM 0 TO 10 STEP 2 DO
            PRINT(i);
          END;
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["0", "2", "4", "6", "8", "10"]

    def test_while_loop(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 0;
          WHILE x < 3 DO
            x := x + 1;
          END;
          PRINT(x);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "3" in out

    def test_repeat_until(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL x := 0;
          REPEAT
            x := x + 1;
          UNTIL x >= 5;
          PRINT(x);
        END;
        """
        out, _, _ = run_ppl(code)
        assert "5" in out


# ── Function call tests ──────────────────────────────────────────

class TestFunctions:

    def test_helper_function(self):
        code = """
        add(a, b)
        BEGIN
          RETURN a + b;
        END;

        EXPORT T()
        BEGIN
          PRINT(add(3, 4));
        END;
        """
        out, _, _ = run_ppl(code)
        assert "7" in out

    def test_recursive_function(self):
        code = """
        fact(n)
        BEGIN
          IF n <= 1 THEN
            RETURN 1;
          END;
          RETURN n * fact(n - 1);
        END;

        EXPORT T()
        BEGIN
          PRINT(fact(5));
        END;
        """
        out, _, _ = run_ppl(code)
        assert "120" in out


# ── Built-in math function tests ─────────────────────────────────

class TestBuiltins:

    def test_abs(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(ABS(-7));
        END;
        """
        out, _, _ = run_ppl(code)
        assert "7" in out

    def test_max_min(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(MAX(3, 9));
          PRINT(MIN(3, 9));
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["9", "3"]

    def test_sqrt(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(SQRT(16));
        END;
        """
        out, _, _ = run_ppl(code)
        assert "4" in out

    def test_floor_ceiling(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(FLOOR(3.7));
          PRINT(CEILING(3.2));
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["3", "4"]

    def test_ifte(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(IFTE(1 > 0, "yes", "no"));
          PRINT(IFTE(1 < 0, "yes", "no"));
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["yes", "no"]

    def test_rgb(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(RGB(255, 0, 0));
        END;
        """
        out, _, _ = run_ppl(code)
        assert str(0xFF0000) in out


# ── Graphics tests ────────────────────────────────────────────────

class TestGraphics:

    def test_rect_clears_screen(self):
        """RECT() with no args should clear screen to white."""
        code = """
        EXPORT T()
        BEGIN
          RECT();
        END;
        """
        _, rt, _ = run_ppl(code)
        # Center pixel should be white
        px = rt.img.getpixel((160, 120))  # pyre-ignore
        assert px == (255, 255, 255)

    def test_pixon(self):
        """PIXON_P should set a specific pixel."""
        code = """
        EXPORT T()
        BEGIN
          RECT();
          PIXON_P(50, 50, #FF0000h);
        END;
        """
        _, rt, _ = run_ppl(code)
        px = rt.img.getpixel((50, 50))  # pyre-ignore
        assert px == (255, 0, 0)

    def test_line(self):
        """LINE_P should draw a black line."""
        code = """
        EXPORT T()
        BEGIN
          RECT();
          LINE_P(0, 0, 100, 0, #000000h);
        END;
        """
        _, rt, _ = run_ppl(code)
        # Pixel on the line should be black
        px = rt.img.getpixel((50, 0))  # pyre-ignore
        assert px == (0, 0, 0)
        # Pixel off the line should be white
        px2 = rt.img.getpixel((50, 50))  # pyre-ignore
        assert px2 == (255, 255, 255)

    def test_filled_rect(self):
        """RECT_P with fill color."""
        code = """
        EXPORT T()
        BEGIN
          RECT();
          RECT_P(10, 10, 50, 50, #0000FFh, #0000FFh);
        END;
        """
        _, rt, _ = run_ppl(code)
        px = rt.img.getpixel((30, 30))  # pyre-ignore
        assert px == (0, 0, 255)

    def test_textout(self):
        """TEXTOUT_P should not crash."""
        code = """
        EXPORT T()
        BEGIN
          RECT();
          TEXTOUT_P("Hello", 10, 10, 1, #000000h);
        END;
        """
        _, rt, _ = run_ppl(code)
        # Just verify it didn't crash and screen exists
        assert rt.img.size == (320, 240)  # pyre-ignore

    def test_circle(self):
        """FILLCIRCLE_P should fill pixels."""
        code = """
        EXPORT T()
        BEGIN
          RECT();
          FILLCIRCLE_P(100, 100, 20, #FF0000h);
        END;
        """
        _, rt, _ = run_ppl(code)
        # Center of circle should be red
        px = rt.img.getpixel((100, 100))  # pyre-ignore
        assert px == (255, 0, 0)


# ── PPL List (1-indexed array) tests ─────────────────────────────

class TestLists:

    def test_list_literal(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL L := {10, 20, 30};
          PRINT(L(1));
          PRINT(L(2));
          PRINT(L(3));
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["10", "20", "30"]

    def test_local_array(self):
        code = """
        EXPORT T()
        BEGIN
          LOCAL A[5];
          A(1) := 99;
          A(2) := 42;
          PRINT(A(1));
          PRINT(A(2));
        END;
        """
        out, _, _ = run_ppl(code)
        lines = printed_lines(out)
        assert lines == ["99", "42"]


# ── Transpiler error handling ─────────────────────────────────────

class TestTranspiler:

    def test_empty_code_still_runs(self):
        """An empty EXPORT function should not crash."""
        code = """
        EXPORT T()
        BEGIN
        END;
        """
        out, _, _ = run_ppl(code)
        # No crash = pass

    def test_transpile_produces_python(self):
        code = """
        EXPORT T()
        BEGIN
          PRINT(1);
        END;
        """
        py = transpile(code)
        assert "def T(" in py
        assert "PRINT" in py


# ── Run directly ──────────────────────────────────────────────────

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
