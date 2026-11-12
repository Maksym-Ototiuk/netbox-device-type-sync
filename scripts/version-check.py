"""
Check that a release tag matches the plugin version in every file that holds it.

Usage: python scripts/version-check.py v1.0.0
"""

import re
import sys

FILES = (
    ('netbox_device_type_sync/version.py', r"__version__\s*=\s*[\"'](\d+\.\d+\.\d+)[\"']"),
    ('netbox_device_type_sync/tests/test_load.py', r"__version__\s*==\s*[\"'](\d+\.\d+\.\d+)[\"']"),
    ('pyproject.toml', r"^version\s*=\s*[\"'](\d+\.\d+\.\d+)[\"']"),
)

tag = sys.argv[1]
tag_version = tag.lstrip('v')
print(f'{"Git tag":>45}: {tag}')

found = []
for path, pattern in FILES:
    with open(path) as f:
        match = re.search(pattern, f.read(), re.MULTILINE)
    if not match:
        sys.stderr.write(f'Could not find the version in {path}\n')
        sys.exit(1)
    found.append(match.group(1))
    print(f'{path:>45}: {match.group(1)}')

if any(version != tag_version for version in found):
    sys.stderr.write('\nUpdate the version string in all files before the release\n')
    sys.exit(1)

print('\nVersions OK')
