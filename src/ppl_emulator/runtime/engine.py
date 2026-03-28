"""
HP Prime runtime engine.

Provides ``HPPrimeRuntime`` — the Python object that is bound to ``_rt`` in
every transpiled program.  It emulates the HP Prime built-in environment:

  * Graphics (RECT_P, LINE_P, CIRCLE_P, TEXTOUT_P, …) via live pygame window
  * Math builtins (SIN/COS take degrees, matching HP Prime behaviour)
  * String functions (LEFT, RIGHT, MID, INSTRING, …)
  * I/O (PRINT, INPUT, CHOOSE, GETKEY) with headless-safe defaults
  * Variable scoping via ScopeStack (locals shadow globals, PPLVar boxing)
"""
import os
import sys
import math
import random
import time
import re
from PIL import Image, ImageDraw, ImageFont  # type: ignore
try:
    import pygame  # type: ignore
except Exception:
    pygame = None
from src.ppl_emulator.runtime.types import PPLList, PPLString, PPLVar, PPLMatrix
from src.ppl_emulator.transpiler.constants import BUILTINS
from src.ppl_emulator.runtime.ppl_runtime import CAS, ppl_expr, DET

def _coerce_list(value):
    """Wrap a plain Python list in the appropriate PPL type.

    A flat list becomes PPLList; a list-of-lists becomes PPLMatrix
    (Discrepancy 1: matrix elements must be mutable).
    PPLVar items are unwrapped to their current value so that list literals
    like [i] store a snapshot of i's value, not a live reference to the variable.
    """
    if isinstance(value, PPLVar):
        # Unwrap the boxed variable so list literals capture the value, not the
        # live PPLVar reference (which would mutate as the variable changes).
        return _coerce_list(value.value)
    if isinstance(value, (PPLList, PPLMatrix, PPLString)):
        if isinstance(value, PPLList):
            # If a PPLList contains list-like rows, treat it as a 2-D matrix.
            if value and all(isinstance(item, (list, PPLList, PPLMatrix)) for item in value):
                return PPLMatrix([[_coerce_list(x) for x in row] for row in value])
        return value
    if isinstance(value, list):
        # Discrepancy 1 fix: a Python list-of-lists (i.e. a 2-D structure) becomes a
        # PPLMatrix so that element assignment is allowed but dimension changes are not.
        if value and all(isinstance(item, (list, PPLList, PPLMatrix)) for item in value):
            return PPLMatrix([[_coerce_list(x) for x in row] for row in value])
        return PPLList([_coerce_list(item) for item in value])
    return value

class HP_Grob:
    """An HP Prime GROB (graphic object) backed by a Pillow Image."""

    def __init__(self, width, height, color=None, runtime=None):
        self.width = int(width)
        self.height = int(height)
        bg = runtime._color(color) if (color is not None and runtime) else (255, 255, 255)
        self.img = Image.new('RGB', (self.width, self.height), bg)
        self.draw = ImageDraw.Draw(self.img)

    def clear(self, color, runtime):
        self.draw.rectangle([0, 0, self.width-1, self.height-1], fill=runtime._color(color))

class PPLError(Exception):
    """Runtime error raised by PPL built-ins (e.g. arity mismatch)."""

    def __init__(self, message, line_no=None):
        super().__init__(message)
        self.message = message
        self.line_no = line_no

class ScopeStack:
    """Stack of variable scopes.

    Each PUSH_BLOCK call adds a new scope frame; POP_BLOCK removes it.
    Variable lookup walks from innermost to outermost scope.
    In compiled_mode, accessing an undeclared variable raises NameError
    instead of silently creating a zero-initialised global.
    """

    def __init__(self, runtime=None, compiled_mode=False):
        self.stack = [{}]
        self.runtime = runtime
        # Discrepancy 3 fix: when compiled_mode is True (i.e. we are running a compiled
        # .hpprgm program), referencing an undeclared variable is a hard NameError rather
        # than silently creating a global initialised to 0.  Interactive/REPL callers
        # leave compiled_mode=False to preserve the tolerant behaviour.
        self.compiled_mode = compiled_mode

    def push(self):
        self.stack.append({})

    def pop(self):
        if len(self.stack) > 1:
            self.stack.pop()

    def get(self, name, line_no=None):
        name = name.upper()
        for scope in reversed(self.stack):
            if name in scope:
                return scope[name]
        if self.compiled_mode:
            loc = f" (line {line_no})" if line_no is not None else ""
            raise NameError(
                f"Undeclared variable '{name}' referenced{loc}. "
                "Declare it with LOCAL or assign it before use."
            )
        # Interactive / tolerant mode: auto-initialise to 0 in global scope.
        from src.ppl_emulator.runtime.types import PPLVar
        new_var = PPLVar(0)
        self.stack[0][name] = new_var
        return new_var

    def set(self, name, value, is_local=False):
        name = name.upper()
        from src.ppl_emulator.runtime.types import PPLVar, PPLList, PPLString

        if isinstance(value, str) and not isinstance(value, PPLString):
            value = PPLString(value)
        if isinstance(value, list) and not isinstance(value, (PPLList, PPLMatrix)):
            value = _coerce_list(value)

        if is_local:
            if name in self.stack[-1] and isinstance(self.stack[-1][name], PPLVar):
                self.stack[-1][name].value = value.value if isinstance(value, PPLVar) else value
            else:
                self.stack[-1][name] = value if isinstance(value, PPLVar) else PPLVar(value)
        else:
            for scope in reversed(self.stack):
                if name in scope:
                    if isinstance(scope[name], PPLVar):
                        scope[name].value = value.value if isinstance(value, PPLVar) else value
                    else:
                        scope[name] = value if isinstance(value, PPLVar) else PPLVar(value)
                    return
            self.stack[0][name] = value if isinstance(value, PPLVar) else PPLVar(value)

class HPPrimeRuntime:
    """Central emulation object — bound to ``_rt`` in every transpiled program.

    Manages variable scopes, graphics output, and all HP Prime built-in
    functions. Graphics are rendered in a 320×240 pygame window and mirrored
    to a Pillow image for compatibility and PNG export.
    """

    _pending_input_queue: list = []
    # When True, always allow PNG save even if a live pygame window exists.
    _force_save_output_default: bool = False
    # Discrepancy 3: set to True before exec()ing transpiled code to enable strict
    # compiled-mode variable lookup (undeclared vars raise NameError).
    # The CLI sets this via HPPrimeRuntime._compiled_mode = True before exec().
    _compiled_mode: bool = False
    # CLI --args values fed into the EXPORT function's default call.
    _entry_args: list = []

    def __init__(self, compiled_mode=None):
        self.width  = 320
        self.height = 240
        # Track whether any graphics call has mutated the framebuffer.
        self.screen_is_dirty = False
        # Track last saved output path (if any).
        self._last_saved_path = None
        self._force_save_output = HPPrimeRuntime._force_save_output_default
        # Optional real-time pygame display.
        self._pg_enabled = False
        self._pg_should_close = False
        self._pg_window = None
        self._pg_window_size = (560, 460)
        self._pg_screen = None
        self._pg_font = None
        self._pg_fonts: dict[int, object] = {}
        self.grobs = [HP_Grob(self.width, self.height, runtime=self)] + [None]*9
        self.G0 = self.grobs[0]
        self.img = self.G0.img
        self.draw = self.G0.draw
        self._getkey_calls = 0
        self._wait_calls   = 0
        self._input_cancelled = 0
        self._iskeydown_calls = 0
        self._choose_calls = 0
        self._input_queue: list = HPPrimeRuntime._pending_input_queue[:]
        HPPrimeRuntime._pending_input_queue = []
        # Terminal text buffer — lines printed via PRINT() shown on the pygame screen.
        self._terminal_lines: list[str] = []
        self._terminal_font = None   # initialised lazily after pygame.font.init()
        # Set to True once any explicit graphics call (RECT_P, LINE_P, etc.) is made.
        # When True, _render_terminal does NOT clear the screen so graphics are preserved.
        self._graphics_mode: bool = False
        self.CAS    = CAS(self)
        self.Finance = _FinanceMock()
        self._fn_registry: dict[str, int] = {}
        # Discrepancy 3: resolve compiled_mode — explicit arg > class flag > default False.
        if compiled_mode is None:
            compiled_mode = HPPrimeRuntime._compiled_mode
        self.scopes = ScopeStack(runtime=self, compiled_mode=compiled_mode)
        self.COERCE = _coerce_list

        # Initialize pygame window if available.
        if pygame is not None:
            try:
                pygame.init()
                pygame.font.init()
                self._pg_window = pygame.display.set_mode(self._pg_window_size, pygame.RESIZABLE)
                self._pg_screen = pygame.Surface((self.width, self.height)).convert()
                pygame.display.set_caption("HP Prime Emulator")
                self._pg_enabled = True
                self._pg_font = self._get_pg_font(14)
                # Start with a white background like the PIL buffer.
                self._pg_screen.fill((255, 255, 255))
                self._present_display()
                pygame.display.flip()
            except Exception:
                self._pg_enabled = False

        for i in range(10):
            name = f"G{i}"
            setattr(self, name, self.grobs[i])
            self.SET_VAR(name, self.grobs[i])
        
        # Pre-seed HP Prime's named single-letter variables (X, Y, Z, T, N, K)
        # with their own name as a string placeholder so they exist in scope.
        for v in ['X', 'Y', 'Z', 'T', 'N', 'K']:
            self.SET_VAR(v, v)

        self.SET_VAR('PI', math.pi)
        self.SET_VAR('E', math.e)

    def __getattr__(self, name):
        name_up = name.upper()
        if name_up in BUILTINS:
            def cas_wrapper(*args):
                return getattr(self.CAS, name.lower())(*args)
            return cas_wrapper
        raise AttributeError(f"'HPPrimeRuntime' object has no attribute '{name}'")

    def REGISTER_FN(self, name: str, arity: int):
        self._fn_registry[name.upper()] = arity

    def CHECK_ARITY(self, name: str, got: int, line_no=None):
        key = name.upper()
        if key in self._fn_registry:
            expected = self._fn_registry[key]
            if got != expected:
                raise PPLError(f'Function "{name}" expects {expected} argument(s), got {got}.', line_no)

    def GET_VAR(self, name, line_no=None):
        return self.scopes.get(name, line_no)

    def SET_VAR(self, name, value, is_local=False):
        self.scopes.set(name, value, is_local)

    def PUSH_BLOCK(self):
        self.scopes.push()

    def POP_BLOCK(self):
        self.scopes.pop()

    # ── Pygame helpers ───────────────────────────────────────────────

    def _get_pg_font(self, size):
        if pygame is None:
            return None
        size = max(1, int(size))
        cached = self._pg_fonts.get(size)
        if cached is not None:
            return cached

        font_obj = None
        for name in ("consolas", "couriernew", "courier", "dejavusansmono", "liberationmono", "monospace"):
            try:
                path = pygame.font.match_font(name)
                if path:
                    font_obj = pygame.font.Font(path, size)
                    break
            except Exception:
                continue
        if font_obj is None:
            font_obj = pygame.font.SysFont("monospace", size)

        self._pg_fonts[size] = font_obj
        return font_obj

    def _present_display(self):
        if not self._pg_enabled or pygame is None or self._pg_window is None or self._pg_screen is None:
            return

        ww, wh = self._pg_window.get_size()

        # ── HP Prime G1 screen-only view ──────────────────────────────
        # Dark aluminium background (matches G1 body colour).
        BG       = (28, 30, 36)
        BEZEL    = (44, 46, 54)       # outer bezel face
        BEZEL_HI = (72, 76, 88)       # highlight rim
        BEZEL_SH = (18, 19, 23)       # shadow rim
        INNER    = (10, 11, 14)       # recessed screen surround
        HDR_BG   = (22, 24, 30)       # title-bar strip
        HDR_TXT  = (180, 185, 200)    # title-bar text
        ACCENT   = (0, 113, 197)      # HP blue accent line

        self._pg_window.fill(BG)

        # Outer bezel — rounded rectangle with a subtle 3-D rim.
        margin = max(18, min(ww, wh) // 18)
        bezel_rect = pygame.Rect(margin, margin, ww - 2 * margin, wh - 2 * margin)
        pygame.draw.rect(self._pg_window, BEZEL, bezel_rect, border_radius=18)
        # Highlight (top-left edge)
        pygame.draw.rect(self._pg_window, BEZEL_HI, bezel_rect, width=1, border_radius=18)
        # Shadow inset (bottom-right feel via a second rect 1 px smaller)
        shadow_r = bezel_rect.inflate(-2, -2)
        pygame.draw.rect(self._pg_window, BEZEL_SH, shadow_r, width=1, border_radius=16)

        # Title bar strip at top of bezel.
        hdr_h = max(22, bezel_rect.height // 14)
        hdr_rect = pygame.Rect(bezel_rect.x + 1, bezel_rect.y + 1,
                               bezel_rect.width - 2, hdr_h)
        # Clip to rounded top corners by drawing over bezel background first.
        pygame.draw.rect(self._pg_window, HDR_BG, hdr_rect)
        # HP blue accent line under the title bar.
        accent_y = hdr_rect.bottom
        pygame.draw.line(self._pg_window, ACCENT,
                         (bezel_rect.x + 4, accent_y),
                         (bezel_rect.right - 4, accent_y), 2)
        # "HP Prime" label in title bar.
        try:
            label_font = pygame.font.SysFont("segoeui,arial,sans-serif", max(11, hdr_h - 6), bold=True)
        except Exception:
            label_font = pygame.font.SysFont("monospace", max(11, hdr_h - 6))
        lbl = label_font.render("HP Prime", True, HDR_TXT)
        self._pg_window.blit(lbl, (bezel_rect.x + 10, hdr_rect.y + (hdr_h - lbl.get_height()) // 2))

        # Recessed screen area below title bar.
        pad = max(10, bezel_rect.width // 28)
        screen_area_top = accent_y + pad
        screen_area = pygame.Rect(
            bezel_rect.x + pad,
            screen_area_top,
            bezel_rect.width - 2 * pad,
            bezel_rect.bottom - screen_area_top - pad,
        )
        pygame.draw.rect(self._pg_window, INNER, screen_area, border_radius=6)
        pygame.draw.rect(self._pg_window, BEZEL_SH, screen_area, width=2, border_radius=6)

        # Scale 320×240 content to fit screen_area, keeping 4:3.
        target_w = screen_area.width - 8
        target_h = int(target_w * 3 / 4)
        if target_h > screen_area.height - 8:
            target_h = screen_area.height - 8
            target_w = int(target_h * 4 / 3)
        target_w = max(4, target_w)
        target_h = max(3, target_h)

        screen_rect = pygame.Rect(
            screen_area.centerx - target_w // 2,
            screen_area.centery - target_h // 2,
            target_w,
            target_h,
        )
        scaled = pygame.transform.scale(self._pg_screen, (target_w, target_h))
        self._pg_window.blit(scaled, screen_rect.topleft)

    def _pg_pump(self):
        if not self._pg_enabled or pygame is None:
            return
        pygame.event.pump()
        for event in pygame.event.get([pygame.QUIT, pygame.VIDEORESIZE]):
            if event.type == pygame.QUIT:
                self._pg_should_close = True
                break
            if event.type == pygame.VIDEORESIZE and self._pg_window is not None:
                new_w = max(380, int(event.w))
                new_h = max(320, int(event.h))
                self._pg_window = pygame.display.set_mode((new_w, new_h), pygame.RESIZABLE)
                self._present_display()
                pygame.display.flip()
        if self._pg_should_close:
            self.close()
            raise SystemExit(0)

    # ── Output ───────────────────────────────────────────────────────

    def PRINT(self, *args):
        text = ' '.join(str(a) for a in args)
        print(text)
        self._terminal_lines.append(text)
        if self._pg_enabled and pygame is not None and self._pg_screen is not None:
            self._render_terminal()
            self._present_display()
            pygame.display.flip()

    def _render_terminal(self):
        """Draw all buffered PRINT lines onto the 320×240 _pg_screen.

        Pure terminal mode (no graphics calls): clears to white first, like the
        HP Prime Home view.  Graphics mode: overlays text on existing content.
        """
        if pygame is None or self._pg_screen is None:
            return
        # Lazily build a small monospace font
        if self._terminal_font is None:
            try:
                self._terminal_font = pygame.font.SysFont("consolas,courier new,monospace", 14)
            except Exception:
                self._terminal_font = pygame.font.Font(None, 16)
        font   = self._terminal_font
        line_h = font.get_linesize() + 2
        pad_x, pad_y = 4, 4
        max_w  = self.width - 2 * pad_x
        max_lines = max(1, (self.height - 2 * pad_y) // line_h)

        if not self._graphics_mode:
            self._pg_screen.fill((255, 255, 255))

        # Build a flat list of display rows (each logical PRINT line may word-wrap)
        rows: list[str] = []
        for line in self._terminal_lines:
            if font.size(line)[0] <= max_w:
                rows.append(line)
            else:
                # Simple character-level wrap
                cur = ''
                for ch in line:
                    if font.size(cur + ch)[0] <= max_w:
                        cur += ch
                    else:
                        rows.append(cur)
                        cur = ch
                if cur:
                    rows.append(cur)

        # Show only the bottom max_lines rows (scroll)
        visible_rows = rows[-max_lines:]
        for i, row in enumerate(visible_rows):
            surf = font.render(row, True, (0, 0, 0))
            self._pg_screen.blit(surf, (pad_x, pad_y + i * line_h))

    def MSGBOX(self, msg):
        text = f"[MSG] {msg}"
        print(text)
        self._terminal_lines.append(text)
        if self._pg_enabled and pygame is not None and self._pg_screen is not None:
            self._render_terminal()
            self._present_display()
            pygame.display.flip()

    def _get_entry_arg(self, idx: int):
        """Return the idx-th CLI --args value, coerced to int/float/str, defaulting to 0."""
        args = HPPrimeRuntime._entry_args
        if idx < len(args):
            val = args[idx]
            try:
                return int(val)
            except (ValueError, TypeError):
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return val
        return 0

    def INPUT(self, vars_spec, title="", labels=None, help_text=None):
        label = title if title else (vars_spec if isinstance(vars_spec, str) else "?")

        if self._input_queue:
            val = self._input_queue.pop(0)
            print(f"[INPUT] '{label}' <- '{val}'")
            if isinstance(vars_spec, str):
                self.SET_VAR(vars_spec, val)
            return 1

        mock_inputs = None
        if 'MOCK_INPUTS' in os.environ:
            mock_inputs = os.environ['MOCK_INPUTS'].split(',')
        if mock_inputs and len(mock_inputs) > 0:
            val = mock_inputs.pop(0)
            print(f"[INPUT] headless — mocking '{label}' with '{val}'")
            if isinstance(vars_spec, str):
                self.SET_VAR(vars_spec, val)
            return 1

        if sys.stdin and not sys.stdin.isatty():
            line = sys.stdin.readline()
            if line:
                val = line.strip()
                print(f"[INPUT] '{label}' (stdin) <- '{val}'")
                if isinstance(vars_spec, str):
                    self.SET_VAR(vars_spec, val)
                return 1
        
        if sys.stdin and sys.stdin.isatty():
            try:
                val = input(f"[INPUT] {label}: ")
                if isinstance(vars_spec, str):
                    self.SET_VAR(vars_spec, val)
                return 1
            except (EOFError, KeyboardInterrupt):
                print()

        self._input_cancelled += 1
        print(f"[INPUT] headless — '{label}' defaulting to \"\"")
        if isinstance(vars_spec, str):
            self.SET_VAR(vars_spec, "")
        return 0

    def CHOOSE(self, title, options, *extra):
        self._choose_calls += 1
        if not self._pg_enabled and self._choose_calls > 20:
            raise SystemExit(0)
        print(f"[CHOOSE] headless — '{title}' → 1 (first option)")
        return 1

    def WAIT(self, t=0):
        self._wait_calls += 1
        if not self._pg_enabled and self._wait_calls > 10:
            raise SystemExit(0)
        if self._pg_enabled and pygame is not None:
            self._present_display()
            pygame.display.flip()
            pygame.event.pump()
            self._pg_pump()
            try:
                pygame.time.delay(max(0, int(float(t) * 1000)))
            except Exception:
                time.sleep(float(t))
            return 4
        try:
            delay = max(0.0, float(t))
        except Exception:
            delay = 0.0
        if delay > 0:
            time.sleep(delay)
        return 4 

    # Maximum GETKEY iterations before auto-sending the ESC keycode (4).
    # This prevents headless programs from looping forever waiting for input.
    _GETKEY_MAX_CALLS: int = 30

    def GETKEY(self):
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            # Yield 5 ms to the OS so tight key-polling loops don't pin a CPU
            # core at 100%.  At 5 ms/call the effective poll rate is ~200 Hz —
            # fast enough to feel instantaneous to any human interaction.
            pygame.time.wait(5)
        self._getkey_calls += 1
        # After the threshold, simulate ESC (keycode 4) so GETKEY-based
        # event loops exit cleanly without requiring Ctrl+C.
        if not self._pg_enabled and self._getkey_calls > self._GETKEY_MAX_CALLS:
            return 4   # ESC / exit key on HP Prime
        # Return -1 (no key) for the first few calls, then start returning 0
        # so that programs that check k >= 0 see something meaningful.
        if self._getkey_calls <= 3:
            return -1
        return 0

    def ISKEYDOWN(self, key_code):
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            # 1 ms yield — shorter than GETKEY since ISKEYDOWN is called inside
            # animation loops that also do other work per frame.
            pygame.time.wait(1)
        self._iskeydown_calls += 1
        if not self._pg_enabled and self._iskeydown_calls > 30:
            raise SystemExit(0)
        return True

    def SIZE(self, obj):
        """Return the number of elements; 0 for non-sequences."""
        try:
            return len(obj)
        except TypeError:
            return 0

    def DIM(self, obj):
        """Alias for SIZE (HP Prime uses both names)."""
        return self.SIZE(obj)

    def MOUSE(self, idx=0): return PPLList([-1, -1, 0, 0, 0])

    def _color(self, c):
        """Convert an HP Prime packed colour integer to an (R, G, B) tuple."""
        if isinstance(c, tuple) and len(c) >= 3:
            return (int(c[0]) & 255, int(c[1]) & 255, int(c[2]) & 255)
        if isinstance(c, str):
            s = c.strip().lower()
            if s.startswith('#') and s.endswith('h'):
                s = f"0x{s[1:-1]}"
            elif s.endswith('h'):
                s = f"0x{s[:-1]}"
            try:
                c = int(s, 0)
            except (TypeError, ValueError):
                return (0, 0, 0)
        try:
            c = int(c)
        except (TypeError, ValueError):
            return (0, 0, 0)
        c = c & 0xFFFFFF
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)

    def RGB(self, r, g, b, a=255):
        return (int(r) << 16) | (int(g) << 8) | int(b)

    # ── Graphics ─────────────────────────────────────────────────────

    def RECT_P(self, *args):
        self.screen_is_dirty = True
        self._graphics_mode = True
        if not args:
            # Clear to white — write to both buffers
            self.draw.rectangle([0, 0, self.width-1, self.height-1], fill=(255,255,255))
            if self._pg_enabled and pygame is not None:
                self._pg_screen.fill((255, 255, 255))
            return
        x1, y1 = int(args[0]), int(args[1])
        x2, y2 = int(args[2]), int(args[3])
        color = self._color(args[4]) if len(args) > 4 else (0,0,0)
        fill = self._color(args[5]) if len(args) > 5 else None
        left, top = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        # Always keep Pillow in sync (used for PNG export and pixel tests)
        self.draw.rectangle([x1, y1, x2, y2], outline=color, fill=fill)
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            if fill is not None:
                pygame.draw.rect(self._pg_screen, fill, (left, top, w, h), 0)
            pygame.draw.rect(self._pg_screen, color, (left, top, w, h), 1)

    def LINE_P(self, x1, y1, x2, y2, color=0):
        self.screen_is_dirty = True
        c = self._color(color)
        # Always keep Pillow in sync
        self.draw.line([int(x1), int(y1), int(x2), int(y2)], fill=c)
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            pygame.draw.line(
                self._pg_screen, c, (int(x1), int(y1)), (int(x2), int(y2)), 1
            )

    def PIXON_P(self, x, y, color=0):
        self.screen_is_dirty = True
        c = self._color(color)
        # Always keep Pillow in sync
        self.draw.point([int(x), int(y)], fill=c)
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            self._pg_screen.set_at((int(x), int(y)), c)

    def RECT(self, *args): self.RECT_P(*args)
    def LINE(self, *args): self.LINE_P(*args)
    def PIXON(self, *args): self.PIXON_P(*args)

    def FILLCIRCLE_P(self, x, y, r, color=0):
        self.screen_is_dirty = True
        x, y, r = int(float(x)), int(float(y)), int(float(r))
        c = self._color(color)
        # Always keep Pillow in sync
        self.draw.ellipse([x-r, y-r, x+r, y+r], fill=c, outline=c)
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            pygame.draw.circle(self._pg_screen, c, (x, y), r, 0)

    def CIRCLE_P(self, x, y, r, color=0):
        self.screen_is_dirty = True
        x, y, r = int(float(x)), int(float(y)), int(float(r))
        c = self._color(color)
        # Always keep Pillow in sync
        self.draw.ellipse([x-r, y-r, x+r, y+r], outline=c)
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            pygame.draw.circle(self._pg_screen, c, (x, y), r, 1)

    def TEXTOUT_P(self, text, x, y, font=1, color=0, width=320, background=None):
        self.screen_is_dirty = True
        x, y = int(float(x)), int(float(y))
        c = self._color(color)
        # Always write to Pillow (PNG export / test pixel checks)
        self.draw.text((x, y), str(text), fill=c, font=ImageFont.load_default())
        if self._pg_enabled and pygame is not None:
            # Also render via pygame font for the live window (higher quality)
            try:
                self._pg_pump()
                size = max(8, int(float(font)))
                self._pg_font = self._get_pg_font(size)
                if self._pg_font is None:
                    self._pg_font = pygame.font.SysFont("monospace", size)
                surf = self._pg_font.render(str(text), True, c)
                self._pg_screen.blit(surf, (x, y))
            except Exception:
                pass

    def INVERT_P(self, x1=0, y1=0, x2=319, y2=239):
        self.screen_is_dirty = True
        x1, y1, x2, y2 = int(float(x1)), int(float(y1)), int(float(x2)), int(float(y2))
        # Ensure bounds are within image and ordered
        ix1 = max(0, min(x1, x2, self.width - 1))
        ix2 = max(0, min(max(x1, x2), self.width - 1))
        iy1 = max(0, min(y1, y2, self.height - 1))
        iy2 = max(0, min(max(y1, y2), self.height - 1))
        
        # Always invert the Pillow buffer (canonical store)
        pixels = self.img.load()
        for py in range(iy1, iy2 + 1):
            for px in range(ix1, ix2 + 1):
                r, g, b = pixels[px, py][:3]
                pixels[px, py] = (255 - r, 255 - g, 255 - b)
        # Mirror to pygame if live
        if self._pg_enabled and pygame is not None:
            self._pg_pump()
            for py in range(iy1, iy2 + 1):
                for px in range(ix1, ix2 + 1):
                    r, g, b, _ = self._pg_screen.get_at((px, py))
                    self._pg_screen.set_at((px, py), (255 - r, 255 - g, 255 - b))

    # ── Math ─────────────────────────────────────────────────────────

    def IP(self, x): return int(float(x))
    def FP(self, x): return float(x) - int(float(x))
    def ABS(self, x):
        r = abs(float(x))
        return int(r) if r.is_integer() else r
    def MAX(self, *args): return max(args)
    def MIN(self, *args): return min(args)
    def FLOOR(self, x): return math.floor(float(x))
    def CEILING(self, x): return math.ceil(float(x))
    def ROUND(self, x, n=0):
        n = int(n)
        r = round(float(x), n)
        return int(r) if n == 0 else r
    def SQ(self, x):
        r = float(x) * float(x)
        return int(r) if r.is_integer() else r
    def SQRT(self, x): return math.sqrt(float(x))
    def LOG(self, x): return math.log10(float(x))
    def LN(self, x): return math.log(float(x))
    def EXP(self, x): return math.exp(float(x))
    # HP Prime trig operates in degrees, not radians
    def SIN(self, x): return math.sin(math.radians(float(x)))
    def COS(self, x): return math.cos(math.radians(float(x)))
    def TAN(self, x): return math.tan(math.radians(float(x)))
    def ASIN(self, x): return math.degrees(math.asin(float(x)))
    def ACOS(self, x): return math.degrees(math.acos(float(x)))
    def ATAN(self, x): return math.degrees(math.atan(float(x)))
    def IFTE(self, cond, a, b): return a if cond else b
    def RANDOM(self, *args): return random.random()
    def RANDINT(self, a, b): return random.randint(int(a), int(b))

    def INTEGER(self, x): return int(float(x))
    def REAL(self, x): return float(x)
    def SIGN(self, x):
        x = float(x)
        return 1 if x > 0 else (-1 if x < 0 else 0)
    def TRUNCATE(self, x, n=0):
        n = int(n)
        if n == 0:
            return math.trunc(float(x))
        factor = 10**n
        r = math.trunc(float(x) * factor) / factor
        return int(r) if r.is_integer() else r

    # ── Strings ──────────────────────────────────────────────────────

    def ASC(self, s):
        s = str(s)
        return ord(s[0]) if s else 0
    def CHR(self, n): return chr(int(n))
    def TRIM(self, s): return str(s).strip()
    def STARTSWITH(self, s, sub): return 1 if str(s).startswith(str(sub)) else 0
    def ENDSWITH(self, s, sub): return 1 if str(s).endswith(str(sub)) else 0
    def CONTAINS(self, s, sub): return 1 if str(sub) in str(s) else 0

    # ── Bit operations ───────────────────────────────────────────────

    def BITSHIFT(self, n, s):
        """Shift n left by s bits (or right if s is negative)."""
        n, s = int(n), int(s)
        if s >= 0:
            return n << s
        else:
            return n >> abs(s)

    # ── List / collection operations ─────────────────────────────────

    def SORT(self, obj):
        if isinstance(obj, PPLVar): obj = obj.value
        if isinstance(obj, list):
            obj.sort()
        return obj

    def REVERSE(self, obj):
        if isinstance(obj, PPLVar): obj = obj.value
        if isinstance(obj, list):
            return PPLList(reversed(obj))
        if isinstance(obj, str):
            return str(obj)[::-1]
        return obj

    def ADDTAIL(self, obj, val):
        if isinstance(obj, PPLVar): obj = obj.value
        if isinstance(obj, list):
            obj.append(val)
        return obj

    def INSTRING(self, target, pattern, start=1):
        target, pattern = str(target), str(pattern)
        idx = target.find(pattern, int(start) - 1)
        return idx + 1 if idx != -1 else 0

    def LEFT(self, s, n): return str(s)[:int(n)]
    def RIGHT(self, s, n): 
        s, n = str(s), int(n)
        return s[-n:] if n > 0 else ""
    def MID(self, s, start, length=None):
        s, start = str(s), int(start) - 1
        if length is None: return s[start:]
        return s[start : start + int(length)]
    def CONCAT(self, a, b):
        if isinstance(a, PPLVar): a = a.value
        if isinstance(b, PPLVar): b = b.value
        if isinstance(a, list) and isinstance(b, list):
            return PPLList(list(a) + list(b))
        return str(a) + str(b)
    def POS(self, target, pattern): return self.INSTRING(target, pattern)
    def UPPER(self, s): return str(s).upper()
    def LOWER(self, s): return str(s).lower()
    def STRING(self, x, precision=None):
        if precision is None: return str(x)
        try: return format(float(x), f".{int(precision)}g")
        except: return str(x)
    def NUM(self, s):
        try: return float(s)
        except: return 0

    def BITAND(self, a, b): return int(a) & int(b)
    def BITOR(self, a, b): return int(a) | int(b)
    def BITXOR(self, a, b): return int(a) ^ int(b)
    def BITNOT(self, a): return ~int(a)

    def MOD(self, a, b): return int(a) % int(b)
    def DIV(self, a, b): return int(a) // int(b)
    def B_to_R(self, x): return int(x)
    def R_to_B(self, x, bits=32, digits=4): return int(round(float(x)))

    def REPLACE(self, obj, start_or_old, length_or_new, replacement=None):
        if replacement is None:
            return str(obj).replace(str(start_or_old), str(length_or_new))
        else:
            start, length = int(start_or_old) - 1, int(length_or_new)
            if isinstance(obj, list):
                res = PPLList(obj)
                res[start : start + length] = list(replacement)
                return res
            else:
                s = str(obj)
                return s[:start] + str(replacement) + s[start + length:]

    def EXPR(self, s): return ppl_expr(s)
    def MAKELIST(self, expr, var_name=None, start=1, end=1, step=1):
        """Create a PPL list by evaluating expr for var from start to end (inclusive).

        expr may be:
          - a no-arg lambda (transpiler wraps expressions so SET_VAR is called first)
          - a plain constant value (for MAKELIST(0, i, 1, n) style calls)
        var_name is the uppercased PPL variable name string used as the loop counter.
        """
        n_start = int(start) if start is not None else 1
        n_end   = int(end)   if end   is not None else 1
        n_step  = int(step)  if step  else 1
        indices = range(n_start, n_end + 1, n_step)
        if callable(expr):
            result = []
            for i in indices:
                if var_name:
                    self.SET_VAR(str(var_name), i)
                result.append(expr())
            return PPLList(result)
        # Constant expression — just repeat the value
        val = expr.value if isinstance(expr, PPLVar) else (expr if expr is not None else 0)
        return PPLList([val] * max(0, len(indices)))
    def EVAL(self, x): return self.EXPR(x)
    def sto(self, *args): return args[0] if args else 0

    def save(self, path='screen.png', force=None):
        if force is None:
            force = self._force_save_output
        if self.screen_is_dirty:
            if self._pg_enabled and pygame is not None and not force:
                return False
            if self._pg_enabled and pygame is not None:
                pygame.image.save(self._pg_screen, path)
            else:
                self.img.save(path)
            self._last_saved_path = os.path.abspath(path)
            return True
        return False

    def close(self):
        if self._pg_enabled and pygame is not None:
            try:
                pygame.display.quit()
                pygame.quit()
            finally:
                self._pg_enabled = False
                self._pg_should_close = False
                self._pg_window = None
                self._pg_screen = None
                self._pg_font = None
                self._pg_fonts.clear()

class _FinanceMock:
    """Stub for the HP Prime Finance object — all methods return 0.0."""

    def __getattr__(self, name):
        return lambda *a: 0.0
