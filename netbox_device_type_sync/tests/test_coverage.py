"""
Tests that fail when a NetBox version adds something the plugin does not know
about: a component template model, a template field, a port mapping field or a
device type field. Update netbox_device_type_sync/components.py (and the
README) before changing these tests.
"""

from django.apps import apps
from django.test import SimpleTestCase, TestCase

from dcim.choices import CoolingMethodChoices, DeviceAirflowChoices
from dcim.models import DeviceType, Platform, PortTemplateMapping
from dcim.models.device_component_templates import ComponentTemplateModel

from netbox_device_type_sync.components import (
    COMPONENT_KINDS,
    DEVICE_FIELDS,
    FieldProperty,
    RelationProperty,
)
from netbox_device_type_sync.tests.utils import SyncTestMixin

# Template fields that identify a template rather than describe the component
IGNORED_TEMPLATE_FIELDS = {
    'id',
    'created',
    'last_updated',
    'name',
    '_name',
    'device_type',
    'module_type',
    'path',
    '_abs_diameter',
    '_abs_max_flow',
}

# Every DeviceType field, by what the plugin does with it
DEVICE_TYPE_FIELDS = {
    # Copied to the device only when it is created: synced by the plugin
    'synced': {'default_platform', 'airflow', 'cooling_method'},
    # Read from the device type, never stored on the device
    'live': {
        'manufacturer',
        'model',
        'slug',
        'part_number',
        'u_height',
        'exclude_from_utilization',
        'is_full_depth',
        'subdevice_role',
        'end_of_life',
        'front_image',
        'rear_image',
        'weight',
        'weight_unit',
        '_abs_weight',
    },
    # Describe the device type itself; agreed not to sync
    'not_synced': {
        'id',
        'created',
        'last_updated',
        'custom_field_data',
        'owner',
        'description',
        'comments',
        'tags',
    },
}


def model_fields(model):
    return {f.name for f in model._meta.concrete_fields} | {
        f.name for f in model._meta.many_to_many
    }


class TemplateCoverageTestCase(SimpleTestCase):
    def test_all_template_models_are_known(self):
        template_models = {
            model
            for model in apps.get_app_config('dcim').get_models()
            if issubclass(model, ComponentTemplateModel)
        }
        self.assertEqual(
            template_models, {kind.template_model for kind in COMPONENT_KINDS}
        )

    def test_all_template_fields_are_known(self):
        for kind in COMPONENT_KINDS:
            with self.subTest(kind=kind.key):
                covered = set()
                for prop in kind.properties:
                    covered.update(prop.template_fields)
                self.assertEqual(
                    model_fields(kind.template_model) - IGNORED_TEMPLATE_FIELDS, covered
                )

    def test_component_models_have_the_template_fields(self):
        for kind in COMPONENT_KINDS:
            component_fields = model_fields(kind.component_model)
            for prop in kind.properties:
                if isinstance(prop, (FieldProperty, RelationProperty)):
                    with self.subTest(kind=kind.key, property=prop.key):
                        self.assertTrue(set(prop.template_fields) <= component_fields)

    def test_port_template_mapping_fields(self):
        self.assertEqual(
            model_fields(PortTemplateMapping),
            {
                'id',
                'created',
                'last_updated',
                'device_type',
                'module_type',
                'front_port',
                'front_port_position',
                'rear_port',
                'rear_port_position',
            },
        )

    def test_kind_order_matches_dependencies(self):
        # Components that other components refer to must be processed first
        keys = [kind.key for kind in COMPONENT_KINDS]
        self.assertLess(keys.index('powerport'), keys.index('poweroutlet'))
        self.assertLess(keys.index('coolingintake'), keys.index('coolingoutflow'))
        self.assertLess(keys.index('rearport'), keys.index('frontport'))
        self.assertEqual(keys[-1], 'inventoryitem')


class DeviceTypeFieldsTestCase(SimpleTestCase):
    def test_all_device_type_fields_are_classified(self):
        fields = {f for f in model_fields(DeviceType) if not f.endswith('_count')}
        classified = set().union(*DEVICE_TYPE_FIELDS.values())
        self.assertEqual(fields, classified)

    def test_device_fields_match_the_synced_fields(self):
        self.assertEqual(
            {f.source for f in DEVICE_FIELDS}, DEVICE_TYPE_FIELDS['synced']
        )


class DeviceCreationTestCase(SyncTestMixin, TestCase):
    """
    The plugin relies on NetBox copying these fields only when a device is
    created, and never when its device type changes.
    """

    def test_fields_are_copied_only_on_creation(self):
        platform_1 = Platform.objects.create(name='Platform 1', slug='platform-1')
        platform_2 = Platform.objects.create(name='Platform 2', slug='platform-2')
        type_1 = self.create_device_type(
            'Type 1',
            default_platform=platform_1,
            airflow=DeviceAirflowChoices.AIRFLOW_FRONT_TO_REAR,
            cooling_method=CoolingMethodChoices.METHOD_AIR,
        )
        type_2 = self.create_device_type(
            'Type 2',
            default_platform=platform_2,
            airflow=DeviceAirflowChoices.AIRFLOW_REAR_TO_FRONT,
            cooling_method=CoolingMethodChoices.METHOD_LIQUID,
        )

        device = self.create_device(type_1)
        self.assertEqual(device.platform, platform_1)
        self.assertEqual(device.airflow, DeviceAirflowChoices.AIRFLOW_FRONT_TO_REAR)
        self.assertEqual(device.cooling_method, CoolingMethodChoices.METHOD_AIR)

        device = self.change_device_type(device, type_2)
        self.assertEqual(device.platform, platform_1)
        self.assertEqual(device.airflow, DeviceAirflowChoices.AIRFLOW_FRONT_TO_REAR)
        self.assertEqual(device.cooling_method, CoolingMethodChoices.METHOD_AIR)
