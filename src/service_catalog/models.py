import uuid
from django.db import models
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.text import slugify
from django.utils import timezone
from decimal import Decimal


class ServiceCategory(models.Model):
    """
    Service categories for organizing services and equipment into sub-calendars.
    Provides hierarchical organization with visual customization.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_id = models.UUIDField()  # Links to business owner's Supabase auth.users.id
    
    # Basic Information
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent_category = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='subcategories'
    )
    
    # Visual Customization for Calendar Display
    color = models.CharField(max_length=7, default='#3B82F6')  # Hex color
    icon = models.CharField(max_length=50, blank=True)  # Icon identifier
    
    # Calendar Integration
    show_in_main_calendar = models.BooleanField(default=True)
    calendar_order = models.IntegerField(default=0)
    
    # Category Configuration
    is_active = models.BooleanField(default=True)
    category_type = models.CharField(
        max_length=50,
        choices=[
            ('equipment', 'Equipment'),
            ('service', 'Service'),
            ('package', 'Package'),
            ('mixed', 'Mixed')
        ],
        default='mixed'
    )
    
    # Booking Rules for Category
    default_booking_duration = models.DurationField(null=True, blank=True)
    max_advance_booking_days = models.IntegerField(default=365)
    min_advance_booking_hours = models.IntegerField(default=24)
    
    # Attribute Templates for Items in Category
    attribute_template = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'service_categories'
        unique_together = ['user_id', 'name']
        indexes = [
            models.Index(fields=['user_id', 'is_active', 'calendar_order']),
            models.Index(fields=['parent_category', 'calendar_order']),
            models.Index(fields=['category_type', 'is_active']),
        ]
        verbose_name_plural = 'Service Categories'
    
    def __str__(self):
        return self.name
    
    @property
    def hierarchy_name(self):
        """Return full hierarchical name."""
        if self.parent_category:
            return f"{self.parent_category.hierarchy_name} > {self.name}"
        return self.name
    
    def get_all_subcategories(self):
        """Get all subcategories recursively."""
        subcategories = list(self.subcategories.filter(is_active=True))
        for subcategory in self.subcategories.filter(is_active=True):
            subcategories.extend(subcategory.get_all_subcategories())
        return subcategories


class Service(models.Model):
    """
    Service offerings including equipment rental, consultations, delivery, setup, etc.
    Flexible model supporting various service types with complex pricing and availability.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_id = models.UUIDField()  # Links to business owner
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name='services')
    
    # Basic Information
    name = models.CharField(max_length=255)
    description = models.TextField()
    short_description = models.CharField(max_length=500, blank=True)
    slug = models.SlugField(max_length=255, blank=True)
    
    # Service Classification
    service_type = models.CharField(
        max_length=50,
        choices=[
            ('equipment', 'Equipment Rental'),
            ('consultation', 'Consultation'),
            ('delivery', 'Delivery Service'),
            ('setup', 'Setup Service'),
            ('training', 'Training Session'),
            ('maintenance', 'Maintenance Service'),
            ('package', 'Service Package')
        ],
        default='equipment'
    )
    
    # Pricing Structure
    base_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    price_per_hour = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    price_per_day = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    price_per_week = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # Availability Configuration
    availability_type = models.CharField(
        max_length=20,
        choices=[
            ('unlimited', 'Unlimited'),  # Can be booked multiple times simultaneously
            ('limited', 'Limited Quantity'),  # Has quantity constraints
            ('unique', 'Unique Item')  # Only one can be booked at a time
        ],
        default='limited'
    )
    quantity_available = models.IntegerField(default=1)
    
    # Duration Constraints
    min_booking_duration = models.DurationField(default=timezone.timedelta(hours=1))
    max_booking_duration = models.DurationField(default=timezone.timedelta(days=30))
    
    # Booking Rules
    advance_booking_days = models.IntegerField(
        default=365,
        help_text="Maximum days in advance that this service can be booked"
    )
    requires_approval = models.BooleanField(default=False)
    
    # Service Specifications (flexible JSON storage)
    specifications = models.JSONField(default=dict, blank=True)
    
    # Equipment-specific fields (for equipment type services)
    brand = models.CharField(max_length=100, blank=True)
    model = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    condition = models.CharField(
        max_length=20,
        choices=[
            ('excellent', 'Excellent'),
            ('good', 'Good'),
            ('fair', 'Fair'),
            ('poor', 'Poor')
        ],
        blank=True
    )
    
    # Deposit and Insurance
    requires_deposit = models.BooleanField(default=False)
    deposit_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    insurance_required = models.BooleanField(default=False)
    insurance_value = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    
    # Service Delivery
    is_mobile_service = models.BooleanField(default=False)
    travel_radius_km = models.IntegerField(null=True, blank=True)
    setup_time_minutes = models.IntegerField(null=True, blank=True)
    
    # Status and Visibility
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True)  # Show in public booking pages
    
    # SEO and Marketing
    search_tags = models.JSONField(default=list, blank=True)
    promotional_text = models.CharField(max_length=255, blank=True)
    
    # Analytics and Performance
    total_bookings = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('5.00'))]
    )
    
    # Maintenance (for equipment)
    last_maintenance_date = models.DateTimeField(null=True, blank=True)
    next_maintenance_due = models.DateTimeField(null=True, blank=True)
    maintenance_interval_days = models.IntegerField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Full-text search
    search_vector = SearchVectorField(null=True, blank=True)
    
    class Meta:
        db_table = 'services'
        indexes = [
            models.Index(fields=['user_id', 'category', 'is_active']),
            models.Index(fields=['service_type', 'is_active', 'is_public']),
            models.Index(fields=['is_featured', 'is_active']),
            models.Index(fields=['brand', 'model']),
            models.Index(fields=['availability_type', 'quantity_available']),
            GinIndex(fields=['search_vector']),
            models.Index(fields=['total_revenue', 'total_bookings']),
        ]
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(f"{self.name}-{self.brand}-{self.model}")
            self.slug = base_slug
            # Ensure unique slug
            counter = 1
            while Service.objects.filter(user_id=self.user_id, slug=self.slug).exists():
                self.slug = f"{base_slug}-{counter}"
                counter += 1
        
        # Save the object first (without search vector for new objects)
        is_new = self.pk is None
        if is_new:
            # For new objects, save without updating search_vector
            super().save(*args, **kwargs)
        else:
            # For existing objects, save normally
            super().save(*args, **kwargs)
        
        # Update search vector after the object exists in the database
        if is_new or 'update_search_vector' in kwargs:
            from django.contrib.postgres.search import SearchVector
            Service.objects.filter(pk=self.pk).update(
                search_vector=(
                    SearchVector('name', weight='A') +
                    SearchVector('brand', weight='A') +
                    SearchVector('model', weight='A') +
                    SearchVector('description', weight='B')
                )
            )
            # Refresh the object to get the updated search_vector
            if is_new:
                self.refresh_from_db(fields=['search_vector'])
    
    @property
    def display_name(self):
        """Return formatted display name with brand/model if available."""
        name_parts = [self.name]
        if self.brand:
            name_parts.append(f"({self.brand}")
            if self.model:
                name_parts.append(f"{self.model})")
            else:
                name_parts.append(")")
        elif self.model:
            name_parts.append(f"({self.model})")
        return " ".join(name_parts)
    
    @property
    def is_equipment(self):
        """Check if this service is equipment rental."""
        return self.service_type == 'equipment'
    
    def get_price_for_duration(self, duration_hours):
        """Calculate price for given duration."""
        if duration_hours <= 1 and self.price_per_hour:
            return self.price_per_hour
        elif duration_hours <= 24 and self.price_per_day:
            return self.price_per_day
        elif duration_hours <= 168 and self.price_per_week:  # 7 days
            return self.price_per_week
        else:
            # Calculate based on available rates
            if self.price_per_week and duration_hours > 168:
                weeks = duration_hours // 168
                remaining_hours = duration_hours % 168
                return (weeks * self.price_per_week) + self.get_price_for_duration(remaining_hours)
            elif self.price_per_day:
                days = max(1, duration_hours // 24)
                return days * self.price_per_day
            elif self.price_per_hour:
                return duration_hours * self.price_per_hour
            else:
                return self.base_price


class Package(models.Model):
    """
    Service and equipment packages with bundled pricing and availability.
    Supports complex package configurations with substitution rules.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user_id = models.UUIDField()  # Links to business owner
    category = models.ForeignKey(ServiceCategory, on_delete=models.CASCADE, related_name='packages')
    
    # Basic Information
    name = models.CharField(max_length=255)
    description = models.TextField()
    short_description = models.CharField(max_length=500, blank=True)
    slug = models.SlugField(max_length=255, blank=True)
    
    # Package Classification
    package_type = models.CharField(
        max_length=50,
        choices=[
            ('equipment', 'Equipment Bundle'),
            ('service', 'Service Bundle'),
            ('mixed', 'Equipment + Service'),
            ('themed', 'Themed Package')
        ],
        default='equipment'
    )
    
    # Pricing Strategy
    pricing_strategy = models.CharField(
        max_length=20,
        choices=[
            ('discount', 'Discount from Individual'),
            ('fixed', 'Fixed Package Price'),
            ('calculated', 'Dynamic Calculation')
        ],
        default='discount'
    )
    
    # Package Pricing
    package_price_daily = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    package_price_weekly = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    discount_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('100.00'))]
    )
    
    # Availability Rules
    min_rental_duration = models.DurationField(default=timezone.timedelta(days=1))
    max_rental_duration = models.DurationField(default=timezone.timedelta(days=30))
    max_concurrent_bookings = models.IntegerField(default=1)
    advance_booking_days = models.IntegerField(default=365)
    
    # Package Configuration
    allow_item_substitution = models.BooleanField(default=False)
    require_all_items = models.BooleanField(default=True)
    allow_partial_booking = models.BooleanField(default=False)
    
    # Status and Marketing
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    is_public = models.BooleanField(default=True)
    promotional_text = models.CharField(max_length=255, blank=True)
    
    # Analytics
    total_bookings = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_rating = models.DecimalField(
        max_digits=3, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(Decimal('0.00')), MaxValueValidator(Decimal('5.00'))]
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'packages'
        indexes = [
            models.Index(fields=['user_id', 'category', 'is_active']),
            models.Index(fields=['package_type', 'is_active', 'is_public']),
            models.Index(fields=['is_featured', 'is_active']),
            models.Index(fields=['total_revenue', 'total_bookings']),
        ]
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
            # Ensure unique slug
            counter = 1
            while Package.objects.filter(user_id=self.user_id, slug=self.slug).exists():
                self.slug = f"{slugify(self.name)}-{counter}"
                counter += 1
        super().save(*args, **kwargs)
    
    def calculate_individual_total(self):
        """Calculate total price if items were booked individually."""
        total = Decimal('0.00')
        for item in self.package_items.all():
            if item.service:
                total += item.service.base_price * item.quantity
        return total
    
    def calculate_package_savings(self):
        """Calculate savings amount compared to individual pricing."""
        individual_total = self.calculate_individual_total()
        if self.package_price_daily and individual_total > 0:
            savings = individual_total - self.package_price_daily
            return max(Decimal('0.00'), savings)
        elif self.discount_percentage and individual_total > 0:
            discount_amount = individual_total * (self.discount_percentage / 100)
            return discount_amount
        return Decimal('0.00')


class PackageItem(models.Model):
    """
    Items included in packages with quantity and substitution rules.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name='package_items')
    service = models.ForeignKey(Service, on_delete=models.CASCADE)
    
    # Item Configuration
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    is_optional = models.BooleanField(default=False)
    display_order = models.IntegerField(default=0)
    
    # Substitution Rules
    substitution_allowed = models.BooleanField(default=False)
    substitution_category = models.ForeignKey(
        ServiceCategory, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        help_text="Allow substitution within this category"
    )
    
    # Custom Pricing within Package
    custom_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Override individual service price for this package"
    )
    
    # Item Notes
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'package_items'
        unique_together = ['package', 'service']
        indexes = [
            models.Index(fields=['package', 'display_order']),
            models.Index(fields=['service', 'package']),
            models.Index(fields=['substitution_category']),
        ]
    
    def __str__(self):
        return f"{self.package.name} - {self.service.name} (x{self.quantity})"
    
    @property
    def effective_price(self):
        """Get the effective price for this item in the package."""
        if self.custom_price:
            return self.custom_price * self.quantity
        return self.service.base_price * self.quantity 