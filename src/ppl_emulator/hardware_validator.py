import re
from dataclasses import dataclass

HARDWARE_FUNCTIONS = {
    "PRINT":       (0, 3),   "MSGBOX":      (1, 1),   "INPUT":       (1, 6),
    "CHOOSE":      (3, None),"DISP":        (2, 2),   "WAIT":        (0, 1),
    "GETKEY":      (0, 0),   "ISKEYDOWN":   (1, 1),   "DRAWMENU":    (0, 6),
    "DISP_FREEZE": (0, 0),   "FREEZE":      (0, 0),   "MOUSE":       (0, 0),
    "RECT":        (0, 6),   "LINE":        (4, 5),   "CIRCLE":      (3, 4),
    "RECT_P":      (4, 7),   "LINE_P":      (4, 6),   "PIXON_P":     (2, 4),
    "PIXOFF_P":    (2, 3),   "CIRCLE_P":    (3, 5),   "ARC_P":       (5, 7),
    "TEXTOUT_P":   (4, 7),   "BLIT_P":      (1, 9),   "FILLPOLY_P":  (1, 3),
    "TRIANGLE_P":  (2, 4),   "DIMGROB_P":   (3, 4),   "FILLCIRCLE_P":(3, 5),
    "INVERT_P":    (0, 5),   "GETPIX_P":    (2, 3),   "SUBGROB_P":   (3, 5),
    "DIMGROB":     (3, 4),   "SUBGROB":     (3, 5),   "BLIT":        (1, 9),
    "FILLPOLY":    (1, 3),   "TRIANGLE":    (2, 4),   "GETPIX":      (2, 3),
    "GROB":        (3, 4),   "INVERT":      (0, 5),   "RGB":         (3, 4),
    "ABS":         (1, 1),   "SQ":          (1, 1),   "SQRT":        (1, 1),
    "LOG":         (1, 2),   "LN":          (1, 1),   "EXP":         (1, 1),
    "IP":          (1, 1),   "FP":          (1, 1),   "FLOOR":       (1, 1),
    "CEILING":     (1, 1),   "ROUND":       (1, 2),   "SIGN":        (1, 1),
    "TRUNCATE":    (1, 2),   "MANT":        (1, 1),   "XPON":        (1, 1),
    "MAX":         (1, None),"MIN":         (1, None),"IFTE":        (3, 3),
    "RANDOM":      (0, 0),   "RANDINT":     (1, 2),   "MAKELIST":    (4, 5),
    "SIZE":        (1, 1),
    "SIN":  (1, 1), "COS":  (1, 1), "TAN":  (1, 1), "ASIN": (1, 1),
    "ACOS": (1, 1), "ATAN": (1, 2), "SINH": (1, 1), "COSH": (1, 1),
    "TANH": (1, 1), "ASINH":(1, 1), "ACOSH":(1, 1), "ATANH":(1, 1),
    "LEFT":        (2, 2),   "RIGHT":       (2, 2),   "MID":         (2, 3),
    "CONCAT":      (2, None),"POS":         (2, 2),   "INSTRING":    (2, 2),
    "UPPER":       (1, 1),   "LOWER":       (1, 1),   "TRIM":        (1, 1),
    "STRING":      (1, 2),   "NUM":         (1, 1),   "EXPR":        (1, 1),
    "ASC":         (1, 1),   "CHR":         (1, 1),   "DIM":         (1, 1),
    "REPLACE":     (3, 4),   "STARTSWITH":  (2, 2),   "ENDSWITH":    (2, 2),
    "CONTAINS":    (2, 2),
    "BITAND":      (2, 2),   "BITOR":       (2, 2),   "BITXOR":      (2, 2),
    "BITNOT":      (1, 1),   "BITSHIFT":    (2, 2),
    "INTEGER":     (1, 1),   "REAL":        (1, 1),   "TYPE":        (1, 1),
    "EVAL":        (1, 1),   "B_to_R":      (1, 1),   "R_to_B":      (1, 1),
    "DET":         (1, 1),   "SORT":        (1, 1),   "REVERSE":     (1, 1),
    "ADDTAIL":     (2, 2),   "SIGMALIST":   (1, 1),   "PILIST":      (1, 1),
    "CAS":         (1, 1),   "FACTOR":      (1, 2),   "EXPAND":      (1, 2),
    "PARTFRAC":    (1, 2),   "SOLVE":       (1, 3),   "ZEROS":       (1, 2),
    "CZEROS":      (1, 2),   "DIFF":        (1, 3),   "INTEGRATE":   (1, 4),
    "SIMPLIFY":    (1, 2),   "APPROX":      (1, 1),   "EXACT":       (1, 1),
    "TAYLOR":      (1, 4),   "LIMIT":       (1, 3),   "SERIES":      (1, 4),
    "SUM":         (1, 4),   "PRODUCT":     (1, 4),   "LAPLACE":     (1, 2),
    "INVLAPLACE":  (1, 2),   "FFT":         (1, 2),   "IFFT":        (1, 2),
    "NDERIV":      (1, 3),   "NINT":        (1, 4),   "FSOLVE":      (1, 4),
    "MEAN":        (1, 2),   "MEDIAN":      (1, 1),   "STDDEV":      (1, 2),
    "VAR":         (1, 2),   "CORR":        (2, 2),   "COV":         (2, 2),
    "POLY":        (1, None),"DEGREE":      (1, 1),   "COEFF":       (1, 2),
    "ROOTS":       (1, 1),   "FACTORS":     (1, 1),   "REG":         (1, 3),
    "PREDY":       (1, 2),   "PREDX":       (1, 2),
}
_HAS_PIXEL_VARIANT = {
    "RECT": "RECT_P",       "LINE": "LINE_P",         "CIRCLE": "CIRCLE_P",
    "FILLCIRCLE": "FILLCIRCLE_P", "FILLPOLY": "FILLPOLY_P",
    "TRIANGLE": "TRIANGLE_P", "SUBGROB": "SUBGROB_P",
    "INVERT": "INVERT_P",   "GETPIX": "GETPIX_P",     "DIMGROB": "DIMGROB_P",
    "PIXON": "PIXON_P",     "PIXOFF": "PIXOFF_P",      "BLIT": "BLIT_P",
    "TEXTOUT": "TEXTOUT_P", "ARC": "ARC_P",
}

_SUGGESTIONS = {
    "FILLRECT": "RECT_P",     "DRAWRECT": "RECT_P",
    "DRAWLINE": "LINE_P",     "DRAWCIRCLE": "CIRCLE_P",
    "CLEARDISPLAY": "RECT_P", "CLEARSCREEN": "RECT_P", "CLRSCR": "RECT_P",
    "SETPIXEL": "PIXON_P",    "PUTPIXEL": "PIXON_P",   "DRAWPIXEL": "PIXON_P",
    "GETPIXEL": "GETPIX_P",   "FILLSCREEN": "RECT_P",
    "DRAWTEXT": "TEXTOUT_P",  "TEXTWRITE": "TEXTOUT_P",
    "PRINTF": "PRINT",        "PRINTLN": "PRINT",
    "WRITELN": "PRINT",       "WRITE": "PRINT",
    "DRAWIMAGE": "BLIT_P",    "BLITIMAGE": "BLIT_P",
}

_STRUCTURAL_KEYWORDS = frozenset([
    "IF", "THEN", "ELSE", "END", "BEGIN", "FOR", "FROM", "TO", "STEP", "DO",
    "WHILE", "REPEAT", "UNTIL", "RETURN", "BREAK", "CONTINUE", "LOCAL",
    "EXPORT", "PROCEDURE", "IFERR", "CASE", "DEFAULT", "AND", "OR", "NOT",
    "MOD", "DIV", "XOR",
])


@dataclass
class HardwareIssue:
    severity: str
    message:  str
    line_no:  int


def _strip_strings(text):
    result = list(text)
    in_str = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == chr(34):
            if not in_str:
                in_str = True
            else:
                if i + 1 < len(text) and text[i + 1] == chr(34):
                    result[i] = result[i + 1] = " "
                    i += 2
                    continue
                else:
                    in_str = False
        elif in_str:
            result[i] = " "
        i += 1
    return "".join(result)


def _strip_comment(line):
    in_str = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == chr(34):
            in_str = not in_str
        elif not in_str and ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i]
        i += 1
    return line


def _count_args(args_str):
    s = args_str.strip()
    if not s:
        return 0
    depth = 0
    in_str = False
    count = 1
    for ch in s:
        if ch == chr(34):
            in_str = not in_str
        elif not in_str:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                count += 1
    return count


def _collect_user_functions(code):
    names = set()
    for line in code.splitlines():
        stripped = _strip_comment(line).strip()
        m = re.match(r"^(?:EXPORT|PROCEDURE)\s+(\w+)\s*\(", stripped, re.IGNORECASE)
        if m:
            names.add(m.group(1).upper())
    return names


def hardware_validate(code):
    """Run all hardware compatibility checks. Returns list of HardwareIssue."""
    issues = []
    user_fns = _collect_user_functions(code)

    for line_no, raw_line in enumerate(code.splitlines(), 1):
        no_comment = _strip_comment(raw_line)
        clean = _strip_strings(no_comment)

        # Check 1: invalid color literals starting with #
        for m in re.finditer(r"(?<![0-9A-Za-z_])#([0-9A-Fa-f]{3,8})\b", clean):
            hex_val = m.group(1)
            issues.append(HardwareIssue(
                severity="ERROR",
                message=(
                    "Invalid color literal " + chr(39) + "#" + hex_val + chr(39) + ". "
                    "Use " + chr(39) + "0x" + chr(39) + " prefix for hex colors on HP Prime "
                    "hardware (e.g. 0x" + hex_val.upper() + ")"
                ),
                line_no=line_no,
            ))

        # Check 2 & 3: function call validation
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", clean):
            fn_name = m.group(1).upper()
            if fn_name in _STRUCTURAL_KEYWORDS:
                continue
            if fn_name in user_fns:
                continue

            # 2a: unknown function
            if fn_name not in HARDWARE_FUNCTIONS:
                if fn_name in _SUGGESTIONS:
                    issues.append(HardwareIssue(
                        severity="ERROR",
                        message="Unknown function " + chr(39) + m.group(1) + chr(39) + ". Did you mean " + chr(39) + _SUGGESTIONS[fn_name] + chr(39) + "?",
                        line_no=line_no,
                    ))
                else:
                    issues.append(HardwareIssue(
                        severity="ERROR",
                        message="Unknown function " + chr(39) + m.group(1) + chr(39) + " is not a valid HP Prime G1/G2 built-in",
                        line_no=line_no,
                    ))
                continue

            # 2b: non-_P graphic command warning
            if fn_name in _HAS_PIXEL_VARIANT:
                pixel_v = _HAS_PIXEL_VARIANT[fn_name]
                issues.append(HardwareIssue(
                    severity="WARNING",
                    message=chr(39) + m.group(1) + chr(39) + " uses screen coordinates. Consider " + chr(39) + pixel_v + chr(39) + " for pixel-exact rendering on hardware",
                    line_no=line_no,
                ))

            # 3: argument count validation
            call_start = m.end()
            depth = 1
            in_s = False
            i = call_start
            while i < len(clean) and depth > 0:
                ch = clean[i]
                if ch == chr(34):
                    in_s = not in_s
                elif not in_s:
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                i += 1
            if depth == 0:
                raw_args = no_comment[call_start: i - 1]
                nargs = _count_args(raw_args)
                min_a, max_a = HARDWARE_FUNCTIONS[fn_name]
                if nargs < min_a or (max_a is not None and nargs > max_a):
                    if max_a is None:
                        expected = "at least " + str(min_a)
                    elif min_a == max_a:
                        expected = str(min_a)
                    else:
                        expected = str(min_a) + "-" + str(max_a)
                    issues.append(HardwareIssue(
                        severity="ERROR",
                        message="Wrong number of arguments for " + chr(39) + m.group(1) + chr(39) + ": got " + str(nargs) + ", expected " + expected,
                        line_no=line_no,
                    ))

    return issues
