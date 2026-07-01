from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import EventEnvironmentViewSet, EventRecordViewSet, EventSourceViewSet, ExternalEventIngestView

router = DefaultRouter()
router.register('events', EventRecordViewSet, basename='event-record')
router.register('event-sources', EventSourceViewSet, basename='event-source')
router.register('event-environments', EventEnvironmentViewSet, basename='event-environment')

urlpatterns = [
    path('event-sources/<slug:type>/ingest/', ExternalEventIngestView.as_view(), name='event-source-ingest'),
    path('', include(router.urls)),
]
