# Global storage for URLs per user
current_urls = {}
user_episodes = {} # user_id -> {'anime_title': title, 'episodes': [...], 'url': url}
user_search_results = {} # user_id -> search_results
user_range_data = {} # user_id -> {'start': int, 'end': int, 'selected_qualities': [], 'msg_id': int}

# ── Continue-watching & info lookups ──
user_watch_next = {}   # user_id -> [next_episode_urls] rendered in /history
user_ani_search = {}   # user_id -> anime name awaiting the "search & download" tap

# ── Ongoing auto-download toggle ─.─
# ongoing_enabled = False # Can be toggled via /settings
