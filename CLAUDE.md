# CLAUDE.md — netbox-device-type-sync

## Project context

- A NetBox plugin, published on GitHub (`Maksym-Ototiuk/netbox-device-type-sync`)
  and on PyPI (`netbox-device-type-sync`).
- It adds a **Sync** button to the *Device Type* card of the Device page. The
  button compares the component templates of the device type with the
  components of the device, lets the user choose which properties to copy
  from the device type, and creates the missing components.
- Supported NetBox versions are listed in `supported-netbox-versions.json`,
  the single source of truth: the test matrix is built from it, and the
  *Compatibility* table of `README.md` must list the same versions
  (`scripts/netbox-versions.py check`, run by `lint.yml`).
- Use only constructs, classes and APIs that exist in the supported NetBox
  versions. Before any work with code, consult the official NetBox
  documentation and the NetBox source code of the supported tag.

## Working rules

- Do not guess or assume anything. Get information from the NetBox
  documentation and source, from the project code, or ask the user.
- Architecture decisions and changes to files happen only after the user
  has agreed to them. Work in the steps agreed with the user and stop after
  each step.
- If a NetBox behaviour is not obvious (validation rules, signals, ordering
  of related objects), stop and ask instead of choosing silently.

## Scope of the sync

Agreed with the user; do not widen it without asking.

- Component types: every concrete subclass of
  `dcim.models.device_component_templates.ComponentTemplateModel` (12 in
  NetBox 4.7.4), plus front/rear port mappings and module bay types.
- Only the properties that a component template defines are compared. Cables,
  IP addresses, VLANs, MAC addresses, VRFs, MTU, mode, custom fields and tags
  of the device components are never touched.
- Components installed by a module (`module` is set) are ignored.
- Components that exist on the device but not in the device type are ignored.
- Missing components are created with the template's `instantiate()`, exactly
  as NetBox does when it creates a device (no description).
- Device fields: `platform` (from `default_platform`), `airflow`,
  `cooling_method` — the fields NetBox copies from the device type only when
  a device is created. Offered only when the device type has a value that
  differs from the device.
- Every property has a checkbox; all checkboxes are unchecked by default.
- Apply runs in a single transaction; any validation error rolls back
  everything.

## Undocumented NetBox internals

The NetBox plugin documentation states that anything not documented in the
plugins API is not supported and may change without warning. The plugin
relies on the following internals. Check each of them for every new NetBox
version:

1. **Sync button.** In `ready()` the plugin finds the
   `dcim.ui.panels.DeviceDeviceTypePanel` instance in
   `dcim.views.DeviceView.layout` and appends a panel action to it. If the
   panel is not found, the plugin logs a warning to the logger
   `netbox.plugins.netbox_device_type_sync` and adds no button. There is no
   fallback button; this was agreed with the user.
2. **Component templates.** `ComponentTemplateModel.instantiate()`,
   `resolve_name()`, `resolve_label()`, the `component_model` attribute and
   the template related names on `DeviceType` (`<model>s`).
3. **Device creation.** The fields that `Device.save()` copies from the device
   type when a device is created.
4. **Port mappings.** `dcim.models.PortMapping`, `PortTemplateMapping`.
5. **Inventory items.** Deprecated since NetBox 4.3 and planned for removal.
   `components.py` imports `InventoryItem` and `InventoryItemTemplate`
   optionally; when NetBox removes them, drop the inventory item kind, its
   properties and tests, and update the README.

The code that relies on items 1–4 lives in `ui.py` (the button),
`components.py` (templates and properties) and `apply.py` (creation).

## Local test environment

The tests run against a NetBox source checkout of a supported tag, the same
way as `.github/workflows/test.yml`:

```bash
# PostgreSQL and Redis on localhost (the credentials match testing/configuration_testing.py)
docker run -d --name dts-pg -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=netbox -e POSTGRES_PASSWORD=netbox -e POSTGRES_DB=netbox postgres:16
docker run -d --name dts-redis -p 127.0.0.1:6379:6379 redis:7

# NetBox source and a virtual environment, outside this repository
git clone --depth 1 --branch v4.7.4 https://github.com/netbox-community/netbox.git ~/netbox-dev/netbox
virtualenv -p python3.12 ~/netbox-dev/venv
~/netbox-dev/venv/bin/pip install -r ~/netbox-dev/netbox/requirements.txt tblib
~/netbox-dev/venv/bin/pip install -e .
ln -s "$PWD/testing/configuration_testing.py" ~/netbox-dev/netbox/netbox/netbox/configuration.py

# Run the tests
cd ~/netbox-dev/netbox
../venv/bin/python netbox/manage.py test netbox_device_type_sync.tests --parallel
```

If `psycopg[c]` fails to build (no `pg_config`), install the requirements with
`psycopg[binary,pool]` instead.

## Supporting a new NetBox version

New NetBox releases are checked automatically every day by
`netbox-latest.yml` (see *GitHub Actions*). A new patch release of the newest
supported minor version (e.g. 4.7.5) is added and released without a human
when all tests pass. A new minor or major version (e.g. 4.8.0) gets a pull
request instead, and a failure gets an issue. For a pull request, an issue,
or a manual update, do all of the following:

1. Run `python scripts/netbox-versions.py add vX.Y.Z`: it adds the version to
   `supported-netbox-versions.json` and the README table, bumps the PATCH
   version and adds a CHANGELOG entry.
2. Run the full test suite against that version. These tests must pass:
   - the Sync button is added to the *Device Type* card and is visible to a
     user with the `dcim.change_device` permission, and hidden from a user
     without it;
   - the coverage tests: no new component template models, no new template
     fields, no new `DeviceType` fields that the plugin does not classify;
   - the sync tests (diff, create, update, rollback).
3. Read the NetBox release notes for changes to device components, component
   templates, `Device.save()`, `DeviceView` and `netbox.ui`.
4. Check the Device page (Sync button) and the sync page in a browser.
5. Update `min_version` in `netbox_device_type_sync/__init__.py` if needed;
   if code changes were necessary, describe them in `CHANGELOG.md` and bump
   MINOR or PATCH as appropriate instead of the PATCH bump of step 1.

Report every failing check to the user before changing code.

## Plugin version

- Follow Semantic Versioning (`MAJOR.MINOR.PATCH`):
  - PATCH — bug fixes, documentation, support for a new NetBox version
    without code changes;
  - MINOR — new functionality or backward-compatible behaviour changes;
  - MAJOR — incompatible changes.
- The version is stored in three places and must always be identical:
  `pyproject.toml`, `netbox_device_type_sync/version.py`,
  `netbox_device_type_sync/tests/test_load.py`. `scripts/version-check.py`
  compares them with the release tag.
- Bump the version once per task. Propose the new version to the user and
  wait for confirmation. Exception, agreed with the user: `netbox-latest.yml`
  bumps PATCH and releases by itself for a new NetBox patch release.

## GitHub Actions

- Never use the `pull_request_target` trigger: it gives workflows started from
  pull requests of forks write access to the repository.
- Request only the permissions a job needs (`permissions:` per workflow or
  job).
- `lint.yml` and `test.yml` run on pushes to branches and on pull requests,
  not on tags. A release tag (`v*`) starts `publish.yaml`, which calls both
  of them (`workflow_call`) and publishes to PyPI only if the version check,
  the lint and all tests pass. Keep this dependency when changing the
  workflows.
- `netbox-latest.yml` runs daily at 11:00 UTC (and manually, as a dry run by default). It
  classifies the latest stable NetBox release with
  `scripts/netbox-versions.py classify` and tests it with `test.yml`:
  - `patch`: on success it runs `netbox-versions.py add`, commits as
    `github-actions[bot]`, tags, pushes to `main` and starts
    `publish.yaml` with `workflow_dispatch` (a tag pushed with `GITHUB_TOKEN`
    does not trigger workflows);
  - `minor`: on success it opens a pull request from the branch
    `netbox-vX.Y.Z` (requires *Allow GitHub Actions to create and approve
    pull requests* in the repository settings);
  - on failure it opens one issue per NetBox version;
  - `supported` or `older`: nothing to do.

## Commits

- Author: `Maksym Ototiuk <git@masik.slmail.me>` (local git config).
  Commits made by `netbox-latest.yml` are authored by `github-actions[bot]`,
  as agreed with the user.
- Do not add a `Co-Authored-By` line to commit messages.
- Commit or push only when the user has agreed. This applies to work done
  by Claude in this repository, not to GitHub Actions workflows that the
  user has agreed to (for example an automatic release workflow).

## Language and documentation

- All code, comments and documentation are written in English.
- `README.md` must have a Table of Contents with jump links to all sections
  and a "Back to ToC" link at the end of each section.
- Update `README.md` and `CHANGELOG.md` with every change that affects users.
- `docs/images/` holds the README screenshots (the Device Type card and the
  sync page). Retake them when the UI changes. They must not show personal
  data: crop away the top navigation bar (user name) and the page footer
  (host name), and use demo data only.
