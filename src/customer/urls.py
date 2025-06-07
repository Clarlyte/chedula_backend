from django.urls import path
from . import views

app_name = 'customer'

urlpatterns = [
    # Customer CRUD URLs
    path('', views.CustomerListCreateView.as_view(), name='customer-list-create'),
    path('<uuid:pk>/', views.CustomerDetailView.as_view(), name='customer-detail'),
    path('search/', views.customer_search, name='customer-search'),
    path('stats/', views.customer_stats, name='customer-stats'),
    
    # Customer Notes URLs
    path('<uuid:customer_id>/notes/', views.CustomerNotesListCreateView.as_view(), name='customer-notes-list-create'),
] 