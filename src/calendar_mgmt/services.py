"""
Calendar Management Service Layer

This module provides comprehensive calendar management functionality including
booking operations, conflict detection, availability checking, and AI assistant integration.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Q, Count, Sum
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import (
    ServiceCategory, Service, Booking, BookingService, 
    CalendarSettings, ConflictLog
)
from customer.models import Customer
from users.authentication import SupabaseUser

logger = logging.getLogger(__name__)


class ConflictDetectionService:
    """Service for detecting and resolving booking conflicts."""
    
    def __init__(self):
        self.channel_layer = get_channel_layer()
    
    def detect_conflicts(self, booking_data: Dict[str, Any], user_id: str, exclude_booking_id: str = None) -> List[Dict[str, Any]]:
        """
        Detect all types of conflicts for a proposed booking.
        
        Args:
            booking_data: Dictionary containing booking details
            user_id: User ID for filtering bookings
            exclude_booking_id: Booking ID to exclude from conflict checking (for updates)
        
        Returns:
            List of conflict dictionaries with details and suggestions
        """
        conflicts = []
        
        # Extract booking details
        start_time = booking_data.get('start_time')
        end_time = booking_data.get('end_time')
        service_ids = booking_data.get('service_ids', [])
        
        if not start_time or not end_time:
            return conflicts
        
        # Convert strings to datetime if necessary
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
        
        # Check service/equipment conflicts
        for service_id in service_ids:
            service_conflicts = self._detect_service_conflicts(
                service_id, start_time, end_time, user_id, exclude_booking_id
            )
            conflicts.extend(service_conflicts)
        
        # Check business hours conflicts
        business_hours_conflicts = self._detect_business_hours_conflicts(
            start_time, end_time, user_id
        )
        conflicts.extend(business_hours_conflicts)
        
        # Check availability limits
        availability_conflicts = self._detect_availability_conflicts(
            service_ids, start_time, end_time, user_id, exclude_booking_id
        )
        conflicts.extend(availability_conflicts)
        
        return conflicts
    
    def _detect_service_conflicts(
        self, 
        service_id: str, 
        start_time: datetime, 
        end_time: datetime, 
        user_id: str,
        exclude_booking_id: str = None
    ) -> List[Dict[str, Any]]:
        """Detect conflicts for a specific service/equipment."""
        conflicts = []
        
        try:
            service = Service.objects.get(id=service_id, user_id=user_id)
            
            # Skip conflict checking for unlimited availability services
            if service.availability_type == 'unlimited':
                return conflicts
            
            # Find overlapping bookings for this service
            overlapping_query = Q(
                booking_services__service_id=service_id,
                start_time__lt=end_time,
                end_time__gt=start_time,
                status__in=['confirmed', 'pending', 'in_progress']
            )
            
            if exclude_booking_id:
                overlapping_query &= ~Q(id=exclude_booking_id)
            
            overlapping_bookings = Booking.objects.filter(
                user_id=user_id
            ).filter(overlapping_query).distinct()
            
            # Calculate total quantity needed vs available
            total_quantity_used = 0
            for booking in overlapping_bookings:
                booking_service = booking.booking_services.filter(service_id=service_id).first()
                if booking_service:
                    total_quantity_used += booking_service.quantity
            
            # Assume quantity of 1 for the new booking (can be overridden)
            requested_quantity = 1
            
            if total_quantity_used + requested_quantity > service.quantity_available:
                for booking in overlapping_bookings:
                    conflicts.append({
                        'type': 'service_overlap',
                        'service_id': service_id,
                        'service_name': service.name,
                        'conflicting_booking_id': str(booking.id),
                        'conflicting_booking_title': booking.title,
                        'overlap_period': {
                            'start': max(start_time, booking.start_time).isoformat(),
                            'end': min(end_time, booking.end_time).isoformat()
                        },
                        'severity': 'high',
                        'suggestions': self._generate_conflict_suggestions(
                            service, start_time, end_time, booking
                        )
                    })
        
        except Service.DoesNotExist:
            logger.warning(f"Service {service_id} not found for user {user_id}")
        
        return conflicts
    
    def _detect_business_hours_conflicts(
        self, 
        start_time: datetime, 
        end_time: datetime, 
        user_id: str
    ) -> List[Dict[str, Any]]:
        """Check if booking is outside business hours."""
        conflicts = []
        
        try:
            settings = CalendarSettings.objects.get(user_id=user_id)
            
            # Convert to local time for business hours checking
            start_local = start_time.time()
            end_local = end_time.time()
            
            if (start_local < settings.business_hours_start or 
                end_local > settings.business_hours_end):
                conflicts.append({
                    'type': 'business_hours',
                    'severity': 'medium',
                    'message': f"Booking is outside business hours ({settings.business_hours_start} - {settings.business_hours_end})",
                    'suggestions': [
                        {
                            'type': 'adjust_time',
                            'suggested_start': f"{start_time.date()} {settings.business_hours_start}",
                            'suggested_end': f"{end_time.date()} {settings.business_hours_end}"
                        }
                    ]
                })
        
        except CalendarSettings.DoesNotExist:
            # No business hours restrictions if settings don't exist
            pass
        
        return conflicts
    
    def _detect_availability_conflicts(
        self, 
        service_ids: List[str], 
        start_time: datetime, 
        end_time: datetime, 
        user_id: str,
        exclude_booking_id: str = None
    ) -> List[Dict[str, Any]]:
        """Check availability limits for all requested services."""
        conflicts = []
        
        for service_id in service_ids:
            try:
                service = Service.objects.get(id=service_id, user_id=user_id)
                
                if service.availability_type == 'unique':
                    # For unique items, any overlap is a conflict
                    existing_bookings = Booking.objects.filter(
                        user_id=user_id,
                        booking_services__service_id=service_id,
                        start_time__lt=end_time,
                        end_time__gt=start_time,
                        status__in=['confirmed', 'pending', 'in_progress']
                    )
                    
                    if exclude_booking_id:
                        existing_bookings = existing_bookings.exclude(id=exclude_booking_id)
                    
                    if existing_bookings.exists():
                        conflicts.append({
                            'type': 'availability_limit',
                            'service_id': service_id,
                            'service_name': service.name,
                            'severity': 'critical',
                            'message': f"{service.name} is a unique item and is already booked during this time",
                            'conflicting_bookings': [
                                {
                                    'id': str(booking.id),
                                    'title': booking.title,
                                    'start_time': booking.start_time.isoformat(),
                                    'end_time': booking.end_time.isoformat()
                                }
                                for booking in existing_bookings
                            ]
                        })
            
            except Service.DoesNotExist:
                continue
        
        return conflicts
    
    def _generate_conflict_suggestions(
        self, 
        service: Service, 
        requested_start: datetime, 
        requested_end: datetime, 
        conflicting_booking: Booking
    ) -> List[Dict[str, Any]]:
        """Generate suggestions for resolving conflicts."""
        suggestions = []
        
        # Suggest time slots before the conflicting booking
        if conflicting_booking.start_time > requested_start:
            duration = requested_end - requested_start
            suggested_end = conflicting_booking.start_time
            suggested_start = suggested_end - duration
            
            suggestions.append({
                'type': 'reschedule_earlier',
                'suggested_start': suggested_start.isoformat(),
                'suggested_end': suggested_end.isoformat(),
                'message': f"Schedule before {conflicting_booking.title}"
            })
        
        # Suggest time slots after the conflicting booking
        if conflicting_booking.end_time < requested_end:
            duration = requested_end - requested_start
            suggested_start = conflicting_booking.end_time
            suggested_end = suggested_start + duration
            
            suggestions.append({
                'type': 'reschedule_later',
                'suggested_start': suggested_start.isoformat(),
                'suggested_end': suggested_end.isoformat(),
                'message': f"Schedule after {conflicting_booking.title}"
            })
        
        return suggestions


class AvailabilityService:
    """Service for checking service and equipment availability."""
    
    def check_availability(
        self, 
        service_ids: List[str], 
        start_time: datetime, 
        end_time: datetime, 
        user_id: str
    ) -> Dict[str, Any]:
        """
        Check availability for multiple services in a time range.
        
        Returns:
            Dictionary with availability status for each service
        """
        availability = {}
        
        for service_id in service_ids:
            try:
                service = Service.objects.get(id=service_id, user_id=user_id, is_active=True)
                availability[service_id] = self._check_service_availability(
                    service, start_time, end_time, user_id
                )
            except Service.DoesNotExist:
                availability[service_id] = {
                    'available': False,
                    'reason': 'Service not found or inactive'
                }
        
        return availability
    
    def _check_service_availability(
        self, 
        service: Service, 
        start_time: datetime, 
        end_time: datetime, 
        user_id: str
    ) -> Dict[str, Any]:
        """Check availability for a single service."""
        
        # Check if service is active
        if not service.is_active:
            return {
                'available': False,
                'reason': 'Service is not active',
                'quantity_available': 0,
                'quantity_total': service.quantity_available
            }
        
        # Unlimited availability services are always available
        if service.availability_type == 'unlimited':
            return {
                'available': True,
                'quantity_available': float('inf'),
                'quantity_total': float('inf')
            }
        
        # Calculate current usage during the requested time period
        overlapping_bookings = Booking.objects.filter(
            user_id=user_id,
            booking_services__service=service,
            start_time__lt=end_time,
            end_time__gt=start_time,
            status__in=['confirmed', 'pending', 'in_progress']
        )
        
        total_quantity_used = sum(
            booking.booking_services.filter(service=service).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            for booking in overlapping_bookings
        )
        
        quantity_available = service.quantity_available - total_quantity_used
        
        return {
            'available': quantity_available > 0,
            'quantity_available': max(0, quantity_available),
            'quantity_total': service.quantity_available,
            'quantity_used': total_quantity_used,
            'conflicting_bookings': [
                {
                    'id': str(booking.id),
                    'title': booking.title,
                    'start_time': booking.start_time.isoformat(),
                    'end_time': booking.end_time.isoformat()
                }
                for booking in overlapping_bookings
            ] if overlapping_bookings.exists() else []
        }
    
    def get_availability_matrix(
        self, 
        start_date: datetime, 
        end_date: datetime, 
        user_id: str,
        category_id: str = None
    ) -> Dict[str, Any]:
        """
        Get a detailed availability matrix for a date range.
        Useful for calendar visualization and sub-calendar filtering.
        """
        services_query = Service.objects.filter(user_id=user_id, is_active=True)
        
        if category_id:
            services_query = services_query.filter(category_id=category_id)
        
        services = services_query.all()
        
        # Generate time slots (daily basis)
        time_slots = []
        current_date = start_date.date()
        while current_date <= end_date.date():
            time_slots.append(current_date)
            current_date += timedelta(days=1)
        
        availability_matrix = {}
        
        for service in services:
            service_availability = {}
            
            for slot_date in time_slots:
                slot_start = datetime.combine(slot_date, datetime.min.time())
                slot_end = datetime.combine(slot_date, datetime.max.time())
                
                availability = self._check_service_availability(
                    service, slot_start, slot_end, user_id
                )
                
                service_availability[slot_date.isoformat()] = availability
            
            availability_matrix[str(service.id)] = {
                'service_name': service.name,
                'category': service.category.name,
                'availability': service_availability
            }
        
        return availability_matrix


class CalendarManagementService:
    """Main service for calendar and booking management with AI integration."""
    
    def __init__(self):
        self.conflict_service = ConflictDetectionService()
        self.availability_service = AvailabilityService()
        self.channel_layer = get_channel_layer()
    
    @transaction.atomic
    def create_booking_from_ai(
        self, 
        user: SupabaseUser, 
        booking_data: Dict[str, Any],
        ai_session_id: str = None,
        ai_message_id: int = None,
        confidence_score: float = None
    ) -> Dict[str, Any]:
        """
        Create a booking from AI assistant with enhanced validation and conflict resolution.
        
        Args:
            user: SupabaseUser instance
            booking_data: Dictionary containing booking details
            ai_session_id: AI chat session ID
            ai_message_id: AI message ID that triggered this booking
            confidence_score: AI confidence in the booking creation
        
        Returns:
            Dictionary with booking details and any conflicts/warnings
        """
        try:
            # Validate required fields
            required_fields = ['title', 'start_time', 'end_time', 'customer', 'services']
            for field in required_fields:
                if field not in booking_data:
                    return {
                        'success': False,
                        'error': f"Missing required field: {field}",
                        'field_errors': {field: 'This field is required'}
                    }
            
            # Get or create customer
            customer = self._get_or_create_customer(user.id, booking_data['customer'])
            
            # Validate services
            services = self._validate_services(user.id, booking_data['services'])
            if not services:
                return {
                    'success': False,
                    'error': 'No valid services found',
                    'field_errors': {'services': 'At least one valid service is required'}
                }
            
            # Parse datetime strings
            start_time = self._parse_datetime(booking_data['start_time'])
            end_time = self._parse_datetime(booking_data['end_time'])
            
            if start_time >= end_time:
                return {
                    'success': False,
                    'error': 'End time must be after start time',
                    'field_errors': {'end_time': 'Must be after start time'}
                }
            
            # Detect conflicts
            service_ids = [str(service.id) for service in services]
            conflicts = self.conflict_service.detect_conflicts({
                'start_time': start_time,
                'end_time': end_time,
                'service_ids': service_ids
            }, user.id)
            
            # Get calendar settings for auto-confirmation logic
            try:
                settings = CalendarSettings.objects.get(user_id=user.id)
                auto_confirm = (
                    settings.ai_booking_auto_confirm and 
                    confidence_score and 
                    confidence_score >= settings.ai_confidence_threshold and
                    not any(c['severity'] in ['high', 'critical'] for c in conflicts)
                )
            except CalendarSettings.DoesNotExist:
                auto_confirm = False
            
            # Create the booking
            booking = Booking.objects.create(
                user_id=user.id,
                customer=customer,
                title=booking_data['title'],
                description=booking_data.get('description', ''),
                start_time=start_time,
                end_time=end_time,
                all_day=booking_data.get('all_day', False),
                status='confirmed' if auto_confirm else 'pending',
                created_via='ai_assistant',
                ai_session_id=ai_session_id,
                ai_message_id=ai_message_id,
                ai_confidence_score=confidence_score,
                notes=booking_data.get('notes', '')
            )
            
            # Create booking services
            total_price = 0
            for service in services:
                # Calculate price (simplified - could be more complex based on duration)
                duration_hours = (end_time - start_time).total_seconds() / 3600
                
                if service.price_per_hour:
                    price = service.price_per_hour * duration_hours
                elif service.price_per_day:
                    duration_days = max(1, duration_hours / 24)
                    price = service.price_per_day * duration_days
                else:
                    price = service.base_price
                
                BookingService.objects.create(
                    booking=booking,
                    service=service,
                    quantity=1,  # Default quantity, could be customized
                    price_per_unit=price,
                    total_price=price,
                    service_status='reserved'
                )
                
                total_price += price
            
            # Log conflicts if any
            for conflict in conflicts:
                ConflictLog.objects.create(
                    user_id=user.id,
                    conflict_type=conflict['type'],
                    primary_booking=booking,
                    description=conflict.get('message', f"Conflict detected: {conflict['type']}"),
                    severity=conflict.get('severity', 'medium'),
                    resolution_status='detected'
                )
            
            # Send real-time update
            self._send_booking_update('booking.created', booking, conflicts)
            
            return {
                'success': True,
                'booking_id': str(booking.id),
                'booking': self._serialize_booking(booking),
                'conflicts': conflicts,
                'auto_confirmed': auto_confirm,
                'total_price': float(total_price),
                'message': f"Booking {'confirmed' if auto_confirm else 'created'} successfully"
            }
        
        except Exception as e:
            logger.error(f"Error creating booking from AI: {e}")
            return {
                'success': False,
                'error': 'Failed to create booking',
                'details': str(e)
            }
    
    def get_calendar_data(
        self, 
        user_id: str, 
        start_date: datetime, 
        end_date: datetime,
        category_ids: List[str] = None
    ) -> Dict[str, Any]:
        """
        Get calendar data for specified date range with sub-calendar filtering.
        
        Args:
            user_id: User ID
            start_date: Start date for calendar data
            end_date: End date for calendar data
            category_ids: Optional list of category IDs to filter by
        
        Returns:
            Dictionary containing bookings, availability, and calendar metadata
        """
        # Build query for bookings
        bookings_query = Booking.objects.filter(
            user_id=user_id,
            start_time__lte=end_date,
            end_time__gte=start_date
        ).select_related('customer').prefetch_related('booking_services__service__category')
        
        # Filter by category if specified
        if category_ids:
            bookings_query = bookings_query.filter(
                booking_services__service__category_id__in=category_ids
            ).distinct()
        
        bookings = bookings_query.all()
        
        # Get calendar settings
        try:
            settings = CalendarSettings.objects.get(user_id=user_id)
            visible_categories = settings.visible_categories if settings.visible_categories else []
        except CalendarSettings.DoesNotExist:
            visible_categories = []
        
        # Get categories for sub-calendar organization
        categories = ServiceCategory.objects.filter(
            user_id=user_id,
            is_active=True
        ).order_by('calendar_order', 'name')
        
        # Get availability matrix
        availability_matrix = self.availability_service.get_availability_matrix(
            start_date, end_date, user_id, category_ids[0] if category_ids else None
        )
        
        return {
            'bookings': [self._serialize_booking(booking) for booking in bookings],
            'categories': [self._serialize_category(category) for category in categories],
            'availability_matrix': availability_matrix,
            'visible_categories': visible_categories,
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            }
        }
    
    def _get_or_create_customer(self, user_id: str, customer_data: Dict[str, Any]) -> Customer:
        """Get existing customer or create new one from AI-provided data."""
        email = customer_data.get('email', '').strip().lower()
        
        if email:
            # Try to find existing customer by email
            try:
                return Customer.objects.get(user_id=user_id, email=email)
            except Customer.DoesNotExist:
                pass
        
        # Create new customer
        return Customer.objects.create(
            user_id=user_id,
            first_name=customer_data.get('first_name', customer_data.get('name', '')).strip(),
            last_name=customer_data.get('last_name', '').strip(),
            email=email,
            phone=customer_data.get('phone', '').strip(),
            company=customer_data.get('company', '').strip(),
            notes=customer_data.get('notes', '').strip()
        )
    
    def _validate_services(self, user_id: str, services_data: List[Dict[str, Any]]) -> List[Service]:
        """Validate and return service objects from AI-provided data."""
        services = []
        
        for service_data in services_data:
            service_id = service_data.get('id')
            service_name = service_data.get('name', '').strip().lower()
            
            try:
                if service_id:
                    # Find by ID
                    service = Service.objects.get(id=service_id, user_id=user_id, is_active=True)
                    services.append(service)
                elif service_name:
                    # Find by name (case-insensitive partial match)
                    service = Service.objects.filter(
                        user_id=user_id,
                        is_active=True,
                        name__icontains=service_name
                    ).first()
                    if service:
                        services.append(service)
            except Service.DoesNotExist:
                continue
        
        return services
    
    def _parse_datetime(self, datetime_str: str) -> datetime:
        """Parse datetime string with timezone awareness."""
        if isinstance(datetime_str, datetime):
            return datetime_str
        
        # Handle various datetime formats
        try:
            if datetime_str.endswith('Z'):
                datetime_str = datetime_str[:-1] + '+00:00'
            return datetime.fromisoformat(datetime_str)
        except ValueError:
            # Fallback to timezone.now() for invalid formats
            logger.warning(f"Invalid datetime format: {datetime_str}")
            return timezone.now()
    
    def _serialize_booking(self, booking: Booking) -> Dict[str, Any]:
        """Serialize booking object for API response."""
        return {
            'id': str(booking.id),
            'title': booking.title,
            'description': booking.description,
            'start_time': booking.start_time.isoformat(),
            'end_time': booking.end_time.isoformat(),
            'all_day': booking.all_day,
            'status': booking.status,
            'created_via': booking.created_via,
            'customer': {
                'id': str(booking.customer.id),
                'name': booking.customer.full_name,
                'email': booking.customer.email,
                'phone': booking.customer.phone
            },
            'services': [
                {
                    'id': str(bs.service.id),
                    'name': bs.service.name,
                    'category': bs.service.category.name,
                    'quantity': bs.quantity,
                    'price': float(bs.total_price),
                    'status': bs.service_status
                }
                for bs in booking.booking_services.all()
            ],
            'ai_metadata': {
                'session_id': str(booking.ai_session_id) if booking.ai_session_id else None,
                'message_id': booking.ai_message_id,
                'confidence_score': booking.ai_confidence_score
            } if booking.created_via == 'ai_assistant' else None,
            'color': booking.color or booking.booking_services.first().service.category.color if booking.booking_services.exists() else '#3B82F6',
            'created_at': booking.created_at.isoformat(),
            'updated_at': booking.updated_at.isoformat()
        }
    
    def _serialize_category(self, category: ServiceCategory) -> Dict[str, Any]:
        """Serialize service category for sub-calendar display."""
        return {
            'id': str(category.id),
            'name': category.name,
            'description': category.description,
            'color': category.color,
            'show_in_main_calendar': category.show_in_main_calendar,
            'service_count': category.services.filter(is_active=True).count()
        }
    
    def _send_booking_update(self, event_type: str, booking: Booking, conflicts: List[Dict] = None):
        """Send real-time booking update via WebSocket."""
        if not self.channel_layer:
            return
        
        # Send to user's personal calendar channel
        channel_group = f"calendar_{booking.user_id}"
        
        message = {
            'type': 'calendar_update',
            'data': {
                'type': event_type,
                'booking': self._serialize_booking(booking),
                'conflicts': conflicts or [],
                'timestamp': timezone.now().isoformat()
            }
        }
        
        async_to_sync(self.channel_layer.group_send)(channel_group, message) 