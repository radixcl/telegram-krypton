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
    
    def __init__(self, rate_limit_seconds=5, queue_maxsize=10):
        """
        Initialize AI worker.
        
        Args:
            rate_limit_seconds: Minimum seconds between AI API calls
            queue_maxsize: Maximum queue size (backpressure)
        """
        self.rate_limit = rate_limit_seconds
        self.queue = queue.Queue(maxsize=queue_maxsize)
        self.last_request_time = 0
        self.lock = threading.Lock()
        self.worker_thread = None
        self.running = False
        self.bot = None
        
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
    
    def submit(self, chat_id, context_messages, query, config):
        """
        Submit an AI request to the queue.
        
        Args:
            chat_id: Telegram chat ID
            context_messages: List of context messages
            query: User's question
            config: AI configuration
            
        Returns:
            True if request was queued, False if queue is full
        """
        try:
            self.queue.put_nowait({
                'chat_id': chat_id,
                'context': context_messages,
                'query': query,
                'config': config
            })
            logger.debug("AI request queued for chat %s", chat_id)
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
            
            # Show typing indicator
            self._send_chat_action(chat_id, 'typing')
            
            # Call AI API
            response_text = ai_module.call_ai_api(context_messages, query, config)
            
            # Send response
            if response_text:
                self._send_message(chat_id, response_text)
            else:
                self._send_message(chat_id, "Sorry, I couldn't process that request.")
    
    def _send_message(self, chat_id, text):
        """Send a message through the bot."""
        if self.bot:
            try:
                self.bot.send_message(chat_id=chat_id, text=text)
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
