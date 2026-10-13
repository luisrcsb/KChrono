import re
import os

for root, dirs, files in os.walk('.'):
    for f in files:
        if f.endswith('.py') and not f.startswith('tools/'):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                for m in re.finditer(r'Classifica[^\s"\)]*', content):
                    print(f'{path}: {m.group()}')
            except:
                pass