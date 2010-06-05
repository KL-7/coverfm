import config

# DUMP_LEVEL: -1, 0, 1 or 2.  Controls how much debug output is
# written to the logs by the internal dump() function during event
# recording.  -1 dumps nothing; 0 dumps one line of information; 1
# dumps more informat and 2 dumps the maximum amount of information.
# You would only need to change this if you were debugging the
# recording implementation.

appstats_DUMP_LEVEL = -1

# The following constants control the resolution and range of the
# memcache keys used to record information about individual requests.
# Two requests that are closer than KEY_DISTANCE milliseconds will be
# mapped to the same key (thus losing all information about the
# earlier of the two requests).  Up to KEY_MODULUS distinct keys are
# generated; after KEY_DISTANCE * KEY_MODULUS milliseconds the key
# values roll over.  Increasing KEY_MODULUS causes a proportional
# increase of the amount of data saved in memcache.  Increasing
# KEY_DISTANCE causes a requests during a larger timespan to be
# recorded, at the cost of increasing risk of assigning the same key
# to two adjacent requests.

appstats_KEY_DISTANCE = 100
appstats_KEY_MODULUS = 1000

# Numerical limits on how much information is saved for each event.
# MAX_STACK limits the number of stack frames saved; MAX_LOCALS limits
# the number of local variables saved per stack frame.  MAX_REPR
# limits the length of the string representation of each variable
# saved; MAX_DEPTH limits the nesting depth used when computing the
# string representation of structured variables (e.g. lists of lists).

appstats_MAX_STACK = 5
appstats_MAX_LOCALS = 10
appstats_MAX_REPR = 60
appstats_MAX_DEPTH = 4

# Timeout for memcache lock management, in seconds.

appstats_LOCK_TIMEOUT = 1

# Timezone offset.  This is used to convert recorded times (which are
# all in UTC) to local time.  The default is US/Pacific winter time.

appstats_TZOFFSET = -3 * 3600

# URL path (sans host) leading to the stats UI.  Should match app.yaml.

appstats_stats_url = '/stats'

# Fraction of requests to record.  Set this to a float between 0.0
# and 1.0 to record that fraction of all requests.

appstats_RECORD_FRACTION = config.APP_STATS_RECORD_FRACTION


def webapp_add_wsgi_middleware(app):
    if config.APP_STATS:
        from google.appengine.ext.appstats import recording
        app = recording.appstats_wsgi_middleware(app)
    return app