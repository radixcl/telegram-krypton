# AI Integration Module
# OpenAI-compatible API client with context management

import requests
import logging

logger = logging.getLogger(__name__)

def call_ai_api(context_messages, query, config):
    """
    Call OpenAI-compatible API with chat context.
    
    Args:
        context_messages: List of dicts with 'author', 'text', 'timestamp'
        query: The user's question/message
        config: AI configuration (url, model_id, api_key, context_size)
    
    Returns:
        AI response text or None on error
    """
    ai_url = config.get('ai_api_url')
    ai_model = config.get('ai_model_id')
    api_key = config.get('ai_api_key')
    system_prompt = config.get('ai_system_prompt', """You are a helpful AI assistant. Answer the user's question based on the conversation context provided.
    
Keep responses concise and relevant. If the context doesn't contain relevant information, do your best to help based on your knowledge.

Format your response naturally as if you're participating in the conversation.""")
    
    if not all([ai_url, ai_model, api_key]):
        logger.error("AI configuration incomplete")
        return None
    
    # Build conversation history
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    # Add context messages (last N messages)
    for msg in context_messages:
        role = "user" if msg.get('author') != "You" else "assistant"
        messages.append({
            "role": role,
            "content": f"{msg['author']}: {msg['text']}"
        })
    
    # Add the current query
    messages.append({"role": "user", "content": query})
    
    # Build headers (OpenRouter requires additional headers)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Telegram Bot"
    }
    
    try:
        response = requests.post(
            ai_url,
            headers=headers,
            json={
                "model": ai_model,
                "messages": messages,
                "max_tokens": 512,
                "temperature": 0.7
            },
            timeout=60
        )
        
        response.raise_for_status()
        result = response.json()
        
        # Extract content from response
        if 'choices' in result and len(result['choices']) > 0:
            return result['choices'][0]['message']['content']
        else:
            logger.error(f"Unexpected AI response format: {result}")
            return None
            
    except requests.exceptions.RequestException as e:
        logger.error(f"AI API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"AI API error: {e}")
        return None

def build_context(messages_list, context_size=50):
    """
    Build context from recent messages.

    Args:
        messages_list: List of message dicts (author, text, timestamp)
        context_size: Maximum number of messages to include

    Returns:
        Truncated list of recent messages
    """
    # Return last N messages (convert deque to list for Python 3.6 compatibility)
    if not isinstance(messages_list, list):
        messages_list = list(messages_list)
    return messages_list[-context_size:]
