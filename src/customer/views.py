from django.shortcuts import render
from rest_framework import generics, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db.models import Q, Count, Sum
from users.authentication import SupabaseJWTAuthentication, require_authenticated_user
from .models import Customer, CustomerNote
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


class CustomerListCreateView(generics.ListCreateAPIView):
    """List and create customers."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = require_authenticated_user(self.request)
        return Customer.objects.filter(user_id=user.id).order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            
            # Get query parameters
            search = request.query_params.get('search', '')
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            sort_by = request.query_params.get('sort_by', '-created_at')
            
            # Base queryset
            customers = Customer.objects.filter(user_id=user.id)
            
            # Search functionality
            if search:
                customers = customers.filter(
                    Q(first_name__icontains=search) |
                    Q(last_name__icontains=search) |
                    Q(email__icontains=search) |
                    Q(phone__icontains=search) |
                    Q(business_name__icontains=search)
                )
            
            # Sorting
            if sort_by:
                customers = customers.order_by(sort_by)
            
            # Pagination
            total_count = customers.count()
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            customers_page = customers[start_index:end_index]
            
            # Serialize customers
            customers_data = []
            for customer in customers_page:
                customers_data.append({
                    'id': str(customer.id),
                    'first_name': customer.first_name,
                    'last_name': customer.last_name,
                    'email': customer.email,
                    'phone': customer.phone,
                    'business_name': customer.business_name,
                    'total_bookings': customer.total_bookings,
                    'total_spent': float(customer.total_spent),
                    'last_booking_date': customer.last_booking_date.isoformat() if customer.last_booking_date else None,
                    'customer_type': customer.customer_type,
                    'loyalty_tier': customer.loyalty_tier,
                    'created_at': customer.created_at.isoformat(),
                    'updated_at': customer.updated_at.isoformat()
                })
            
            return Response({
                'customers': customers_data,
                'count': len(customers_data),
                'total_count': total_count,
                'page': page,
                'page_size': page_size,
                'total_pages': (total_count + page_size - 1) // page_size
            })
            
        except Exception as e:
            logger.error(f"Error listing customers: {e}")
            return Response(
                {'error': 'Failed to retrieve customers'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def create(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            
            # Extract customer data
            customer_data = {
                'first_name': request.data.get('first_name', ''),
                'last_name': request.data.get('last_name', ''),
                'email': request.data.get('email', ''),
                'phone': request.data.get('phone', ''),
                'business_name': request.data.get('business_name', ''),
                'address': request.data.get('address', ''),
                'city': request.data.get('city', ''),
                'state': request.data.get('state', ''),
                'postal_code': request.data.get('postal_code', ''),
                'country': request.data.get('country', ''),
                'customer_type': request.data.get('customer_type', 'individual'),
                'preferred_contact_method': request.data.get('preferred_contact_method', 'email'),
                'notes': request.data.get('notes', ''),
                'marketing_consent': request.data.get('marketing_consent', False),
            }
            
            # Basic validation
            if not customer_data['first_name'] or not customer_data['last_name']:
                return Response(
                    {'error': 'First name and last name are required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check for duplicate email if provided
            if customer_data['email']:
                existing_customer = Customer.objects.filter(
                    user_id=user.id, 
                    email=customer_data['email']
                ).first()
                if existing_customer:
                    return Response(
                        {'error': 'Customer with this email already exists'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Create customer
            customer = Customer.objects.create(user_id=user.id, **customer_data)
            
            return Response({
                'id': str(customer.id),
                'first_name': customer.first_name,
                'last_name': customer.last_name,
                'email': customer.email,
                'message': 'Customer created successfully'
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating customer: {e}")
            return Response(
                {'error': 'Failed to create customer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CustomerDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update, or delete a customer."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_object(self):
        user = require_authenticated_user(self.request)
        return get_object_or_404(Customer, id=self.kwargs['pk'], user_id=user.id)
    
    def retrieve(self, request, *args, **kwargs):
        try:
            customer = self.get_object()
            
            # Get customer notes
            notes = customer.customer_notes.order_by('-created_at')
            notes_data = [{
                'id': str(note.id),
                'content': note.content,
                'note_type': note.note_type,
                'created_at': note.created_at.isoformat(),
                'updated_at': note.updated_at.isoformat()
            } for note in notes[:10]]  # Latest 10 notes
            
            return Response({
                'id': str(customer.id),
                'first_name': customer.first_name,
                'last_name': customer.last_name,
                'email': customer.email,
                'phone': customer.phone,
                'business_name': customer.business_name,
                'address': customer.address,
                'city': customer.city,
                'state': customer.state,
                'postal_code': customer.postal_code,
                'country': customer.country,
                'customer_type': customer.customer_type,
                'preferred_contact_method': customer.preferred_contact_method,
                'equipment_preferences': customer.equipment_preferences,
                'rental_history_summary': customer.rental_history_summary,
                'notes': customer.notes,
                'marketing_consent': customer.marketing_consent,
                'total_bookings': customer.total_bookings,
                'total_spent': float(customer.total_spent),
                'lifetime_value': float(customer.lifetime_value),
                'average_booking_value': float(customer.average_booking_value),
                'last_booking_date': customer.last_booking_date.isoformat() if customer.last_booking_date else None,
                'loyalty_tier': customer.loyalty_tier,
                'referral_source': customer.referral_source,
                'customer_notes': notes_data,
                'created_at': customer.created_at.isoformat(),
                'updated_at': customer.updated_at.isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error retrieving customer: {e}")
            return Response(
                {'error': 'Failed to retrieve customer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def update(self, request, *args, **kwargs):
        try:
            customer = self.get_object()
            
            # Update fields
            updateable_fields = [
                'first_name', 'last_name', 'email', 'phone', 'business_name',
                'address', 'city', 'state', 'postal_code', 'country',
                'customer_type', 'preferred_contact_method', 'notes',
                'marketing_consent', 'equipment_preferences', 'referral_source'
            ]
            
            for field in updateable_fields:
                if field in request.data:
                    setattr(customer, field, request.data[field])
            
            # Check for duplicate email if changed
            if 'email' in request.data and request.data['email']:
                existing_customer = Customer.objects.filter(
                    user_id=customer.user_id,
                    email=request.data['email']
                ).exclude(id=customer.id).first()
                
                if existing_customer:
                    return Response(
                        {'error': 'Customer with this email already exists'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            customer.save()
            
            return Response({
                'id': str(customer.id),
                'message': 'Customer updated successfully'
            })
            
        except Exception as e:
            logger.error(f"Error updating customer: {e}")
            return Response(
                {'error': 'Failed to update customer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def destroy(self, request, *args, **kwargs):
        try:
            customer = self.get_object()
            customer_name = f"{customer.first_name} {customer.last_name}"
            customer.delete()
            
            return Response({
                'message': f'Customer {customer_name} deleted successfully'
            })
            
        except Exception as e:
            logger.error(f"Error deleting customer: {e}")
            return Response(
                {'error': 'Failed to delete customer'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CustomerNotesListCreateView(generics.ListCreateAPIView):
    """List and create customer notes."""
    authentication_classes = [SupabaseJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = require_authenticated_user(self.request)
        customer_id = self.kwargs['customer_id']
        return CustomerNote.objects.filter(
            customer_id=customer_id, 
            user_id=user.id
        ).order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            customer_id = self.kwargs['customer_id']
            
            # Verify customer exists and belongs to user
            customer = get_object_or_404(Customer, id=customer_id, user_id=user.id)
            
            notes = self.get_queryset()
            notes_data = [{
                'id': str(note.id),
                'content': note.content,
                'note_type': note.note_type,
                'created_at': note.created_at.isoformat(),
                'updated_at': note.updated_at.isoformat()
            } for note in notes]
            
            return Response({
                'notes': notes_data,
                'count': len(notes_data),
                'customer': {
                    'id': str(customer.id),
                    'name': f"{customer.first_name} {customer.last_name}"
                }
            })
            
        except Exception as e:
            logger.error(f"Error listing customer notes: {e}")
            return Response(
                {'error': 'Failed to retrieve customer notes'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def create(self, request, *args, **kwargs):
        try:
            user = require_authenticated_user(request)
            customer_id = self.kwargs['customer_id']
            
            # Verify customer exists and belongs to user
            customer = get_object_or_404(Customer, id=customer_id, user_id=user.id)
            
            content = request.data.get('content', '')
            note_type = request.data.get('note_type', 'general')
            
            if not content:
                return Response(
                    {'error': 'Note content is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            note = CustomerNote.objects.create(
                customer=customer,
                user_id=user.id,
                content=content,
                note_type=note_type
            )
            
            return Response({
                'id': str(note.id),
                'content': note.content,
                'note_type': note.note_type,
                'created_at': note.created_at.isoformat(),
                'message': 'Note created successfully'
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating customer note: {e}")
            return Response(
                {'error': 'Failed to create customer note'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_search(request):
    """Advanced customer search."""
    try:
        user = require_authenticated_user(request)
        
        query = request.query_params.get('q', '')
        customer_type = request.query_params.get('customer_type')
        loyalty_tier = request.query_params.get('loyalty_tier')
        min_bookings = request.query_params.get('min_bookings')
        max_bookings = request.query_params.get('max_bookings')
        
        customers = Customer.objects.filter(user_id=user.id)
        
        if query:
            customers = customers.filter(
                Q(first_name__icontains=query) |
                Q(last_name__icontains=query) |
                Q(email__icontains=query) |
                Q(phone__icontains=query) |
                Q(business_name__icontains=query)
            )
        
        if customer_type:
            customers = customers.filter(customer_type=customer_type)
        
        if loyalty_tier:
            customers = customers.filter(loyalty_tier=loyalty_tier)
        
        if min_bookings:
            customers = customers.filter(total_bookings__gte=min_bookings)
        
        if max_bookings:
            customers = customers.filter(total_bookings__lte=max_bookings)
        
        customers = customers.order_by('-total_spent')[:50]  # Limit results
        
        customers_data = []
        for customer in customers:
            customers_data.append({
                'id': str(customer.id),
                'first_name': customer.first_name,
                'last_name': customer.last_name,
                'email': customer.email,
                'phone': customer.phone,
                'business_name': customer.business_name,
                'total_bookings': customer.total_bookings,
                'total_spent': float(customer.total_spent),
                'loyalty_tier': customer.loyalty_tier,
                'last_booking_date': customer.last_booking_date.isoformat() if customer.last_booking_date else None
            })
        
        return Response({
            'customers': customers_data,
            'count': len(customers_data),
            'query': query
        })
        
    except Exception as e:
        logger.error(f"Error searching customers: {e}")
        return Response(
            {'error': 'Failed to search customers'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_stats(request):
    """Get customer statistics."""
    try:
        user = require_authenticated_user(request)
        
        customers = Customer.objects.filter(user_id=user.id)
        
        stats = {
            'total_customers': customers.count(),
            'new_customers_this_month': customers.filter(
                created_at__month=timezone.now().month,
                created_at__year=timezone.now().year
            ).count(),
            'total_bookings': customers.aggregate(Sum('total_bookings'))['total_bookings__sum'] or 0,
            'total_revenue': float(customers.aggregate(Sum('total_spent'))['total_spent__sum'] or 0),
            'average_customer_value': 0,
            'customer_types': {},
            'loyalty_tiers': {}
        }
        
        if stats['total_customers'] > 0:
            stats['average_customer_value'] = stats['total_revenue'] / stats['total_customers']
        
        # Customer type breakdown
        type_breakdown = customers.values('customer_type').annotate(count=Count('customer_type'))
        for item in type_breakdown:
            stats['customer_types'][item['customer_type']] = item['count']
        
        # Loyalty tier breakdown
        tier_breakdown = customers.values('loyalty_tier').annotate(count=Count('loyalty_tier'))
        for item in tier_breakdown:
            stats['loyalty_tiers'][item['loyalty_tier']] = item['count']
        
        return Response(stats)
        
    except Exception as e:
        logger.error(f"Error getting customer stats: {e}")
        return Response(
            {'error': 'Failed to retrieve customer statistics'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
