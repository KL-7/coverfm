#!usr/bin/env python
# -*- coding: utf-8 -*-
# author: Kirill Lashuk

import lastfm_api_info
from libs import pylast

# Application constants

DEBUG = True

# Appstats settings
APP_STATS = False
APP_STATS_RECORD_FRACTION = 0.3

# Last.fm api_key stored in lastfm_api_info
LASTFM_API_KEY = lastfm_api_info.API_KEY

# Final TopArt width
ABOUT_ME_WIDTH = 300

# Default fetched covers size
COVER_SIZE = pylast.COVER_SMALL 

# Memcache expiration time
EXPIRATION_TIME = 0     # 4 * 24 * 3600 is 4 day in seconds

# Batch db.put limit of entities
BATCH_PUT_LIMIT = 300   # Actual quota is 500 entities
