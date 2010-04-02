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
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

import config

from libs import pylast


# Application models

class TopArtsChart(db.Model):
    nick = db.StringProperty()
    owner = db.UserProperty()
    period = db.StringProperty()
    width = db.IntegerProperty()
    height = db.IntegerProperty()
    image = db.BlobProperty()
    creation_date = db.DateTimeProperty(auto_now_add=True)

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

        chart = get_chart(nick, period, w, h, False)
        if chart is None:
            size = config.ABOUT_ME_WIDTH // w
            arts_urls, error = get_user_top_arts(nick, period, w*h)
            if error:
                return self.response.out.write(error)

            img = generate_chart(arts_urls, w, h, size)
            chart = TopArtsChart(nick=nick, period=period, width=w, height=h)
            chart.owner = users.get_current_user()
            chart.image = img
            chart.put()
            logging.info('new request for key=%s' % chart.key())
            memcache.set(chart.get_url(), chart, config.EXPIRATION_TIME)
    
        self.generate('generated.html', {'topart': chart, 'nick': nick})


class UserTopArt(webapp.RequestHandler):
    def get(self, nick, period, width, height):
        width = int(width)
        height = int(height)
        chart = get_chart(nick, period, width, height)
        if chart:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(chart.image)


class About(BaseRequestHandler):
    def get(self):
        self.generate('about.html', auth_req=False)


class TopArts(BaseRequestHandler):
    def get(self):
        toparts = TopArtsChart.all().order('-creation_date').fetch(100)
        topart_urls = [topart.get_url() for topart in toparts]
        self.generate('toparts.html', {'topart_urls': topart_urls})


class TestPage(webapp.RequestHandler):
    def get(self):
        link = 'http://userserve-ak.last.fm/serve/126/25513267.jpg'
        img = images.Image(urlfetch.Fetch(link).content)
        img.resize(60, 60)
        img = img.execute_transforms(output_encoding=images.JPEG)
        self.response.headers['Content-Type'] = 'image/jpeg'
        self.response.out.write(img)


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


def get_chart(nick, period, w, h, use_cache=True):
    key = get_topart_url(nick, period, w, h)
    chart = memcache.get(key) if use_cache else None
    if chart is None:
        charts = TopArtsChart.all()
        charts.filter('nick =', nick)
        charts.filter('period =', period)
        charts.filter('width =', w)
        charts.filter('height =', h)
        charts = charts.fetch(1)
        chart = charts[0] if charts else None
        if chart is not None:
            memcache.set(key, chart, config.EXPIRATION_TIME)
            logging.info('new request for key=%s' % chart.key())
    '''else:
        logging.info('cache usage for key=%s' % chart.key())'''

    return chart


def get_user_top_arts(nick, period=pylast.PERIOD_OVERALL, num=5,
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


def generate_chart(img_urls, w, h, size):
    MAX_COMPOSITE_NUM = 16
    imgs = []
    for i in xrange(h):
        for j in xrange(w):
            url = img_urls[i*w+j]
            img = images.Image(urlfetch.Fetch(url).content)
            img.resize(size, size)
            img = img.execute_transforms(output_encoding=images.JPEG)
            imgs.append((img, size*j, size*i, 1.0, images.TOP_LEFT))
    res = None
    if imgs:
        res = imgs[0][0]
        while len(imgs) > 1:
            res = images.composite(imgs[:MAX_COMPOSITE_NUM], 
                            w*size, h*size, output_encoding=images.JPEG)
            imgs = [(res, 0, 0, 1.0, images.TOP_LEFT)] + imgs[MAX_COMPOSITE_NUM:]

    return images.composite(imgs, w*size, h*size, output_encoding=images.JPEG)


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
                                      ('/toparts', TopArts),
                                      ('/about', About),
                                      ('/test', TestPage),
                                      ('/avatar/(.*)', UserAvatar),
                                      ('/(.*)/(.*)/(\d)x(\d).jpg', UserTopArt)],
                                     debug=config.DEBUG)

# Application main function

def main():
    run_wsgi_app(application)


if __name__ == "__main__":
    main()
