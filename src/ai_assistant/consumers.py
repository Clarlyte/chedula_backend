"""
WebSocket Consumer for AI Assistant Chat

This module handles real-time WebSocket connections for the AI assistant chat functionality,
including authentication, message processing, and real-time communication.
"""

import json
import logging
from typing import Dict, Any, Optional
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.utils import timezone
import jwt

from users.authentication import SupabaseUser
from .services import AIAssistantService
from .models import ChatSession, ChatMessage

logger = logging.getLogger(__name__)


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time AI assistant chat.
    Handles authentication, message processing, and real-time communication.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.session_id = None
        self.ai_service = AIAssistantService()
        self.authenticated = False
        
    async def connect(self):
        """Handle WebSocket connection."""
        # Get session ID from URL if provided
        self.session_id = self.scope.get('url_route', {}).get('kwargs', {}).get('session_id')
        
        # Accept connection first (authentication happens after)
        await self.accept()
        
        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection.established',
            'message': 'Connected to AI Assistant. Please authenticate.',
            'timestamp': timezone.now().isoformat()
        }))
        
        logger.info(f"WebSocket connection established from {self.scope.get('client', ['unknown'])[0]}")
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if self.authenticated and self.user:
            logger.info(f"WebSocket disconnected for user {self.user.id}, code: {close_code}")
        else:
            logger.info(f"Unauthenticated WebSocket disconnected, code: {close_code}")
    
    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type', 'unknown')
            
            # Handle different message types
            if message_type == 'authenticate':
                await self._handle_authentication(data)
            elif message_type == 'chat.message':
                await self._handle_chat_message(data)
            elif message_type == 'ping':
                await self._handle_ping(data)
            elif message_type == 'get_history':
                await self._handle_get_history(data)
            elif message_type == 'action.confirm':
                await self._handle_action_confirmation(data)
            else:
                await self._send_error(f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError:
            await self._send_error("Invalid JSON format")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
            await self._send_error("Internal server error")
    
    async def _handle_authentication(self, data: Dict[str, Any]):
        """Handle user authentication."""
        token = data.get('token', '')
        
        if not token:
            await self._send_error("Authentication token required")
            return
        
        try:
            # Authenticate using Supabase JWT
            user = await self._authenticate_token(token)
            
            if user:
                self.user = user
                self.authenticated = True
                
                await self.send(text_data=json.dumps({
                    'type': 'authentication.success',
                    'message': 'Successfully authenticated',
                    'user_id': user.id,
                    'session_id': self.session_id,
                    'timestamp': timezone.now().isoformat()
                }))
                
                logger.info(f"WebSocket authenticated for user {user.id}")
            else:
                await self._send_error("Invalid authentication token")
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await self._send_error("Authentication failed")
    
    async def _handle_chat_message(self, data: Dict[str, Any]):
        """Handle incoming chat messages."""
        if not self.authenticated:
            await self._send_error("Authentication required")
            return
        
        message_content = data.get('message', '').strip()
        if not message_content:
            await self._send_error("Message content cannot be empty")
            return
        
        # Send typing indicator
        await self.send(text_data=json.dumps({
            'type': 'ai.typing',
            'status': True,
            'timestamp': timezone.now().isoformat()
        }))
        
        try:
            # Process message with AI service
            result = await self._process_ai_message(message_content)
            
            # Send typing indicator off
            await self.send(text_data=json.dumps({
                'type': 'ai.typing',
                'status': False,
                'timestamp': timezone.now().isoformat()
            }))
            
            if result['success']:
                # Send AI response
                await self.send(text_data=json.dumps({
                    'type': 'chat.response',
                    'message': result['response_text'],
                    'user_message_id': result['user_message_id'],
                    'ai_message_id': result['ai_message_id'],
                    'session_id': result['session_id'],
                    'timestamp': timezone.now().isoformat(),
                    'metadata': {
                        'processing_time_ms': result.get('processing_time_ms', 0),
                        'entities': result.get('entities', []),
                        'actions_count': len(result.get('actions', []))
                    }
                }))
                
                # Send action feedback if any actions were performed
                if result.get('actions'):
                    for action in result['actions']:
                        await self.send(text_data=json.dumps({
                            'type': 'action.feedback',
                            'action_id': action.get('action_id'),
                            'status': action.get('status'),
                            'message': action.get('message', ''),
                            'result': action.get('result'),
                            'timestamp': timezone.now().isoformat()
                        }))
            else:
                await self._send_error(result.get('error', 'Failed to process message'))
                
        except Exception as e:
            logger.error(f"Error processing chat message: {e}")
            
            # Send typing indicator off
            await self.send(text_data=json.dumps({
                'type': 'ai.typing',
                'status': False,
                'timestamp': timezone.now().isoformat()
            }))
            
            await self._send_error("Failed to process your message. Please try again.")
    
    async def _handle_ping(self, data: Dict[str, Any]):
        """Handle ping messages for keepalive."""
        await self.send(text_data=json.dumps({
            'type': 'pong',
            'timestamp': timezone.now().isoformat()
        }))
    
    async def _handle_get_history(self, data: Dict[str, Any]):
        """Handle chat history requests."""
        if not self.authenticated:
            await self._send_error("Authentication required")
            return
        
        try:
            limit = min(data.get('limit', 50), 100)  # Max 100 messages
            session_id = data.get('session_id', self.session_id)
            
            history = await self._get_chat_history(self.user.id, session_id, limit)
            
            await self.send(text_data=json.dumps({
                'type': 'chat.history',
                'messages': history,
                'session_id': session_id,
                'count': len(history),
                'timestamp': timezone.now().isoformat()
            }))
            
        except Exception as e:
            logger.error(f"Error retrieving chat history: {e}")
            await self._send_error("Failed to retrieve chat history")
    
    async def _handle_action_confirmation(self, data: Dict[str, Any]):
        """Handle action confirmation from user."""
        if not self.authenticated:
            await self._send_error("Authentication required")
            return
        
        action_id = data.get('action_id')
        confirmed = data.get('confirmed', False)
        
        if not action_id:
            await self._send_error("Action ID required for confirmation")
            return
        
        try:
            # TODO: Implement action confirmation logic
            # This would involve finding the pending action and executing it if confirmed
            
            await self.send(text_data=json.dumps({
                'type': 'action.confirmed',
                'action_id': action_id,
                'confirmed': confirmed,
                'message': f"Action {'confirmed' if confirmed else 'cancelled'}",
                'timestamp': timezone.now().isoformat()
            }))
            
        except Exception as e:
            logger.error(f"Error handling action confirmation: {e}")
            await self._send_error("Failed to process action confirmation")
    
    async def _authenticate_token(self, token: str) -> Optional[SupabaseUser]:
        """Authenticate user using Supabase JWT token."""
        try:
            # Decode JWT token
            jwt_secret = settings.SUPABASE_JWT_SECRET
            if not jwt_secret:
                logger.error("Supabase JWT secret not configured")
                return None
            
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=['HS256'],
                audience='authenticated',
                options={
                    'verify_signature': True,
                    'verify_exp': True,
                    'verify_aud': True,
                    'require_exp': True,
                    'require_iat': True,
                    'require_sub': True
                }
            )
            
            # Create SupabaseUser instance
            user = SupabaseUser(payload)
            return user
            
        except jwt.ExpiredSignatureError:
            logger.warning("Expired JWT token in WebSocket authentication")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token in WebSocket authentication: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in WebSocket authentication: {e}")
            return None
    
    @database_sync_to_async
    def _process_ai_message(self, message_content: str) -> Dict[str, Any]:
        """Process message through AI service (database sync to async)."""
        return self.ai_service.process_message(
            self.user, 
            message_content, 
            self.session_id
        )
    
    @database_sync_to_async
    def _get_chat_history(self, user_id: str, session_id: str = None, limit: int = 50) -> list:
        """Get chat history (database sync to async)."""
        return self.ai_service.get_chat_history(user_id, session_id, limit)
    
    async def _send_error(self, error_message: str):
        """Send error message to client."""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'error': error_message,
            'timestamp': timezone.now().isoformat()
        }))
    
    # Group messaging methods (for future use with multiple users)
    
    async def chat_message(self, event):
        """Handle chat message from group."""
        await self.send(text_data=json.dumps({
            'type': 'chat.message',
            'message': event['message'],
            'sender': event.get('sender', 'system'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))
    
    async def notification(self, event):
        """Handle notification from group."""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'title': event.get('title', 'Notification'),
            'message': event['message'],
            'level': event.get('level', 'info'),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))