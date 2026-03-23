# AI Worker Module
# Background thread for non-blocking AI API calls with rate limiting

import threading
import time
import queue
import logging
from collections import deque

logger = logging.getLogger(__name__)

class AIWorker:
    """Background worker that processes AI requests with rate limiting."""

    def __init__(self, rate_limit_seconds=5, queue_maxsize=10, verbose=False):
        """
        Initialize AI worker.

        Args:
            rate_limit_seconds: Minimum seconds between AI API calls
            queue_maxsize: Maximum queue size (backpressure)
            verbose: Enable verbose/debug logging
        """
        self.rate_limit = rate_limit_seconds
        self.queue = queue.Queue(maxsize=queue_maxsize)
        self.last_request_time = 0
        self.lock = threading.Lock()
        self.worker_thread = None
        self.running = False
        self.bot = None
        self.verbose = verbose

    def start(self, bot_instance):
        """Start the background worker thread."""
        self.bot = bot_instance
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        logger.info("AI worker started with rate limit: %s seconds", self.rate_limit)

    def stop(self):
        """Stop the background worker thread."""
        self.running = False
        # Queue any remaining requests to be processed before exit
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        logger.info("AI worker stopped")

    def submit(self, chat_id, context_messages, query, config, reply_to_message_id=None, message_id=None):
        """
        Submit an AI request to the queue.

        Args:
            chat_id: Telegram chat ID
            context_messages: List of context messages
            query: User's question
            config: AI configuration
            reply_to_message_id: Optional message ID to reply to
            message_id: Original message ID (to track that we've responded to it)

        Returns:
            True if request was queued, False if queue is full
        """
        try:
            self.queue.put_nowait({
                'chat_id': chat_id,
                'context': context_messages,
                'query': query,
                'config': config,
                'reply_to_message_id': reply_to_message_id,
                'message_id': message_id
            })
            # Log context in debug mode
            logger.debug("AI request queued for chat %s", chat_id)
            if self.verbose:
                logger.debug("AI CONTEXT: chat_id=%s, query=%s", chat_id, query[:100] if query else None)
                logger.debug("AI CONTEXT: messages=%s", context_messages[-5:] if len(context_messages) > 5 else context_messages)
            return True
        except queue.Full:
            logger.warning("AI queue is full, request dropped for chat %s", chat_id)
            self._send_queue_full_message(chat_id)
            return False

    def _worker_loop(self):
        """Background worker loop that processes AI requests."""
        while self.running:
            try:
                # Wait for request with timeout
                request = self.queue.get(timeout=1)
            except queue.Empty:
                continue

            chat_id = request['chat_id']
            context_messages = request['context']
            query = request['query']
            config = request['config']
            reply_to_message_id = request.get('reply_to_message_id')
            message_id = request.get('message_id')

            # Apply rate limiting
            with self.lock:
                elapsed = time.time() - self.last_request_time
                if elapsed < self.rate_limit:
                    wait_time = self.rate_limit - elapsed
                    logger.info("Rate limiting: waiting %.1fs before AI request", wait_time)
                    time.sleep(wait_time)
                self.last_request_time = time.time()

            # Import ai module here to avoid circular imports
            import lib.ai as ai_module

            # Log context before API call (in verbose mode)
            if self.verbose:
                logger.debug("="*60)
                logger.debug("AI API CALL:")
                logger.debug("  chat_id: %s", chat_id)
                logger.debug("  query: %s", query[:200] if query else None)
                logger.debug("  context messages (last 10):")
                for i, msg in enumerate(context_messages[-10:] if len(context_messages) > 10 else context_messages):
                    logger.debug("    [%d] %s: %s", i, msg.get('author', 'unknown'), msg.get('text', '')[:100])
                logger.debug("  config: %s", request['config'].get('ai_model_id', 'N/A'))
                logger.debug("="*60)

            # Call AI API
            response_text = ai_module.call_ai_api(context_messages, query, config)

            # Send typing indicator JUST before sending response
            # This keeps the user informed that the bot is about to reply
            self._send_chat_action(chat_id, 'typing')
            
            # Small delay to ensure typing indicator is visible
            time.sleep(1)

            # Send response (with reply_to_message_id if set)
            if response_text:
                self._send_message(chat_id, response_text, reply_to_message_id, message_id)
            else:
                self._send_message(chat_id, "Sorry, I couldn't process that request.", reply_to_message_id, message_id)

    def _send_message(self, chat_id, text, reply_to_message_id=None, message_id=None):
        """Send a message through the bot."""
        if not self.bot:
            logger.error("self.bot == FALSE!")
            return False
        
        try:
            # DEBUG: Log the text before processing
            logger.debug(f"SENDING MESSAGE (chat_id={chat_id}, reply_to={reply_to_message_id}):")
            logger.debug(f"  Original text (repr): {repr(text[:200])}...")

            # Ensure text is a proper UTF-8 string
            # Handle potential encoding issues from AI API response
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='replace')
            elif isinstance(text, str):
                # Encode and decode to catch/fix any broken encoding
                try:
                    text = text.encode('utf-8').decode('utf-8')
                except UnicodeEncodeError:
                    text = text.encode('utf-8', errors='replace').decode('utf-8')

            # Ensure text is not wrapped in code formatting that would escape Markdown
            # Remove any accidental code block wrapping
            if text.startswith('`') and text.endswith('`'):
                text = text[1:-1].strip()
                logger.debug(f"  Removed code block wrapping")

            # Ensure text has proper newlines for Markdown parsing
            # Telegram requires \n between block elements
            import re
            text = re.sub(r'\n+', '\n\n', text)

            logger.debug(f"  Final text (repr): {repr(text[:200])}...")
            
            # Send message with explicit Markdown parse mode
            # Telegram needs this to render Markdown formatting
            self.bot.send_message(
                chat_id=chat_id, 
                text=text, 
                reply_to_message_id=reply_to_message_id,
                parse_mode='Markdown'
            )
            # Save bot response to chat history and mark message_id as responded_to
            self._save_bot_response(chat_id, text, message_id)
        except Exception as e:
            logger.error("Failed to send AI response: %s", e)

    def _send_chat_action(self, chat_id, action):
        """Send a chat action (typing, etc.) through the bot."""
        if self.bot:
            try:
                self.bot.send_chat_action(chat_id=chat_id, action=action)
            except Exception as e:
                logger.error("Failed to send chat action: %s", e)

    def _send_queue_full_message(self, chat_id):
        """Send a message when queue is full."""
        self._send_message(chat_id, "I'm busy processing another request. Please try again in a moment.")

    def _save_bot_response(self, chat_id, text, message_id=None):
        """
        Save bot response to chat history and mark message_id as responded_to.

        Args:
            chat_id: Telegram chat ID
            text: Bot's response text
            message_id: Original message ID (to mark as responded_to)
        """
        # Import globvars to access shared state
        import lib.globvars as globvars_module

        chat_id_str = str(chat_id)

        # Save bot response to chat history
        if chat_id_str in globvars_module.chat_history:
            msg_record = {
                'author': 'You',  # Bot
                'text': text,
                'timestamp': time.time()
            }
            globvars_module.chat_history[chat_id_str].append(msg_record)

        # Mark message_id as responded_to (to avoid duplicate responses)
        if message_id is not None:
            if chat_id_str not in globvars_module.responded_to_message_ids:
                globvars_module.responded_to_message_ids[chat_id_str] = set()
            globvars_module.responded_to_message_ids[chat_id_str].add(message_id)
