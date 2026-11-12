from django.test import TestCase
from ipam.models import VLAN, IPAddress

from dcim.choices import (
    DeviceAirflowChoices,
    InterfaceModeChoices,
    InterfaceTypeChoices,
    PortTypeChoices,
)
from dcim.models import (
    Cable,
    FrontPortTemplate,
    Interface,
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
)
from utilities.testing import TestCase as NetBoxTestCase

from netbox_device_type_sync.apply import SyncError, apply_plan
from netbox_device_type_sync.diff import build_plan
from netbox_device_type_sync.tests.utils import SyncTestMixin


def sync(device, selected=(), user=None):
    return apply_plan(build_plan(device), selected, user=user)


class ApplyTestCase(SyncTestMixin, TestCase):
    def setUp(self):
        self.type_1 = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=self.type_1, name='eth0', type='1000base-t'
        )
        InterfaceTemplate.objects.create(
            device_type=self.type_1, name='eth1', type='1000base-t'
        )
        self.type_2 = self.create_device_type('Type 2')
        InterfaceTemplate.objects.create(
            device_type=self.type_2,
            name='eth0',
            type=InterfaceTypeChoices.TYPE_10GE_SFP_PLUS,
            description='Uplink',
        )
        InterfaceTemplate.objects.create(
            device_type=self.type_2, name='eth2', type='1000base-t'
        )

    def test_replacement_keeps_cables_ip_addresses_and_vlans(self):
        device = self.create_device(self.type_1)
        peer = self.create_device(self.type_1, name='Peer')
        eth0 = device.interfaces.get(name='eth0')
        Cable(
            a_terminations=[eth0], b_terminations=[peer.interfaces.get(name='eth0')]
        ).save()
        ip = IPAddress.objects.create(address='192.0.2.1/24', assigned_object=eth0)
        vlan = VLAN.objects.create(vid=10, name='VLAN 10')
        eth0.refresh_from_db()
        eth0.mode = InterfaceModeChoices.MODE_ACCESS
        eth0.untagged_vlan = vlan
        eth0.save()
        device = self.change_device_type(device, self.type_2)

        result = sync(device, selected=['interface.type'])

        eth0 = device.interfaces.get(name='eth0')
        self.assertEqual(eth0.type, InterfaceTypeChoices.TYPE_10GE_SFP_PLUS)
        self.assertEqual(eth0.description, '')  # not selected
        self.assertIsNotNone(eth0.cable)
        self.assertEqual(eth0.untagged_vlan, vlan)
        self.assertEqual(eth0.mode, InterfaceModeChoices.MODE_ACCESS)
        ip.refresh_from_db()
        self.assertEqual(ip.assigned_object, eth0)
        # eth1 exists only on the device: kept as it is
        self.assertEqual(device.interfaces.get(name='eth1').type, '1000base-t')
        # eth2 is created without a description, like NetBox does
        self.assertTrue(device.interfaces.filter(name='eth2').exists())
        self.assertEqual(result.created['interface'], 1)
        self.assertEqual(result.updated['interface'], 1)
        self.assertEqual(build_plan(device).create_count, 0)

    def test_unselected_properties_are_kept(self):
        device = self.change_device_type(self.create_device(self.type_1), self.type_2)

        sync(device, selected=[])

        self.assertEqual(device.interfaces.get(name='eth0').type, '1000base-t')
        self.assertTrue(device.interfaces.filter(name='eth2').exists())

    def test_selected_description(self):
        device = self.change_device_type(self.create_device(self.type_1), self.type_2)

        sync(device, selected=['interface.description'])

        eth0 = device.interfaces.get(name='eth0')
        self.assertEqual(eth0.description, 'Uplink')
        self.assertEqual(eth0.type, '1000base-t')

    def test_validation_error_rolls_back_everything(self):
        device = self.create_device(self.type_1)
        peer = self.create_device(self.type_1, name='Peer')
        Cable(
            a_terminations=[device.interfaces.get(name='eth0')],
            b_terminations=[peer.interfaces.get(name='eth0')],
        ).save()
        self.type_2.interfacetemplates.filter(name='eth0').update(type='virtual')
        device = self.change_device_type(device, self.type_2)

        with self.assertRaises(SyncError) as cm:
            sync(device, selected=['interface.type', 'interface.description'])

        self.assertEqual(len(cm.exception.errors), 1)
        self.assertIn('Interface eth0', cm.exception.errors[0])
        self.assertIn('cable', cm.exception.errors[0])
        # Nothing was changed: eth2 was not created, eth0 kept its values
        self.assertFalse(device.interfaces.filter(name='eth2').exists())
        self.assertEqual(device.interfaces.get(name='eth0').description, '')

    def test_device_fields(self):
        platform = Platform.objects.create(name='Platform 1', slug='platform-1')
        self.type_2.default_platform = platform
        self.type_2.airflow = DeviceAirflowChoices.AIRFLOW_FRONT_TO_REAR
        self.type_2.save()
        device = self.change_device_type(self.create_device(self.type_1), self.type_2)

        result = sync(device, selected=['device.platform'])

        device.refresh_from_db()
        self.assertEqual(device.platform, platform)
        self.assertIsNone(device.airflow)  # not selected
        self.assertEqual(result.device_fields, ['Platform'])

    def test_unknown_selection_keys_are_ignored(self):
        device = self.change_device_type(self.create_device(self.type_1), self.type_2)

        sync(device, selected=['interface.name', 'device.serial', 'nothing'])

        self.assertEqual(device.interfaces.get(name='eth0').type, '1000base-t')

    def test_module_conflicts_are_skipped(self):
        bay = ModuleBayTemplate.objects.create(device_type=self.type_1, name='Bay 1')
        module_type = ModuleType.objects.create(
            manufacturer=self.manufacturer, model='Module 1'
        )
        InterfaceTemplate.objects.create(
            module_type=module_type, name='eth2', type='1000base-t'
        )
        device = self.create_device(self.type_1)
        Module.objects.create(
            device=device,
            module_bay=device.modulebays.get(name=bay.name),
            module_type=module_type,
        )
        device = self.change_device_type(device, self.type_2)

        result = sync(device)

        self.assertEqual(result.created_count, 0)
        self.assertIsNotNone(device.interfaces.get(name='eth2').module)


class ApplyRelationsTestCase(SyncTestMixin, TestCase):
    def test_new_interfaces_get_parent_and_bridge(self):
        device_type = self.create_device_type('Type 1')
        eth0 = InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='1000base-t'
        )
        device = self.create_device(device_type)
        bridge = InterfaceTemplate.objects.create(
            device_type=device_type, name='br0', type='bridge'
        )
        InterfaceTemplate.objects.create(
            device_type=device_type,
            name='eth0.10',
            type='virtual',
            parent=eth0,
            bridge=bridge,
        )

        sync(device)

        child = device.interfaces.get(name='eth0.10')
        self.assertEqual(child.parent.name, 'eth0')
        self.assertEqual(child.bridge.name, 'br0')

    def test_existing_interface_gets_new_parent(self):
        device_type = self.create_device_type('Type 1')
        sub = InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0.10', type='virtual'
        )
        device = self.create_device(device_type)
        sub.parent = InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='1000base-t'
        )
        sub.save()

        sync(device, selected=['interface.parent'])

        self.assertEqual(device.interfaces.get(name='eth0.10').parent.name, 'eth0')

    def test_channelized_interface(self):
        device_type = self.create_device_type('Type 1')
        parent = InterfaceTemplate.objects.create(
            device_type=device_type,
            name='eth0',
            type=InterfaceTypeChoices.TYPE_100GE_QSFP28,
        )
        device = self.create_device(device_type)
        parent.channels = 4
        parent.save()
        InterfaceTemplate.objects.create(
            device_type=device_type,
            name='eth0:1',
            type=InterfaceTypeChoices.TYPE_CHANNEL,
            parent=parent,
            channel_id=1,
        )

        sync(device, selected=['interface.channels'])

        self.assertEqual(device.interfaces.get(name='eth0').channels, 4)
        child = device.interfaces.get(name='eth0:1')
        self.assertEqual(child.channel_id, 1)
        self.assertEqual(child.parent.name, 'eth0')

    def test_power_outlet_refers_to_new_power_port(self):
        device_type = self.create_device_type('Type 1')
        device = self.create_device(device_type)
        power_port = PowerPortTemplate.objects.create(
            device_type=device_type, name='PSU1'
        )
        PowerOutletTemplate.objects.create(
            device_type=device_type, name='Out1', power_port=power_port
        )

        sync(device)

        self.assertEqual(device.poweroutlets.get(name='Out1').power_port.name, 'PSU1')

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
        # Re-point Front1 to position 2, and add Front2 on position 1
        mapping.rear_port_position = 2
        mapping.save()
        front_2 = FrontPortTemplate.objects.create(
            device_type=device_type, name='Front2', type=PortTypeChoices.TYPE_LC
        )
        PortTemplateMapping.objects.create(
            front_port=front_2,
            rear_port=rear,
            front_port_position=1,
            rear_port_position=1,
        )

        sync(device, selected=['frontport.mappings'])

        mappings = {
            (
                m.front_port.name,
                m.front_port_position,
                m.rear_port.name,
                m.rear_port_position,
            )
            for m in device.port_mappings.all()
        }
        self.assertEqual(mappings, {('Front1', 1, 'Rear', 2), ('Front2', 1, 'Rear', 1)})
        self.assertTrue(build_plan(device).is_empty)

    def test_rear_port_positions_reduced_with_mappings(self):
        device_type = self.create_device_type('Type 1')
        rear = RearPortTemplate.objects.create(
            device_type=device_type,
            name='Rear',
            type=PortTypeChoices.TYPE_LC,
            positions=2,
        )
        fronts = [
            FrontPortTemplate.objects.create(
                device_type=device_type, name=f'Front{i}', type=PortTypeChoices.TYPE_LC
            )
            for i in (1, 2)
        ]
        mappings = [
            PortTemplateMapping.objects.create(
                front_port=front,
                rear_port=rear,
                front_port_position=1,
                rear_port_position=i,
            )
            for i, front in enumerate(fronts, start=1)
        ]
        device = self.create_device(device_type)
        mappings[1].delete()
        rear.positions = 1
        rear.save()

        sync(device, selected=['rearport.positions', 'frontport.mappings'])

        self.assertEqual(device.rearports.get(name='Rear').positions, 1)
        self.assertEqual(device.port_mappings.count(), 1)

    def test_inventory_items_are_created_parents_first(self):
        device_type = self.create_device_type('Type 1')
        device = self.create_device(device_type)
        eth0 = InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='1000base-t'
        )
        chassis = InventoryItemTemplate.objects.create(
            device_type=device_type, name='Chassis'
        )
        InventoryItemTemplate.objects.create(
            device_type=device_type,
            name='SFP',
            parent=chassis,
            component=eth0,
            part_id='SFP-1',
        )

        sync(device)

        sfp = device.inventoryitems.get(name='SFP')
        self.assertEqual(sfp.parent.name, 'Chassis')
        self.assertEqual(sfp.component, device.interfaces.get(name='eth0'))
        self.assertEqual(sfp.part_id, 'SFP-1')

    def test_inventory_item_fields_match_netbox(self):
        # The plugin builds inventory items itself; compare with instantiate()
        device_type = self.create_device_type('Type 1')
        device = self.create_device(device_type)
        template = InventoryItemTemplate.objects.create(
            device_type=device_type, name='PSU', label='Power', part_id='PWR-1'
        )
        expected = template.instantiate(device=device)

        sync(device)

        item = InventoryItem.objects.get(device=device, name='PSU')
        for field_name in (
            'name',
            'label',
            'parent_id',
            'component_type_id',
            'component_id',
            'role_id',
            'manufacturer_id',
            'part_id',
            'description',
        ):
            with self.subTest(field=field_name):
                self.assertEqual(
                    getattr(item, field_name), getattr(expected, field_name)
                )

    def test_module_bay_types(self):
        device_type = self.create_device_type('Type 1')
        bay_1 = ModuleBayTemplate.objects.create(device_type=device_type, name='Bay 1')
        device = self.create_device(device_type)
        sfp = ModuleBayType.objects.create(name='SFP', slug='sfp')
        bay_1.module_bay_types.add(sfp)
        bay_2 = ModuleBayTemplate.objects.create(device_type=device_type, name='Bay 2')
        bay_2.module_bay_types.add(sfp)

        sync(device, selected=['modulebay.module_bay_types'])

        for name in ('Bay 1', 'Bay 2'):
            with self.subTest(bay=name):
                bay = device.modulebays.get(name=name)
                self.assertEqual(list(bay.module_bay_types.all()), [sfp])


class ApplyPermissionsTestCase(SyncTestMixin, NetBoxTestCase):
    def test_missing_add_permission_rolls_back(self):
        device_type = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='1000base-t'
        )
        device = self.create_device(device_type)
        device_type.interfacetemplates.update(description='Uplink')
        InterfaceTemplate.objects.create(
            device_type=device_type, name='eth1', type='1000base-t'
        )
        self.add_permissions('dcim.change_interface')

        with self.assertRaises(SyncError) as cm:
            sync(device, selected=['interface.description'], user=self.user)

        self.assertIn('Interface eth1', cm.exception.errors[0])
        self.assertIn('permission', cm.exception.errors[0])
        self.assertEqual(device.interfaces.get(name='eth0').description, '')

    def test_with_permissions(self):
        device_type = self.create_device_type('Type 1')
        device = self.create_device(device_type)
        InterfaceTemplate.objects.create(
            device_type=device_type, name='eth0', type='1000base-t'
        )
        self.add_permissions('dcim.add_interface')

        result = sync(device, user=self.user)

        self.assertEqual(result.created['interface'], 1)
        self.assertTrue(Interface.objects.filter(device=device, name='eth0').exists())
