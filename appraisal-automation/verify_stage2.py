import sys, ast
sys.stdout.reconfigure(encoding='utf-8')

with open('stage2_review.py', 'r', encoding='utf-8') as f:
    src = f.read()

# Syntax check
try:
    ast.parse(src)
    print('SYNTAX: OK')
except SyntaxError as e:
    print(f'SYNTAX ERROR: {e}')
    sys.exit(1)

# Import check
from stage2_review import Finding, ReviewResponse, SYSTEM_PROMPT
from config import REVIEW_MODEL

# Verify Pydantic field names
fields = list(Finding.model_fields.keys())
expected = ['paragraph_index', 'category', 'severity', 'comment', 'suggestion']
print(f'Pydantic fields : {fields}')
print(f'Fields match    : {fields == expected}')

# Check system prompt contains all correct field names (not aliases)
print('\nSystem prompt field name checks:')
correct   = ['paragraph_index', 'category', 'severity', 'comment', 'suggestion']
incorrect = ['id', 'type', 'level', 'description', 'note', 'fix', 'index', 'priority']
for name in correct:
    print(f'  [{"OK" if name in SYSTEM_PROMPT else "MISSING"}] has "{name}"')
for name in incorrect:
    print(f'  [{"BAD - present!" if name in SYSTEM_PROMPT else "OK - absent"}] no "{name}"')

# Verify model
print(f'\nREVIEW_MODEL    : {REVIEW_MODEL}')
print(f'Old model gone  : {"claude-3-5-sonnet-20241022" not in src}')
print(f'No response_format param: {"response_format" not in src}')
