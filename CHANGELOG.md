# Changelog

All notable changes to netbox-device-type-sync. The versions follow
[semantic versioning](https://semver.org/).

## 0.1.0 (unreleased)

First release, for NetBox 4.7.4.

### Added

- A **Sync** button in the header of the *Device Type* card on the Device
  page, shown to users who may change the device.
- A sync page that compares a device with its device type: the components
  to create, and for each component type the properties that differ, each
  with a checkbox (unchecked by default) and the values on the device and in
  the device type.
- Sync of all 12 component types of NetBox 4.7.4 (console ports, console
  server ports, power ports, power outlets, cooling intakes, cooling
  outflows, interfaces, rear ports, front ports, module bays, device bays,
  inventory items), front/rear port mappings and module bay types.
- Sync of the device fields NetBox copies from the device type only when a
  device is created: platform, airflow, cooling method.
- Missing components are created the way NetBox creates them for a new
  device, including interface parents and bridges, port mappings, module bay
  types and custom field defaults.
- All changes are made in one transaction and recorded in the change log
  with the message `Synced with device type <name>`; any validation or
  permission error rolls back everything.
