"""
Calendar Management API Views

This module provides REST API endpoints for calendar management,
including booking operations, service management, and AI integration.
"""

from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, timedelta
from typing import Dict, Any

from .models import ServiceCategory, Service, Booking, BookingService, CalendarSettings, ConflictLog
from customer.models import Customer
from .serializers import (
    ServiceCategorySerializer, ServiceSerializer, CustomerSerializer,
    BookingSerializer, CalendarEventSerializer, CalendarSettingsSerializer,
    BookingCreateSerializer, AvailabilityCheckSerializer, ConflictLogSerializer
)
from .services import CalendarManagementService
from users.authentication import SupabaseJWTAuthentication


class ServiceCategoryListCreateView(generics.ListCreateAPIView):
    """API view for listing and creating service categories (sub-calendars)."""
    serializer_class = ServiceCategorySerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ServiceCategory.objects.filter(
            user_id=self.request.user.id,
            is_active=True
        ).order_by('calendar_order', 'name')
    
    def perform_create(self, serializer):
        serializer.save(user_id=self.request.user.id)


class ServiceCategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """API view for retrieving, updating, and deleting service categories."""
    serializer_class = ServiceCategorySerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ServiceCategory.objects.filter(user_id=self.request.user.id)


class ServiceListCreateView(generics.ListCreateAPIView):
    """API view for listing and creating services/equipment."""
    serializer_class = ServiceSerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = Service.objects.filter(
            user_id=self.request.user.id,
            is_active=True
        ).select_related('category')
        
        # Filter by category if specified
        category_id = self.request.query_params.get('category_id')
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        
        # Filter by service type
        service_type = self.request.query_params.get('service_type')
        if service_type:
            queryset = queryset.filter(service_type=service_type)
        
        # Search by name
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)
        
        return queryset.order_by('category__calendar_order', 'name')
    
    def perform_create(self, serializer):
        serializer.save(user_id=self.request.user.id)


class ServiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    """API view for retrieving, updating, and deleting services."""
    serializer_class = ServiceSerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Service.objects.filter(user_id=self.request.user.id)


class BookingListCreateView(generics.ListCreateAPIView):
    """API view for listing and creating bookings."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return BookingCreateSerializer
        return BookingSerializer
    
    def get_queryset(self):
        queryset = Booking.objects.filter(
            user_id=self.request.user.id
        ).select_related('customer').prefetch_related('booking_services__service__category')
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        
        if start_date:
            try:
                start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                queryset = queryset.filter(start_time__gte=start_date)
            except ValueError:
                pass
        
        if end_date:
            try:
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                queryset = queryset.filter(end_time__lte=end_date)
            except ValueError:
                pass
        
        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by customer
        customer_id = self.request.query_params.get('customer_id')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        
        # Filter by category (sub-calendar)
        category_ids = self.request.query_params.getlist('category_ids[]')
        if category_ids:
            queryset = queryset.filter(
                booking_services__service__category_id__in=category_ids
            ).distinct()
        
        # Filter by AI created
        ai_created = self.request.query_params.get('ai_created')
        if ai_created:
            queryset = queryset.filter(created_via='ai_assistant')
        
        return queryset.order_by('-start_time')
    
    def create(self, request, *args, **kwargs):
        """Create a new booking with conflict detection."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Use calendar service to create booking
        calendar_service = CalendarManagementService()
        
        # Extract booking data from validated serializer data
        booking_data = {
            'title': serializer.validated_data['title'],
            'description': serializer.validated_data.get('description', ''),
            'start_time': serializer.validated_data['start_time'],
            'end_time': serializer.validated_data['end_time'],
            'all_day': serializer.validated_data['all_day'],
            'notes': serializer.validated_data.get('notes', ''),
            'customer': self._resolve_customer_data(serializer.validated_data),
            'services': self._resolve_service_data(serializer.validated_data)
        }
        
        result = calendar_service.create_booking_from_ai(
            user=request.user,
            booking_data=booking_data
        )
        
        if result['success']:
            return Response(result, status=status.HTTP_201_CREATED)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
    
    def _resolve_customer_data(self, validated_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve customer data from various input formats."""
        customer_id = validated_data.get('customer_id')
        customer_email = validated_data.get('customer_email')
        customer_data = validated_data.get('customer_data', {})
        
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id, user_id=self.request.user.id)
                return {
                    'id': str(customer.id),
                    'email': customer.email,
                    'first_name': customer.first_name,
                    'last_name': customer.last_name,
                    'phone': customer.phone,
                    'company': customer.company
                }
            except Customer.DoesNotExist:
                pass
        
        if customer_email:
            return {'email': customer_email}
        
        return customer_data
    
    def _resolve_service_data(self, validated_data: Dict[str, Any]) -> list:
        """Resolve service data from service IDs."""
        service_ids = validated_data.get('service_ids', [])
        service_quantities = validated_data.get('service_quantities', {})
        
        services = []
        for service_id in service_ids:
            try:
                service = Service.objects.get(id=service_id, user_id=self.request.user.id)
                services.append({
                    'id': str(service.id),
                    'name': service.name,
                    'quantity': service_quantities.get(str(service_id), 1)
                })
            except Service.DoesNotExist:
                continue
        
        return services


class BookingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """API view for retrieving, updating, and deleting bookings."""
    serializer_class = BookingSerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Booking.objects.filter(user_id=self.request.user.id)


class CalendarEventsView(APIView):
    """API view for fetching calendar events in FullCalendar format."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get calendar events for specified date range and filters."""
        # Parse date range
        start_date = request.query_params.get('start')
        end_date = request.query_params.get('end')
        
        if not start_date or not end_date:
            return Response(
                {'error': 'start and end dates are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            return Response(
                {'error': 'Invalid date format'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get category filters for sub-calendars
        category_ids = request.query_params.getlist('category_ids[]')
        
        # Use calendar service to get data
        calendar_service = CalendarManagementService()
        calendar_data = calendar_service.get_calendar_data(
            user_id=request.user.id,
            start_date=start_date,
            end_date=end_date,
            category_ids=category_ids if category_ids else None
        )
        
        # Serialize bookings for FullCalendar
        events = []
        for booking in calendar_data['bookings']:
            # Determine color
            color = booking.get('color')
            if not color and booking.get('services'):
                # Use category color if no custom color
                color = booking['services'][0].get('category_color', '#3B82F6')
            
            event = {
                'id': booking['id'],
                'title': booking['title'],
                'start': booking['start_time'],
                'end': booking['end_time'],
                'allDay': booking['all_day'],
                'color': color,
                'extendedProps': {
                    'status': booking['status'],
                    'created_via': booking['created_via'],
                    'customer': booking['customer'],
                    'services': booking.get('services', []),
                    'ai_metadata': booking.get('ai_metadata'),
                    'conflicts': booking.get('conflicts', [])
                }
            }
            events.append(event)
        
        return Response({
            'events': events,
            'categories': calendar_data['categories'],
            'visible_categories': calendar_data['visible_categories']
        })


class AvailabilityCheckView(APIView):
    """API view for checking service availability."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Check availability for specified services and time range."""
        serializer = AvailabilityCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Use calendar service to check availability
        calendar_service = CalendarManagementService()
        availability = calendar_service.availability_service.check_availability(
            service_ids=[str(sid) for sid in serializer.validated_data['service_ids']],
            start_time=serializer.validated_data['start_time'],
            end_time=serializer.validated_data['end_time'],
            user_id=request.user.id
        )
        
        return Response({
            'availability': availability,
            'checked_at': timezone.now().isoformat()
        })


class ConflictDetectionView(APIView):
    """API view for detecting booking conflicts."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Detect conflicts for a proposed booking."""
        # Extract booking data
        booking_data = {
            'start_time': request.data.get('start_time'),
            'end_time': request.data.get('end_time'),
            'service_ids': request.data.get('service_ids', [])
        }
        
        exclude_booking_id = request.data.get('exclude_booking_id')
        
        # Use calendar service to detect conflicts
        calendar_service = CalendarManagementService()
        conflicts = calendar_service.conflict_service.detect_conflicts(
            booking_data=booking_data,
            user_id=request.user.id,
            exclude_booking_id=exclude_booking_id
        )
        
        return Response({
            'conflicts': conflicts,
            'has_conflicts': len(conflicts) > 0,
            'checked_at': timezone.now().isoformat()
        })


class CalendarSettingsView(generics.RetrieveUpdateAPIView):
    """API view for calendar settings management."""
    serializer_class = CalendarSettingsSerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        settings, created = CalendarSettings.objects.get_or_create(
            user_id=self.request.user.id,
            defaults={
                'default_view': 'week',
                'week_start_day': 1,
                'business_hours_start': '08:00',
                'business_hours_end': '18:00',
                'show_weekends': True,
                'color_scheme': 'category_based',
                'ai_booking_auto_confirm': False,
                'ai_confidence_threshold': 0.8,
                'conflict_notifications': True,
                'booking_reminders': True,
                'auto_resolve_minor_conflicts': False
            }
        )
        return settings


class ConflictLogListView(generics.ListAPIView):
    """API view for listing conflict logs."""
    serializer_class = ConflictLogSerializer
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        queryset = ConflictLog.objects.filter(
            user_id=self.request.user.id
        ).select_related('primary_booking', 'conflicting_booking', 'affected_service')
        
        # Filter by resolution status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(resolution_status=status_filter)
        
        # Filter by severity
        severity = self.request.query_params.get('severity')
        if severity:
            queryset = queryset.filter(severity=severity)
        
        return queryset.order_by('-created_at')


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def resolve_conflict(request, conflict_id):
    """Resolve a specific conflict."""
    try:
        conflict = ConflictLog.objects.get(
            id=conflict_id,
            user_id=request.user.id
        )
        
        resolution_notes = request.data.get('resolution_notes', '')
        resolved_by = request.data.get('resolved_by', 'manual')
        
        conflict.resolution_status = 'resolved'
        conflict.resolution_notes = resolution_notes
        conflict.resolved_by = resolved_by
        conflict.resolved_at = timezone.now()
        conflict.save()
        
        serializer = ConflictLogSerializer(conflict)
        return Response(serializer.data)
        
    except ConflictLog.DoesNotExist:
        return Response(
            {'error': 'Conflict not found'},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def dashboard_stats(request):
    """Get dashboard statistics for calendar management."""
    user_id = request.user.id
    
    # Get date range (default: current month)
    start_date = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    
    # Query bookings
    bookings = Booking.objects.filter(
        user_id=user_id,
        start_time__gte=start_date,
        end_time__lte=end_date
    )
    
    # Calculate statistics
    stats = {
        'total_bookings': bookings.count(),
        'confirmed_bookings': bookings.filter(status='confirmed').count(),
        'pending_bookings': bookings.filter(status='pending').count(),
        'ai_created_bookings': bookings.filter(created_via='ai_assistant').count(),
        'conflicts': ConflictLog.objects.filter(
            user_id=user_id,
            created_at__gte=start_date,
            resolution_status__in=['detected', 'escalated']
        ).count(),
        'active_services': Service.objects.filter(
            user_id=user_id,
            is_active=True
        ).count(),
        'active_customers': Customer.objects.filter(
            user_id=user_id,
            status='active',
            bookings__start_time__gte=start_date
        ).distinct().count()
    }
    
    # Get recent AI bookings
    recent_ai_bookings = bookings.filter(
        created_via='ai_assistant'
    ).order_by('-created_at')[:5]
    
    stats['recent_ai_bookings'] = BookingSerializer(
        recent_ai_bookings,
        many=True
    ).data
    
    return Response(stats)
