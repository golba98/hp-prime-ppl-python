# ─────────────────────────────────────────────────────────────────
#  Constants and Configuration
# ─────────────────────────────────────────────────────────────────

_OPS = [
    (r'\bAND\b',  'and'),
    (r'\bOR\b',   'or'),
    (r'\bNOT\b',  'not '),
    (r'\bMOD\b',  '%'),
    (r'\bDIV\b',  '//'),
    (r'\bXOR\b',  '^'),
    (r'≠',        '!='),
    (r'≤',        '<='),
    (r'≥',        '>='),
    (r'<>',       '!='),
    (r'(?<![<>!:=])=(?![=>])', '=='),  # PPL = is equality (not assignment)
]

_PYTHON_RESERVED = frozenset({'set', 'list', 'map', 'filter', 'input', 'type', 'dir', 'id', 'hex', 'oct', 'bin', 'str'})

BUILTINS = frozenset([
    'PRINT','MSGBOX','INPUT','CHOOSE','WAIT','GETKEY','ISKEYDOWN','MOUSE','SIZE',
    'RECT','RECT_P','LINE','LINE_P','PIXON','PIXON_P','CIRCLE_P',
    'FILLCIRCLE_P','ARC_P','TEXTOUT_P','BLIT_P','DRAWMENU','DISP_FREEZE','FREEZE',
    'RGB','IP','FP','ABS','MAX','MIN','FLOOR','CEILING','ROUND','SQ',
    'SQRT','LOG','LN','EXP','SIN','COS','TAN','IFTE','RANDOM','RANDINT',
    'MAKELIST','SUBGROB','GROB','INVERT_P','INSTRING', 'LEFT', 'RIGHT', 'MID', 'CONCAT', 'POS', 'UPPER', 'LOWER', 'DIM', 'STRING', 'NUM', 'EXPR',
    'BITAND', 'BITOR', 'BITXOR', 'BITNOT',
])

_STRUCTURAL = frozenset(['IF','THEN','ELSE','END','FOR','FROM','TO','STEP','DO','WHILE','REPEAT','UNTIL','RETURN','BREAK','CONTINUE','LOCAL','BEGIN','EXPORT','PROCEDURE','IFERR'])

_PPL_KEYWORDS = BUILTINS | _STRUCTURAL
