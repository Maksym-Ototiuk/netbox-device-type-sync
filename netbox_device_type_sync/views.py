from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from core.signals import clear_events
from dcim.models import Device
from netbox.views import generic
from utilities.permissions import get_permission_for_model

from .apply import SyncError, apply_plan, describe_kind_counts
from .diff import build_plan
from .forms import DeviceSyncForm

__all__ = ('DeviceSyncView',)


class DeviceSyncView(generic.ObjectView):
    """
    Show the differences between a device and its device type, and apply the
    properties the user selects.
    """

    queryset = Device.objects.all()
    template_name = 'netbox_device_type_sync/device_sync.html'
    actions = ()

    def get_required_permission(self):
        return get_permission_for_model(Device, 'change')

    def get(self, request, pk):
        device = self.get_object(pk=pk)
        plan = build_plan(device)
        return self.render(request, plan, DeviceSyncForm(plan=plan))

    def post(self, request, pk):
        device = self.get_object(pk=pk)
        plan = build_plan(device)
        form = DeviceSyncForm(request.POST, plan=plan)
        errors = []
        if form.is_valid():
            try:
                result = apply_plan(
                    plan,
                    form.selected_keys(),
                    user=request.user,
                    changelog_message=_('Synced with device type {device_type}').format(
                        device_type=plan.device_type
                    ),
                )
            except SyncError as e:
                clear_events.send(sender=self)
                errors = e.errors
            else:
                self.report(request, plan, result)
                return redirect(device.get_absolute_url())
        return self.render(request, plan, form, errors)

    @staticmethod
    def report(request, plan, result):
        parts = []
        if result.created_count:
            parts.append(
                _('created {items}').format(items=describe_kind_counts(result.created))
            )
        if result.updated_count:
            parts.append(
                _('updated {items}').format(items=describe_kind_counts(result.updated))
            )
        if result.device_fields:
            parts.append(
                _('updated device fields: {fields}').format(
                    fields=', '.join(result.device_fields)
                )
            )
        if not parts:
            messages.info(request, _('No changes were made.'))
            return
        messages.success(
            request,
            _('Synced {device} with device type {device_type}: {changes}.').format(
                device=plan.device,
                device_type=plan.device_type,
                changes='; '.join(parts),
            ),
        )

    def render(self, request, plan, form, errors=()):
        kinds = [
            {
                'diff': kind_diff,
                'summaries': [
                    (s, form[s.selection_key]) for s in kind_diff.property_summaries
                ],
            }
            for kind_diff in plan.changed_kinds
        ]
        return render(
            request,
            self.get_template_name(),
            {
                'object': plan.device,
                'plan': plan,
                'form': form,
                'errors': errors,
                'device_rows': [(d, form[d.selection_key]) for d in plan.device_fields],
                'kinds': kinds,
                'return_url': plan.device.get_absolute_url(),
            },
        )
