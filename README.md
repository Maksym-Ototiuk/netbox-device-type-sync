# NetBox Device Type Sync

A [NetBox](https://github.com/netbox-community/netbox) plugin that brings the
components of a device in line with its device type.

## Table of Contents

- [Purpose](#purpose)
- [How it works](#how-it-works)
- [What is synchronized](#what-is-synchronized)
- [Compatibility](#compatibility)
- [Installation](#installation)
- [Limitations](#limitations)
- [License](#license)

## Purpose

NetBox creates the components of a device (interfaces, ports, bays and so on)
from its device type only once, when the device is created. Later changes do
not reach the device:

- **A device is replaced by another model.** After you change the device type
  of the device, its components still have the names, types and settings of
  the old model.
- **A component is added to a device type.** Existing devices of that type do
  not get it.

Deleting and recreating the device would lose its cables, IP addresses, VLANs
and other settings. This plugin updates the device in place instead.

[⬆ Back to ToC](#table-of-contents)

## How it works

1. On the Device page, click **Sync** in the header of the *Device Type* card.
2. The plugin compares the component templates of the device type with the
   components of the device that have the same name, and shows:
   - the components that exist in the device type but not on the device —
     they will be created, exactly as NetBox creates them for a new device;
   - for each component type, the properties that differ, each with a
     checkbox. A checked property is copied from the device type to every
     component of that type with the same name; an unchecked property keeps
     the value of the device. All checkboxes are unchecked by default.
3. Click **Apply**. All changes are made in one transaction: if any
   component fails validation, nothing is changed and the errors are shown.
   Every change is recorded in the NetBox change log.

[⬆ Back to ToC](#table-of-contents)

## What is synchronized

Only the properties that a component template defines are compared:

| Component | Properties |
| --- | --- |
| Console port, console server port | label, description, type |
| Power port | label, description, type, maximum draw, allocated draw |
| Power outlet | label, description, type, color, power port, feed leg |
| Cooling intake | label, description, type, diameter, maximum flow |
| Cooling outflow | label, description, type, diameter, cooling intake |
| Interface | label, description, type, enabled, management only, parent, bridge, PoE mode, PoE type, wireless role, channels, channel ID |
| Front port | label, description, type, color, positions, port mappings |
| Rear port | label, description, type, color, positions |
| Module bay | label, description, position, enabled, module bay types |
| Device bay | label, description, enabled |
| Inventory item | label, description, parent, component, role, manufacturer, part ID |

Device fields that NetBox copies from the device type only when a device is
created: **platform** (from the default platform of the device type),
**airflow** and **cooling method**. They are offered only when the device type
has a value that differs from the device.

Never touched: cables, IP addresses, VLANs, MAC addresses, VRFs, MTU, mode,
custom fields and tags of components; components installed by modules;
components that exist on the device but not in the device type.

[⬆ Back to ToC](#table-of-contents)

## Compatibility

| NetBox | netbox-device-type-sync |
| ------ | ----------------------- |
| 4.7.4  | 0.1.0                   |

Every NetBox version in this table has been tested with the plugin. Versions
that are not listed are not guaranteed to work: the Sync button relies on the
internal structure of the NetBox Device page (see
[Limitations](#limitations)).

NetBox 4.7 requires Python 3.12 or later, PostgreSQL 15 or later and Redis 6
or later.

[⬆ Back to ToC](#table-of-contents)

## Installation

1. Install the package into the NetBox virtual environment:

    ```bash
    source /opt/netbox/venv/bin/activate
    pip install netbox-device-type-sync
    ```

    To keep the plugin across NetBox upgrades, add it to
    `/opt/netbox/local_requirements.txt`:

    ```bash
    echo netbox-device-type-sync >> /opt/netbox/local_requirements.txt
    ```

2. Enable the plugin in `/opt/netbox/netbox/netbox/configuration.py`:

    ```python
    PLUGINS = [
        'netbox_device_type_sync',
    ]
    ```

3. Restart NetBox:

    ```bash
    sudo systemctl restart netbox netbox-rq
    ```

The plugin has no settings and no database tables.

[⬆ Back to ToC](#table-of-contents)

## Limitations

- **The Sync button relies on NetBox internals.** NetBox has no plugin API to
  add a button to a built-in card. The plugin adds the button to the
  *Device Type* card of the Device page when NetBox starts. If a NetBox
  version changes that card so the plugin cannot find it, the button is not
  shown and the plugin logs a warning to the logger
  `netbox.plugins.netbox_device_type_sync`. With the default NetBox logging
  configuration the warning goes to the journal of the NetBox service:

    ```bash
    sudo journalctl -u netbox | grep netbox_device_type_sync
    ```

- **Components are matched by name.** A component that was renamed in the new
  device type (for example `GigabitEthernet1/0/1` → `TenGigabitEthernet1/0/1`)
  is treated as a new component; the old one is left as it is.

[⬆ Back to ToC](#table-of-contents)

## License

[MIT](LICENSE)

[⬆ Back to ToC](#table-of-contents)
