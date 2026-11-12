"""
The component types and the properties that the plugin compares.

A component template defines only some properties of a component. The plugin
compares exactly those properties; everything else on a device component
(cables, IP addresses, VLANs, MAC addresses, custom fields, tags, ...) is never
read or written.

Each property knows how to read its value from a template and from a device
component, and how to write the template value to a component. Values are
compared as plain Python values; every read also returns a human-readable
display string for the sync page.
"""

from dataclasses import dataclass

from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from dcim.models import (
    ConsolePortTemplate,
    ConsoleServerPortTemplate,
    CoolingIntakeTemplate,
    CoolingOutflowTemplate,
    DeviceBayTemplate,
    FrontPortTemplate,
    InterfaceTemplate,
    InventoryItem,
    InventoryItemTemplate,
    ModuleBayTemplate,
    PowerOutletTemplate,
    PowerPortTemplate,
    RearPortTemplate,
)

__all__ = (
    'COMPONENT_KINDS',
    'DEVICE_FIELDS',
    'ComponentKind',
    'DeviceField',
    'EMPTY',
    'display_field',
    'SyncContext',
    'get_kind',
)

# Display string for an empty value
EMPTY = '—'


def _normalize(value):
    # NetBox stores "no value" as both None and '' in optional fields
    return None if value == '' else value


def display_field(obj, field_name, value):
    """
    Return a human-readable representation of a model field value.
    """
    if value is None:
        return EMPTY
    field = obj._meta.get_field(field_name)
    if field.is_relation:
        return str(getattr(obj, field_name))
    if field.choices:
        return str(dict(field.flatchoices).get(value, value))
    if isinstance(value, bool):
        return str(_('Yes')) if value else str(_('No'))
    return str(value)


class SyncContext:
    """
    The device being synced, with lookups shared by all properties.
    """

    def __init__(self, device):
        self.device = device
        self._inventory_paths = None

    def template_name(self, template):
        """
        Return the name a template gives a component on this device.
        """
        if hasattr(template, 'resolve_name'):
            return template.resolve_name(device=self.device)
        return template.name

    def find_component(self, model, name):
        """
        Return the component of this device with the given model and name, or None.
        """
        return model.objects.filter(device=self.device, name=name).first()

    #
    # Inventory items have no unique name on a device; they are identified by
    # the names of their parents and their own name.
    #

    @staticmethod
    def template_path(template):
        path = []
        while template is not None:
            path.insert(0, template.name)
            template = template.parent
        return tuple(path)

    def component_path(self, item):
        if item is None:
            return None
        path = []
        while item is not None:
            path.insert(0, item.name)
            item = item.parent
        return tuple(path)

    def find_inventory_item(self, path):
        if self._inventory_paths is None:
            self._inventory_paths = {}
        if path not in self._inventory_paths:
            self._inventory_paths[path] = None
            for item in InventoryItem.objects.filter(device=self.device, name=path[-1]):
                if self.component_path(item) == path:
                    self._inventory_paths[path] = item
                    break
        return self._inventory_paths[path]

    def forget_inventory_items(self):
        self._inventory_paths = None


#
# Properties
#


class Property:
    """
    A comparable property of a component.

    Attributes:
        key: The identifier of the property within its component type
        template_fields: The template model fields covered by the property
        deferred: True if the property is written after the component is saved
    """

    key = None
    template_fields = ()
    deferred = False

    def label(self, component_model):
        raise NotImplementedError

    def read_template(self, template, ctx):
        """Return (value, display) of the property for a template."""
        raise NotImplementedError

    def read_component(self, component, ctx):
        """Return (value, display) of the property for a device component."""
        raise NotImplementedError

    def write(self, component, template, ctx):
        """
        Copy the value of the template to the component. Return an error message
        if the value cannot be written, otherwise None.
        """
        raise NotImplementedError


class FieldProperty(Property):
    """
    One or more model fields that the template and the component share, for
    example "type", or "diameter" together with its unit.
    """

    # Template fields whose value contains {vc_position} or {module} tokens
    RESOLVED_FIELDS = ('label', 'position')

    def __init__(self, *fields):
        self.key = fields[0]
        self.template_fields = fields

    def label(self, component_model):
        return capfirst(component_model._meta.get_field(self.key).verbose_name)

    def _template_value(self, template, field_name, ctx):
        resolver = getattr(template, f'resolve_{field_name}', None)
        if field_name in self.RESOLVED_FIELDS and resolver is not None:
            return resolver(device=ctx.device)
        return getattr(template, template._meta.get_field(field_name).attname)

    def _read(self, obj, values):
        value = tuple(_normalize(v) for v in values)
        if value[0] is None:
            # A unit without a value (e.g. diameter_unit without diameter) means nothing
            return (None,) * len(value), EMPTY
        display = ' '.join(
            display_field(obj, name, v)
            for name, v in zip(self.template_fields, value)
            if v is not None
        )
        return value, display

    def read_template(self, template, ctx):
        return self._read(
            template,
            [self._template_value(template, f, ctx) for f in self.template_fields],
        )

    def read_component(self, component, ctx):
        return self._read(
            component,
            [
                getattr(component, component._meta.get_field(f).attname)
                for f in self.template_fields
            ],
        )

    def write(self, component, template, ctx):
        for field_name in self.template_fields:
            value = self._template_value(template, field_name, ctx)
            field = component._meta.get_field(field_name)
            if value is None and not field.null:
                value = ''
            setattr(component, field.attname, value)


class RelationProperty(Property):
    """
    A reference to another component of the same device (for example the
    parent of an interface), matched by name.
    """

    def __init__(self, field_name):
        self.key = field_name
        self.template_fields = (field_name,)

    def label(self, component_model):
        return capfirst(component_model._meta.get_field(self.key).verbose_name)

    def read_template(self, template, ctx):
        target = getattr(template, self.key)
        name = ctx.template_name(target) if target is not None else None
        return name, name or EMPTY

    def read_component(self, component, ctx):
        target = getattr(component, self.key)
        name = target.name if target is not None else None
        return name, name or EMPTY

    def write(self, component, template, ctx):
        name, _display = self.read_template(template, ctx)
        if name is None:
            setattr(component, self.key, None)
            return None
        model = component._meta.get_field(self.key).related_model
        target = ctx.find_component(model, name)
        if target is None:
            return _('{model} {name} does not exist on the device.').format(
                model=capfirst(model._meta.verbose_name), name=name
            )
        setattr(component, self.key, target)
        return None


class InventoryParentProperty(Property):
    """
    The parent of an inventory item, identified by the names of its parents.
    """

    key = 'parent'
    template_fields = ('parent',)

    def label(self, component_model):
        return capfirst(component_model._meta.get_field('parent').verbose_name)

    @staticmethod
    def _display(path):
        return ' / '.join(path) if path else EMPTY

    def read_template(self, template, ctx):
        path = ctx.template_path(template.parent) if template.parent else None
        return path, self._display(path)

    def read_component(self, component, ctx):
        path = ctx.component_path(component.parent)
        return path, self._display(path)

    def write(self, component, template, ctx):
        path, display = self.read_template(template, ctx)
        if path is None:
            component.parent = None
            return None
        parent = ctx.find_inventory_item(path)
        if parent is None:
            return _('Inventory item {name} does not exist on the device.').format(
                name=display
            )
        component.parent = parent
        return None


class InventoryComponentProperty(Property):
    """
    The component an inventory item is assigned to, identified by its type and
    name.
    """

    key = 'component'
    template_fields = ('component_type', 'component_id')

    def label(self, component_model):
        return _('Component')

    @staticmethod
    def _value(model, name):
        value = (model._meta.label_lower, name)
        display = f'{capfirst(model._meta.verbose_name)} {name}'
        return value, display

    def read_template(self, template, ctx):
        target = template.component
        if target is None:
            return None, EMPTY
        return self._value(target.component_model, ctx.template_name(target))

    def read_component(self, component, ctx):
        target = component.component
        if target is None:
            return None, EMPTY
        return self._value(type(target), target.name)

    def write(self, component, template, ctx):
        target_template = template.component
        if target_template is None:
            component.component = None
            return None
        model = target_template.component_model
        name = ctx.template_name(target_template)
        target = ctx.find_component(model, name)
        if target is None:
            return _('{model} {name} does not exist on the device.').format(
                model=capfirst(model._meta.verbose_name), name=name
            )
        component.component = target
        return None


class ModuleBayTypesProperty(Property):
    """
    The module bay types of a module bay (a many-to-many relation).
    """

    key = 'module_bay_types'
    template_fields = ('module_bay_types',)
    deferred = True

    def label(self, component_model):
        return capfirst(component_model._meta.get_field(self.key).verbose_name)

    @staticmethod
    def _read(manager):
        types = sorted(manager.all(), key=lambda t: t.name)
        value = frozenset(t.pk for t in types)
        return value, ', '.join(t.name for t in types) or EMPTY

    def read_template(self, template, ctx):
        return self._read(template.module_bay_types)

    def read_component(self, component, ctx):
        return self._read(component.module_bay_types)

    def write(self, component, template, ctx):
        component.module_bay_types.set(template.module_bay_types.all())
        return None


class PortMappingsProperty(Property):
    """
    The mappings of a front port to rear port positions. The mappings are
    written by the apply step, which must remove obsolete mappings before port
    positions change and create new mappings after.
    """

    key = 'mappings'
    template_fields = ()
    deferred = True

    def label(self, component_model):
        return _('Port mappings')

    @staticmethod
    def _display(value):
        if not value:
            return EMPTY
        return ', '.join(
            f'{front_pos} → {rear}:{rear_pos}'
            for front_pos, rear, rear_pos in sorted(value)
        )

    @staticmethod
    def desired(template, ctx):
        return frozenset(
            (
                m.front_port_position,
                ctx.template_name(m.rear_port),
                m.rear_port_position,
            )
            for m in template.mappings.all()
        )

    @staticmethod
    def current(component):
        return frozenset(
            (m.front_port_position, m.rear_port.name, m.rear_port_position)
            for m in component.mappings.all()
        )

    def read_template(self, template, ctx):
        value = self.desired(template, ctx)
        return value, self._display(value)

    def read_component(self, component, ctx):
        value = self.current(component)
        return value, self._display(value)

    def write(self, component, template, ctx):
        # Written by apply.sync_port_mappings()
        raise NotImplementedError


#
# Component types
#


@dataclass(frozen=True)
class ComponentKind:
    """
    A type of device component and the properties its template defines.
    """

    template_model: type
    properties: tuple

    @property
    def component_model(self):
        return self.template_model.component_model

    @property
    def key(self):
        return self.component_model._meta.model_name

    @property
    def template_accessor(self):
        # related_name='%(class)ss' on DeviceType
        return f'{self.template_model._meta.model_name}s'

    @property
    def component_accessor(self):
        # related_name='%(class)ss' on Device
        return f'{self.component_model._meta.model_name}s'

    @property
    def verbose_name(self):
        return capfirst(self.component_model._meta.verbose_name)

    @property
    def verbose_name_plural(self):
        return capfirst(self.component_model._meta.verbose_name_plural)

    @property
    def is_modular(self):
        # Modular components may belong to an installed module
        return any(f.name == 'module' for f in self.component_model._meta.fields)

    def get_property(self, key):
        for prop in self.properties:
            if prop.key == key:
                return prop
        raise KeyError(key)


LABEL = FieldProperty('label')
DESCRIPTION = FieldProperty('description')
TYPE = FieldProperty('type')

# In the order NetBox instantiates components for a new device
# (dcim.models.Device.save()); components that others refer to come first.
COMPONENT_KINDS = (
    ComponentKind(ConsolePortTemplate, (TYPE, LABEL, DESCRIPTION)),
    ComponentKind(ConsoleServerPortTemplate, (TYPE, LABEL, DESCRIPTION)),
    ComponentKind(
        PowerPortTemplate,
        (
            TYPE,
            FieldProperty('maximum_draw'),
            FieldProperty('allocated_draw'),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(
        PowerOutletTemplate,
        (
            TYPE,
            FieldProperty('color'),
            RelationProperty('power_port'),
            FieldProperty('feed_leg'),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(
        CoolingIntakeTemplate,
        (
            TYPE,
            FieldProperty('diameter', 'diameter_unit'),
            FieldProperty('max_flow', 'max_flow_unit'),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(
        CoolingOutflowTemplate,
        (
            TYPE,
            FieldProperty('diameter', 'diameter_unit'),
            RelationProperty('cooling_intake'),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(
        InterfaceTemplate,
        (
            TYPE,
            FieldProperty('enabled'),
            FieldProperty('mgmt_only'),
            FieldProperty('poe_mode'),
            FieldProperty('poe_type'),
            FieldProperty('rf_role'),
            FieldProperty('channels'),
            FieldProperty('channel_id'),
            RelationProperty('parent'),
            RelationProperty('bridge'),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(
        RearPortTemplate,
        (TYPE, FieldProperty('color'), FieldProperty('positions'), LABEL, DESCRIPTION),
    ),
    ComponentKind(
        FrontPortTemplate,
        (
            TYPE,
            FieldProperty('color'),
            FieldProperty('positions'),
            PortMappingsProperty(),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(
        ModuleBayTemplate,
        (
            FieldProperty('position'),
            FieldProperty('enabled'),
            ModuleBayTypesProperty(),
            LABEL,
            DESCRIPTION,
        ),
    ),
    ComponentKind(DeviceBayTemplate, (FieldProperty('enabled'), LABEL, DESCRIPTION)),
    ComponentKind(
        InventoryItemTemplate,
        (
            InventoryParentProperty(),
            InventoryComponentProperty(),
            FieldProperty('role'),
            FieldProperty('manufacturer'),
            FieldProperty('part_id'),
            LABEL,
            DESCRIPTION,
        ),
    ),
)


def get_kind(key):
    for kind in COMPONENT_KINDS:
        if kind.key == key:
            return kind
    raise KeyError(key)


#
# Device fields
#


@dataclass(frozen=True)
class DeviceField:
    """
    A device field that NetBox copies from the device type only when a device
    is created (dcim.models.Device.save()).

    Attributes:
        name: The field of Device
        source: The field of DeviceType that holds the value
    """

    name: str
    source: str

    @property
    def key(self):
        return self.name

    def label(self):
        from dcim.models import Device

        return capfirst(Device._meta.get_field(self.name).verbose_name)


DEVICE_FIELDS = (
    DeviceField('platform', 'default_platform'),
    DeviceField('airflow', 'airflow'),
    DeviceField('cooling_method', 'cooling_method'),
)
