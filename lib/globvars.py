# Global variables

# config_file will be set in main() from command line args
config_file = None

# config will be loaded from file when needed
config = None

groups_name_track = {}
groups_member_track = {}
users_track = {}
chat_history = {}  # Per-chat message history for AI context
responded_to_message_ids = {}  # Track which message IDs bot has responded to
