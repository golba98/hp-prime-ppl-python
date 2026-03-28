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

_PYTHON_RESERVED = frozenset({
    # Built-in names that clash with common PPL variable/function names
    'set', 'list', 'map', 'filter', 'input', 'type',
    'dir', 'id', 'hex', 'oct', 'bin', 'str',
    # Python keywords that are not valid identifiers
    'yield', 'lambda', 'global', 'class', 'del', 'raise',
    'with', 'assert', 'async', 'await',
})

_SYSTEM_GLOBALS = frozenset({'ANS', 'THETA', 'VAR', 'EXACT', 'WINDOW'})

BUILTINS = frozenset([
    # I/O
    'PRINT', 'MSGBOX', 'INPUT', 'CHOOSE', 'WAIT', 'GETKEY', 'ISKEYDOWN', 'MOUSE',
    'DISP', 'DISP_FREEZE', 'FREEZE', 'DRAWMENU',
    # Graphics
    'RECT', 'RECT_P', 'LINE', 'LINE_P',
    'PIXON', 'PIXON_P', 'CIRCLE_P', 'FILLCIRCLE_P', 'ARC_P',
    'TEXTOUT_P', 'BLIT_P', 'BLIT', 'INVERT_P',
    'RGB', 'FILLPOLY_P', 'FILLPOLY', 'TRIANGLE_P', 'TRIANGLE',
    'SUBGROB', 'GROB', 'DIMGROB_P', 'DIMGROB', 'GETPIX',
    # Math
    'ABS', 'MAX', 'MIN', 'FLOOR', 'CEILING', 'ROUND', 'SQ', 'SQRT',
    'LOG', 'LN', 'EXP', 'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN',
    'SINH', 'COSH', 'TANH', 'ASINH', 'ACOSH', 'ATANH',
    'IP', 'FP', 'IFTE', 'RANDOM', 'RANDINT',
    'INTEGER', 'REAL', 'SIGN', 'TRUNCATE', 'MANT', 'XPON',
    'MOD', 'DIV', 'DET',
    # Bit operations
    'BITAND', 'BITOR', 'BITXOR', 'BITNOT', 'BITSHIFT', 'B_to_R', 'R_to_B',
    # Strings
    'INSTRING', 'LEFT', 'RIGHT', 'MID', 'CONCAT', 'POS', 'REPLACE',
    'UPPER', 'LOWER', 'STRING', 'NUM', 'ASC', 'CHR', 'CHAR', 'TRIM',
    'STARTSWITH', 'ENDSWITH', 'CONTAINS',
    # Lists / collections
    'SIZE', 'DIM', 'MAKELIST', 'SORT', 'REVERSE', 'ADDTAIL', 'SIGMALIST', 'PILIST',
    # Type / eval
    'TYPE', 'EXPR', 'EVAL', 'APPROX', 'EXACT',
    # CAS
    'CAS', 'FACTOR', 'EXPAND', 'PARTFRAC', 'SIMPLIFY',
    'SOLVE', 'ZEROS', 'CZEROS', 'DIFF', 'INTEGRATE',
    'LIMIT', 'SERIES', 'TAYLOR', 'LAPLACE', 'INVLAPLACE',
    'FFT', 'IFFT', 'POLY', 'DEGREE', 'COEFF', 'ROOTS', 'FACTORS',
    'FSOLVE', 'NDERIV', 'NINT',
    # Statistics
    'MEAN', 'MEDIAN', 'STDDEV', 'VAR', 'CORR', 'COV', 'REG', 'PREDY', 'PREDX',
    'SUM', 'PRODUCT',
    # Control-flow keywords (also needed for _xform identifier pass-through)
    'FOR', 'FROM', 'TO', 'STEP', 'DO', 'WHILE', 'REPEAT', 'UNTIL',
    'IF', 'THEN', 'ELSE', 'END', 'CASE', 'DEFAULT', 'BREAK', 'CONTINUE',
    'LOCAL', 'EXPORT', 'PROCEDURE', 'BEGIN', 'RETURN', 'IFERR',
])

BUILTINS_ZERO_ARGS = frozenset(['GETKEY', 'RECT', 'RECT_P', 'WAIT', 'MOUSE', 'FREEZE', 'DRAWMENU', 'DISP_FREEZE'])

_STRUCTURAL = frozenset([
    # Block structure
    'BEGIN', 'END', 'IF', 'THEN', 'ELSE', 'IFERR',
    'FOR', 'FROM', 'TO', 'STEP', 'DOWNTO', 'DO',
    'WHILE', 'REPEAT', 'UNTIL',
    'CASE', 'DEFAULT',
    # Flow control
    'RETURN', 'BREAK', 'CONTINUE',
    # Scope
    'LOCAL', 'EXPORT', 'PROCEDURE',
    # Logical operators (lowercased by _OPS before reaching identifier matching)
    'AND', 'OR', 'NOT',
])

# Combined set used to decide whether a token is a keyword or a user identifier
_PPL_KEYWORDS = BUILTINS | _STRUCTURAL | _SYSTEM_GLOBALS
