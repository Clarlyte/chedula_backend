from django.urls import path
from . import views

app_name = 'service_catalog'

urlpatterns = [
    # Service Category URLs
    path('categories/', views.ServiceCategoryListCreateView.as_view(), name='category-list-create'),
    path('categories/<uuid:pk>/', views.ServiceCategoryDetailView.as_view(), name='category-detail'),
    
    # Service URLs
    path('services/', views.ServiceListCreateView.as_view(), name='service-list-create'),
    path('services/<uuid:pk>/', views.ServiceDetailView.as_view(), name='service-detail'),
    path('services/search/', views.service_search, name='service-search'),
    
    # Package URLs
    path('packages/', views.PackageListCreateView.as_view(), name='package-list-create'),
    
    # Availability and Pricing URLs
    path('availability/check/', views.check_service_availability, name='check-availability'),
    path('pricing/calculate/', views.calculate_service_price, name='calculate-price'),
] 