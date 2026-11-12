from django.urls import path

from . import views

urlpatterns = (
    path('devices/<int:pk>/sync/', views.DeviceSyncView.as_view(), name='device_sync'),
)
