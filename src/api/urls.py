from django.urls import path, include
from . import views

urlpatterns = [
    # Health check endpoint
    path('health/', views.health_check, name='health_check'),
    
    # Feature module endpoints
    path('customers/', include('customer.urls')),
    path('services/', include('service_catalog.urls')),
    path('calendar/', include('calendar_mgmt.urls')),
    path('ai/', include('ai_assistant.urls')),
] 