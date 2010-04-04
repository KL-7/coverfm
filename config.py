#!usr/bin/env python
# -*- coding: utf-8 -*-
# author: Kirill Lashuk

from libs import pylast

# Application constants

DEBUG = True

LASTFM_API_KEY = '0429cda1804dd4d7b1922aa90a1af646'

ABOUT_ME_WIDTH = 300

COVER_SIZE = pylast.COVER_SMALL 

EXPIRATION_TIME = 4 * 24 * 3600 # 4 day in seconds

BATCH_PUT_LIMIT = 300 # Actual quota is 500 entities
