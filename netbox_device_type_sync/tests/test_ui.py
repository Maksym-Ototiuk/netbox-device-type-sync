"""
Tests of the Sync button on the Device page. The button relies on NetBox
internals (see CLAUDE.md); these tests must pass for every supported NetBox
version.
"""

import re
from unittest import mock

from django.test import SimpleTestCase
from django.urls import reverse

from core.models import ObjectType
from dcim.models import Device
from dcim.ui.panels import DeviceDeviceTypePanel
from dcim.views import DeviceView
from netbox.ui import layout
from users.models import ObjectPermission
from utilities.testing import TestCase

from netbox_device_type_sync.tests.utils import SyncTestMixin
from netbox_device_type_sync.ui import SyncDeviceAction, add_sync_button


def device_type_panels():
    return [
        panel
        for row in DeviceView.layout
        for column in row
        for panel in column
        if isinstance(panel, DeviceDeviceTypePanel)
    ]


class AddSyncButtonTestCase(SimpleTestCase):
    def test_button_is_added_on_startup(self):
        panels = device_type_panels()

        self.assertEqual(len(panels), 1)
        actions = [a for a in panels[0].actions if isinstance(a, SyncDeviceAction)]
        self.assertEqual(len(actions), 1)

    def test_adding_twice_adds_one_button(self):
        self.assertTrue(add_sync_button())

        actions = device_type_panels()[0].actions
        self.assertEqual(
            len([a for a in actions if isinstance(a, SyncDeviceAction)]), 1
        )

    def test_missing_panel_logs_a_warning(self):
        other_layout = layout.SimpleLayout(left_panels=[], right_panels=[])
        with mock.patch.object(DeviceView, 'layout', other_layout):
            with self.assertLogs(
                'netbox.plugins.netbox_device_type_sync', 'WARNING'
            ) as logs:
                self.assertFalse(add_sync_button())

        self.assertIn('Sync button was not added', logs.output[0])

    def test_changed_netbox_internals_log_a_warning(self):
        with mock.patch('dcim.views.DeviceView.layout', None):
            with self.assertLogs('netbox.plugins.netbox_device_type_sync', 'WARNING'):
                self.assertFalse(add_sync_button())


class SyncButtonViewTestCase(SyncTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.device = self.create_device(self.create_device_type('Type 1'))
        self.sync_url = reverse(
            'plugins:netbox_device_type_sync:device_sync', kwargs={'pk': self.device.pk}
        )

    def device_type_card(self):
        response = self.client.get(self.device.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        match = re.search(
            r'<!-- begin DeviceDeviceTypePanel -->(.*?)<!-- end DeviceDeviceTypePanel -->',
            response.content.decode(),
            re.DOTALL,
        )
        self.assertIsNotNone(
            match, 'The Device Type card is missing on the Device page'
        )
        return match.group(1)

    def test_button_in_device_type_card(self):
        self.add_permissions('dcim.view_device', 'dcim.change_device')

        card = self.device_type_card()

        self.assertIn(f'href="{self.sync_url}"', card)
        self.assertIn('mdi-sync', card)

    def test_button_hidden_without_change_permission(self):
        self.add_permissions('dcim.view_device')

        self.assertNotIn(self.sync_url, self.device_type_card())

    def test_button_hidden_by_object_constraints(self):
        self.add_permissions('dcim.view_device')
        permission = ObjectPermission.objects.create(
            name='Change other devices',
            actions=['change'],
            constraints={'name': 'Other'},
        )
        permission.users.add(self.user)
        permission.object_types.add(ObjectType.objects.get_for_model(Device))

        self.assertNotIn(self.sync_url, self.device_type_card())
