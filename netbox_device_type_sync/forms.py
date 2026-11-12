from django import forms

__all__ = ('DeviceSyncForm',)


def field_name(selection_key):
    """
    Return the form field name of a selection key ("interface.type" -> "interface__type").
    """
    return selection_key.replace('.', '__')


class DeviceSyncForm(forms.Form):
    """
    One unchecked checkbox for every property that differs between a device and
    its device type.
    """

    def __init__(self, *args, plan, **kwargs):
        super().__init__(*args, **kwargs)
        self.selection_keys = plan.selection_keys
        for key in self.selection_keys:
            # NetBox renders BooleanField checkboxes with the form-check-input class
            self.fields[field_name(key)] = forms.BooleanField(
                required=False, initial=False
            )

    def __getitem__(self, name):
        # Accept selection keys as well as field names
        return super().__getitem__(field_name(name))

    def selected_keys(self):
        return [
            key for key in self.selection_keys if self.cleaned_data.get(field_name(key))
        ]
