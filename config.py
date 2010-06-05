#!usr/bin/env python
# Author: Kirill Lashuk

import lastfm_api_info
from libs import pylast

# Application constants

DEBUG = True

# Appstats settings
APP_STATS = True
APP_STATS_RECORD_FRACTION = 0.4

# Last.fm api_key stored in lastfm_api_info
LASTFM_API_KEY = lastfm_api_info.API_KEY

# Final TopArt width
ABOUT_ME_WIDTH = 300

# Default fetched covers size
COVER_SIZE = pylast.COVER_LARGE

# Memcache expiration time
EXPIRATION_TIME = 0     # 4 * 24 * 3600 is 4 day in seconds

# Max number of toparts added to update list on UpdateAll
UPDATE_LIMIT = 500

# Batch db.put limit of entities
BATCH_PUT_LIMIT = 300   # Actual quota is 500 entities
