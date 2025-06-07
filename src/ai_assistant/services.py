"""
AI Assistant Service Layer

This module provides the core AI functionality for the scheduling assistant,
including OpenRouter API integration, entity extraction, intent recognition,
and action execution coordination.
"""

import json
import time
import logging
import requests
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction

from .models import ChatSession, ChatMessage, AIAction, ConversationContext
from users.authentication import SupabaseUser

logger = logging.getLogger(__name__)


class OpenRouterService:
    """
    Service class for interacting with OpenRouter API.
    Handles AI text generation, conversation management, and response parsing.
    """
    
    def __init__(self):
        self.api_key = settings.OPENROUTER_API_KEY
        self.base_url = settings.OPENROUTER_BASE_URL
        self.model = settings.OPENROUTER_MODEL
        self.settings = settings.AI_ASSISTANT_SETTINGS
        
        if not self.api_key:
            logger.error("OpenRouter API key not configured")
            raise ValueError("OpenRouter API key not configured")
    
    def generate_response(
        self, 
        prompt: str, 
        context: Dict[str, Any] = None,
        system_prompt: str = None
    ) -> Dict[str, Any]:
        """
        Generate AI response using OpenRouter API.
        
        Args:
            prompt: User input message
            context: Conversation context and history
            system_prompt: Custom system prompt (optional)
        
        Returns:
            Dictionary containing response text, metadata, and extracted actions
        """
        start_time = time.time()
        
        try:
            # Build message array
            messages = self._build_message_array(prompt, context, system_prompt)
            
            # Prepare request payload
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.settings["max_tokens"],
                "temperature": self.settings["temperature"],
                "stream": False
            }
            
            # Check cache first
            cache_key = self._generate_cache_key(payload)
            cached_response = cache.get(cache_key)
            if cached_response:
                logger.info("Using cached response for AI request")
                return cached_response
            
            # Make API request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://your-domain.com",  # Required by OpenRouter
                "X-Title": "AI Scheduling Assistant"
            }
            
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.settings["timeout"]
            )
            
            response.raise_for_status()
            response_data = response.json()
            
            # Process response
            processing_time = int((time.time() - start_time) * 1000)
            result = self._process_response(response_data, processing_time)
            
            # Cache successful responses
            cache.set(cache_key, result, self.settings["response_cache_ttl"])
            
            logger.info(f"AI response generated successfully in {processing_time}ms")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"OpenRouter API request failed: {e}")
            return {
                "success": False,
                "error": f"AI service temporarily unavailable: {str(e)}",
                "response_text": "I'm having trouble connecting to my AI service. Please try again in a moment.",
                "processing_time_ms": int((time.time() - start_time) * 1000)
            }
        except Exception as e:
            logger.error(f"Unexpected error in AI response generation: {e}")
            return {
                "success": False,
                "error": str(e),
                "response_text": "I encountered an unexpected error. Please try again.",
                "processing_time_ms": int((time.time() - start_time) * 1000)
            }
    
    def _build_message_array(
        self, 
        prompt: str, 
        context: Dict[str, Any] = None,
        system_prompt: str = None
    ) -> List[Dict[str, str]]:
        """Build the message array for OpenRouter API request."""
        
        messages = []
        
        # Add system prompt
        if not system_prompt:
            system_prompt = self._get_default_system_prompt()
        
        messages.append({
            "role": "system",
            "content": system_prompt
        })
        
        # Add conversation history from context
        if context and "message_history" in context:
            for msg in context["message_history"][-self.settings["context_window_size"]:]:
                messages.append({
                    "role": "user" if msg["sender_type"] == "user" else "assistant",
                    "content": msg["content"]
                })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": prompt
        })
        
        return messages
    
    def _get_default_system_prompt(self) -> str:
        """Get the default system prompt for the AI assistant."""
        return """You are an AI assistant for a service-based and equipment scheduling business. Your primary role is to help business owners manage their schedules, customers, services and equipment through natural language commands.

WORKFLOW PRIORITY:
1. When user provides equipment/service details with pricing: CREATE the service directly
2. For booking requests: Check if required services/equipment exist in the catalog first
3. If services/equipment don't exist for booking, ask user to create them first
4. Check if customer exists, create if needed
5. THEN: Create bookings with proper relationships
6. Update all relevant pages (calendar, customers, services)

AVAILABLE ACTIONS:
- create_service: Add new services or equipment to catalog (when user provides name + pricing)
- update_service: Modify service details or pricing
- check_service_exists: Verify if a service/equipment exists in catalog
- search_customer: Find existing customer information
- create_customer: Add new customers to the system
- update_customer: Modify customer information
- check_availability: Check equipment availability for specific dates
- create_booking: Create new equipment rental bookings (only after service and customer exist)
- update_booking: Modify existing bookings
- cancel_booking: Cancel bookings

BUSINESS WORKFLOW RULES:
1. When user says things like "Canon G7X Mark III, the rate is 700 per day" - CREATE the service immediately
2. For booking requests: NEVER create a booking without first confirming the service/equipment exists
3. Always ask "What equipment or service would you like to book?" if not specified
4. If equipment doesn't exist for booking, say: "I don't see [equipment name] in your catalog. Would you like me to help you add it first?"
5. For new customers, collect: name, email, phone at minimum
6. Always confirm booking details before creating

RESPONSE FORMAT:
Always respond in a conversational, helpful tone. When you identify an action to perform, include it in your response with the following JSON structure at the end:

ACTION_DATA:
{
  "action": "action_name",
  "parameters": {
    "key": "value"
  },
  "confidence": 0.95,
  "requires_confirmation": false
}

SERVICE CREATION EXAMPLES:

Example 1 - With pricing:
User: "Canon G7X Mark III, the rate is 700 per day"

Response: "I'll add the Canon G7X Mark III to your equipment catalog with a rental rate of ₱700 per day.

ACTION_DATA:
{
  "action": "create_service",
  "parameters": {
    "name": "Canon G7X Mark III",
    "service_type": "equipment",
    "price_per_day": 700,
    "description": "Canon G7X Mark III camera",
    "category": "Camera",
    "availability_type": "limited",
    "quantity_available": 1
  },
  "confidence": 0.95,
  "requires_confirmation": false
}
"

Example 2 - Without pricing (always create, price can be set later):
User: "add G7x to equipment catalog"

Response: "I'll add the Canon G7X to your equipment catalog. You can set the pricing later.

ACTION_DATA:
{
  "action": "create_service",
  "parameters": {
    "name": "Canon G7X",
    "service_type": "equipment",
    "price_per_day": 0,
    "description": "Canon G7X compact camera",
    "category": "Camera",
    "availability_type": "limited",
    "quantity_available": 1
  },
  "confidence": 0.9,
  "requires_confirmation": false
}
"

BOOKING WORKFLOW EXAMPLE:
User: "Book Camera A for John Smith next Monday"

Step 1 - Check service exists:
"Let me check if Camera A is available in your equipment catalog first.

ACTION_DATA:
{
  "action": "check_service_exists",
  "parameters": {
    "service_name": "Camera A"
  },
  "confidence": 0.9,
  "requires_confirmation": false
}
"

If service doesn't exist:
"I don't see Camera A in your equipment catalog. Would you like me to help you add it to your services first? You can provide the details like 'Camera A, rate is 500 per day' and I'll create it for you."

If service exists, Step 2 - Check/create customer:
"Great! Camera A is available. Now let me check if John Smith is in your customer database.

ACTION_DATA:
{
  "action": "search_customer",
  "parameters": {
    "name": "John Smith"
  },
  "confidence": 0.9,
  "requires_confirmation": false
}
"

Step 3 - Create booking (only after confirming service and customer exist):
"Perfect! I'll create the booking for John Smith to rent Camera A next Monday.

ACTION_DATA:
{
  "action": "create_booking",
  "parameters": {
    "customer_id": "customer_id_here",
    "service_id": "service_id_here",
    "start_date": "next Monday",
    "duration": "1 day",
    "title": "Camera A rental for John Smith"
  },
  "confidence": 0.95,
  "requires_confirmation": false
}
"

CUSTOMER CREATION EXAMPLES:

When user provides full name:
User: "create customer, Cale Espinosa name"
Response: "I'll create a customer profile for Cale Espinosa.

ACTION_DATA:
{
  "action": "create_customer",
  "parameters": {
    "first_name": "Cale",
    "last_name": "Espinosa",
    "email": "",
    "phone": "",
    "customer_type": "individual"
  },
  "confidence": 0.9,
  "requires_confirmation": false
}
"

When customer doesn't exist during booking:
"I don't see John Smith in your customer database. Let me create a customer profile for him.

ACTION_DATA:
{
  "action": "create_customer",
  "parameters": {
    "first_name": "John",
    "last_name": "Smith",
    "email": "",
    "phone": "",
    "customer_type": "individual"
  },
  "confidence": 0.8,
  "requires_confirmation": false
}
"

Always be helpful, ask clarifying questions when information is missing, and guide users through the proper workflow to maintain data integrity."""
    
    def _process_response(self, response_data: Dict[str, Any], processing_time: int) -> Dict[str, Any]:
        """Process OpenRouter API response and extract actions."""
        
        try:
            # Extract response text
            response_text = response_data["choices"][0]["message"]["content"]
            
            # Extract tokens used
            tokens_used = response_data.get("usage", {}).get("total_tokens", 0)
            
            # Parse actions from response
            actions = self._extract_actions_from_response(response_text)
            
            # Clean response text (remove action data)
            clean_text = self._clean_response_text(response_text)
            
            return {
                "success": True,
                "response_text": clean_text,
                "raw_response": response_text,
                "actions": actions,
                "tokens_used": tokens_used,
                "processing_time_ms": processing_time,
                "model_used": self.model
            }
            
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse OpenRouter response: {e}")
            return {
                "success": False,
                "error": "Failed to parse AI response",
                "response_text": "I received an unexpected response format. Please try again.",
                "processing_time_ms": processing_time
            }
    
    def _extract_actions_from_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Extract action data from AI response text."""
        actions = []
        
        try:
            # Look for ACTION_DATA: markers
            if "ACTION_DATA:" in response_text:
                # Split by ACTION_DATA: and process each action
                parts = response_text.split("ACTION_DATA:")
                for part in parts[1:]:  # Skip first part (before any ACTION_DATA)
                    # Extract JSON from this part
                    lines = part.strip().split("\n")
                    json_lines = []
                    in_json = False
                    
                    for line in lines:
                        if line.strip().startswith("{"):
                            in_json = True
                        if in_json:
                            json_lines.append(line)
                        if line.strip().endswith("}") and in_json:
                            break
                    
                    if json_lines:
                        try:
                            json_str = "\n".join(json_lines)
                            action_data = json.loads(json_str)
                            actions.append(action_data)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Failed to parse action JSON: {e}")
                            continue
            
        except Exception as e:
            logger.error(f"Error extracting actions from response: {e}")
        
        return actions
    
    def _clean_response_text(self, response_text: str) -> str:
        """Remove action data from response text for clean display."""
        if "ACTION_DATA:" in response_text:
            return response_text.split("ACTION_DATA:")[0].strip()
        return response_text.strip()
    
    def _generate_cache_key(self, payload: Dict[str, Any]) -> str:
        """Generate cache key for response caching."""
        # Create hash of the payload for caching
        import hashlib
        payload_str = json.dumps(payload, sort_keys=True)
        return f"ai_response:{hashlib.md5(payload_str.encode()).hexdigest()}"


class EntityExtractionService:
    """
    Service for extracting entities from user messages.
    Identifies dates, names, equipment, and other relevant business entities.
    """
    
    def extract_entities(self, text: str, context: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Extract entities from user input text.
        
        Args:
            text: User input message
            context: Conversation context for better extraction
        
        Returns:
            List of extracted entities with type, value, and confidence
        """
        entities = []
        
        # Basic entity extraction patterns
        entities.extend(self._extract_dates(text))
        entities.extend(self._extract_names(text))
        entities.extend(self._extract_equipment(text))
        entities.extend(self._extract_actions(text))
        
        return entities
    
    def _extract_dates(self, text: str) -> List[Dict[str, Any]]:
        """Extract date entities from text."""
        import re
        from dateutil import parser
        
        entities = []
        
        # Common date patterns
        date_patterns = [
            r'\b(next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b',
            r'\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b',
            r'\btomorrow\b',
            r'\btoday\b',
            r'\byesterday\b',
        ]
        
        for pattern in date_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                entities.append({
                    "type": "date",
                    "value": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                    "confidence": 0.8
                })
        
        return entities
    
    def _extract_names(self, text: str) -> List[Dict[str, Any]]:
        """Extract name entities from text."""
        import re
        
        entities = []
        
        # Simple name pattern (capitalized words)
        name_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b'
        
        matches = re.finditer(name_pattern, text)
        for match in matches:
            # Skip common words that aren't names
            name = match.group()
            if name.lower() not in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday', 'Camera']:
                entities.append({
                    "type": "person_name",
                    "value": name,
                    "start": match.start(),
                    "end": match.end(),
                    "confidence": 0.7
                })
        
        return entities
    
    def _extract_equipment(self, text: str) -> List[Dict[str, Any]]:
        """Extract equipment entities from text."""
        import re
        
        entities = []
        
        # Camera equipment patterns
        equipment_patterns = [
            r'\bcamera\s*[A-Z]?\b',
            r'\blens\s*kit\b',
            r'\btripod\b',
            r'\bflash\b',
            r'\bmicrophone\b',
            r'\bbattery\s*pack\b',
            r'\bmemory\s*card\b',
        ]
        
        for pattern in equipment_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                entities.append({
                    "type": "equipment",
                    "value": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                    "confidence": 0.8
                })
        
        return entities
    
    def _extract_actions(self, text: str) -> List[Dict[str, Any]]:
        """Extract action entities from text."""
        import re
        
        entities = []
        
        # Action patterns
        action_patterns = {
            'create_booking': [r'\b(book|schedule|reserve)\b'],
            'update_booking': [r'\b(change|modify|update|reschedule)\b'],
            'cancel_booking': [r'\b(cancel|delete|remove)\b'],
            'check_availability': [r'\b(check|available|availability)\b'],
            'create_customer': [r'\b(add|create|new)\s+(customer|client)\b'],
            'create_service': [r'\b(add|create|new)\s+(service|equipment)\b', r'\b(add|create)\s+.+\s+(camera|lens|equipment|service)\b', r'\brate\s+is\b', r'\bprice\s+is\b', r'\bcost\s+is\b'],
            'update_service': [r'\b(update|modify|change)\s+(service|equipment|price|rate)\b'],
            'check_service_exists': [r'\b(check|find|search)\s+(service|equipment)\b'],
        }
        
        for action_type, patterns in action_patterns.items():
            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    entities.append({
                        "type": "action",
                        "value": action_type,
                        "text": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                        "confidence": 0.7
                    })
        
        return entities


class AIAssistantService:
    """
    Main service class that coordinates AI processing, action execution,
    and conversation management for the scheduling assistant.
    """
    
    def __init__(self):
        self.openrouter = OpenRouterService()
        self.entity_extractor = EntityExtractionService()
    
    def process_message(
        self, 
        user: SupabaseUser, 
        message_content: str, 
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Process a user message through the AI assistant pipeline.
        
        Args:
            user: Authenticated user
            message_content: User's message content
            session_id: Optional session ID for conversation context
        
        Returns:
            Dictionary containing AI response and action results
        """
        start_time = time.time()
        
        try:
            with transaction.atomic():
                # Get or create session
                session = self._get_or_create_session(user.id, session_id)
                
                # Save user message
                user_message = self._save_user_message(
                    user.id, message_content, session.id
                )
                
                # Extract entities
                entities = self.entity_extractor.extract_entities(
                    message_content, session.context
                )
                user_message.add_entities(entities)
                
                # Get conversation context
                context = self._build_conversation_context(session)
                
                # Generate AI response
                ai_response = self.openrouter.generate_response(
                    message_content, context
                )
                
                if not ai_response["success"]:
                    return {
                        "success": False,
                        "error": ai_response["error"],
                        "user_message_id": user_message.id,
                        "session_id": str(session.id)
                    }
                
                # Save AI response message
                ai_message = self._save_ai_message(
                    user.id, ai_response, session.id, user_message.id
                )
                
                # Process actions
                action_results = []
                if ai_response.get("actions"):
                    action_results = self._process_actions(
                        user, ai_response["actions"], ai_message.id, session.id
                    )
                
                # Update session context
                self._update_session_context(session, entities, ai_response)
                
                processing_time = int((time.time() - start_time) * 1000)
                
                return {
                    "success": True,
                    "response_text": ai_response["response_text"],
                    "user_message_id": user_message.id,
                    "ai_message_id": ai_message.id,
                    "session_id": str(session.id),
                    "actions": action_results,
                    "entities": entities,
                    "processing_time_ms": processing_time
                }
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return {
                "success": False,
                "error": f"Failed to process message: {str(e)}",
                "processing_time_ms": int((time.time() - start_time) * 1000)
            }
    
    def _get_or_create_session(self, user_id: str, session_id: str = None) -> ChatSession:
        """Get existing session or create new one."""
        if session_id:
            try:
                return ChatSession.objects.get(id=session_id, user_id=user_id)
            except ChatSession.DoesNotExist:
                pass
        
        return ChatSession.objects.create(
            user_id=user_id,
            title=f"Chat Session {timezone.now().strftime('%Y-%m-%d %H:%M')}"
        )
    
    def _save_user_message(self, user_id: str, content: str, session_id: str) -> ChatMessage:
        """Save user message to database."""
        message = ChatMessage.objects.create(
            user_id=user_id,
            session_id=session_id,
            sender_type='user',
            content=content,
            status='sent'
        )
        
        # Update session
        session = ChatSession.objects.get(id=session_id)
        session.increment_message_count()
        
        return message
    
    def _save_ai_message(
        self, 
        user_id: str, 
        ai_response: Dict[str, Any], 
        session_id: str, 
        parent_message_id: int
    ) -> ChatMessage:
        """Save AI response message to database."""
        message = ChatMessage.objects.create(
            user_id=user_id,
            session_id=session_id,
            sender_type='ai',
            content=ai_response["response_text"],
            status='processed',
            parent_message_id=parent_message_id,
            metadata={
                "actions_count": len(ai_response.get("actions", [])),
                "tokens_used": ai_response.get("tokens_used", 0),
                "model_used": ai_response.get("model_used", "")
            }
        )
        
        # Set AI response data
        message.set_ai_response_data(
            ai_response.get("model_used", ""),
            ai_response.get("processing_time_ms", 0),
            ai_response.get("tokens_used", 0)
        )
        
        # Update session
        session = ChatSession.objects.get(id=session_id)
        session.increment_message_count()
        
        return message
    
    def _build_conversation_context(self, session: ChatSession) -> Dict[str, Any]:
        """Build conversation context for AI processing."""
        # Get recent messages
        recent_messages = ChatMessage.objects.filter(
            session_id=session.id
        ).order_by('-timestamp')[:self.openrouter.settings["context_window_size"]]
        
        message_history = []
        for msg in reversed(recent_messages):
            message_history.append({
                "sender_type": msg.sender_type,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            })
        
        # Get conversation context
        conversation_context = ConversationContext.get_context_for_session(str(session.id))
        
        return {
            "session_id": str(session.id),
            "message_history": message_history,
            "session_context": session.context,
            "conversation_context": conversation_context,
            "last_intent": session.last_intent,
            "active_workflow": session.active_workflow
        }
    
    def _process_actions(
        self, 
        user: SupabaseUser, 
        actions: List[Dict[str, Any]], 
        message_id: int, 
        session_id: str
    ) -> List[Dict[str, Any]]:
        """Process actions identified by AI."""
        action_results = []
        
        for action_data in actions:
            try:
                # Create action record
                ai_action = AIAction.objects.create(
                    message_id=message_id,
                    user_id=user.id,
                    session_id=session_id,
                    action_type=action_data.get("action", "unknown"),
                    target_model=self._determine_target_model(action_data.get("action", "")),
                    parameters=action_data.get("parameters", {}),
                    requires_confirmation=action_data.get("requires_confirmation", False)
                )
                
                # Execute action if not requiring confirmation
                if not ai_action.requires_confirmation:
                    result = self._execute_action(user, ai_action)
                    action_results.append(result)
                else:
                    ai_action.request_confirmation()
                    action_results.append({
                        "action_id": str(ai_action.id),
                        "action_type": ai_action.action_type,
                        "status": "pending_confirmation",
                        "message": "This action requires confirmation before execution."
                    })
                
            except Exception as e:
                logger.error(f"Error processing action {action_data}: {e}")
                action_results.append({
                    "status": "error",
                    "error": str(e),
                    "action_data": action_data
                })
        
        return action_results
    
    def _determine_target_model(self, action_type: str) -> str:
        """Determine target model based on action type."""
        mapping = {
            'create_booking': 'booking',
            'update_booking': 'booking',
            'cancel_booking': 'booking',
            'reschedule_booking': 'booking',
            'check_availability': 'booking',
            'create_customer': 'customer',
            'update_customer': 'customer',
            'search_customer': 'customer',
            'create_service': 'service',
            'update_service': 'service',
            'create_equipment': 'equipment',
            'update_equipment': 'equipment',
        }
        return mapping.get(action_type, 'system')
    
    def _execute_action(self, user: SupabaseUser, ai_action: AIAction) -> Dict[str, Any]:
        """Execute an AI action."""
        ai_action.mark_in_progress()
        
        try:
            # Import action executor
            from .action_executor import ActionExecutor
            executor = ActionExecutor()
            
            # Execute the action
            result = executor.execute_action(
                ai_action.action_type,
                ai_action.parameters,
                user.id
            )
            
            ai_action.mark_completed(result, result.get("id"))
            
            # Update session action count
            session = ChatSession.objects.get(id=ai_action.session_id)
            session.increment_action_count()
            
            return {
                "action_id": str(ai_action.id),
                "action_type": ai_action.action_type,
                "status": "completed",
                "message": result.get("message", "Action completed successfully"),
                "result": result
            }
            
        except Exception as e:
            ai_action.mark_failed(str(e))
            logger.error(f"Action execution failed: {e}")
            return {
                "action_id": str(ai_action.id),
                "action_type": ai_action.action_type,
                "status": "failed",
                "message": f"Action failed: {str(e)}",
                "error": str(e)
            }
    
    def _update_session_context(
        self, 
        session: ChatSession, 
        entities: List[Dict[str, Any]], 
        ai_response: Dict[str, Any]
    ):
        """Update session context with new information."""
        
        # Update last intent if actions were identified
        if ai_response.get("actions"):
            action_types = [action.get("action", "") for action in ai_response["actions"]]
            session.last_intent = ", ".join(action_types)
        
        # Store entities in context
        for entity in entities:
            if entity["type"] in ["person_name", "equipment", "date"]:
                context_key = f"last_{entity['type']}"
                session.context[context_key] = entity["value"]
        
        session.save(update_fields=['last_intent', 'context'])
    
    def get_chat_history(self, user_id: str, session_id: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get chat history for a user or session."""
        query = ChatMessage.objects.filter(user_id=user_id)
        
        if session_id:
            query = query.filter(session_id=session_id)
        
        messages = query.order_by('-timestamp')[:limit]
        
        return [
            {
                "id": msg.id,
                "session_id": str(msg.session_id) if msg.session_id else None,
                "sender_type": msg.sender_type,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
                "status": msg.status,
                "entities": msg.entities_extracted,
                "metadata": msg.metadata
            }
            for msg in reversed(messages)
        ] 