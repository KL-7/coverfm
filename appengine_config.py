def webapp_add_wsgi_middleware(app):
    from google.appengine.ext.appstats import recording
    app = recording.appstats_wsgi_middleware(app)
    return app

appstats_MAX_STACK = 10
appstats_MAX_LOCALS = 10
appstats_MAX_REPR = 100
appstats_MAX_DEPTH = 10
