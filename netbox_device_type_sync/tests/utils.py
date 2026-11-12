from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Site


class SyncTestMixin:
    """
    Objects shared by the tests: a site, a manufacturer and a device role.
    """

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name='Site 1', slug='site-1')
        cls.manufacturer = Manufacturer.objects.create(
            name='Manufacturer 1', slug='manufacturer-1'
        )
        cls.role = DeviceRole.objects.create(name='Role 1', slug='role-1')

    @classmethod
    def create_device_type(cls, model, **kwargs):
        return DeviceType.objects.create(
            manufacturer=cls.manufacturer,
            model=model,
            slug=model.lower().replace(' ', '-'),
            **kwargs,
        )

    @classmethod
    def create_device(cls, device_type, name='Device 1', **kwargs):
        return Device.objects.create(
            device_type=device_type,
            role=cls.role,
            site=cls.site,
            name=name,
            **kwargs,
        )

    @staticmethod
    def change_device_type(device, device_type):
        device.device_type = device_type
        device.full_clean()
        device.save()
        return Device.objects.get(pk=device.pk)
