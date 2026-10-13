with open('i18n/en_US/LC_MESSAGES/kchrono.po', 'r', encoding='utf-8') as f:
    content = f.read()
import re
for m in re.finditer(r'msgid "([^"]*)"', content):
    if 'Classifica' in m.group(1) or 'Corrida' in m.group(1) or 'Treino' in m.group(1):
        print(f'msgid: {m.group(1)}')