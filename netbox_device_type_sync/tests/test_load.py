from django.apps import apps
from django.test import SimpleTestCase

from netbox_device_type_sync import __version__


class VersionTestCase(SimpleTestCase):
    def test_version(self):
        assert __version__ == '1.0.2'


class PluginLoadTestCase(SimpleTestCase):
    def test_plugin_is_installed(self):
        config = apps.get_app_config('netbox_device_type_sync')
        self.assertEqual(config.version, __version__)
