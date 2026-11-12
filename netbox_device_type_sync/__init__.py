from netbox.plugins import PluginConfig

from .version import __version__


class NetBoxDeviceTypeSyncConfig(PluginConfig):
    name = 'netbox_device_type_sync'
    verbose_name = 'NetBox Device Type Sync'
    version = __version__
    description = 'Sync the components of a NetBox device with its device type.'
    author = 'Maksym Ototiuk'
    author_email = 'pypi@masik.slmail.me'
    base_url = 'device-type-sync'
    min_version = '4.7.4'

    def ready(self):
        super().ready()
        from .ui import add_sync_button

        add_sync_button()


config = NetBoxDeviceTypeSyncConfig
