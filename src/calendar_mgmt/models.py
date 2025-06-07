import uuid
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.contrib.postgres.fields import JSONField

# Import Customer from the dedicated customer app
from customer.models import Customer
from service_catalog.models import Service, ServiceCategory




class Booking(models.Model):
    """Main booking model with AI assistant integration."""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('no_show', 'No Show'),
    ]
    
    CREATED_VIA_CHOICES = [
        ('manual', 'Manual Entry'),
        ('ai_assistant', 'AI Assistant'),
        ('booking_link', 'Booking Link'),
        ('api', 'API'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_id = models.UUIDField()  # Links to business owner's Supabase auth.users.id
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='bookings')
    
    # Booking details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    
    # Status and metadata
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    created_via = models.CharField(max_length=20, choices=CREATED_VIA_CHOICES, default='manual')
    
    # AI Assistant integration
    ai_session_id = models.UUIDField(null=True, blank=True)  # Links to AI chat session
    ai_message_id = models.BigIntegerField(null=True, blank=True)  # Links to specific AI message
    ai_confidence_score = models.FloatField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    
    # Visual customization
    color = models.CharField(max_length=7, blank=True)  # Hex color override
    
    # Google Calendar integration
    google_event_id = models.CharField(max_length=255, blank=True)
    google_calendar_id = models.CharField(max_length=255, blank=True)
    
    # Recurring events
    recurrence_rule = models.TextField(blank=True)  # iCalendar RRULE format
    parent_booking = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    recurrence_exception_dates = models.JSONField(default=list, blank=True)
    
    # Notes and conflict resolution
    notes = models.TextField(blank=True)
    conflict_resolution_notes = models.TextField(blank=True)
    last_conflict_check = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'bookings'
        indexes = [
            models.Index(fields=['user_id', 'start_time', 'end_time']),
            models.Index(fields=['customer', 'start_time']),
            models.Index(fields=['status', 'start_time']),
            models.Index(fields=['ai_session_id']),
            models.Index(fields=['parent_booking']),
            models.Index(fields=['created_via', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.customer.full_name}"


class BookingService(models.Model):
    """Services associated with a booking."""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='booking_services')
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='service_bookings')
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    
    # Pricing at time of booking (to preserve historical data)
    price_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Status tracking
    service_status = models.CharField(
        max_length=20,
        choices=[
            ('reserved', 'Reserved'),
            ('prepared', 'Prepared'),
            ('delivered', 'Delivered'),
            ('in_use', 'In Use'),
            ('returned', 'Returned'),
            ('damaged', 'Damaged'),
        ],
        default='reserved'
    )
    
    # Notes for specific service/equipment
    notes = models.TextField(blank=True)
    
    # Conflict tracking
    conflict_detected = models.BooleanField(default=False)
    conflict_resolution = models.CharField(max_length=255, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'booking_services'
        unique_together = ['booking', 'service']
        indexes = [
            models.Index(fields=['service', 'booking']),
            models.Index(fields=['conflict_detected']),
            models.Index(fields=['service_status']),
        ]
    
    def __str__(self):
        return f"{self.booking.title} - {self.service.name} (x{self.quantity})"


class CalendarSettings(models.Model):
    """User calendar preferences and settings."""
    VIEW_CHOICES = [
        ('day', 'Day View'),
        ('week', 'Week View'),
        ('month', 'Month View'),
    ]
    
    COLOR_SCHEME_CHOICES = [
        ('category_based', 'Color by Category'),
        ('service_based', 'Color by Service'),
        ('status_based', 'Color by Status'),
        ('custom', 'Custom Colors'),
    ]
    
    SYNC_DIRECTION_CHOICES = [
        ('both', 'Two-way Sync'),
        ('to_google', 'To Google Only'),
        ('from_google', 'From Google Only'),
        ('disabled', 'Sync Disabled'),
    ]
    
    user_id = models.UUIDField(unique=True)  # Links to Supabase auth.users.id
    
    # View preferences
    default_view = models.CharField(max_length=20, choices=VIEW_CHOICES, default='week')
    week_start_day = models.IntegerField(default=1, validators=[MinValueValidator(0), MaxValueValidator(6)])  # 0=Sunday
    business_hours_start = models.TimeField(default='08:00')
    business_hours_end = models.TimeField(default='18:00')
    show_weekends = models.BooleanField(default=True)
    
    # Sub-calendar preferences
    visible_categories = JSONField(default=list, blank=True)  # List of category IDs to show
    category_display_settings = JSONField(default=dict, blank=True)  # Per-category display settings
    
    # Color coding preferences
    color_scheme = models.CharField(max_length=50, choices=COLOR_SCHEME_CHOICES, default='category_based')
    custom_colors = JSONField(default=dict, blank=True)
    
    # Google Calendar integration
    google_calendar_enabled = models.BooleanField(default=False)
    google_calendar_id = models.CharField(max_length=255, blank=True)
    google_sync_direction = models.CharField(max_length=20, choices=SYNC_DIRECTION_CHOICES, default='both')
    last_google_sync = models.DateTimeField(null=True, blank=True)
    google_access_token = models.TextField(blank=True)  # Encrypted token storage
    google_refresh_token = models.TextField(blank=True)  # Encrypted token storage
    
    # AI Assistant preferences
    ai_booking_auto_confirm = models.BooleanField(default=False)  # Auto-confirm AI bookings
    ai_confidence_threshold = models.FloatField(
        default=0.8,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    ai_notification_preferences = JSONField(default=dict, blank=True)
    
    # Notification preferences
    conflict_notifications = models.BooleanField(default=True)
    booking_reminders = models.BooleanField(default=True)
    auto_resolve_minor_conflicts = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'calendar_settings'
    
    def __str__(self):
        return f"Calendar Settings for User {self.user_id}"


class ConflictLog(models.Model):
    """Log of booking conflicts and their resolutions."""
    CONFLICT_TYPES = [
        ('service_overlap', 'Service/Equipment Overlap'),
        ('time_conflict', 'Time Conflict'),
        ('availability_limit', 'Availability Limit Exceeded'),
        ('business_hours', 'Outside Business Hours'),
    ]
    
    RESOLUTION_STATUS = [
        ('detected', 'Detected'),
        ('resolved', 'Resolved'),
        ('ignored', 'Ignored'),
        ('escalated', 'Escalated'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_id = models.UUIDField()
    
    # Conflict details
    conflict_type = models.CharField(max_length=30, choices=CONFLICT_TYPES)
    primary_booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='primary_conflicts')
    conflicting_booking = models.ForeignKey(Booking, on_delete=models.CASCADE, null=True, blank=True, related_name='secondary_conflicts')
    affected_service = models.ForeignKey(Service, on_delete=models.CASCADE, null=True, blank=True)
    
    # Conflict details
    description = models.TextField()
    severity = models.CharField(
        max_length=20,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')],
        default='medium'
    )
    
    # Resolution
    resolution_status = models.CharField(max_length=20, choices=RESOLUTION_STATUS, default='detected')
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.CharField(max_length=50, blank=True)  # 'ai_assistant', 'manual', 'automatic'
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'conflict_logs'
        indexes = [
            models.Index(fields=['user_id', 'created_at']),
            models.Index(fields=['resolution_status', 'severity']),
            models.Index(fields=['primary_booking']),
        ]
    
    def __str__(self):
        return f"{self.conflict_type} - {self.primary_booking.title}"
