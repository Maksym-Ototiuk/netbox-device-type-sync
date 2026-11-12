"""
Compare a device with its device type.

build_plan() returns a SyncPlan: the device fields that differ, and for each
component type the components to create, the components whose properties
differ, and the template names that clash with components of installed
modules. Building a plan never changes the database.
"""

from dataclasses import dataclass, field

from .components import (
    COMPONENT_KINDS,
    DEVICE_FIELDS,
    EMPTY,
    ComponentKind,
    DeviceField,
    SyncContext,
    display_field,
)

__all__ = (
    'ComponentDiff',
    'DeviceFieldDiff',
    'KindDiff',
    'PropertyChange',
    'PropertySummary',
    'SyncPlan',
    'TemplateToCreate',
    'build_plan',
)


@dataclass
class PropertyChange:
    """A property of one component whose value differs from its template."""

    current: str
    desired: str


@dataclass
class ComponentDiff:
    """A device component whose properties differ from its template."""

    name: str
    component: object
    template: object
    changes: dict  # property key -> PropertyChange


@dataclass
class TemplateToCreate:
    """A template that has no component on the device."""

    name: str
    template: object


@dataclass
class Conflict:
    """A template whose name is taken by a component of an installed module."""

    name: str
    component: object


@dataclass
class PropertySummary:
    """A property and all the components of one type on which it differs."""

    prop: object
    label: str
    selection_key: str
    components: list  # (component name, PropertyChange)

    @property
    def count(self):
        return len(self.components)


@dataclass
class KindDiff:
    """The differences for one component type."""

    kind: ComponentKind
    create: list = field(default_factory=list)
    update: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)

    @property
    def is_empty(self):
        return not (self.create or self.update or self.conflicts)

    @property
    def property_summaries(self):
        summaries = []
        for prop in self.kind.properties:
            components = [
                (diff.name, diff.changes[prop.key])
                for diff in self.update
                if prop.key in diff.changes
            ]
            if components:
                summaries.append(
                    PropertySummary(
                        prop=prop,
                        label=str(prop.label(self.kind.component_model)),
                        selection_key=f'{self.kind.key}.{prop.key}',
                        components=components,
                    )
                )
        return summaries


@dataclass
class DeviceFieldDiff:
    """A device field whose value differs from the device type."""

    field: DeviceField
    label: str
    selection_key: str
    current: str
    desired: str


@dataclass
class SyncPlan:
    device: object
    device_type: object
    device_fields: list
    kinds: list  # KindDiff for every component type, in COMPONENT_KINDS order

    @property
    def changed_kinds(self):
        return [k for k in self.kinds if not k.is_empty]

    @property
    def create_count(self):
        return sum(len(k.create) for k in self.kinds)

    @property
    def selection_keys(self):
        """All the property keys the user can select."""
        keys = [f.selection_key for f in self.device_fields]
        for kind_diff in self.kinds:
            keys.extend(s.selection_key for s in kind_diff.property_summaries)
        return keys

    @property
    def is_empty(self):
        return not self.device_fields and not self.changed_kinds


def _diff_device_fields(device, device_type):
    diffs = []
    for device_field in DEVICE_FIELDS:
        source = device_type._meta.get_field(device_field.source)
        desired = getattr(device_type, source.attname)
        current = getattr(device, device._meta.get_field(device_field.name).attname)
        # Like Device.save(): an empty device type value is never copied
        if desired in (None, '') or desired == current:
            continue
        diffs.append(
            DeviceFieldDiff(
                field=device_field,
                label=str(device_field.label()),
                selection_key=f'device.{device_field.key}',
                current=display_field(device, device_field.name, current)
                if current not in (None, '')
                else EMPTY,
                desired=display_field(device_type, device_field.source, desired),
            )
        )
    return diffs


def _template_key(kind, template, ctx):
    if kind.key == 'inventoryitem':
        return ctx.template_path(template)
    return ctx.template_name(template)


def _component_key(kind, component, ctx):
    if kind.key == 'inventoryitem':
        return ctx.component_path(component)
    return component.name


def _key_display(key):
    return ' / '.join(key) if isinstance(key, tuple) else key


def diff_kind(kind, device, ctx):
    result = KindDiff(kind=kind)
    templates = getattr(device.device_type, kind.template_accessor).all()
    components = getattr(device, kind.component_accessor).all()

    device_components = {}
    module_components = {}
    for component in components:
        if kind.is_modular and component.module_id is not None:
            module_components[component.name] = component
        else:
            device_components[_component_key(kind, component, ctx)] = component

    for template in templates:
        key = _template_key(kind, template, ctx)
        name = _key_display(key)
        component = device_components.get(key)
        if component is None:
            if key in module_components:
                result.conflicts.append(
                    Conflict(name=name, component=module_components[key])
                )
            else:
                result.create.append(TemplateToCreate(name=name, template=template))
            continue

        changes = {}
        for prop in kind.properties:
            desired, desired_display = prop.read_template(template, ctx)
            current, current_display = prop.read_component(component, ctx)
            if desired != current:
                changes[prop.key] = PropertyChange(
                    current=current_display, desired=desired_display
                )
        if changes:
            result.update.append(
                ComponentDiff(
                    name=name, component=component, template=template, changes=changes
                )
            )

    return result


def build_plan(device):
    """
    Compare the device with its device type and return a SyncPlan.
    """
    ctx = SyncContext(device)
    return SyncPlan(
        device=device,
        device_type=device.device_type,
        device_fields=_diff_device_fields(device, device.device_type),
        kinds=[diff_kind(kind, device, ctx) for kind in COMPONENT_KINDS],
    )
