from django.urls import path, include
from . import views

app_name = 'calendar_mgmt'

urlpatterns = [
    # Service Categories (Sub-calendars)
    path('categories/', views.ServiceCategoryListCreateView.as_view(), name='category-list-create'),
    path('categories/<uuid:pk>/', views.ServiceCategoryDetailView.as_view(), name='category-detail'),
    
    # Services/Equipment
    path('services/', views.ServiceListCreateView.as_view(), name='service-list-create'),
    path('services/<uuid:pk>/', views.ServiceDetailView.as_view(), name='service-detail'),
    
    # Bookings
    path('bookings/', views.BookingListCreateView.as_view(), name='booking-list-create'),
    path('bookings/<uuid:pk>/', views.BookingDetailView.as_view(), name='booking-detail'),
    
    # Calendar Events (FullCalendar format)
    path('events/', views.CalendarEventsView.as_view(), name='calendar-events'),
    
    # Availability and Conflicts
    path('availability/check/', views.AvailabilityCheckView.as_view(), name='availability-check'),
    path('conflicts/detect/', views.ConflictDetectionView.as_view(), name='conflict-detect'),
    path('conflicts/', views.ConflictLogListView.as_view(), name='conflict-list'),
    path('conflicts/<uuid:conflict_id>/resolve/', views.resolve_conflict, name='conflict-resolve'),
    
    # Settings
    path('settings/', views.CalendarSettingsView.as_view(), name='calendar-settings'),
    
    # Dashboard
    path('dashboard/stats/', views.dashboard_stats, name='dashboard-stats'),
] 