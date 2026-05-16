import ast, os, sys

files = [
    'server/bot.py',
    'server/app.py',
    'server/tools/__init__.py',
    'server/integrations/calcom_client.py',
    'server/integrations/twilio_client.py',
    'server/prompts/system_prompt.md',
    'server/pyproject.toml',
    'server/Dockerfile',
]

all_ok = True
for f in files:
    if not os.path.exists(f):
        print(f'MISSING: {f}')
        all_ok = False
        continue
    with open(f) as fh:
        c = fh.read()
    if f.endswith('.py'):
        try:
            ast.parse(c)
            print(f'OK: {f} ({len(c.splitlines())} lines)')
        except SyntaxError as e:
            print(f'SYNTAX ERROR: {f} - {e}')
            all_ok = False
    else:
        print(f'OK: {f} ({len(c.splitlines())} lines)')

if all_ok:
    print('\nAll files pass validation!')
else:
    print('\nSome files failed!')
    sys.exit(1)
