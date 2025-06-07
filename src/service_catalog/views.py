from django.shortcuts import render
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q
from users.authentication import SupabaseJWTAuthentication, require_authenticated_user
from .models import Service, ServiceCategory, Package, PackageItem
from .services import ServiceCatalogService
import logging

logger = logging.getLogger(__name__)


# Create your views here.

# Service Category Views
class ServiceCategoryListCreateView(generics.ListCreateAPIView):
    """List and create service categories."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = require_authenticated_user(self.request)
        return ServiceCategory.objects.filter(user_id=user.id, is_active=True).order_by('calendar_order', 'name')
    
    def perform_create(self, serializer):
        user = require_authenticated_user(self.request)
        serializer.save(user_id=user.id)
    
    def list(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            categories = ServiceCategory.objects.filter(user_id=user.id, is_active=True).order_by('calendar_order', 'name')
            
            categories_data = []
            for category in categories:
                categories_data.append({
                    'id': str(category.id),
                    'name': category.name,
                    'description': category.description,
                    'color': category.color,
                    'icon': category.icon,
                    'category_type': category.category_type,
                    'show_in_main_calendar': category.show_in_main_calendar,
                    'calendar_order': category.calendar_order,
                    'service_count': category.services.filter(is_active=True).count(),
                    'parent_category': str(category.parent_category.id) if category.parent_category else None,
                    'hierarchy_name': category.hierarchy_name,
                    'created_at': category.created_at.isoformat(),
                    'updated_at': category.updated_at.isoformat()
                })
            
            return Response({
                'categories': categories_data,
                'count': len(categories_data)
            })
            
        except Exception as e:
            logger.error(f"Error listing service categories: {e}")
            return Response(
                {'error': 'Failed to retrieve categories'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def create(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            
            category_data = {
                'name': request.data.get('name', ''),
                'description': request.data.get('description', ''),
                'color': request.data.get('color', '#3B82F6'),
                'icon': request.data.get('icon', ''),
                'category_type': request.data.get('category_type', 'mixed'),
                'show_in_main_calendar': request.data.get('show_in_main_calendar', True),
                'calendar_order': request.data.get('calendar_order', 0)
            }
            
            # Handle parent category
            parent_category_id = request.data.get('parent_category_id')
            if parent_category_id:
                try:
                    parent_category = ServiceCategory.objects.get(id=parent_category_id, user_id=user.id)
                    category_data['parent_category'] = parent_category
                except ServiceCategory.DoesNotExist:
                    return Response(
                        {'error': 'Parent category not found'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            category = ServiceCategory.objects.create(user_id=user.id, **category_data)
            
            return Response({
                'id': str(category.id),
                'name': category.name,
                'message': 'Category created successfully'
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating service category: {e}")
            return Response(
                {'error': 'Failed to create category'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ServiceCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a service category."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        user = require_authenticated_user(self.request)
        return get_object_or_404(ServiceCategory, id=self.kwargs['pk'], user_id=user.id)
    
    def retrieve(self, request, *args, **kwargs):
        try:
            category = self.get_object()
            
            return Response({
                'id': str(category.id),
                'name': category.name,
                'description': category.description,
                'color': category.color,
                'icon': category.icon,
                'category_type': category.category_type,
                'show_in_main_calendar': category.show_in_main_calendar,
                'calendar_order': category.calendar_order,
                'parent_category': str(category.parent_category.id) if category.parent_category else None,
                'subcategories': [str(sub.id) for sub in category.subcategories.filter(is_active=True)],
                'service_count': category.services.filter(is_active=True).count(),
                'created_at': category.created_at.isoformat(),
                'updated_at': category.updated_at.isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error retrieving service category: {e}")
            return Response(
                {'error': 'Failed to retrieve category'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# Service Views
class ServiceListCreateView(generics.ListCreateAPIView):
    """List and create services."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def list(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            
            # Get query parameters
            category_id = request.query_params.get('category_id')
            service_type = request.query_params.get('service_type')
            search = request.query_params.get('search')
            is_active = request.query_params.get('is_active', 'true').lower() == 'true'
            
            # Use service catalog service
            service_catalog = ServiceCatalogService()
            filters = {
                'category_id': category_id,
                'service_type': service_type,
                'search': search,
                'is_active': is_active
            }
            
            result = service_catalog.get_services(user.id, filters)
            
            if result['success']:
                return Response({
                    'services': result['services'],
                    'count': result['count']
                })
            else:
                return Response(
                    {'error': result['error']},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
        except Exception as e:
            logger.error(f"Error listing services: {e}")
            return Response(
                {'error': 'Failed to retrieve services'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def create(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            
            # Use service catalog service
            service_catalog = ServiceCatalogService()
            result = service_catalog.create_service(user.id, request.data)
            
            if result['success']:
                return Response(result, status=status.HTTP_201_CREATED)
            else:
                return Response(
                    {'error': result['error']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
        except Exception as e:
            logger.error(f"Error creating service: {e}")
            return Response(
                {'error': 'Failed to create service'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a service."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        user = require_authenticated_user(self.request)
        return get_object_or_404(Service, id=self.kwargs['pk'], user_id=user.id)
    
    def retrieve(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            service = self.get_object()
            
            service_catalog = ServiceCatalogService()
            serialized_service = service_catalog._serialize_service(service)
            
            return Response(serialized_service)
            
        except Exception as e:
            logger.error(f"Error retrieving service: {e}")
            return Response(
                {'error': 'Failed to retrieve service'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def update(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            service = self.get_object()
            
            service_catalog = ServiceCatalogService()
            result = service_catalog.update_service(user.id, str(service.id), request.data)
            
            if result['success']:
                return Response(result)
            else:
                return Response(
                    {'error': result['error']},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
        except Exception as e:
            logger.error(f"Error updating service: {e}")
            return Response(
                {'error': 'Failed to update service'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# Availability and Pricing Views
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_service_availability(request):
    """Check availability for a specific service."""
    try:
        user = require_authenticated_user(request)
        
        service_id = request.data.get('service_id')
        start_time = request.data.get('start_time')
        end_time = request.data.get('end_time')
        quantity = request.data.get('quantity', 1)
        
        if not all([service_id, start_time, end_time]):
            return Response(
                {'error': 'service_id, start_time, and end_time are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service_catalog = ServiceCatalogService()
        result = service_catalog.check_service_availability(
            user.id, service_id, start_time, end_time, quantity
        )
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error checking service availability: {e}")
        return Response(
            {'error': 'Failed to check availability'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def calculate_service_price(request):
    """Calculate price for a service booking."""
    try:
        user = require_authenticated_user(request)
        
        service_id = request.data.get('service_id')
        start_time = request.data.get('start_time')
        end_time = request.data.get('end_time')
        quantity = request.data.get('quantity', 1)
        
        if not all([service_id, start_time, end_time]):
            return Response(
                {'error': 'service_id, start_time, and end_time are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        service_catalog = ServiceCatalogService()
        result = service_catalog.calculate_service_price(
            user.id, service_id, start_time, end_time, quantity
        )
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error calculating service price: {e}")
        return Response(
            {'error': 'Failed to calculate price'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Package Views
class PackageListCreateView(generics.ListCreateAPIView):
    """List and create packages."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = require_authenticated_user(self.request)
        return Package.objects.filter(user_id=user.id, is_active=True).select_related('category')
    
    def list(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            packages = self.get_queryset()
            
            packages_data = []
            for package in packages:
                packages_data.append({
                    'id': str(package.id),
                    'name': package.name,
                    'description': package.description,
                    'package_type': package.package_type,
                    'pricing_strategy': package.pricing_strategy,
                    'package_price_daily': float(package.package_price_daily) if package.package_price_daily else None,
                    'package_price_weekly': float(package.package_price_weekly) if package.package_price_weekly else None,
                    'discount_percentage': float(package.discount_percentage) if package.discount_percentage else None,
                    'is_featured': package.is_featured,
                    'category': {
                        'id': str(package.category.id),
                        'name': package.category.name
                    },
                    'item_count': package.package_items.count(),
                    'total_bookings': package.total_bookings,
                    'created_at': package.created_at.isoformat()
                })
            
            return Response({
                'packages': packages_data,
                'count': len(packages_data)
            })
            
        except Exception as e:
            logger.error(f"Error listing packages: {e}")
            return Response(
                {'error': 'Failed to retrieve packages'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def service_search(request):
    """Advanced service search."""
    try:
        user = require_authenticated_user(request)
        
        query = request.query_params.get('q', '')
        category_id = request.query_params.get('category_id')
        service_type = request.query_params.get('service_type')
        min_price = request.query_params.get('min_price')
        max_price = request.query_params.get('max_price')
        
        services = Service.objects.filter(user_id=user.id, is_active=True)
        
        if query:
            services = services.filter(
                Q(name__icontains=query) |
                Q(description__icontains=query) |
                Q(brand__icontains=query) |
                Q(model__icontains=query)
            )
        
        if category_id:
            services = services.filter(category_id=category_id)
        
        if service_type:
            services = services.filter(service_type=service_type)
        
        if min_price:
            services = services.filter(base_price__gte=min_price)
        
        if max_price:
            services = services.filter(base_price__lte=max_price)
        
        services = services.select_related('category')[:50]  # Limit results
        
        service_catalog = ServiceCatalogService()
        services_data = [service_catalog._serialize_service(service) for service in services]
        
        return Response({
            'services': services_data,
            'count': len(services_data),
            'query': query
        })
        
    except Exception as e:
        logger.error(f"Error searching services: {e}")
        return Response(
            {'error': 'Failed to search services'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
