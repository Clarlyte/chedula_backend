# serializers for calendar_mgmt app 
from rest_framework import serializers
from django.utils import timezone
from .models import ServiceCategory, Service, Booking, BookingService, CalendarSettings, ConflictLog
from customer.models import Customer


class ServiceCategorySerializer(serializers.ModelSerializer):
    """Serializer for service categories (sub-calendars)."""
    service_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ServiceCategory
        fields = [
            'id', 'name', 'description', 'color', 'is_active',
            'show_in_main_calendar', 'calendar_order', 'service_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'service_count']
    
    def get_service_count(self, obj):
        return obj.services.filter(is_active=True).count()


class ServiceSerializer(serializers.ModelSerializer):
    """Serializer for services and equipment."""
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_color = serializers.CharField(source='category.color', read_only=True)
    
    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description', 'service_type', 'category', 'category_name', 'category_color',
            'base_price', 'price_per_hour', 'price_per_day',
            'availability_type', 'quantity_available',
            'min_booking_duration', 'max_booking_duration', 'advance_booking_days',
            'specifications', 'requires_approval', 'is_active', 'is_featured',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'category_name', 'category_color']


class CustomerSerializer(serializers.ModelSerializer):
    """Serializer for customer data."""
    full_name = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    
    class Meta:
        model = Customer
        fields = [
            'id', 'first_name', 'last_name', 'full_name', 'display_name',
            'email', 'phone', 'company', 'website', 'notes',
            'preferred_contact_method', 'customer_type', 'status',
            'total_bookings', 'total_spent', 'average_booking_value', 'last_booking_date',
            'tags', 'is_vip', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'full_name', 'display_name', 'total_bookings', 'total_spent',
            'average_booking_value', 'last_booking_date', 'created_at', 'updated_at'
        ]


class BookingServiceSerializer(serializers.ModelSerializer):
    """Serializer for booking services relationship."""
    service_name = serializers.CharField(source='service.name', read_only=True)
    service_category = serializers.CharField(source='service.category.name', read_only=True)
    service_type = serializers.CharField(source='service.service_type', read_only=True)
    
    class Meta:
        model = BookingService
        fields = [
            'id', 'service', 'service_name', 'service_category', 'service_type',
            'quantity', 'price_per_unit', 'total_price', 'service_status',
            'notes', 'conflict_detected', 'conflict_resolution'
        ]
        read_only_fields = ['id', 'service_name', 'service_category', 'service_type']


class BookingSerializer(serializers.ModelSerializer):
    """Serializer for booking data with AI integration support."""
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True)
    booking_services = BookingServiceSerializer(many=True, read_only=True)
    total_price = serializers.SerializerMethodField()
    duration_hours = serializers.SerializerMethodField()
    conflicts = serializers.SerializerMethodField()
    
    class Meta:
        model = Booking
        fields = [
            'id', 'title', 'description', 'start_time', 'end_time', 'all_day',
            'status', 'created_via', 'customer', 'customer_name', 'customer_email', 'customer_phone',
            'booking_services', 'total_price', 'duration_hours',
            'ai_session_id', 'ai_message_id', 'ai_confidence_score',
            'color', 'google_event_id', 'google_calendar_id',
            'recurrence_rule', 'parent_booking', 'recurrence_exception_dates',
            'notes', 'conflict_resolution_notes', 'conflicts',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'customer_name', 'customer_email', 'customer_phone',
            'booking_services', 'total_price', 'duration_hours', 'conflicts',
            'created_at', 'updated_at'
        ]
    
    def get_total_price(self, obj):
        return float(sum(bs.total_price for bs in obj.booking_services.all()))
    
    def get_duration_hours(self, obj):
        if obj.start_time and obj.end_time:
            duration = obj.end_time - obj.start_time
            return round(duration.total_seconds() / 3600, 2)
        return 0
    
    def get_conflicts(self, obj):
        # Get recent conflicts for this booking
        conflicts = ConflictLog.objects.filter(
            primary_booking=obj,
            resolution_status__in=['detected', 'escalated']
        ).order_by('-created_at')[:5]
        
        return [
            {
                'id': str(conflict.id),
                'type': conflict.conflict_type,
                'severity': conflict.severity,
                'description': conflict.description,
                'created_at': conflict.created_at.isoformat()
            }
            for conflict in conflicts
        ]


class CalendarEventSerializer(serializers.Serializer):
    """Simplified serializer for calendar event display."""
    id = serializers.UUIDField()
    title = serializers.CharField()
    start = serializers.DateTimeField(source='start_time')
    end = serializers.DateTimeField(source='end_time')
    allDay = serializers.BooleanField(source='all_day')
    color = serializers.CharField()
    status = serializers.CharField()
    created_via = serializers.CharField()
    
    # Customer info
    customer_name = serializers.CharField(source='customer.full_name')
    customer_email = serializers.CharField(source='customer.email')
    
    # Service info
    services = serializers.SerializerMethodField()
    categories = serializers.SerializerMethodField()
    
    # AI metadata
    ai_created = serializers.SerializerMethodField()
    ai_confidence = serializers.FloatField(source='ai_confidence_score')
    
    def get_services(self, obj):
        return [bs.service.name for bs in obj.booking_services.all()]
    
    def get_categories(self, obj):
        return list(set(bs.service.category.name for bs in obj.booking_services.all()))
    
    def get_ai_created(self, obj):
        return obj.created_via == 'ai_assistant'


class CalendarSettingsSerializer(serializers.ModelSerializer):
    """Serializer for calendar settings and preferences."""
    
    class Meta:
        model = CalendarSettings
        fields = [
            'user_id', 'default_view', 'week_start_day',
            'business_hours_start', 'business_hours_end', 'show_weekends',
            'visible_categories', 'category_display_settings',
            'color_scheme', 'custom_colors',
            'google_calendar_enabled', 'google_calendar_id', 'google_sync_direction',
            'last_google_sync',
            'ai_booking_auto_confirm', 'ai_confidence_threshold', 'ai_notification_preferences',
            'conflict_notifications', 'booking_reminders', 'auto_resolve_minor_conflicts',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'user_id', 'last_google_sync', 'google_access_token', 'google_refresh_token',
            'created_at', 'updated_at'
        ]
    
    def validate_ai_confidence_threshold(self, value):
        if not 0.0 <= value <= 1.0:
            raise serializers.ValidationError("Confidence threshold must be between 0.0 and 1.0")
        return value


class BookingCreateSerializer(serializers.Serializer):
    """Serializer for creating bookings via API."""
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    all_day = serializers.BooleanField(default=False)
    
    # Customer information
    customer_id = serializers.UUIDField(required=False)
    customer_email = serializers.EmailField(required=False)
    customer_data = serializers.DictField(required=False)
    
    # Services/equipment
    service_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1
    )
    service_quantities = serializers.DictField(
        child=serializers.IntegerField(min_value=1),
        required=False
    )
    
    # Additional options
    notes = serializers.CharField(required=False, allow_blank=True)
    color = serializers.CharField(max_length=7, required=False)
    auto_confirm = serializers.BooleanField(default=True)
    
    def validate(self, data):
        # Validate time range
        if data['end_time'] <= data['start_time']:
            raise serializers.ValidationError("End time must be after start time")
        
        # Validate customer information
        if not any([data.get('customer_id'), data.get('customer_email'), data.get('customer_data')]):
            raise serializers.ValidationError("Customer ID, email, or customer data is required")
        
        return data


class AvailabilityCheckSerializer(serializers.Serializer):
    """Serializer for availability checking."""
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    service_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1
    )
    exclude_booking_id = serializers.UUIDField(required=False)
    
    def validate(self, data):
        if data['end_time'] <= data['start_time']:
            raise serializers.ValidationError("End time must be after start time")
        return data


class ConflictLogSerializer(serializers.ModelSerializer):
    """Serializer for conflict logs."""
    primary_booking_title = serializers.CharField(source='primary_booking.title', read_only=True)
    conflicting_booking_title = serializers.CharField(source='conflicting_booking.title', read_only=True)
    affected_service_name = serializers.CharField(source='affected_service.name', read_only=True)
    
    class Meta:
        model = ConflictLog
        fields = [
            'id', 'conflict_type', 'primary_booking', 'primary_booking_title',
            'conflicting_booking', 'conflicting_booking_title',
            'affected_service', 'affected_service_name',
            'description', 'severity', 'resolution_status', 'resolution_notes',
            'resolved_by', 'resolved_at', 'created_at'
        ]
        read_only_fields = [
            'id', 'primary_booking_title', 'conflicting_booking_title',
            'affected_service_name', 'created_at'
        ] 