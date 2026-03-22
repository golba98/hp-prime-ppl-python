# ─────────────────────────────────────────────────────────────────
#  HP Prime PPL Emulator — Runtime
#  Provides a 320×240 Pillow canvas + all PPL built-in functions.
#  PRINT → stdout   |   Graphics → PNG
# ─────────────────────────────────────────────────────────────────

from PIL import Image, ImageDraw, ImageFont
import sys, math, random

SCREEN_W = 320
SCREEN_H = 240

# Common HP Prime named colors (0xRRGGBB)
HP_BLACK   = 0x000000
HP_WHITE   = 0xFFFFFF
HP_RED     = 0xFF0000
HP_GREEN   = 0x00FF00
HP_BLUE    = 0x0000FF
HP_GRAY    = 0x808080
HP_YELLOW  = 0xFFFF00
HP_CYAN    = 0x00FFFF
HP_MAGENTA = 0xFF00FF


# ── PPLList ──────────────────────────────────────────────────────
# HP PPL arrays are 1-indexed.  PPLList wraps a Python list so that
# both  arr(i)  (read, via __call__) and  arr[i] = v  (write, via
# __setitem__) use 1-based indices, matching PPL semantics.

class PPLList(list):
    """1-indexed list for PPL array emulation."""

    def __call__(self, i):
        """Read element at 1-based index i."""
        res = list.__getitem__(self, int(i) - 1)
        if isinstance(res, list) and not isinstance(res, PPLList):
            return PPLList(res)
        return res

    def __getitem__(self, i):
        if isinstance(i, int):
            res = list.__getitem__(self, i - 1)
            if isinstance(res, list) and not isinstance(res, PPLList):
                return PPLList(res)
            return res
        # Slices return plain lists by default in Python; convert to PPLList
        res = list.__getitem__(self, i)
        return PPLList(res) if isinstance(res, list) else res

    def __setitem__(self, i, v):
        if isinstance(i, int):
            list.__setitem__(self, i - 1, v)
        else:
            list.__setitem__(self, i, v)       # slice pass-through

    # ── Operators must return PPLList to remain callable ──────────

    def __add__(self, other):
        return PPLList(list.__add__(self, other))

    def __radd__(self, other):
        return PPLList(list.__add__(other, self))

    def __mul__(self, other):
        return PPLList(list.__mul__(self, other))

    def __rmul__(self, other):
        return PPLList(list.__mul__(self, other))


class HPPrimeRuntime:

    def __init__(self):
        self.img  = Image.new('RGB', (SCREEN_W, SCREEN_H), (255, 255, 255))
        self.draw = ImageDraw.Draw(self.img)
        self._output = []
        # _wait_calls / _getkey_calls: in headless mode, return ESC (4) 
        # after a frame so loops terminate and we get a screen save.
        self._wait_calls = 0
        self._getkey_calls = 0
        try:
            self.font = ImageFont.load_default()
        except Exception:
            self.font = None

    # ── Color conversion ────────────────────────────────────────

    def _rgb(self, c):
        """HP Prime int color (0xRRGGBB) → PIL (R,G,B) tuple."""
        if c is None:
            return None
        if isinstance(c, tuple):
            return c
        c = int(c)
        return ((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)

    def _xy(self, x, y):
        return int(x), int(y)

    # ── Text output ─────────────────────────────────────────────

    def PRINT(self, *args):
        text = ' '.join(str(a) for a in args)
        print(text)
        self._output.append(text)

    def MSGBOX(self, msg):
        text = f"[MSGBOX] {msg}"
        print(text)
        self._output.append(text)

    # ── Screen clear ────────────────────────────────────────────

    def RECT(self, x1=0, y1=0, x2=SCREEN_W-1, y2=SCREEN_H-1,
             border=HP_BLACK, fill=HP_WHITE):
        self.RECT_P(x1, y1, x2, y2, border, fill)

    # ── Drawing primitives ───────────────────────────────────────

    def _get_args(self, args, min_args):
        """Handle optional G argument in graphics calls."""
        if len(args) > min_args and isinstance(args[0], (int, float)) and args[0] <= 9:
            return args[1:]
        return args

    def RECT_P(self, *args):
        args = self._get_args(args, 4)
        x1, y1, x2, y2 = args[:4]
        x1, x2 = sorted([x1, x2])
        y1, y2 = sorted([y1, y2])
        border = args[4] if len(args) > 4 else HP_BLACK
        fill = args[5] if len(args) > 5 else None
        if fill is None:
            fill = border
        self.draw.rectangle(
            [int(x1), int(y1), int(x2), int(y2)],
            fill=self._rgb(fill), outline=self._rgb(border)
        )

    def LINE_P(self, *args):
        args = self._get_args(args, 4)
        x1, y1, x2, y2 = args[:4]
        color = args[4] if len(args) > 4 else HP_BLACK
        self.draw.line([int(x1), int(y1), int(x2), int(y2)],
                       fill=self._rgb(color), width=1)

    def LINE(self, x1, y1, x2, y2, color=HP_BLACK):
        self.LINE_P(x1, y1, x2, y2, color)

    def PIXON_P(self, *args):
        args = self._get_args(args, 2)
        x, y = args[:2]
        color = args[2] if len(args) > 2 else HP_BLACK
        x, y = int(x), int(y)
        if 0 <= x < SCREEN_W and 0 <= y < SCREEN_H:
            self.img.putpixel((x, y), self._rgb(color))

    def PIXON(self, x, y, color=HP_BLACK):
        self.PIXON_P(x, y, color)

    def BLIT_P(self, *args):
        """BLIT_P([G_Target,] [G_Source,] ...) — no-op in emulator."""
        pass

    def CIRCLE_P(self, x, y, r, border=HP_BLACK, fill=None):
        x, y, r = int(x), int(y), int(r)
        bbox = [x - r, y - r, x + r, y + r]
        self.draw.ellipse(bbox,
                          fill=self._rgb(fill) if fill is not None else None,
                          outline=self._rgb(border))

    def FILLCIRCLE_P(self, x, y, r, color=HP_BLACK):
        self.CIRCLE_P(x, y, r, border=color, fill=color)

    def ARC_P(self, x, y, r, a1=0, a2=6.2832,
              color=HP_BLACK, fill=None, width=1):
        """
        Draw an arc/circle on the pixel screen.
        a1, a2  — start/end angles in RADIANS (HP PPL convention).
        color   — border/line color (0xRRGGBB int).
        fill    — interior fill color; if provided draws a filled ellipse.
        """
        x, y, r = int(x), int(y), int(r)
        bbox = [x - r, y - r, x + r, y + r]
        c = self._rgb(color)
        f = self._rgb(fill) if fill is not None else None

        is_full = abs(float(a2) - float(a1) - 2 * math.pi) < 0.05

        if is_full or (float(a1) == 0 and float(a2) == 0):
            # Full circle: use ellipse for clean rendering
            self.draw.ellipse(bbox, fill=f, outline=c)
        else:
            if f is not None:
                self.draw.ellipse(bbox, fill=f, outline=None)
            # Convert radians (CCW from East) → degrees (CW from East) for Pillow
            start_d = (-math.degrees(float(a2))) % 360
            end_d   = (-math.degrees(float(a1))) % 360
            self.draw.arc(bbox, start=start_d, end=end_d, fill=c)

    def TEXTOUT_P(self, *args):
        """
        HP PPL signature: TEXTOUT_P(text, [G,] x, y, [font_size, color, clip_width])
        """
        text = args[0]
        rest = self._get_args(args[1:], 2)
        x, y = rest[:2]
        font = rest[2] if len(rest) > 2 else 1
        color = rest[3] if len(rest) > 3 else HP_BLACK
        self.draw.text((int(x), int(y)), str(text),
                       fill=self._rgb(color), font=self.font)

    def DRAWMENU(self, *labels):
        """Render soft-key bar at bottom of screen."""
        bar_y = SCREEN_H - 18
        self.draw.rectangle([0, bar_y, SCREEN_W, SCREEN_H],
                             fill=(200, 200, 200), outline=(0, 0, 0))
        slot_w = SCREEN_W // 6
        for i, lbl in enumerate(labels[:6]):
            self.draw.text((i * slot_w + 4, bar_y + 3),
                           str(lbl), fill=(0, 0, 0), font=self.font)

    def DISP_FREEZE(self):
        """Standard PPL command for freezing the display."""
        pass

    def FREEZE(self):
        """Alternative name for DISP_FREEZE."""
        pass
  # no-op

    # ── Input stubs (headless mode) ─────────────────────────────

    def INPUT(self, *args):
        """Headless: always cancel (returns 0/False)."""
        print("[INPUT] headless — cancelled", file=sys.stderr)
        return 0

    def CHOOSE(self, *args):
        """
        Headless: always select first option (Yes/OK).
        Returns 1 so that  var = CHOOSE(...)  sets var to 1.
        """
        label = args[0] if args else '?'
        print(f"[CHOOSE] headless — '{label}' → 1 (first option)", file=sys.stderr)
        return 1

    def WAIT(self, t=-1):
        """
        Headless: on the FIRST call return ESC (key 4) so the main loop
        draws the initial screen and then exits cleanly.
        """
        self._wait_calls += 1
        if self._wait_calls >= 1:
            return 4   # ESC → triggers quit branch → BREAK
        return -1

    def GETKEY(self):
        self._getkey_calls += 1
        if self._getkey_calls >= 1:
            return 4   # ESC
        return -1

    def SIZE(self, obj):
        try:
            return len(obj)
        except Exception:
            return 0

    def MOUSE(self):
        """Returns empty list in headless mode."""
        return PPLList()

    # ── Math helpers ─────────────────────────────────────────────

    def RGB(self, r, g, b):
        return (int(r) << 16) | (int(g) << 8) | int(b)

    def IP(self, x):   return int(x)
    def FP(self, x):   return x - int(x)
    def ABS(self, x):  return abs(x)
    def MAX(self, a, b): return max(a, b)
    def MIN(self, a, b): return min(a, b)
    def FLOOR(self, x):  return math.floor(x)
    def CEILING(self, x): return math.ceil(x)
    def ROUND(self, x, n=0): return round(x, n)
    def MAKELIST(self, expr, var=None, start=1, end=1, step=1):
        """MAKELIST(expr, var, start, end [, step]) — build a PPLList.
        expr can be a value (constant) or a callable (lambda)."""
        result = PPLList()
        i = int(start)
        end_i = int(end)
        step_i = int(step) if step != 0 else 1
        while (step_i > 0 and i <= end_i) or (step_i < 0 and i >= end_i):
            if callable(expr):
                result.append(expr(i))
            else:
                result.append(expr)
            i += step_i
        return result

    def SQ(self, x):   return x * x
    def SQRT(self, x): return math.sqrt(x)
    def LOG(self, x):  return math.log10(x)
    def LN(self, x):   return math.log(x)
    def EXP(self, x):  return math.exp(x)
    def SIN(self, x):  return math.sin(math.radians(x))
    def COS(self, x):  return math.cos(math.radians(x))
    def TAN(self, x):  return math.tan(math.radians(x))
    def IFTE(self, cond, a, b): return a if cond else b
    def RANDOM(self, *args):
        if len(args) == 0:
            return random.random()
        elif len(args) == 1:
            return random.random() * args[0]
        else:
            return random.uniform(args[0], args[1])
    def RANDINT(self, a, b):
        return random.randint(int(a), int(b))

    # ── Screen save ──────────────────────────────────────────────

    def save(self, path='screen.png'):
        self.img.save(path)
        print(f"[EMU] screen → {path}", file=sys.stderr)
