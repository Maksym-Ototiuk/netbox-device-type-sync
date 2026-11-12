"""
Print the release notes of a version: its section of CHANGELOG.md.

Usage: python scripts/release-notes.py v1.0.0
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / 'CHANGELOG.md'
README_URL = 'https://github.com/Maksym-Ototiuk/netbox-device-type-sync#installation'

version = sys.argv[1].lstrip('v')
text = CHANGELOG.read_text()
match = re.search(
    rf'^## {re.escape(version)}\b[^\n]*\n(.*?)(?=^## |\Z)', text, re.MULTILINE | re.DOTALL
)
if not match:
    sys.exit(f'No section for {version} in CHANGELOG.md')

# Join the wrapped lines of each paragraph and list item into one line
lines = []
for line in match.group(1).strip().splitlines():
    if lines and line.startswith('  ') and lines[-1]:
        lines[-1] += ' ' + line.strip()
    elif lines and line and not line.startswith(('#', '-', '|')) and lines[-1] and not lines[-1].startswith('#'):
        lines[-1] += ' ' + line.strip()
    else:
        lines.append(line)

print('\n'.join(lines))
print()
print(f'Install: `pip install netbox-device-type-sync=={version}` — see the [README]({README_URL}).')
