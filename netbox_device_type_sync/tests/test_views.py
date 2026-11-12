import re

from django.urls import reverse

from core.choices import ObjectChangeActionChoices
from core.models import ObjectChange
from dcim.choices import InterfaceTypeChoices
from dcim.models import Cable, InterfaceTemplate
from utilities.testing import TestCase

from netbox_device_type_sync.tests.utils import SyncTestMixin


class DeviceSyncViewTestCase(SyncTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.type_1 = self.create_device_type('Type 1')
        InterfaceTemplate.objects.create(
            device_type=self.type_1, name='eth0', type='1000base-t'
        )
        self.type_2 = self.create_device_type('Type 2')
        InterfaceTemplate.objects.create(
            device_type=self.type_2,
            name='eth0',
            type=InterfaceTypeChoices.TYPE_10GE_SFP_PLUS,
        )
        InterfaceTemplate.objects.create(
            device_type=self.type_2, name='eth1', type='1000base-t'
        )
        self.device = self.change_device_type(
            self.create_device(self.type_1), self.type_2
        )
        self.url = reverse(
            'plugins:netbox_device_type_sync:device_sync', kwargs={'pk': self.device.pk}
        )

    def test_get_without_permission(self):
        self.add_permissions('dcim.view_device')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_get(self):
        self.add_permissions('dcim.change_device')

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('name="interface__type"', content)
        # All checkboxes are unchecked
        self.assertIsNone(re.search(r'<input type="checkbox"[^>]*\schecked', content))
        self.assertIn('SFP+ (10GE)', content)
        self.assertIn('eth1', content)
        self.assertIn('1 interface will be created', content)

    def test_get_in_sync(self):
        self.add_permissions('dcim.change_device')
        device = self.create_device(self.type_2, name='Device 2')
        url = reverse(
            'plugins:netbox_device_type_sync:device_sync', kwargs={'pk': device.pk}
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'The device is in sync with its device type', response.content.decode()
        )

    def test_post(self):
        self.add_permissions(
            'dcim.change_device', 'dcim.add_interface', 'dcim.change_interface'
        )

        response = self.client.post(self.url, {'interface__type': 'on'})

        self.assertRedirects(
            response, self.device.get_absolute_url(), fetch_redirect_response=False
        )
        self.assertEqual(
            self.device.interfaces.get(name='eth0').type,
            InterfaceTypeChoices.TYPE_10GE_SFP_PLUS,
        )
        self.assertTrue(self.device.interfaces.filter(name='eth1').exists())
        changes = ObjectChange.objects.filter(message='Synced with device type Type 2')
        self.assertEqual(
            sorted(changes.values_list('action', flat=True)),
            [
                ObjectChangeActionChoices.ACTION_CREATE,
                ObjectChangeActionChoices.ACTION_UPDATE,
            ],
        )

    def test_post_unchecked_keeps_values(self):
        self.add_permissions(
            'dcim.change_device', 'dcim.add_interface', 'dcim.change_interface'
        )

        self.client.post(self.url, {})

        self.assertEqual(self.device.interfaces.get(name='eth0').type, '1000base-t')
        self.assertTrue(self.device.interfaces.filter(name='eth1').exists())

    def test_post_with_errors(self):
        self.add_permissions(
            'dcim.change_device', 'dcim.add_interface', 'dcim.change_interface'
        )
        peer = self.create_device(self.type_1, name='Peer')
        Cable(
            a_terminations=[self.device.interfaces.get(name='eth0')],
            b_terminations=[peer.interfaces.get(name='eth0')],
        ).save()
        self.type_2.interfacetemplates.filter(name='eth0').update(type='virtual')

        response = self.client.post(self.url, {'interface__type': 'on'})

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Nothing was changed', content)
        self.assertIn('Interface eth0', content)
        self.assertFalse(self.device.interfaces.filter(name='eth1').exists())
