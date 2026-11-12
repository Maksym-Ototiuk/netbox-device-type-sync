from django.test import TestCase

from dcim.choices import (
    DeviceAirflowChoices,
    InterfacePoEModeChoices,
    InterfaceTypeChoices,
    PortTypeChoices,
    PowerPortTypeChoices,
)
from dcim.models import (
    ConsolePortTemplate,
    CoolingIntakeTemplate,
    FrontPortTemplate,
    InterfaceTemplate,
    InventoryItem,
    InventoryItemTemplate,
    Module,
    ModuleBayTemplate,
    ModuleBayType,
    ModuleType,
    Platform,
    PortTemplateMapping,
    PowerOutletTemplate,
    PowerPortTemplate,
    RearPortTemplate,
    VirtualChassis,
)
from netbox.choices import DiameterUnitChoices

from netbox_device_type_sync.diff import build_plan
from netbox_device_type_sync.tests.utils import SyncTestMixin


def kind_diff(plan, key):
    return next(k for k in plan.kinds if k.kind.key == key)


class DiffTestCase(SyncTestMixin, TestCase):
    def test_new_device_is_in_sync(self):
        device_type = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='1000base-t'
        )
        ConsolePortTemplate.objects.create(
            device_type=device_type, name='con0', type='rj-45'
        )
        device = self.create_device(device_type)

        plan = build_plan(device)

        self.assertTrue(plan.is_empty)
        self.assertEqual(plan.selection_keys, [])

    def test_replaced_device_type(self):
        type_1 = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=type_1, name='eth0', type='1000base-t'
        )
        InterfaceTemplate.objects.create(
            device_type=type_1, name='eth1', type='1000base-t'
        )
        type_2 = self.create_device_type('Type 2')
        InterfaceTemplate.objects.create(
            device_type=type_2,
            name='eth0',
            type=InterfaceTypeChoices.TYPE_10GE_SFP_PLUS,
            poe_mode=InterfacePoEModeChoices.MODE_PSE,
        )
        InterfaceTemplate.objects.create(
            device_type=type_2, name='eth2', type='1000base-t'
        )
        device = self.change_device_type(self.create_device(type_1), type_2)

        plan = build_plan(device)
        interfaces = kind_diff(plan, 'interface')

        self.assertEqual([c.name for c in interfaces.create], ['eth2'])
        self.assertEqual(len(interfaces.update), 1)
        update = interfaces.update[0]
        self.assertEqual(update.name, 'eth0')
        self.assertEqual(set(update.changes), {'type', 'poe_mode'})
        self.assertEqual(update.changes['type'].current, '1000BASE-T (1GE)')
        self.assertEqual(update.changes['type'].desired, 'SFP+ (10GE)')
        self.assertEqual(update.changes['poe_mode'].current, '—')
        self.assertEqual(update.changes['poe_mode'].desired, 'PSE')
        # eth1 exists only on the device: ignored
        self.assertNotIn('eth1', [c.name for c in interfaces.update])
        self.assertEqual(
            [s.selection_key for s in interfaces.property_summaries],
            ['interface.type', 'interface.poe_mode'],
        )
        self.assertEqual(plan.create_count, 1)

    def test_description_is_not_compared(self):
        # NetBox does not copy the description to a new device, so the plugin
        # does not sync it either
        device_type = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=device_type,
            name='eth0',
            type='1000base-t',
            description='Uplink',
        )
        device = self.create_device(device_type)
        self.assertEqual(device.interfaces.get(name='eth0').description, '')

        plan = build_plan(device)
        interfaces = kind_diff(plan, 'interface')

        self.assertEqual(interfaces.update, [])
        self.assertEqual(plan.selection_keys, [])

    def test_virtual_chassis_position_is_resolved(self):
        device_type = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=device_type,
            name='Gi{vc_position}/0/1',
            label='Port {vc_position}/1',
            type='1000base-t',
        )
        vc = VirtualChassis.objects.create(name='VC 1')
        device = self.create_device(device_type, virtual_chassis=vc, vc_position=2)
        self.assertTrue(device.interfaces.filter(name='Gi2/0/1').exists())
        InterfaceTemplate.objects.create(
            device_type=device_type, name='Gi{vc_position}/0/2', type='1000base-t'
        )

        plan = build_plan(device)
        interfaces = kind_diff(plan, 'interface')

        self.assertEqual([c.name for c in interfaces.create], ['Gi2/0/2'])
        self.assertEqual(interfaces.update, [])

    def test_module_components_are_ignored(self):
        device_type = self.create_device_type('Type 1')
        ModuleBayTemplate.objects.create(device_type=device_type, name='Bay 1')
        module_type = ModuleType.objects.create(
            manufacturer=self.manufacturer, model='Module 1'
        )
        InterfaceTemplate.objects.create(
            module_type=module_type, name='mod0', type='1000base-t'
        )
        device = self.create_device(device_type)
        Module.objects.create(
            device=device,
            module_bay=device.modulebays.get(name='Bay 1'),
            module_type=module_type,
        )
        InterfaceTemplate.objects.create(
            device_type=device_type,
            name='mod0',
            type=InterfaceTypeChoices.TYPE_10GE_SFP_PLUS,
        )

        interfaces = kind_diff(build_plan(device), 'interface')

        self.assertEqual(interfaces.create, [])
        self.assertEqual(interfaces.update, [])
        self.assertEqual([c.name for c in interfaces.conflicts], ['mod0'])

    def test_relations_are_compared_by_name(self):
        device_type = self.create_device_type('Type 1')
        lag = InterfaceTemplate.objects.create(
            device_type=device_type, name='lag0', type='lag'
        )
        eth0 = InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='virtual'
        )
        pp1 = PowerPortTemplate.objects.create(device_type=device_type, name='PSU1')
        PowerPortTemplate.objects.create(device_type=device_type, name='PSU2')
        outlet = PowerOutletTemplate.objects.create(
            device_type=device_type, name='Out1', power_port=pp1
        )
        device = self.create_device(device_type)
        eth0.parent = lag
        eth0.save()
        outlet.power_port = device_type.powerporttemplates.get(name='PSU2')
        outlet.save()

        plan = build_plan(device)
        interface = kind_diff(plan, 'interface').update[0]
        outlet_diff = kind_diff(plan, 'poweroutlet').update[0]

        self.assertEqual(interface.changes['parent'].current, '—')
        self.assertEqual(interface.changes['parent'].desired, 'lag0')
        self.assertEqual(outlet_diff.changes['power_port'].current, 'PSU1')
        self.assertEqual(outlet_diff.changes['power_port'].desired, 'PSU2')

    def test_port_mappings(self):
        device_type = self.create_device_type('Type 1')
        rear = RearPortTemplate.objects.create(
            device_type=device_type,
            name='Rear',
            type=PortTypeChoices.TYPE_LC,
            positions=2,
        )
        front_1 = FrontPortTemplate.objects.create(
            device_type=device_type, name='Front1', type=PortTypeChoices.TYPE_LC
        )
        mapping = PortTemplateMapping.objects.create(
            front_port=front_1,
            rear_port=rear,
            front_port_position=1,
            rear_port_position=1,
        )
        device = self.create_device(device_type)
        self.assertTrue(build_plan(device).is_empty)
        mapping.rear_port_position = 2
        mapping.save()

        front = kind_diff(build_plan(device), 'frontport').update[0]

        self.assertEqual(front.changes['mappings'].current, '1 → Rear:1')
        self.assertEqual(front.changes['mappings'].desired, '1 → Rear:2')

    def test_inventory_items_are_matched_by_path(self):
        # NetBox 4.7.4 cannot create a device from nested inventory item templates
        # (Device._instantiate_components() instantiates all templates before it
        # saves any), so the device items are created by hand.
        device_type = self.create_device_type('Type 1')
        device = self.create_device(device_type)
        item = InventoryItem.objects.create(device=device, name='Chassis')
        InventoryItem.objects.create(
            device=device, name='Fan', parent=item, part_id='FAN-1'
        )
        InventoryItem.objects.create(device=device, name='Fan', part_id='FAN-1')
        chassis = InventoryItemTemplate.objects.create(
            device_type=device_type, name='Chassis'
        )
        fan = InventoryItemTemplate.objects.create(
            device_type=device_type, name='Fan', parent=chassis, part_id='FAN-1'
        )
        self.assertTrue(build_plan(device).is_empty)
        fan.part_id = 'FAN-2'
        fan.save()
        InventoryItemTemplate.objects.create(
            device_type=device_type, name='PSU', parent=chassis
        )

        items = kind_diff(build_plan(device), 'inventoryitem')

        self.assertEqual(items.update[0].name, 'Chassis / Fan')
        self.assertEqual(items.update[0].changes['part_id'].desired, 'FAN-2')
        self.assertEqual([c.name for c in items.create], ['Chassis / PSU'])

    def test_module_bay_types(self):
        device_type = self.create_device_type('Type 1')
        bay = ModuleBayTemplate.objects.create(device_type=device_type, name='Bay 1')
        device = self.create_device(device_type)
        bay.module_bay_types.add(ModuleBayType.objects.create(name='SFP', slug='sfp'))

        bays = kind_diff(build_plan(device), 'modulebay')

        self.assertEqual(bays.update[0].changes['module_bay_types'].current, '—')
        self.assertEqual(bays.update[0].changes['module_bay_types'].desired, 'SFP')

    def test_values_with_units(self):
        device_type = self.create_device_type('Type 1')
        intake = CoolingIntakeTemplate.objects.create(
            device_type=device_type, name='In1'
        )
        device = self.create_device(device_type)
        intake.diameter = 25
        intake.diameter_unit = DiameterUnitChoices.UNIT_MILLIMETER
        intake.save()

        change = (
            kind_diff(build_plan(device), 'coolingintake').update[0].changes['diameter']
        )

        self.assertEqual(change.current, '—')
        self.assertEqual(change.desired, '25.00 Millimeters')

    def test_power_port_values(self):
        device_type = self.create_device_type('Type 1')
        PowerPortTemplate.objects.create(
            device_type=device_type, name='PSU1', type=PowerPortTypeChoices.TYPE_IEC_C14
        )
        device = self.create_device(device_type)
        device_type.powerporttemplates.update(maximum_draw=350)

        changes = kind_diff(build_plan(device), 'powerport').update[0].changes

        self.assertEqual(set(changes), {'maximum_draw'})
        self.assertEqual(changes['maximum_draw'].desired, '350')


class DeviceFieldDiffTestCase(SyncTestMixin, TestCase):
    def test_device_fields(self):
        platform = Platform.objects.create(name='Platform 1', slug='platform-1')
        type_1 = self.create_device_type('Type 1')
        type_2 = self.create_device_type(
            'Type 2',
            default_platform=platform,
            airflow=DeviceAirflowChoices.AIRFLOW_FRONT_TO_REAR,
        )
        device = self.change_device_type(self.create_device(type_1), type_2)

        plan = build_plan(device)

        self.assertEqual(plan.selection_keys, ['device.platform', 'device.airflow'])
        platform_diff, airflow_diff = plan.device_fields
        self.assertEqual(platform_diff.current, '—')
        self.assertEqual(platform_diff.desired, 'Platform 1')
        self.assertEqual(airflow_diff.desired, 'Front to rear')

    def test_empty_device_type_values_are_not_offered(self):
        platform = Platform.objects.create(name='Platform 1', slug='platform-1')
        type_1 = self.create_device_type(
            'Type 1',
            default_platform=platform,
            airflow=DeviceAirflowChoices.AIRFLOW_FRONT_TO_REAR,
        )
        type_2 = self.create_device_type('Type 2')
        device = self.change_device_type(self.create_device(type_1), type_2)

        self.assertEqual(build_plan(device).device_fields, [])
