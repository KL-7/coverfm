#!usr/bin/env python
# -*- coding: utf-8 -*-
# author: Kirill Lashuk

from __future__ import division

import os
import logging
import datetime

from google.appengine.api import images
from google.appengine.api import memcache
from google.appengine.api import urlfetch
from google.appengine.api import users
from google.appengine.api.labs import taskqueue

from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

import config

from libs import pylast


# Application models

class TopArt(db.Model):
    nick = db.StringProperty()
    owner = db.UserProperty()
    period = db.StringProperty()
    width = db.IntegerProperty()
    height = db.IntegerProperty()
    image = db.BlobProperty()
    auto_upd = db.BooleanProperty(default=False)
    wait_for_upd = db.BooleanProperty(default=False)
    creation_date = db.DateTimeProperty(auto_now_add=True)
    last_upd_date = db.DateTimeProperty(auto_now_add=True)

    def url(self):
        return get_topart_url(self.nick, self.period,
                        self.width, self.height)

    def id(self):
        return self.key().id()

# Application request handlers

class BaseRequestHandler(webapp.RequestHandler):
    def generate(self, template_name, template_values=None, auth_req=True):
        sign_url, sign_label, user_name, user_is_admin = get_user_info()
        host = self.request.host_url
        
        if auth_req and not self.is_authorized():
            return self.redirect('/about')
                        
        values = {'user_name': user_name,
                  'user_is_admin': user_is_admin, 
                  'sign': sign_label,
                  'sign_url': sign_url,
                  'host': host}

        if template_values:
            values.update(template_values)

        root_dir = os.path.dirname(__file__)
        path = os.path.join(root_dir, 'templates', template_name)
        html = template.render(path, values, debug=config.DEBUG)
        self.response.out.write(html)

    def is_authorized(self):
        return users.is_current_user_admin()
 

class MainPage(BaseRequestHandler):
    def get(self):
        self.generate('index.html')

    def post(self):
        if 'generate' not in self.request.POST:
            self.redirect('/')
            return

        nick = self.request.get('nick')
        period = self.request.get('period')
        w = int(self.request.get('width'))
        h = int(self.request.get('height'))

        topart = get_topart(nick, period, w, h, False)

        if not topart:
            img, error = generate_topart(nick, period, w, h)

            if error:
                return self.generate('generated.html', {'error': error})

            topart = TopArt(nick=nick, period=period, width=w, height=h)
            topart.owner = users.get_current_user()
            topart.image = img
            topart.put()
            #logging.info('new request for key=%s' % topart.key())
            #logging.info('memcache.set in MainPage')
            memcache.set(topart.url(), topart, config.EXPIRATION_TIME)
    
        self.generate('generated.html', {'topart': topart, 'nick': nick})


class UserTopArt(webapp.RequestHandler):
    def get(self, nick, period, width, height):
        width = int(width)
        height = int(height)
        topart = get_topart(nick, period, width, height)
        if topart:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(topart.image)


class About(BaseRequestHandler):
    def get(self):
        self.generate('about.html', auth_req=False)


class ManageTopArts(BaseRequestHandler):
    def get(self):
        toparts = TopArt.all().order('-last_upd_date').fetch(100)
        #toparts = [{'topart': topart, 'url': topart.url()} for topart in toparts]
        self.generate('toparts.html', {'toparts': toparts})


def set_wait_for_upd(toparts, state):
    storage = []
    for topart in toparts:
        topart.wait_for_upd = state
        storage.append(topart)
        if len(storage) == config.BATCH_PUT_LIMIT:
            db.put(storage)
            storage = []

    if storage:
        db.put(storage)


class UpdateAllTopArts(webapp.RequestHandler):
    def get(self):
        toparts = TopArt.all().filter('auto_upd =', True)
        toparts = toparts.filter('wait_for_upd =', False)
        toparts = toparts.order('last_upd_date')

        #logging.info('UPDATE fill taskqueue (size=%d)' % toparts.count())

        tasks = [taskqueue.Task(url='/update', method='GET', 
                            params={'id': topart.id()}) for topart in toparts]

        set_wait_for_upd(toparts, True)

        for task in tasks:
            task.add('update')

        if not self.request.headers.get('X-AppEngine-Cron')
            self.redirect('/toparts')


class ResetAllWaitingUpdates(webapp.RequestHandler):
    def get(self):
        toparts = TopArt.all().filter('wait_for_upd =', True)
        set_wait_for_upd(toparts, False)
        self.redirect('/toparts')    


class UpdateTopArt(webapp.RequestHandler):
    def get(self):
        queue_request = True if self.request.headers.get('X-AppEngine-TaskName') else False
        topart = None

        try:
            id = int(self.request.get('id'))
            topart = TopArt.get_by_id(id)
        except ValueError:
            logging.info('id=%s is not a number' % self.request.get('id'))

        if not topart:
            logging.error('UPDATE ERROR: Failed to update %d - missing previous topart' % id)
            return
        
        info = 'nick=%s, period=%s, size=%dx%d'  % (topart.nick, 
                    topart.period, topart.width, topart.height)

        if queue_request:
            if topart.wait_for_upd:
                topart.wait_for_upd = False
            else:
                logging.info('UPDATE: topart id=%d is not waiting for update' % id)
                return

        img, error = generate_topart(topart.nick, topart.period, 
                        topart.width, topart.height)

        if not error:
            topart.image = img
            topart.last_upd_date = datetime.datetime.now()
            topart.put()
            #logging.info('memcache.delete in UpdateTopArts')
            memcache.delete(topart.url())
            logging.info('UPDATED %s' % info)
        else:
            if queue_request:
                topart.put()
            logging.error('UPDATE ERROR: %s\n Failed to update %s  - generating error' 
                            % (error, info))

        if not queue_request:
            self.redirect(topart.url())
                                                                                    

class UserAvatar(webapp.RequestHandler):
    def get(self, nick):
        url, error = get_user_avatar(nick)
        if error:
            self.response.out.write(error)
        else:
            img = urlfetch.Fetch(url).content
            #img = images.resize(img, 40, 40, images.JPEG)
            img = images.resize(img, 100, 100)
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(img)
  

# Useful functions

def get_topart_url(nick, period, w, h):
    return '/'.join(('topart', nick, period, '%dx%d.jpg' % (w, h)))


def get_topart(nick, period, w, h, use_cache=True):
    key = get_topart_url(nick, period, w, h)
    topart = memcache.get(key) if use_cache else None
    if not topart:
        toparts = TopArt.all()
        toparts.filter('nick =', nick)
        toparts.filter('period =', period)
        toparts.filter('width =', w)
        toparts.filter('height =', h)
        toparts = toparts.fetch(1)
        topart = toparts[0] if toparts else None
        if topart:
            #logging.info('memcache.set in get_topart')
            memcache.set(topart.url(), topart, config.EXPIRATION_TIME)
            #logging.info('new request for key=%s' % topart.key())

    return topart


def cover_filter(link):
    return link is not None and 'default_album' not in link


def get_arts_urls(nick, period=pylast.PERIOD_OVERALL, num=5,
                        size=config.COVER_SIZE):
    net = pylast.get_lastfm_network(api_key = config.LASTFM_API_KEY)
    arts_urls = []
    error = ''
    try:
        arts_urls = net.get_user(nick).get_top_albums_with_arts(period, size)
        arts_urls = [ta['image'] for ta in arts_urls]
        arts_urls = filter(cover_filter, arts_urls)[:num]
    except pylast.WSError, e:
        error = str(e)

    return arts_urls, error


def generate_topart(nick, period, w, h):
    size = config.ABOUT_ME_WIDTH // w
    req_size = opt_size(size)

    error = ''
    topart = None
    arts_urls, error = get_arts_urls(nick, period, w*h, req_size)

    if arts_urls and not error:
        if len(arts_urls) < w*h:
            if len(arts_urls) >= w:
                h = len(arts_urls) // w
                arts_urls = arts_urls[:w*h]
            else:
                h = 1
                w = len(arts_urls)

        imgs = []
        for i in xrange(h):
            for j in xrange(w):
                url = arts_urls[i*w+j]
                img = urlfetch.Fetch(url).content
                img = images.resize(img, size, size, images.JPEG)
                imgs.append((img, size*j, size*i, 1.0, images.TOP_LEFT))

        if imgs:
            width = w * size
            height = h * size
            topart = composite_arts(imgs, width, height)
        else:
            error = 'Failed to fetch images'
    else:
        error = 'Topart generating failed'            
    
    return topart, error


def opt_size(size):
    sizes = [34, 64, 126, 300]
    #sizes = [34, 64, 174, 300]

    for i, s in enumerate(sizes):
        if s >= size:
            return i
    
    return 3


def composite_arts(imgs, w, h):
    MAX_COMPOSITE_NUM = 16
    while len(imgs) > 1:
        comp = images.composite(imgs[:MAX_COMPOSITE_NUM], 
                        w, h, output_encoding=images.JPEG)
        imgs = [(comp, 0, 0, 1.0, images.TOP_LEFT)] + imgs[MAX_COMPOSITE_NUM:]

    return imgs[0][0]


def get_user_avatar(nick):
    net = pylast.get_lastfm_network(api_key = config.LASTFM_API_KEY)
    avatar_url = None
    error = ''
    try:
        avatar_url = net.get_user(nick).get_image()
    except pylast.WSError, e:
        error = str(e)

    return avatar_url, error


def get_user_info():
    user = users.get_current_user()
        
    if user:
        sign_url = users.create_logout_url('/')
        sign_label = 'Sign out'
        user_name = users.get_current_user().email()
        is_admin = users.is_current_user_admin()
    else:
        sign_url = users.create_login_url('/')
        sign_label = 'Sign in'
        user_name = ''
        is_admin = False

    return sign_url, sign_label, user_name, is_admin


# Application instance

application = webapp.WSGIApplication([('/', MainPage), 
                                      ('/toparts', ManageTopArts),
                                      ('/update', UpdateTopArt),
                                      ('/update/all', UpdateAllTopArts),
                                      ('/update/reset', ResetAllWaitingUpdates),
                                      ('/about', About),
                                      ('/avatar/(.*)', UserAvatar),
                                      ('/topart/(.*)/(.*)/(\d)x(\d).jpg', UserTopArt)],
                                     debug=config.DEBUG)

# Application main function

def main():
    run_wsgi_app(application)


if __name__ == "__main__":
    main()
