import sys
import math
import random
import time
from PIL import Image, ImageDraw  # type: ignore
from .types import PPLList, CASMock

class HPPrimeRuntime:
    def __init__(self):
        self.width  = 320
        self.height = 240
        self.img    = Image.new('RGB', (self.width, self.height), (255, 255, 255))
        self.draw   = ImageDraw.Draw(self.img)
        self._getkey_calls = 0
        self._input_cancelled = 0
        self.CAS    = CASMock()

    # ── I/O ──────────────────────────────────────────────────────

    def PRINT(self, *args):
        print(*(str(a) for a in args))

    def MSGBOX(self, msg):
        print(f"[MSGBOX] {msg}")

    def INPUT(self, vars_spec, title="", labels=None, help_text=None):
        self._input_cancelled += 1
        print(f"[INPUT] headless — cancelled")
        return 0

    def CHOOSE(self, title, options):
        print(f"[CHOOSE] headless — '{title}' → 1 (first option)")
        return 1

    def WAIT(self, t=0):
        if t > 0: time.sleep(float(t))

    def GETKEY(self):
        self._getkey_calls += 1
        if self._getkey_calls >= 1:
            return 4   # ESC
        return -1

    def ISKEYDOWN(self, key_code):
        return True

    def SIZE(self, obj):
        try: return len(obj)
        except: return 0

    def DIM(self, obj): return self.SIZE(obj)

    def MOUSE(self, idx=0): return PPLList([-1, -1, 0, 0, 0])

    # ── Graphics ─────────────────────────────────────────────────

    def _color(self, c):
        if isinstance(c, tuple): return c
        c = int(c)
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)

    def RGB(self, r, g, b, a=255):
        return (int(r) << 16) | (int(g) << 8) | int(b)

    def RECT(self, x1=0, y1=0, x2=319, y2=239, edge_color=(0,0,0), fill_color=(255,255,255)):
        self.draw.rectangle([x1, y1, x2, y2], fill=self._color(fill_color), outline=self._color(edge_color))

    def RECT_P(self, x1=0, y1=0, x2=319, y2=239, edge_color=(0,0,0), fill_color=(255,255,255)):
        self.RECT(x1, y1, x2, y2, edge_color, fill_color)

    def LINE(self, x1, y1, x2, y2, color=(0,0,0)):
        self.draw.line([x1, y1, x2, y2], fill=self._color(color))

    def LINE_P(self, x1, y1, x2, y2, color=(0,0,0)):
        self.LINE(x1, y1, x2, y2, color)

    def PIXON(self, x, y, color=(0,0,0)):
        self.draw.point([x, y], fill=self._color(color))

    def PIXON_P(self, x, y, color=(0,0,0)):
        self.PIXON(x, y, color)

    def CIRCLE_P(self, x, y, r, color=(0,0,0)):
        self.draw.ellipse([x-r, y-r, x+r, y+r], outline=self._color(color))

    def FILLCIRCLE_P(self, x, y, r, color=(0,0,0)):
        self.draw.ellipse([x-r, y-r, x+r, y+r], fill=self._color(color))

    def DRAWMENU(self, *args): pass
    def DISP_FREEZE(self): pass
    def FREEZE(self): pass
    def SUBGROB(self, *args): return None
    def GROB(self, *args): return None
    def INVERT_P(self, *args): pass
    def ARC_P(self, *args): pass
    def TEXTOUT_P(self, *args): pass
    def BLIT_P(self, *args): pass

    # ── Math / String ───────────────────────────────────────────

    def IP(self, x): return int(x)
    def FP(self, x): return x - int(x)
    def ABS(self, x): return abs(x)
    def MAX(self, *args): return max(args)
    def MIN(self, *args): return min(args)
    def FLOOR(self, x): return math.floor(x)
    def CEILING(self, x): return math.ceil(x)
    def ROUND(self, x, n=0): return round(x, n)
    def SQ(self, x): return x * x
    def SQRT(self, x): return math.sqrt(x)
    def LOG(self, x): return math.log10(x)
    def LN(self, x): return math.log(x)
    def EXP(self, x): return math.exp(x)
    def SIN(self, x): return math.sin(math.radians(x))
    def COS(self, x): return math.cos(math.radians(x))
    def TAN(self, x): return math.tan(math.radians(x))
    def IFTE(self, cond, a, b): return a if cond else b
    def RANDOM(self, *args): return random.random()
    def RANDINT(self, a, b): return random.randint(int(a), int(b))

    def INSTRING(self, target, pattern, start=1):
        target, pattern = str(target), str(pattern)
        idx = target.find(pattern, int(start) - 1)
        return idx + 1 if idx != -1 else 0

    def LEFT(self, s, n): return str(s)[:int(n)]  # type: ignore
    def RIGHT(self, s, n): 
        s, n = str(s), int(n)
        return s[-n:] if n > 0 else ""  # type: ignore
    def MID(self, s, start, length=None):
        s, start = str(s), int(start) - 1
        if length is None: return s[start:]  # type: ignore
        return s[start : start + int(length)]  # type: ignore
    def CONCAT(self, a, b):
        if isinstance(a, list) and isinstance(b, list):
            return PPLList(list(a) + list(b))
        return str(a) + str(b)
    def POS(self, target, pattern): return self.INSTRING(target, pattern)
    def UPPER(self, s): return str(s).upper()
    def LOWER(self, s): return str(s).lower()
    def STRING(self, x, precision=None):
        if precision is None: return str(x)
        try:
            return format(float(x), f".{int(precision)}g")
        except: return str(x)
    def NUM(self, s):
        try: return float(s)
        except: return 0

    def BITAND(self, a, b): return int(a) & int(b)
    def BITOR(self, a, b): return int(a) | int(b)
    def BITXOR(self, a, b): return int(a) ^ int(b)
    def BITNOT(self, a): return ~int(a)

    # HP Prime: Binary<->Real conversions
    def B_to_R(self, x): return int(x)
    def R_to_B(self, x, bits=32, digits=4): return int(round(float(x)))

    def REPLACE(self, obj, start_or_old, length_or_new, replacement=None):
        if replacement is None:
            return str(obj).replace(str(start_or_old), str(length_or_new))
        else:
            start, length = int(start_or_old) - 1, int(length_or_new)
            if isinstance(obj, list):
                res = PPLList(obj)
                res[start : start + length] = list(replacement)  # type: ignore
                return res
            else:
                s = str(obj)
                return s[:start] + str(replacement) + s[start + length:]  # type: ignore

    def EXPR(self, s):
        try:
            return eval(str(s).replace('^', '**'), {"__builtins__": None}, {
                "math": math, "ABS": abs, "IP": int, "FP": lambda x: x - int(x),
                "MIN": min, "MAX": max
            })
        except: return 0

    def MAKELIST(self, expr, var=None, start=1, end=1, step=1):
        return PPLList([0] * (int(end) - int(start) + 1))

    # ── Screen save ──────────────────────────────────────────────

    def save(self, path='screen.png'):
        self.img.save(path)
        print(f"[EMU] screen → {path}", file=sys.stderr)
