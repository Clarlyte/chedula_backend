import uuid
from django.db import models
from django.core.validators import RegexValidator
from django.utils import timezone


class Customer(models.Model):
    """
    Customer information for bookings and business relationships.
    Central hub for all customer data across the platform.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_id = models.UUIDField()  # Links to business owner's Supabase auth.users.id
    
    # Basic information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(
        max_length=20, 
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed."
            )
        ]
    )
    
    # Additional information
    company = models.CharField(max_length=200, blank=True)
    website = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    
    # Address information
    address_line_1 = models.CharField(max_length=255, blank=True)
    address_line_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, blank=True, default='US')
    
    # Customer preferences
    preferred_contact_method = models.CharField(
        max_length=20, 
        choices=[
            ('email', 'Email'),
            ('phone', 'Phone'),
            ('sms', 'SMS'),
            ('both', 'Email & Phone'),
            ('any', 'Any Method')
        ],
        default='email'
    )
    
    # Customer classification
    customer_type = models.CharField(
        max_length=20,
        choices=[
            ('individual', 'Individual'),
            ('business', 'Business'),
            ('organization', 'Organization')
        ],
        default='individual'
    )
    
    # Customer status and engagement
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('prospective', 'Prospective'),
            ('blocked', 'Blocked')
        ],
        default='active'
    )
    
    # Customer value tracking
    total_bookings = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    average_booking_value = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    last_booking_date = models.DateTimeField(null=True, blank=True)
    
    # Communication preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    marketing_emails = models.BooleanField(default=True)
    
    # AI Assistant integration
    ai_created = models.BooleanField(default=False)  # Created by AI assistant
    ai_session_id = models.UUIDField(null=True, blank=True)  # AI session that created this customer
    ai_confidence_score = models.FloatField(null=True, blank=True)  # AI confidence in data accuracy
    
    # Source tracking
    source = models.CharField(
        max_length=30,
        choices=[
            ('manual', 'Manual Entry'),
            ('ai_assistant', 'AI Assistant'),
            ('booking_link', 'Booking Link'),
            ('import', 'Data Import'),
            ('api', 'API'),
            ('referral', 'Referral')
        ],
        default='manual'
    )
    
    # Tags for flexible categorization
    tags = models.JSONField(default=list, blank=True)  # List of tag strings
    
    # Internal tracking
    is_vip = models.BooleanField(default=False)
    internal_notes = models.TextField(blank=True)  # Private notes not visible to customer
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_contact_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'customers'
        unique_together = ['user_id', 'email']
        indexes = [
            models.Index(fields=['user_id', 'status']),
            models.Index(fields=['email']),
            models.Index(fields=['first_name', 'last_name']),
            models.Index(fields=['company']),
            models.Index(fields=['customer_type', 'status']),
            models.Index(fields=['last_booking_date']),
            models.Index(fields=['total_spent']),
            models.Index(fields=['created_at']),
            models.Index(fields=['ai_created', 'source']),
        ]
        
        # Add database-level constraints
        constraints = [
            models.CheckConstraint(
                check=models.Q(total_bookings__gte=0),
                name='positive_total_bookings'
            ),
            models.CheckConstraint(
                check=models.Q(total_spent__gte=0),
                name='positive_total_spent'
            ),
            models.CheckConstraint(
                check=models.Q(average_booking_value__gte=0),
                name='positive_average_booking_value'
            ),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def full_name(self):
        """Return customer's full name."""
        return f"{self.first_name} {self.last_name}".strip()
    
    @property
    def display_name(self):
        """Return display name with company if available."""
        name = self.full_name
        if self.company:
            return f"{name} ({self.company})"
        return name
    
    @property
    def full_address(self):
        """Return formatted full address."""
        address_parts = []
        if self.address_line_1:
            address_parts.append(self.address_line_1)
        if self.address_line_2:
            address_parts.append(self.address_line_2)
        if self.city:
            city_state = self.city
            if self.state:
                city_state += f", {self.state}"
            if self.postal_code:
                city_state += f" {self.postal_code}"
            address_parts.append(city_state)
        if self.country and self.country != 'US':
            address_parts.append(self.country)
        return '\n'.join(address_parts)
    
    def update_booking_stats(self):
        """Update customer booking statistics."""
        from calendar_mgmt.models import Booking  # Import here to avoid circular imports
        
        bookings = Booking.objects.filter(
            customer=self,
            status__in=['confirmed', 'completed']
        )
        
        self.total_bookings = bookings.count()
        
        if self.total_bookings > 0:
            # Calculate total spent from booking services
            total_spent = 0
            for booking in bookings:
                booking_total = booking.booking_services.aggregate(
                    total=models.Sum('total_price')
                )['total'] or 0
                total_spent += booking_total
            
            self.total_spent = total_spent
            self.average_booking_value = total_spent / self.total_bookings
            self.last_booking_date = bookings.order_by('-start_time').first().start_time
        else:
            self.total_spent = 0
            self.average_booking_value = 0
            self.last_booking_date = None
        
        self.save(update_fields=[
            'total_bookings', 'total_spent', 'average_booking_value', 'last_booking_date'
        ])
    
    def add_tag(self, tag: str):
        """Add a tag to the customer."""
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.save(update_fields=['tags'])
    
    def remove_tag(self, tag: str):
        """Remove a tag from the customer."""
        if tag in self.tags:
            self.tags.remove(tag)
            self.save(update_fields=['tags'])
    
    def update_last_contact(self):
        """Update the last contact date to now."""
        self.last_contact_date = timezone.now()
        self.save(update_fields=['last_contact_date'])


class CustomerNote(models.Model):
    """Notes and interactions history for customers."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='customer_notes')
    user_id = models.UUIDField()  # User who created the note
    
    # Note content
    title = models.CharField(max_length=200, blank=True)
    content = models.TextField()
    
    # Note type and categorization
    note_type = models.CharField(
        max_length=20,
        choices=[
            ('general', 'General Note'),
            ('call', 'Phone Call'),
            ('email', 'Email'),
            ('meeting', 'Meeting'),
            ('complaint', 'Complaint'),
            ('feedback', 'Feedback'),
            ('follow_up', 'Follow Up'),
            ('ai_generated', 'AI Generated')
        ],
        default='general'
    )
    
    # AI integration
    ai_generated = models.BooleanField(default=False)
    ai_session_id = models.UUIDField(null=True, blank=True)
    
    # Priority and follow-up
    priority = models.CharField(
        max_length=10,
        choices=[
            ('low', 'Low'),
            ('normal', 'Normal'),
            ('high', 'High'),
            ('urgent', 'Urgent')
        ],
        default='normal'
    )
    
    # Follow-up tracking
    requires_follow_up = models.BooleanField(default=False)
    follow_up_date = models.DateTimeField(null=True, blank=True)
    follow_up_completed = models.BooleanField(default=False)
    
    # Visibility
    is_private = models.BooleanField(default=False)  # Private to the business owner
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'customer_notes'
        indexes = [
            models.Index(fields=['customer', 'created_at']),
            models.Index(fields=['note_type', 'created_at']),
            models.Index(fields=['requires_follow_up', 'follow_up_date']),
            models.Index(fields=['ai_generated', 'ai_session_id']),
        ]
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Note for {self.customer.full_name}: {self.title or self.content[:50]}"
