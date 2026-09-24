# AI Integration Module
# OpenAI-compatible API client with context management

import requests
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from lib import ai_tools

logger = logging.getLogger(__name__)

def _now(config):
    """Current date/time for the prompt (models don't know what day it is)."""
    try:
        now = datetime.now(ZoneInfo(config.get('ai_timezone', 'America/Santiago')))
    except Exception:  # no tzdata: fall back to the server's local time
        now = datetime.now().astimezone()
    return now.strftime('%A %Y-%m-%d %H:%M %Z')


def call_ai_api(context_messages, query, config, ctx=None):
    """
    Call OpenAI-compatible API with chat context.

    Args:
        context_messages: List of dicts with 'author', 'text', 'timestamp'
        query: The user's question/message
        config: AI configuration (url, model_id, api_key, context_size)
        ctx: who is asking ({'chat_id', 'user'}), for tools like reminders

    Returns:
        AI response text or None on error
    """
    # Validate config is not None
    if config is None:
        logger.error("AI configuration is None")
        return None

    ai_url = config.get('ai_api_url')
    ai_model = config.get('ai_model_id')
    api_key = config.get('ai_api_key')
    system_prompt = config.get('ai_system_prompt', """You are a helpful AI assistant. Answer the user's question based on the conversation context provided.

Keep responses concise and relevant. If the context doesn't contain relevant information, do your best to help based on your knowledge.

Format your response naturally as if you're participating in the conversation.""")
    
    # Get retry and timeout configuration
    ai_timeout = config.get('ai_timeout', 30)  # Default: 30 seconds (LLMs are slow)
    ai_retries = config.get('ai_retries', 2)  # Default: 2 retries

    if not all([ai_url, ai_model, api_key]):
        logger.error("AI configuration incomplete")
        return None

    # Build conversation history
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\nCurrent date and time: {_now(config)}"}
    ]

    # Add context messages (last N messages)
    for msg in context_messages:
        if msg.get('author') == "You":
            # bot's own past replies: no "You:" prefix, or the model imitates it
            messages.append({"role": "assistant", "content": msg['text']})
        else:
            messages.append({"role": "user", "content": f"{msg['author']}: {msg['text']}"})

    # Add the current query
    messages.append({"role": "user", "content": query})

    # Build headers (OpenRouter requires additional headers)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Telegram Bot"
    }

    schemas = ai_tools.active_schemas(config, ctx) if config.get('ai_tools_enabled', False) else []
    max_rounds = config.get('ai_tools_max_rounds', 3)

    for round_ in range(max_rounds + 1):
        payload = {"model": ai_model, "messages": messages, "max_tokens": 512, "temperature": 0.7}
        if schemas and round_ < max_rounds:
            payload["tools"] = schemas
        elif round_ > 0:  # last round: no tools, force a text answer
            messages.append({"role": "user", "content": "No more tools available. Answer now with what you found."})
        message = _chat(ai_url, headers, payload, ai_timeout, ai_retries)
        if message is None:
            return None
        calls = message.get('tool_calls')
        if not calls:
            content = message.get('content')
            if content and '<tool_call>' in content:  # model wrote a call as text: don't show it
                logger.warning("AI answered with a raw tool call, dropping it")
                return None
            return content
        messages.append(message)
        for call in calls:
            messages.append({"role": "tool", "tool_call_id": call['id'], "content": ai_tools.run_tool(call, config, ctx)})
    return None


def _chat(url, headers, payload, timeout, retries):
    """POST one chat completion (retries on timeout/429). Returns the message dict or None."""
    for attempt in range(retries + 1):
        try:
            logger.debug("AI API request attempt %d/%d", attempt + 1, retries + 1)
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            if result.get('choices'):
                return result['choices'][0]['message']
            logger.error(f"Unexpected AI response format: {result}")
            return None

        except requests.exceptions.Timeout:
            logger.warning("AI API request timed out (%ds)", timeout)
            if attempt < retries:
                logger.info("Retrying... (%d/%d)", attempt + 1, retries)
                time.sleep(1)
                continue
            logger.error("AI API request failed after %d retries (timeout)", retries)
            return None

        except requests.exceptions.HTTPError as e:
            # 429 = rate limited: wait (honor Retry-After, max 30s) and retry
            if e.response is not None and e.response.status_code == 429 and attempt < retries:
                try:
                    wait = min(float(e.response.headers.get('Retry-After', 5)), 30)
                except ValueError:
                    wait = 5
                logger.warning("AI API rate limited (429), retrying in %.0fs (%d/%d)", wait, attempt + 1, retries)
                time.sleep(wait)
                continue
            logger.error(f"AI API request failed: {e}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"AI API request failed: {e}")
            return None
        except Exception as e:
            logger.error(f"AI API error: {e}")
            return None
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
