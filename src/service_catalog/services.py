"""
Service Catalog Management Services

This module provides comprehensive service and equipment management functionality
for the service catalog feature, including availability checking, pricing calculations,
and package management.
"""

from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum, Count, F
from datetime import datetime, timedelta

from .models import Service, ServiceCategory, Package, PackageItem


class ServiceCatalogService:
    """
    Core service for managing service catalog operations including
    service/equipment management, availability checking, and pricing calculations.
    """
    
    def __init__(self):
        self.service_model = Service
        self.category_model = ServiceCategory
        self.package_model = Package
    
    # Service Management
    
    def create_service(self, user_id: str, service_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new service or equipment item."""
        try:
            with transaction.atomic():
                # Validate category exists
                category = self.category_model.objects.get(
                    id=service_data['category_id'],
                    user_id=user_id
                )
                
                # Create service
                service = self.service_model.objects.create(
                    user_id=user_id,
                    category=category,
                    name=service_data['name'],
                    description=service_data.get('description', ''),
                    short_description=service_data.get('short_description', ''),
                    service_type=service_data.get('service_type', 'equipment'),
                    base_price=Decimal(str(service_data.get('base_price', '0.00'))),
                    price_per_hour=service_data.get('price_per_hour'),
                    price_per_day=service_data.get('price_per_day'),
                    price_per_week=service_data.get('price_per_week'),
                    availability_type=service_data.get('availability_type', 'limited'),
                    quantity_available=service_data.get('quantity_available', 1),
                    specifications=service_data.get('specifications', {}),
                    brand=service_data.get('brand', ''),
                    model=service_data.get('model', ''),
                    requires_deposit=service_data.get('requires_deposit', False),
                    deposit_amount=service_data.get('deposit_amount'),
                    is_active=service_data.get('is_active', True),
                    is_public=service_data.get('is_public', True)
                )
                
                return {
                    'success': True,
                    'service_id': str(service.id),
                    'message': f'Service "{service.name}" created successfully',
                    'service': self._serialize_service(service)
                }
                
        except self.category_model.DoesNotExist:
            return {
                'success': False,
                'error': 'Invalid category specified'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to create service: {str(e)}'
            }
    
    def update_service(self, user_id: str, service_id: str, service_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing service."""
        try:
            with transaction.atomic():
                service = self.service_model.objects.get(
                    id=service_id,
                    user_id=user_id
                )
                
                # Update fields if provided
                for field, value in service_data.items():
                    if field == 'category_id':
                        category = self.category_model.objects.get(
                            id=value,
                            user_id=user_id
                        )
                        service.category = category
                    elif hasattr(service, field):
                        setattr(service, field, value)
                
                service.save()
                
                return {
                    'success': True,
                    'message': f'Service "{service.name}" updated successfully',
                    'service': self._serialize_service(service)
                }
                
        except self.service_model.DoesNotExist:
            return {
                'success': False,
                'error': 'Service not found'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to update service: {str(e)}'
            }
    
    def get_services(self, user_id: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get services with optional filtering."""
        try:
            queryset = self.service_model.objects.filter(user_id=user_id)
            
            if filters:
                if filters.get('category_id'):
                    queryset = queryset.filter(category_id=filters['category_id'])
                if filters.get('service_type'):
                    queryset = queryset.filter(service_type=filters['service_type'])
                if filters.get('is_active') is not None:
                    queryset = queryset.filter(is_active=filters['is_active'])
                if filters.get('is_featured') is not None:
                    queryset = queryset.filter(is_featured=filters['is_featured'])
                if filters.get('search'):
                    search_term = filters['search']
                    queryset = queryset.filter(
                        Q(name__icontains=search_term) |
                        Q(description__icontains=search_term) |
                        Q(brand__icontains=search_term) |
                        Q(model__icontains=search_term)
                    )
            
            services = queryset.select_related('category').order_by('name')
            
            return {
                'success': True,
                'services': [self._serialize_service(service) for service in services],
                'count': services.count()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to get services: {str(e)}'
            }
    
    def check_service_availability(self, user_id: str, service_id: str, 
                                   start_time: datetime, end_time: datetime,
                                   quantity: int = 1) -> Dict[str, Any]:
        """Check if a service is available for booking."""
        try:
            service = self.service_model.objects.get(
                id=service_id,
                user_id=user_id
            )
            
            if not service.is_active:
                return {
                    'available': False,
                    'reason': 'Service is not active',
                    'conflicts': []
                }
            
            # For unlimited availability services
            if service.availability_type == 'unlimited':
                return {
                    'available': True,
                    'conflicts': [],
                    'available_quantity': quantity
                }
            
            # Check existing bookings for this service
            from calendar_mgmt.models import BookingService, Booking
            
            overlapping_bookings = BookingService.objects.filter(
                service=service,
                booking__start_time__lt=end_time,
                booking__end_time__gt=start_time,
                booking__status__in=['confirmed', 'pending', 'in_progress']
            ).aggregate(
                total_quantity=Sum('quantity')
            )
            
            booked_quantity = overlapping_bookings['total_quantity'] or 0
            available_quantity = service.quantity_available - booked_quantity
            
            if available_quantity >= quantity:
                return {
                    'available': True,
                    'conflicts': [],
                    'available_quantity': available_quantity
                }
            else:
                return {
                    'available': False,
                    'reason': f'Insufficient quantity available. Requested: {quantity}, Available: {available_quantity}',
                    'conflicts': [],
                    'available_quantity': available_quantity
                }
                
        except self.service_model.DoesNotExist:
            return {
                'available': False,
                'reason': 'Service not found',
                'conflicts': []
            }
        except Exception as e:
            return {
                'available': False,
                'reason': f'Error checking availability: {str(e)}',
                'conflicts': []
            }
    
    def calculate_service_price(self, user_id: str, service_id: str, 
                               start_time: datetime, end_time: datetime,
                               quantity: int = 1) -> Dict[str, Any]:
        """Calculate pricing for a service booking."""
        try:
            service = self.service_model.objects.get(
                id=service_id,
                user_id=user_id
            )
            
            duration = end_time - start_time
            duration_hours = duration.total_seconds() / 3600
            
            # Calculate base price using service's pricing logic
            unit_price = service.get_price_for_duration(duration_hours)
            total_price = unit_price * quantity
            
            return {
                'success': True,
                'unit_price': float(unit_price),
                'total_price': float(total_price),
                'quantity': quantity,
                'duration_hours': duration_hours,
                'pricing_details': {
                    'service_name': service.name,
                    'base_price': float(service.base_price),
                    'calculated_rate': float(unit_price)
                }
            }
            
        except self.service_model.DoesNotExist:
            return {
                'success': False,
                'error': 'Service not found'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to calculate price: {str(e)}'
            }
    
    # Category Management
    
    def create_category(self, user_id: str, category_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new service category."""
        try:
            category = self.category_model.objects.create(
                user_id=user_id,
                name=category_data['name'],
                description=category_data.get('description', ''),
                color=category_data.get('color', '#3B82F6'),
                category_type=category_data.get('category_type', 'mixed'),
                is_active=category_data.get('is_active', True)
            )
            
            return {
                'success': True,
                'category_id': str(category.id),
                'message': f'Category "{category.name}" created successfully',
                'category': self._serialize_category(category)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to create category: {str(e)}'
            }
    
    def get_categories(self, user_id: str) -> Dict[str, Any]:
        """Get all categories for a user."""
        try:
            categories = self.category_model.objects.filter(
                user_id=user_id
            ).order_by('calendar_order', 'name')
            
            return {
                'success': True,
                'categories': [self._serialize_category(cat) for cat in categories],
                'count': categories.count()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to get categories: {str(e)}'
            }
    
    # Package Management
    
    def create_package(self, user_id: str, package_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new service package."""
        try:
            with transaction.atomic():
                # Create package
                package = self.package_model.objects.create(
                    user_id=user_id,
                    category_id=package_data['category_id'],
                    name=package_data['name'],
                    description=package_data.get('description', ''),
                    package_type=package_data.get('package_type', 'equipment'),
                    pricing_strategy=package_data.get('pricing_strategy', 'discount'),
                    package_price_daily=package_data.get('package_price_daily'),
                    discount_percentage=package_data.get('discount_percentage'),
                    is_active=package_data.get('is_active', True)
                )
                
                # Add items to package
                if package_data.get('items'):
                    for item_data in package_data['items']:
                        PackageItem.objects.create(
                            package=package,
                            service_id=item_data['service_id'],
                            quantity=item_data.get('quantity', 1),
                            is_optional=item_data.get('is_optional', False)
                        )
                
                return {
                    'success': True,
                    'package_id': str(package.id),
                    'message': f'Package "{package.name}" created successfully',
                    'package': self._serialize_package(package)
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to create package: {str(e)}'
            }
    
    # Helper Methods
    
    def _serialize_service(self, service: Service) -> Dict[str, Any]:
        """Serialize service object to dictionary."""
        return {
            'id': str(service.id),
            'name': service.name,
            'description': service.description,
            'service_type': service.service_type,
            'category': {
                'id': str(service.category.id),
                'name': service.category.name,
                'color': service.category.color
            },
            'pricing': {
                'base_price': float(service.base_price),
                'price_per_hour': float(service.price_per_hour) if service.price_per_hour else None,
                'price_per_day': float(service.price_per_day) if service.price_per_day else None,
                'price_per_week': float(service.price_per_week) if service.price_per_week else None
            },
            'availability': {
                'type': service.availability_type,
                'quantity_available': service.quantity_available
            },
            'equipment_info': {
                'brand': service.brand,
                'model': service.model,
                'condition': service.condition
            },
            'is_active': service.is_active,
            'is_featured': service.is_featured,
            'created_at': service.created_at.isoformat(),
            'updated_at': service.updated_at.isoformat()
        }
    
    def _serialize_category(self, category: ServiceCategory) -> Dict[str, Any]:
        """Serialize category object to dictionary."""
        return {
            'id': str(category.id),
            'name': category.name,
            'description': category.description,
            'color': category.color,
            'category_type': category.category_type,
            'is_active': category.is_active,
            'show_in_main_calendar': category.show_in_main_calendar,
            'calendar_order': category.calendar_order,
            'created_at': category.created_at.isoformat()
        }
    
    def _serialize_package(self, package: Package) -> Dict[str, Any]:
        """Serialize package object to dictionary."""
        return {
            'id': str(package.id),
            'name': package.name,
            'description': package.description,
            'package_type': package.package_type,
            'pricing_strategy': package.pricing_strategy,
            'package_price_daily': float(package.package_price_daily) if package.package_price_daily else None,
            'discount_percentage': float(package.discount_percentage) if package.discount_percentage else None,
            'is_active': package.is_active,
            'is_featured': package.is_featured,
            'created_at': package.created_at.isoformat()
        } 