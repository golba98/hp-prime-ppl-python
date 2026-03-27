# ─────────────────────────────────────────────────────────────────
#  Constants and Configuration
# ─────────────────────────────────────────────────────────────────

_OPS = [
    (r'(?<![A-Za-z_])AND(?![A-Za-z_])',  ' and '),
    (r'(?<![A-Za-z_])OR(?![A-Za-z_])',   ' or '),
    (r'(?<![A-Za-z_])NOT(?![A-Za-z_])',  ' not '),
    (r'(?<![A-Za-z_])MOD(?![A-Za-z_(])',  '%'),
    (r'(?<![A-Za-z_])DIV(?![A-Za-z_(])',  '//'),
    (r'(?<![A-Za-z_])XOR(?![A-Za-z_])',  '^'),
    (r'≠',        '!='),
    (r'≤',        '<='),
    (r'≥',        '>='),
    (r'<>',       '!='),
    (r'(?<![<>!:=])=(?![=>])', '=='),  # PPL = is equality (not assignment)
]

_PYTHON_RESERVED = frozenset({'set', 'list', 'map', 'filter', 'input', 'type', 'dir', 'id', 'hex', 'oct', 'bin', 'str', 'yield', 'lambda', 'global', 'class', 'del', 'raise', 'with', 'assert', 'async', 'await'})

_SYSTEM_GLOBALS = frozenset({'ANS', 'THETA', 'VAR', 'EXACT', 'WINDOW'})

BUILTINS = frozenset([
    'PRINT','MSGBOX','INPUT','CHOOSE','WAIT','GETKEY','ISKEYDOWN','MOUSE','SIZE',
    'RECT','RECT_P','LINE','LINE_P','PIXON','PIXON_P','CIRCLE_P',
    'FILLCIRCLE_P','ARC_P','TEXTOUT_P','BLIT_P','DRAWMENU','DISP_FREEZE','FREEZE',
    'RGB','IP','FP','ABS','MAX','MIN','FLOOR','CEILING','ROUND','SQ',
    'SQRT','LOG','LN','EXP','SIN','COS','TAN','IFTE','RANDOM','RANDINT',
    'MAKELIST','SUBGROB','GROB','INVERT_P','INSTRING', 'LEFT', 'RIGHT', 'MID', 'CONCAT', 'POS', 'UPPER', 'LOWER', 'DIM', 'STRING', 'NUM', 'EXPR',
    'MOD', 'DIV',
    'BITAND', 'BITOR', 'BITXOR', 'BITNOT',
    'B_to_R', 'R_to_B', 'REPLACE', 'EVAL', 'DET', 'PIXON_P',
    'INTEGER', 'REAL', 'SIGN', 'TRUNCATE', 'MANT', 'XPON', 'BITSHIFT',
    'SORT', 'REVERSE', 'ADDTAIL', 'SIGMALIST', 'PILIST',
    'ASC', 'CHR', 'CHAR', 'TRIM', 'STARTSWITH', 'ENDSWITH', 'CONTAINS', 'DISP',
    'TYPE', 'FILLPOLY_P', 'TRIANGLE_P', 'DIMGROB_P', 'CAS',
    # CAS / Advanced
    'FACTOR', 'EXPAND', 'PARTFRAC', 'SOLVE', 'LIMIT', 'SERIES', 'SIMPLIFY',
    'APPROX', 'EXACT', 'SOLVE', 'ZEROS', 'CZEROS', 'DIFF', 'INTEGRATE',
    'LN', 'LOG', 'EXP', 'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN',
    'SINH', 'COSH', 'TANH', 'ASINH', 'ACOSH', 'ATANH',
    'SUM', 'PRODUCT', 'LIMIT', 'SERIES', 'TAYLOR', 'LAPLACE', 'INVLAPLACE',
    'FFT', 'IFFT', 'POLY', 'DEGREE', 'COEFF', 'ROOTS', 'FACTORS',
    'FSOLVE', 'NDERIV', 'NINT', 'MIN', 'MAX', 'MEAN', 'MEDIAN', 'STDDEV',
    'VAR', 'CORR', 'COV', 'REG', 'PREDY', 'PREDX',
    'DIMGROB', 'BLIT', 'FILLPOLY', 'TRIANGLE', 'SUBGROB', 'GETPIX',
    'FOR', 'FROM', 'TO', 'STEP', 'DO', 'WHILE', 'REPEAT', 'UNTIL',
    'IF', 'THEN', 'ELSE', 'END', 'CASE', 'DEFAULT', 'BREAK', 'CONTINUE',
    'LOCAL', 'EXPORT', 'PROCEDURE', 'BEGIN', 'RETURN', 'IFERR'
])

BUILTINS_ZERO_ARGS = frozenset(['GETKEY', 'RECT', 'RECT_P', 'WAIT', 'MOUSE', 'FREEZE', 'DRAWMENU', 'DISP_FREEZE'])

_STRUCTURAL = frozenset(['IF','THEN','ELSE','END','FOR','FROM','TO','STEP','DO','WHILE','REPEAT','UNTIL','RETURN','BREAK','CONTINUE','LOCAL','BEGIN','EXPORT','PROCEDURE','IFERR','AND','OR','NOT'])

_PPL_KEYWORDS = BUILTINS | _STRUCTURAL | _SYSTEM_GLOBALS
