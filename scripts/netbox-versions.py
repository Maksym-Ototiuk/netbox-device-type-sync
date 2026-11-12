"""
Manage the list of supported NetBox versions.

supported-netbox-versions.json is the single source of truth: the test
matrix is built from it, and the Compatibility table of README.md must list
the same versions.

Usage:
    python scripts/netbox-versions.py matrix          # JSON list for the test matrix
    python scripts/netbox-versions.py check           # README table matches the JSON file
    python scripts/netbox-versions.py classify v4.7.5 # supported | patch | minor | older
    python scripts/netbox-versions.py add v4.7.5      # add a version, bump PATCH, update docs
"""

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS_FILE = ROOT / 'supported-netbox-versions.json'
README = ROOT / 'README.md'
CHANGELOG = ROOT / 'CHANGELOG.md'
VERSION_FILES = (
    (ROOT / 'pyproject.toml', r'^(version\s*=\s*")(\d+\.\d+\.\d+)(")'),
    (ROOT / 'netbox_device_type_sync/version.py', r"^(__version__\s*=\s*')(\d+\.\d+\.\d+)(')"),
    (
        ROOT / 'netbox_device_type_sync/tests/test_load.py',
        r"(__version__\s*==\s*')(\d+\.\d+\.\d+)(')",
    ),
)
TABLE_ROW = re.compile(r'^\| (\d+\.\d+\.\d+) +\| (\d+\.\d+\.\d+) +\|$', re.MULTILINE)
TAG = re.compile(r'^v(\d+)\.(\d+)\.(\d+)$')


def parse(tag):
    match = TAG.match(tag)
    if not match:
        sys.exit(f'Not a NetBox release tag: {tag!r}')
    return tuple(int(part) for part in match.groups())


def load_versions():
    versions = json.loads(VERSIONS_FILE.read_text())['versions']
    return sorted(set(versions), key=parse)


def save_versions(versions):
    data = {'versions': sorted(set(versions), key=parse)}
    VERSIONS_FILE.write_text(json.dumps(data, indent=2) + '\n')


def readme_versions():
    return [f'v{netbox}' for netbox, _plugin in TABLE_ROW.findall(README.read_text())]


def cmd_matrix():
    print(json.dumps(load_versions()))


def cmd_check():
    versions, documented = load_versions(), readme_versions()
    if versions != sorted(documented, key=parse):
        sys.exit(
            f'{VERSIONS_FILE.name} lists {versions}, but the README Compatibility '
            f'table lists {documented}'
        )
    print(f'Supported NetBox versions: {", ".join(versions)}')


def cmd_classify(tag):
    """
    supported: already in the list
    patch:     a newer patch release of the newest supported minor version
    minor:     a newer minor or major version
    older:     older than the newest supported version (ignored)
    """
    versions = load_versions()
    if tag in versions:
        print('supported')
        return
    newest = parse(versions[-1])
    candidate = parse(tag)
    if candidate < newest:
        print('older')
    elif candidate[:2] == newest[:2]:
        print('patch')
    else:
        print('minor')


def bump_patch():
    new_version = None
    for path, pattern in VERSION_FILES:
        text = path.read_text()
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            sys.exit(f'No version found in {path}')
        major, minor, patch = (int(p) for p in match.group(2).split('.'))
        version = f'{major}.{minor}.{patch + 1}'
        if new_version not in (None, version):
            sys.exit('The version files disagree; run scripts/version-check.py')
        new_version = version
        path.write_text(
            re.sub(pattern, rf'\g<1>{version}\g<3>', text, count=1, flags=re.MULTILINE)
        )
    return new_version


def add_readme_row(tag, plugin_version):
    text = README.read_text()
    rows = list(TABLE_ROW.finditer(text))
    if not rows:
        sys.exit('The README Compatibility table was not found')
    row = f'| {tag[1:]:<6} | {plugin_version:<23} |'
    end = rows[-1].end()
    README.write_text(text[:end] + '\n' + row + text[end:])


def add_changelog_entry(tag, plugin_version):
    text = CHANGELOG.read_text()
    match = re.search(r'^## ', text, re.MULTILINE)
    if not match:
        sys.exit('No release section found in CHANGELOG.md')
    today = datetime.date.today().isoformat()
    entry = (
        f'## {plugin_version} ({today})\n\n'
        f'### Changed\n\n'
        f'- Tested with NetBox {tag[1:]}; no code changes.\n\n'
    )
    CHANGELOG.write_text(text[: match.start()] + entry + text[match.start() :])


def cmd_add(tag):
    parse(tag)
    versions = load_versions()
    if tag in versions:
        sys.exit(f'{tag} is already supported')
    save_versions(versions + [tag])
    plugin_version = bump_patch()
    add_readme_row(tag, plugin_version)
    add_changelog_entry(tag, plugin_version)
    cmd_check()
    print(plugin_version)


def main():
    commands = {'matrix': cmd_matrix, 'check': cmd_check, 'classify': cmd_classify, 'add': cmd_add}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]](*sys.argv[2:])


if __name__ == '__main__':
    main()
