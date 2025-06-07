"""
AI Action Executor

This module handles the execution of AI-identified actions,
particularly calendar and booking-related operations.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from django.db import transaction, models
from django.utils import timezone
from django.core.exceptions import ValidationError

from calendar_mgmt.services import CalendarManagementService
from service_catalog.services import ServiceCatalogService
from customer.models import Customer
from calendar_mgmt.models import Booking
from service_catalog.models import Service, ServiceCategory
from users.authentication import SupabaseUser

logger = logging.getLogger(__name__)


class ActionExecutor:
    """Executes AI-identified actions for calendar and booking operations."""
    
    def __init__(self):
        self.calendar_service = CalendarManagementService()
        self.service_catalog = ServiceCatalogService()
    
    def execute_action(self, action_type: str, parameters: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """
        Execute an action based on its type and parameters.
        
        Args:
            action_type: Type of action to execute
            parameters: Action parameters
            user_id: User ID executing the action
        
        Returns:
            Dictionary with execution result
        """
        try:
            # Create SupabaseUser object
            user = SupabaseUser({'sub': user_id})
            
            # Route to appropriate handler
            if action_type == 'check_service_exists':
                return self._handle_check_service_exists(user, parameters)
            elif action_type == 'create_booking':
                return self._handle_create_booking(user, parameters)
            elif action_type == 'update_booking':
                return self._handle_update_booking(user, parameters)
            elif action_type == 'cancel_booking':
                return self._handle_cancel_booking(user, parameters)
            elif action_type == 'check_availability':
                return self._handle_check_availability(user, parameters)
            elif action_type == 'create_customer':
                return self._handle_create_customer(user, parameters)
            elif action_type == 'update_customer':
                return self._handle_update_customer(user, parameters)
            elif action_type == 'search_customer':
                return self._handle_search_customer(user, parameters)
            elif action_type == 'create_service':
                return self._handle_create_service(user, parameters)
            elif action_type == 'update_service':
                return self._handle_update_service(user, parameters)
            else:
                return {
                    'success': False,
                    'error': f'Unknown action type: {action_type}'
                }
        
        except Exception as e:
            logger.error(f"Error executing action {action_type}: {e}")
            return {
                'success': False,
                'error': f'Action execution failed: {str(e)}'
            }
    
    @transaction.atomic
    def _handle_create_booking(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle booking creation from AI."""
        try:
            # Extract and validate booking parameters
            booking_data = self._extract_booking_data(parameters)
            
            # Use calendar service to create booking
            result = self.calendar_service.create_booking_from_ai(
                user=user,
                booking_data=booking_data,
                ai_session_id=parameters.get('ai_session_id'),
                ai_message_id=parameters.get('ai_message_id'),
                confidence_score=parameters.get('confidence_score', 0.8)
            )
            
            if result['success']:
                logger.info(f"AI created booking {result['booking_id']} for user {user.id}")
                return {
                    'success': True,
                    'id': result['booking_id'],
                    'type': 'booking',
                    'message': result['message'],
                    'data': result['booking'],
                    'conflicts': result.get('conflicts', []),
                    'auto_confirmed': result.get('auto_confirmed', False)
                }
            else:
                return result
        
        except Exception as e:
            logger.error(f"Error creating booking from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to create booking: {str(e)}'
            }
    
    def _handle_update_booking(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle booking update from AI."""
        try:
            booking_id = parameters.get('booking_id')
            if not booking_id:
                return {
                    'success': False,
                    'error': 'Booking ID is required for updates'
                }
            
            # Find the booking
            try:
                booking = Booking.objects.get(id=booking_id, user_id=user.id)
            except Booking.DoesNotExist:
                return {
                    'success': False,
                    'error': 'Booking not found'
                }
            
            # Extract update data
            updates = {}
            if 'title' in parameters:
                updates['title'] = parameters['title']
            if 'description' in parameters:
                updates['description'] = parameters['description']
            if 'start_time' in parameters:
                updates['start_time'] = self._parse_datetime(parameters['start_time'])
            if 'end_time' in parameters:
                updates['end_time'] = self._parse_datetime(parameters['end_time'])
            if 'notes' in parameters:
                updates['notes'] = parameters['notes']
            
            # Update the booking
            for field, value in updates.items():
                setattr(booking, field, value)
            
            booking.save()
            
            # Log the update
            logger.info(f"AI updated booking {booking_id} for user {user.id}")
            
            return {
                'success': True,
                'id': str(booking.id),
                'type': 'booking',
                'message': 'Booking updated successfully',
                'data': self.calendar_service._serialize_booking(booking)
            }
        
        except Exception as e:
            logger.error(f"Error updating booking from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to update booking: {str(e)}'
            }
    
    def _handle_cancel_booking(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle booking cancellation from AI."""
        try:
            booking_id = parameters.get('booking_id')
            if not booking_id:
                return {
                    'success': False,
                    'error': 'Booking ID is required for cancellation'
                }
            
            # Find and cancel the booking
            try:
                booking = Booking.objects.get(id=booking_id, user_id=user.id)
                booking.status = 'cancelled'
                booking.notes += f"\nCancelled by AI on {timezone.now().isoformat()}"
                booking.save()
                
                logger.info(f"AI cancelled booking {booking_id} for user {user.id}")
                
                return {
                    'success': True,
                    'id': str(booking.id),
                    'type': 'booking',
                    'message': 'Booking cancelled successfully',
                    'data': self.calendar_service._serialize_booking(booking)
                }
            
            except Booking.DoesNotExist:
                return {
                    'success': False,
                    'error': 'Booking not found'
                }
        
        except Exception as e:
            logger.error(f"Error cancelling booking from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to cancel booking: {str(e)}'
            }
    
    def _handle_check_availability(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle availability checking from AI."""
        try:
            # Extract parameters
            start_time = self._parse_datetime(parameters.get('start_time'))
            end_time = self._parse_datetime(parameters.get('end_time'))
            service_names = parameters.get('services', [])
            
            # Find services by name
            service_ids = []
            for service_name in service_names:
                services = Service.objects.filter(
                    user_id=user.id,
                    name__icontains=service_name,
                    is_active=True
                )
                if services.exists():
                    service_ids.append(str(services.first().id))
            
            if not service_ids:
                return {
                    'success': False,
                    'error': 'No services found matching the specified names'
                }
            
            # Check availability
            availability = self.calendar_service.availability_service.check_availability(
                service_ids, start_time, end_time, user.id
            )
            
            # Format response
            available_services = []
            unavailable_services = []
            
            for service_id, avail_data in availability.items():
                service = Service.objects.get(id=service_id)
                service_info = {
                    'name': service.name,
                    'category': service.category.name,
                    'available': avail_data['available'],
                    'quantity_available': avail_data.get('quantity_available', 0)
                }
                
                if avail_data['available']:
                    available_services.append(service_info)
                else:
                    service_info['reason'] = avail_data.get('reason', 'Not available')
                    unavailable_services.append(service_info)
            
            return {
                'success': True,
                'type': 'availability_check',
                'message': f'Availability checked for {len(service_ids)} services',
                'data': {
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat(),
                    'available_services': available_services,
                    'unavailable_services': unavailable_services,
                    'total_checked': len(service_ids)
                }
            }
        
        except Exception as e:
            logger.error(f"Error checking availability from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to check availability: {str(e)}'
            }
    
    def _handle_create_customer(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer creation from AI."""
        try:
            # Extract customer data
            email = parameters.get('email', '').strip()
            
            # Handle empty email to avoid unique constraint violation
            if not email:
                # Check if a customer with empty email already exists for this user
                existing_empty_email = Customer.objects.filter(
                    user_id=user.id, 
                    email__in=['', None]
                ).first()
                
                if existing_empty_email:
                    # Update the existing customer instead of creating a new one
                    existing_empty_email.first_name = parameters.get('first_name', parameters.get('name', ''))
                    existing_empty_email.last_name = parameters.get('last_name', '')
                    existing_empty_email.phone = parameters.get('phone', '')
                    existing_empty_email.company = parameters.get('company', '')
                    existing_empty_email.notes = parameters.get('notes', '')
                    existing_empty_email.save()
                    
                    logger.info(f"AI updated existing customer {existing_empty_email.id} with no email for user {user.id}")
                    
                    return {
                        'success': True,
                        'id': str(existing_empty_email.id),
                        'type': 'customer',
                        'message': f'Customer {existing_empty_email.full_name} updated successfully',
                        'data': {
                            'id': str(existing_empty_email.id),
                            'name': existing_empty_email.full_name,
                            'email': existing_empty_email.email,
                            'phone': existing_empty_email.phone,
                            'company': existing_empty_email.company
                        }
                    }
            
            customer_data = {
                'first_name': parameters.get('first_name', parameters.get('name', '')),
                'last_name': parameters.get('last_name', ''),
                'email': email,
                'phone': parameters.get('phone', ''),
                'company': parameters.get('company', ''),
                'notes': parameters.get('notes', ''),
                'source': 'ai_assistant',
                'ai_created': True,
                'ai_session_id': parameters.get('ai_session_id'),
                'ai_confidence_score': parameters.get('confidence_score', 0.8)
            }
            
            # Create customer
            customer = Customer.objects.create(
                user_id=user.id,
                **customer_data
            )
            
            logger.info(f"AI created customer {customer.id} for user {user.id}")
            
            return {
                'success': True,
                'id': str(customer.id),
                'type': 'customer',
                'message': f'Customer {customer.full_name} created successfully',
                'data': {
                    'id': str(customer.id),
                    'name': customer.full_name,
                    'email': customer.email,
                    'phone': customer.phone,
                    'company': customer.company
                }
            }
        
        except Exception as e:
            logger.error(f"Error creating customer from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to create customer: {str(e)}'
            }
    
    def _handle_update_customer(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer update from AI."""
        try:
            customer_id = parameters.get('customer_id')
            email = parameters.get('email')
            
            # Find customer by ID or email
            customer = None
            if customer_id:
                try:
                    customer = Customer.objects.get(id=customer_id, user_id=user.id)
                except Customer.DoesNotExist:
                    pass
            
            if not customer and email:
                try:
                    customer = Customer.objects.get(email=email, user_id=user.id)
                except Customer.DoesNotExist:
                    pass
            
            if not customer:
                return {
                    'success': False,
                    'error': 'Customer not found'
                }
            
            # Update customer fields
            updates = {}
            for field in ['first_name', 'last_name', 'email', 'phone', 'company', 'notes']:
                if field in parameters:
                    updates[field] = parameters[field]
            
            for field, value in updates.items():
                setattr(customer, field, value)
            
            customer.save()
            
            logger.info(f"AI updated customer {customer.id} for user {user.id}")
            
            return {
                'success': True,
                'id': str(customer.id),
                'type': 'customer',
                'message': f'Customer {customer.full_name} updated successfully',
                'data': {
                    'id': str(customer.id),
                    'name': customer.full_name,
                    'email': customer.email,
                    'phone': customer.phone,
                    'company': customer.company
                }
            }
        
        except Exception as e:
            logger.error(f"Error updating customer from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to update customer: {str(e)}'
            }
    
    def _handle_search_customer(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle customer search from AI."""
        try:
            query = parameters.get('query', '')
            email = parameters.get('email', '')
            phone = parameters.get('phone', '')
            
            # Build search query
            customers = Customer.objects.filter(user_id=user.id, status='active')
            
            if email:
                customers = customers.filter(email__icontains=email)
            elif phone:
                customers = customers.filter(phone__icontains=phone)
            elif query:
                customers = customers.filter(
                    models.Q(first_name__icontains=query) |
                    models.Q(last_name__icontains=query) |
                    models.Q(company__icontains=query) |
                    models.Q(email__icontains=query)
                )
            
            customers = customers[:10]  # Limit results
            
            results = [
                {
                    'id': str(customer.id),
                    'name': customer.full_name,
                    'email': customer.email,
                    'phone': customer.phone,
                    'company': customer.company,
                    'total_bookings': customer.total_bookings,
                    'last_booking_date': customer.last_booking_date.isoformat() if customer.last_booking_date else None
                }
                for customer in customers
            ]
            
            return {
                'success': True,
                'type': 'customer_search',
                'message': f'Found {len(results)} customers',
                'data': {
                    'customers': results,
                    'total_found': len(results)
                }
            }
        
        except Exception as e:
            logger.error(f"Error searching customers from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to search customers: {str(e)}'
            }
    
    def _handle_create_service(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle service creation from AI."""
        try:
            # Get or create category first
            category_name = parameters.get('category', 'General')
            category_result = self.service_catalog.get_categories(user.id)
            
            category_id = None
            if category_result['success']:
                # Find existing category
                for cat in category_result['categories']:
                    if cat['name'].lower() == category_name.lower():
                        category_id = cat['id']
                        break
            
            # Create category if not found
            if not category_id:
                cat_result = self.service_catalog.create_category(user.id, {
                    'name': category_name,
                    'description': f'Category for {category_name} services'
                })
                if cat_result['success']:
                    category_id = cat_result['category_id']
                else:
                    return cat_result
            
            # Prepare service data
            service_data = {
                'category_id': category_id,
                'name': parameters.get('name', ''),
                'description': parameters.get('description', ''),
                'service_type': parameters.get('service_type', 'equipment'),
                'base_price': parameters.get('base_price', 0),
                'price_per_hour': parameters.get('price_per_hour'),
                'price_per_day': parameters.get('price_per_day'),
                'price_per_week': parameters.get('price_per_week'),
                'quantity_available': parameters.get('quantity_available', 1),
                'availability_type': parameters.get('availability_type', 'limited'),
                'brand': parameters.get('brand', ''),
                'model': parameters.get('model', ''),
                'specifications': parameters.get('specifications', {})
            }
            
            # Create service using service catalog
            result = self.service_catalog.create_service(user.id, service_data)
            
            if result['success']:
                logger.info(f"AI created service {result['service_id']} for user {user.id}")
                return {
                    'success': True,
                    'id': result['service_id'],
                    'type': 'service',
                    'message': result['message'],
                    'data': result['service']
                }
            else:
                return result
        
        except Exception as e:
            logger.error(f"Error creating service from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to create service: {str(e)}'
            }
    
    def _handle_update_service(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle service update from AI."""
        try:
            service_id = parameters.get('service_id')
            service_name = parameters.get('service_name')
            
            # Find service ID if not provided
            if not service_id and service_name:
                services_result = self.service_catalog.get_services(user.id, {
                    'search': service_name
                })
                if services_result['success'] and services_result['services']:
                    service_id = services_result['services'][0]['id']
            
            if not service_id:
                return {
                    'success': False,
                    'error': 'Service not found'
                }
            
            # Prepare update data
            update_data = {}
            for field in ['name', 'description', 'base_price', 'price_per_hour', 'price_per_day', 'price_per_week', 'quantity_available', 'brand', 'model']:
                if field in parameters:
                    update_data[field] = parameters[field]
            
            # Update service using service catalog
            result = self.service_catalog.update_service(user.id, service_id, update_data)
            
            if result['success']:
                logger.info(f"AI updated service {service_id} for user {user.id}")
                return {
                    'success': True,
                    'id': service_id,
                    'type': 'service',
                    'message': result['message'],
                    'data': result['service']
                }
            else:
                return result
        
        except Exception as e:
            logger.error(f"Error updating service from AI: {e}")
            return {
                'success': False,
                'error': f'Failed to update service: {str(e)}'
            }
    
    def _handle_check_service_exists(self, user: SupabaseUser, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Check if a service/equipment exists in the catalog."""
        try:
            service_name = parameters.get('service_name', '').strip()
            if not service_name:
                return {
                    'success': False,
                    'error': 'Service name is required'
                }
            
            # Search for service by name (case-insensitive)
            services = Service.objects.filter(
                user_id=user.id,
                is_active=True,
                name__icontains=service_name
            )
            
            if services.exists():
                service = services.first()
                return {
                    'success': True,
                    'exists': True,
                    'service_id': str(service.id),
                    'service_name': service.name,
                    'service_type': service.service_type,
                    'message': f'Found service: {service.name}',
                    'data': {
                        'id': str(service.id),
                        'name': service.name,
                        'service_type': service.service_type,
                        'base_price': float(service.base_price),
                        'availability_type': service.availability_type,
                        'quantity_available': service.quantity_available
                    }
                }
            else:
                return {
                    'success': True,
                    'exists': False,
                    'service_name': service_name,
                    'message': f'Service "{service_name}" not found in catalog',
                    'suggestions': self._get_similar_services(user, service_name)
                }
                
        except Exception as e:
            logger.error(f"Error checking service exists: {e}")
            return {
                'success': False,
                'error': f'Failed to check service: {str(e)}'
            }
    
    def _get_similar_services(self, user: SupabaseUser, service_name: str) -> List[str]:
        """Get similar service names for suggestions."""
        try:
            # Get all active services for the user
            services = Service.objects.filter(
                user_id=user.id,
                is_active=True
            ).values_list('name', flat=True)[:5]
            
            return list(services)
        except Exception:
            return []
    
    def _extract_booking_data(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Extract and validate booking data from AI parameters."""
        booking_data = {
            'title': parameters.get('title', parameters.get('name', '')),
            'description': parameters.get('description', ''),
            'start_time': parameters.get('start_time'),
            'end_time': parameters.get('end_time'),
            'all_day': parameters.get('all_day', False),
            'notes': parameters.get('notes', ''),
            'customer': parameters.get('customer', {}),
            'services': parameters.get('services', [])
        }
        
        return booking_data
    
    def _parse_datetime(self, datetime_str: str) -> datetime:
        """Parse datetime string with timezone awareness."""
        if isinstance(datetime_str, datetime):
            return datetime_str
        
        # Handle None or empty strings
        if not datetime_str:
            logger.warning(f"Empty datetime provided, using current time")
            return timezone.now()
        
        try:
            if datetime_str.endswith('Z'):
                datetime_str = datetime_str[:-1] + '+00:00'
            return datetime.fromisoformat(datetime_str)
        except ValueError:
            logger.warning(f"Invalid datetime format: {datetime_str}")
            return timezone.now() 