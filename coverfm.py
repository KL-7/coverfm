#!usr/bin/env python
# -*- coding: utf-8 -*-
# author: Kirill Lashuk

from __future__ import division

import os
import logging

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
    last_upd_date = db.DateTimeProperty(auto_now=True)

    def get_url(self):
        return get_topart_url(self.nick, self.period,
                        self.width, self.height)


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

        if topart is None:
            img, error = generate_topart(nick, period, w, h)

            if error:
                return self.response.out.write(error)

            topart = TopArt(nick=nick, period=period, width=w, height=h)
            topart.owner = users.get_current_user()
            topart.image = img
            topart.put()
            #logging.info('new request for key=%s' % topart.key())
            memcache.set(topart.get_url(), topart, config.EXPIRATION_TIME)
    
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
        toparts = TopArt.all().order('-creation_date').fetch(100)
        topart_urls = [topart.get_url() for topart in toparts]
        self.generate('toparts.html', {'topart_urls': topart_urls})


class UpdateTopArts(webapp.RequestHandler):
    def get(self):
        toparts = TopArt.all()
        toparts = toparts.filter('auto_upd =', True)
        toparts = toparts.filter('wait_for_upd =', False)
        toparts = toparts.order('last_upd_date')

        #logging.info('UPDATE fill taskqueue (size=%d)' % toparts.count())
        
        for topart in toparts:
            topart.wait_for_upd = True
            topart.put()
            '''params = {'nick': topart.nick, 'period': topart.period,
                      'width': topart.width, 'height': topart.height}
            taskqueue.Task(url='/update', params=params).add('update')'''
            taskqueue.Task(url='/update', params={'id': topart.key().id()}).add('update')

        self.redirect('/')
        

    def post(self):
        '''nick = self.request.get('nick')
        period = self.request.get('period')
        w = int(self.request.get('width'))
        h = int(self.request.get('height'))

        info = 'nick=%s, period=%s, w=%d, h=%d'  % (nick, period, w, h)

        #logging.info('UPDATING %s started' % info)

        topart = get_topart(nick, period, w, h, False)'''
        id = int(self.request.get('id'))
        topart = TopArt.get_by_id(id)
        if topart:
            logging.info('updating %s\'s topart with id=%s' % (topart.nick, id))
            img, error = generate_topart(topart.nick, topart.period, 
                            topart.width, topart.height)

            if error:
                logging.error('UPDATE ERROR: %s\n Failed to update %s' 
                                % (error, info))
            else:
                topart.image = img
                topart.wait_for_upd = False
                topart.put()
                memcache.set(topart.get_url(), topart, config.EXPIRATION_TIME)
                logging.info('UPDATED %s' % info)
        else:
            logging.error('UPDATE ERROR: failed to update %s' % info)
                                                                                    

class UserAvatar(webapp.RequestHandler):
    def get(self, nick):
        url, error = get_user_avatar(nick)
        if error:
            self.response.out.write(error)
        else:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(urlfetch.Fetch(url).content)
  

# Useful functions

def get_topart_url(nick, period, w, h):
    return '/'.join((nick, period, '%dx%d.jpg' % (w, h)))


def get_topart(nick, period, w, h, use_cache=True):
    key = get_topart_url(nick, period, w, h)
    topart = memcache.get(key) if use_cache else None
    if topart is None:
        toparts = TopArt.all()
        toparts.filter('nick =', nick)
        toparts.filter('period =', period)
        toparts.filter('width =', w)
        toparts.filter('height =', h)
        toparts = toparts.fetch(1)
        topart = toparts[0] if toparts else None
        if topart is not None:
            memcache.set(key, topart, config.EXPIRATION_TIME)
            #logging.info('new request for key=%s' % topart.key())

    return topart


def get_arts_urls(nick, period=pylast.PERIOD_OVERALL, num=5,
                        size=config.COVER_SIZE):
    net = pylast.get_lastfm_network(api_key = config.LASTFM_API_KEY)
    arts_urls = []
    error = ''
    try:
        arts_urls = net.get_user(nick).get_top_albums(period)
        arts_urls = [item['item'].get_cover_image(size) for item in arts_urls]
        arts_urls = filter(lambda x: x is not None, arts_urls)[:num]
    except pylast.WSError, e:
        error = str(e)

    return arts_urls, error


def generate_topart(nick, period, w, h):
    size = config.ABOUT_ME_WIDTH // w
    req_size = opt_size(size)

    #logging.info('GENERATE s=%(size)d, req_s=%(req_size)d' % locals())

    error = ''
    topart = None
    arts_urls, error = get_arts_urls(nick, period, w*h, req_size)

    if not error:
        imgs = []
        for i in xrange(h):
            for j in xrange(w):
                url = arts_urls[i*w+j]
                img = urlfetch.Fetch(url).content
                img = images.resize(img, size, size)
                imgs.append((img, size*j, size*i, 1.0, images.TOP_LEFT))

        if imgs:
            width = w * size
            height = h * size
            topart = composite_arts(imgs, width, height)
        else:
            error = 'Failed to fetch images'
    
    return topart, error


def opt_size(size):
    sizes = [34, 64, 174, 300]

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
                                      ('/update', UpdateTopArts),
                                      ('/about', About),

                                      ('/avatar/(.*)', UserAvatar),
                                      
                                      ('/(.*)/(.*)/(\d)x(\d).jpg', UserTopArt)],
                                     debug=config.DEBUG)

# Application main function

def main():
    run_wsgi_app(application)


if __name__ == "__main__":
    main()
