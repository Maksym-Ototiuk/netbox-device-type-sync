"""
The Sync button in the header of the Device Type card on the Device page.

NetBox has no plugin API to add an action to a built-in panel. When NetBox
starts, add_sync_button() finds the DeviceDeviceTypePanel instance in the
layout of dcim.views.DeviceView and appends a SyncDeviceAction to its actions.
These are undocumented NetBox internals: if the panel cannot be found, the
plugin logs a warning and adds no button.
"""

import logging

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from netbox.ui.actions import LinkAction

__all__ = (
    'SyncDeviceAction',
    'add_sync_button',
)

logger = logging.getLogger('netbox.plugins.netbox_device_type_sync')


class SyncDeviceAction(LinkAction):
    """
    A link to the sync page of the device shown by the panel.
    """

    def __init__(self):
        super().__init__(
            view_name='plugins:netbox_device_type_sync:device_sync',
            label=_('Sync'),
            button_icon='sync',
            permissions=['dcim.change_device'],
        )

    def get_url(self, context):
        return reverse(self.view_name, kwargs={'pk': context['object'].pk})

    def render(self, context):
        # Hide the button unless the user may change this particular device
        # (object permissions can be limited by constraints)
        from dcim.models import Device

        device = context.get('object')
        user = context['request'].user
        if device is None or not user.has_perms(self.permissions):
            return ''
        if not Device.objects.restrict(user, 'change').filter(pk=device.pk).exists():
            return ''
        return super().render(context)


def _find_panels(layout, panel_class):
    return [
        panel
        for row in layout
        for column in row
        for panel in column
        if isinstance(panel, panel_class)
    ]


def add_sync_button():
    """
    Add the Sync button to the Device Type card of the Device page. Return True
    if the button is present afterwards. Never raises: a NetBox version with a
    different Device page must not prevent NetBox from starting.
    """
    try:
        from dcim.ui.panels import DeviceDeviceTypePanel
        from dcim.views import DeviceView

        panels = _find_panels(DeviceView.layout, DeviceDeviceTypePanel)
    except Exception:
        logger.warning(
            'The Sync button was not added: the Device Type card of the Device page '
            'could not be found in this NetBox version.',
            exc_info=True,
        )
        return False

    if len(panels) != 1:
        logger.warning(
            'The Sync button was not added: expected one Device Type card on the Device '
            'page, found %d.',
            len(panels),
        )
        return False

    panel = panels[0]
    if not any(isinstance(action, SyncDeviceAction) for action in panel.actions):
        panel.actions.append(SyncDeviceAction())
    return True
