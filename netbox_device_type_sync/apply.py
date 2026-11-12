"""
Apply a sync plan to a device.

apply_plan() creates the missing components and copies the selected
properties from the templates to the device components, in one database
transaction. If any object fails validation or the user lacks a permission,
it raises SyncError with every error found, and nothing is changed.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, router, transaction
from django.utils.text import capfirst
from django.utils.translation import gettext as _

from dcim.models import Device, PortMapping, RearPort
from extras.models import CustomField

from .components import (
    PortMappingsProperty,
    RelationProperty,
    SyncContext,
)

__all__ = (
    'SyncError',
    'SyncResult',
    'apply_plan',
    'describe_kind_counts',
    'format_validation_error',
)

logger = logging.getLogger('netbox.plugins.netbox_device_type_sync')

# Kinds whose templates refer to templates of the same kind; parents first
_SELF_REFERENCING = {'interface', 'inventoryitem'}

# Relations that a template's instantiate() resolves itself
_INSTANTIATE_LOOKUPS = {
    'poweroutlet': 'power_port',
    'coolingoutflow': 'cooling_intake',
}


class SyncError(Exception):
    def __init__(self, errors):
        super().__init__('; '.join(errors))
        self.errors = errors


@dataclass
class SyncResult:
    device_fields: list = field(default_factory=list)
    created: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)

    @property
    def created_count(self):
        return sum(self.created.values())

    @property
    def updated_count(self):
        return sum(self.updated.values())


def format_validation_error(error):
    if hasattr(error, 'error_dict'):
        parts = []
        for field_name, messages in error.message_dict.items():
            text = ' '.join(messages)
            parts.append(text if field_name == '__all__' else f'{field_name}: {text}')
        return ' '.join(parts)
    return ' '.join(error.messages)


def _template_depth(kind, template):
    if kind.key not in _SELF_REFERENCING:
        return 0
    depth = 0
    while template.parent is not None:
        depth += 1
        template = template.parent
    return depth


class _Applier:
    def __init__(self, plan, selected, user, changelog_message):
        self.plan = plan
        self.device = plan.device
        self.selected = set(selected) & set(plan.selection_keys)
        self.user = user
        self.changelog_message = changelog_message
        self.ctx = SyncContext(self.device)
        self.errors = []
        self.result = SyncResult()
        # Interfaces whose bridge is set after all interfaces exist
        self.pending_bridges = []
        # Front ports whose mappings are created after all ports exist
        self.pending_mappings = []

    def is_selected(self, kind, prop):
        return f'{kind.key}.{prop.key}' in self.selected

    def error(self, kind, name, message):
        self.errors.append(f'{kind.verbose_name} {name}: {message}')

    #
    # Saving
    #

    def save(self, obj, action, describe):
        """
        Validate, save and check object permissions. Return True on success.
        """
        obj._changelog_message = self.changelog_message
        try:
            obj.full_clean()
            # A savepoint keeps the transaction usable after a database error
            with transaction.atomic(using=router.db_for_write(type(obj))):
                obj.save()
        except ValidationError as e:
            self.errors.append(f'{describe}: {format_validation_error(e)}')
            return False
        except IntegrityError as e:
            self.errors.append(f'{describe}: {e}')
            return False
        if self.user is not None and action is not None:
            permitted = type(obj).objects.restrict(self.user, action).filter(pk=obj.pk)
            if not permitted.exists():
                self.errors.append(
                    _('{object}: you do not have permission to {action} it.').format(
                        object=describe, action=action
                    )
                )
                return False
        return True

    #
    # Device fields
    #

    def apply_device_fields(self):
        diffs = [f for f in self.plan.device_fields if f.selection_key in self.selected]
        if not diffs:
            return
        device = self.device
        device.snapshot()
        for diff in diffs:
            source = self.plan.device_type._meta.get_field(diff.field.source)
            target = device._meta.get_field(diff.field.name)
            setattr(
                device, target.attname, getattr(self.plan.device_type, source.attname)
            )
        if self.save(device, 'change', str(device)):
            self.result.device_fields = [d.label for d in diffs]

    #
    # Components
    #

    def apply_kind(self, kind_diff):
        kind = kind_diff.kind
        items = [(d.template, d) for d in kind_diff.update]
        items += [(c.template, c) for c in kind_diff.create]
        items.sort(key=lambda item: _template_depth(kind, item[0]))
        for template, item in items:
            if hasattr(item, 'component'):
                self.update_component(kind, item)
            else:
                self.create_component(kind, item)
            if kind.key == 'inventoryitem':
                self.ctx.forget_inventory_items()

    def split_properties(self, kind, diff):
        """
        Return the selected properties of a component diff that are written
        before and after the component is saved. Port mappings and interface
        bridges are queued for the passes that run once all components exist.
        """
        direct, deferred = [], []
        for key in diff.changes:
            prop = kind.get_property(key)
            if not self.is_selected(kind, prop):
                continue
            if isinstance(prop, PortMappingsProperty):
                self.pending_mappings.append((diff.component, diff.template, False))
            elif kind.key == 'interface' and prop.key == 'bridge':
                self.pending_bridges.append((diff.component, diff.template, diff.name))
            elif prop.deferred:
                deferred.append(prop)
            else:
                direct.append(prop)
        return direct, deferred

    def update_component(self, kind, diff):
        selected = [
            k for k in diff.changes if self.is_selected(kind, kind.get_property(k))
        ]
        if not selected:
            return
        component = diff.component
        component.snapshot()
        direct, deferred = self.split_properties(kind, diff)
        self.result.updated[kind.key] += 1
        if not (direct or deferred):
            return
        for prop in direct:
            if message := prop.write(component, diff.template, self.ctx):
                self.error(kind, diff.name, message)
                return
        if self.save(component, 'change', f'{kind.verbose_name} {diff.name}'):
            for prop in deferred:
                prop.write(component, diff.template, self.ctx)

    def instantiate(self, kind, template):
        """
        Build a new component from its template the way NetBox does for a new
        device (dcim.models.Device._instantiate_components()).
        """
        if kind.key == 'inventoryitem':
            # InventoryItemTemplate.instantiate() looks up the parent by name
            # only; build the item here so the parent is matched by its path.
            component = kind.component_model(
                device=self.device,
                name=template.name,
                label=template.label,
                role=template.role,
                manufacturer=template.manufacturer,
                part_id=template.part_id,
            )
            for prop in (kind.get_property('parent'), kind.get_property('component')):
                if message := prop.write(component, template, self.ctx):
                    raise ObjectDoesNotExist(message)
            return component
        if relation := _INSTANTIATE_LOOKUPS.get(kind.key):
            # instantiate() looks the related component up by name; check it
            # first to report a readable error
            name, _display = RelationProperty(relation).read_template(
                template, self.ctx
            )
            model = kind.component_model._meta.get_field(relation).related_model
            if name is not None and self.ctx.find_component(model, name) is None:
                raise ObjectDoesNotExist(
                    _('{model} {name} does not exist on the device.').format(
                        model=capfirst(model._meta.verbose_name), name=name
                    )
                )
        component = template.instantiate(device=self.device)
        if kind.key == 'interface' and template.parent is not None:
            # NetBox sets interface parents after instantiation (update_interface_parents())
            message = RelationProperty('parent').write(component, template, self.ctx)
            if message:
                raise ObjectDoesNotExist(message)
        return component

    def create_component(self, kind, item):
        try:
            component = self.instantiate(kind, item.template)
        except ObjectDoesNotExist as e:
            self.error(
                kind, item.name, str(e) or _('A related component does not exist.')
            )
            return
        if cf_defaults := CustomField.objects.get_defaults_for_model(
            kind.component_model
        ):
            component.custom_field_data = cf_defaults
        if not self.save(component, 'add', f'{kind.verbose_name} {item.name}'):
            return
        if src := getattr(component, '_source_template', None):
            # Module bays: copy module_bay_types, as Device._instantiate_components() does
            component.module_bay_types.set(src.module_bay_types.all())
        if kind.key == 'interface' and item.template.bridge is not None:
            self.pending_bridges.append((component, item.template, item.name))
        if kind.key == 'frontport':
            self.pending_mappings.append((component, item.template, True))
        self.result.created[kind.key] += 1

    def apply_bridges(self, kind):
        bridge = kind.get_property('bridge')
        for component, template, name in self.pending_bridges:
            component.snapshot()
            if message := bridge.write(component, template, self.ctx):
                self.error(kind, name, message)
                continue
            self.save(component, 'change', f'{kind.verbose_name} {name}')

    #
    # Port mappings
    #

    def remove_obsolete_mappings(self, kind_diff):
        # Before port positions change, so that fewer positions validate
        prop = kind_diff.kind.get_property('mappings')
        if not self.is_selected(kind_diff.kind, prop):
            return
        for diff in kind_diff.update:
            if 'mappings' not in diff.changes:
                continue
            desired = prop.desired(diff.template, self.ctx)
            for mapping in diff.component.mappings.select_related('rear_port'):
                key = (
                    mapping.front_port_position,
                    mapping.rear_port.name,
                    mapping.rear_port_position,
                )
                if key not in desired:
                    mapping._changelog_message = self.changelog_message
                    mapping.delete()

    def create_mappings(self, kind):
        prop = kind.get_property('mappings')
        for front_port, template, is_new in self.pending_mappings:
            existing = set() if is_new else prop.current(front_port)
            for front_pos, rear_name, rear_pos in sorted(
                prop.desired(template, self.ctx)
            ):
                if (front_pos, rear_name, rear_pos) in existing:
                    continue
                rear_port = self.ctx.find_component(RearPort, rear_name)
                if rear_port is None:
                    self.error(
                        kind,
                        front_port.name,
                        _('Rear port {name} does not exist on the device.').format(
                            name=rear_name
                        ),
                    )
                    continue
                mapping = PortMapping(
                    device=self.device,
                    front_port=front_port,
                    front_port_position=front_pos,
                    rear_port=rear_port,
                    rear_port_position=rear_pos,
                )
                self.save(mapping, None, f'{kind.verbose_name} {front_port.name}')

    #
    # Entry point
    #

    def run(self):
        self.apply_device_fields()
        kind_diffs = {k.kind.key: k for k in self.plan.kinds}
        self.remove_obsolete_mappings(kind_diffs['frontport'])
        for kind_diff in self.plan.kinds:
            self.apply_kind(kind_diff)
            if kind_diff.kind.key == 'interface':
                self.apply_bridges(kind_diff.kind)
            elif kind_diff.kind.key == 'frontport':
                self.create_mappings(kind_diff.kind)
        return self.result


def apply_plan(plan, selected, user=None, changelog_message=''):
    """
    Apply the plan to its device.

    Args:
        plan: A SyncPlan from diff.build_plan()
        selected: The selection keys of the properties to copy from the device
            type (for example "interface.type" or "device.airflow"). Missing
            components are always created.
        user: The user whose object permissions are enforced (None: no checks)
        changelog_message: The message recorded with every change

    Returns:
        A SyncResult. Raises SyncError (and changes nothing) on any error.
    """
    applier = _Applier(plan, selected, user, changelog_message)
    with transaction.atomic(using=router.db_for_write(Device)):
        result = applier.run()
        if applier.errors:
            raise SyncError(applier.errors)
    logger.info(
        'Synced device %s with device type %s: %d created, %d updated',
        plan.device.pk,
        plan.device_type.pk,
        result.created_count,
        result.updated_count,
    )
    return result


def describe_kind_counts(counter):
    """
    Return e.g. "3 interfaces, 1 console port" for a Counter of kind keys.
    """
    from .components import get_kind

    parts = []
    for key, count in counter.items():
        model = get_kind(key).component_model
        name = (
            model._meta.verbose_name if count == 1 else model._meta.verbose_name_plural
        )
        parts.append(f'{count} {name}')
    return ', '.join(parts)
