#!usr/bin/env python
# Author: Kirill Lashuk

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

from google.appengine.api.urlfetch import DownloadError
from google.appengine.api.images import BadImageError

import config

from libs import pylast


# Application models

class Permission(db.Model):
    email = db.StringProperty()

    def id(self):
        return self.key().id()

    @classmethod
    def authorized(cls):
        '''Return True if user is allowed to use the application.'''
        return users.is_current_user_admin() or cls.has_permission(users.get_current_user())

    @classmethod
    def has_permission(cls, user):
        return user is not None and Permission.all().filter('email =', user.email()).count() > 0

class TopArt(db.Model):
    '''Store user's topart information:
        nick - user's nick on last.fm;
        owner - user's UserProperty.
    '''
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
        '''Return url for this TopArt.'''
        return get_topart_url(self.nick, self.period,
                        self.width, self.height)

    def id(self):
        '''Return TopArt ID.'''
        return self.key().id()

    def __str__(self):
        return 'nick=%s, period=%s, size=%dx%d' % (self.nick,
                        self.period, self.width, self.height)


def get_topart_url(nick, period, w, h):
    '''Generate url for TopArt with specific parameters.'''
    return '/topart/%s/%s/%dx%d' % (nick, period, w, h)


##################################
## Application request handlers ##
##################################

class BaseRequestHandler(webapp.RequestHandler):
    '''Base request handler class. Add basic information about the user to the request.'''
    def generate(self, template_name, template_values=None):
        '''Generate html from template. Add some parameters to the teplate_values list:
            user_name       - current user name;
            user_is_admin   - True if current user is admin of the application;
            sign            - sign label text;
            sign_url        - sign in/out url;
            host            - application host name.'''
        sign_url, sign_label, user_name, user_is_admin, user_is_auth = get_user_info()
        host = self.request.host_url

        values = {'user_name': user_name,
                  'user_is_admin': user_is_admin,
                  'user_is_auth': user_is_auth,
                  'sign': sign_label,
                  'sign_url': sign_url,
                  'host': host}

        if template_values:
            values.update(template_values)

        root_dir = os.path.dirname(__file__)
        path = os.path.join(root_dir, 'templates', template_name)
        html = template.render(path, values, debug=config.DEBUG)
        self.response.out.write(html)

    @staticmethod
    def authorized_only(method):
        '''Decorate method in a such way that it will be processed only for authorized users.'''
        def wrapped(self, *args, **kwargs):
            if not Permission.authorized():
                user = users.get_current_user()
                if user:
                    logging.info('Unauthorized access from %s' % (user.email()))
                return self.redirect('/faq')
            else:
                method(self, *args, **kwargs)
        return wrapped

    @staticmethod
    def admin_only(method):
        '''Decorate method in a such way that it will be processed only for admin users.'''
        def wrapped(self, *args, **kwargs):
            if not users.is_current_user_admin():
                return self.redirect('/')
            else:
                method(self, *args, **kwargs)
        return wrapped


class MainPage(BaseRequestHandler):
    '''MainPage request.'''
    @BaseRequestHandler.authorized_only
    def get(self):
        self.generate('index.html')

    @BaseRequestHandler.authorized_only
    def post(self):
        if 'generate' not in self.request.POST:
            return self.redirect('/')

        nick = self.request.get('nick')
        period = self.request.get('period')
        w = int(self.request.get('width'))
        h = int(self.request.get('height'))
        if self.request.get('autoupd') == 'on':
            auto_upd = True
        else:
            auto_upd = False

        # try to get topart from cache or db
        topart = get_topart(nick, period, w, h, False)

        # generate requested topart if there is no one already
        if not topart:
            img, error = generate_topart(nick, period, w, h)

            if error:
                return self.generate('index.html', {'error': error})

            topart = TopArt(nick=nick, period=period, width=w, height=h)
            topart.owner = users.get_current_user()
            topart.image = img
            topart.auto_upd = auto_upd
            topart.put()
            #logging.info('new request for key=%s' % topart.key())
            #logging.info('memcache.set in MainPage')
            memcache.set(topart.url(), topart, config.EXPIRATION_TIME)

        self.redirect(topart.url())


class Permissions(BaseRequestHandler):
    '''MainPage request.'''
    @BaseRequestHandler.admin_only
    def get(self):
        permissions = Permission.all().fetch(10)
        self.generate('permissions.html', { 'permissions': permissions })

    @BaseRequestHandler.admin_only
    def post(self):
        email = self.request.get('email')

        if email and not Permission.all().filter('email =', email).count():
            Permission(email=email).put()

        self.redirect('/permissions')


class DeletePermission(BaseRequestHandler):
    @BaseRequestHandler.admin_only
    def get(self, id):
        permission = Permission.get_by_id(int(id))

        if not permission:
            logging.error('''DELETE ERROR: Failed to delete id=%d -
                    missing permission''' % id)

        logging.info('DELETED: %s permission' % permission)
        permission.delete()
        self.redirect('/permissions')


class FAQ(BaseRequestHandler):
    def get(self):
        self.generate('faq.html')


class TopArtImage(BaseRequestHandler):
    def get(self, nick, period, width, height):
        width = int(width)
        height = int(height)
        topart = get_topart(nick, period, width, height)
        if topart:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(topart.image)


class TopArtPage(BaseRequestHandler):
    @BaseRequestHandler.authorized_only
    def get(self, nick, period, width, height):
        width = int(width)
        height = int(height)
        topart = get_topart(nick, period, width, height)
        if topart:
            self.generate('topart_page.html', {'topart': topart, 'nick': topart.nick})
        else:
            self.redirect('/toparts')


class ManageTopArts(BaseRequestHandler):
    '''TopArts managing page request handler.'''
    @BaseRequestHandler.authorized_only
    def get(self):
        toparts = TopArt.all()
        if users.is_current_user_admin():
            toparts = toparts.order('last_upd_date')
            toparts = toparts.fetch(20)
        else:
            toparts = toparts.filter('owner =', users.get_current_user())
            toparts = toparts.order('-last_upd_date')
            toparts = toparts.fetch(10)

        self.generate('toparts.html', { 'toparts': toparts })


class UpdateAllTopArts(BaseRequestHandler):
    '''Add no more than config.UPDATE_LIMIT toparts to update task queue. Choose
    toparts, that arn't waiting for update and haven't been updated for the longest time.'''
    def get(self):
        logging.info('UPDATE all')
        self.fill_update_queue()
        if not self.request.headers.get('X-AppEngine-Cron'):
            self.redirect('/toparts')

    def fill_update_queue(self):
        toparts = TopArt.all()
        toparts = toparts.filter('auto_upd =', True)
        toparts = toparts.filter('wait_for_upd =', False)
        toparts = toparts.order('last_upd_date')
        toparts = toparts.fetch(1000)

        #logging.info('UPDATE fill taskqueue (size=%d)' % toparts.count())

        tasks = [taskqueue.Task(url='/ad/update/%d' % topart.id()) for topart in toparts]

        set_wait_for_upd(toparts, True)

        for task in tasks:
            task.add('update')


class ResetAllWaitingUpdates(BaseRequestHandler):
    '''Reset all toparts that are waiting for update, so they won't be skiped while updating.'''
    def get(self):
        toparts = TopArt.all().filter('wait_for_upd =', True)
        set_wait_for_upd(toparts, False)
        logging.info('RESET all')
        return self.redirect('/toparts')


class UpdateTopArtRequestHandler(BaseRequestHandler):
    def update_topart(self, topart):
        img, error = generate_topart(topart.nick, topart.period,
                        topart.width, topart.height)
        if not error:
            topart.image = img
            topart.last_upd_date = datetime.datetime.now()
            #logging.info('memcache.delete in UpdateTopArts')
            memcache.delete(topart.url())
            logging.info('UPDATED %s' % topart)
            return True
        else:
            logging.error('''UPDATE ERROR: %s\n Failed to update
                            %s  - generating error''' % (error, topart.id()))
            return False


class UpdateTopArt(UpdateTopArtRequestHandler):
    @BaseRequestHandler.authorized_only
    def get(self, id):
        topart = TopArt.get_by_id(int(id))
        if not topart:
            return self.redirect('/toparts')
        has_access = users.is_current_user_admin() or users.get_current_user() == topart.owner
        if has_access and self.update_topart(topart):
            topart.put()
            return self.redirect(topart.url())
        else:
            return self.redirect('/toparts')


class UpdateTopArtTask(UpdateTopArtRequestHandler):
    def post(self, id):
        #logging.info(self.request.headers)
        if self.request.headers.get('X-AppEngine-TaskName'):
            topart = TopArt.get_by_id(int(id))
            if not topart:
                logging.error('''UPDATE ERROR: Failed to update id=%d -
                                missing previous topart''' % id)

            if topart.wait_for_upd:
                self.update_topart(topart)
                topart.wait_for_upd = False
                topart.put()
        else:
            return self.redirect('/')


class DeleteTopArt(BaseRequestHandler):
    @BaseRequestHandler.authorized_only
    def get(self, id):
        topart = TopArt.get_by_id(int(id))

        if not topart:
            logging.error('''DELETE ERROR: Failed to delete id=%d -
                    missing topart''' % id)
            return self.redirect('/')

        if not (users.is_current_user_admin() or users.get_current_user() == topart.owner):
            return self.redirect('/')

        logging.info('DELETED: %s' % topart)
        topart.delete()
        self.redirect('/toparts')


# Useful functions

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
#    return link is not None and 'default_album' not in link
#    if 'last' not in link: logging.info(link)
    return link is not None and 'default_album' not in link and 'last' in link


def get_arts_urls(nick, period=pylast.PERIOD_OVERALL, num=5,
                        size=config.COVER_SIZE):
    net = pylast.get_lastfm_network(api_key=config.LASTFM_API_KEY)
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
    arts_urls, error = get_arts_urls(nick, period, w * h, req_size)

    if arts_urls and not error:
        if len(arts_urls) < w * h:
            if len(arts_urls) >= w:
                h = len(arts_urls) // w
                arts_urls = arts_urls[:w * h]
            else:
                h = 1
                w = len(arts_urls)

        try:
            imgs = []
            for i in xrange(h):
                for j in xrange(w):
                    url = arts_urls[i * w + j]
                    img = urlfetch.Fetch(url).content
                    img = images.resize(img, size, size, images.JPEG)
                    imgs.append((img, size * j, size * i, 1.0, images.TOP_LEFT))
            if imgs:
                width = w * size
                height = h * size
                topart = composite_arts(imgs, width, height)
            else:
                error = 'Failed to fetch images'
        except DownloadError, e:
            logging.error('DownloadError: %s (url - "%s")' % (e, url))
            error = 'Failed to fetch image ' + url
        except BadImageError, e:
            logging.error('BadImageError: %s (url - "%s")' % (e, url))
            error = 'Failed to process image ' + url
    else:
        error = 'Topart generating failed'

    return topart, error


def opt_size(size):
    '''Return optimal pylast size constant based on required artwork size.
    Sizes are:
        COVER_SMALL = 0         - 34x34 px
        COVER_MEDIUM = 1        - 64x64 px
        COVER_LARGE = 2         - 126x126 px
        COVER_EXTRA_LARGE = 3   - 300x300 px'''

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


def get_user_info():
    '''Gather user information and generate sign in/out url.'''
    user = users.get_current_user()

    if user:
        sign_url = users.create_logout_url('/')
        sign_label = 'Sign out'
        user_name = users.get_current_user().email()
        is_admin = users.is_current_user_admin()
        is_auth = Permission.authorized()
    else:
        sign_url = users.create_login_url('/')
        sign_label = 'Sign in'
        user_name = ''
        is_admin = False
        is_auth = False

    return sign_url, sign_label, user_name, is_admin, is_auth


# Application instance

application = webapp.WSGIApplication(
                        [
                            ('/', MainPage),
                            ('/faq', FAQ),
                            ('/update/(\d+)', UpdateTopArt),
                            ('/ad/update/(\d+)', UpdateTopArtTask),
                            ('/ad/update/all', UpdateAllTopArts),
                            ('/ad/reset/all', ResetAllWaitingUpdates),
                            ('/delete/(\d+)', DeleteTopArt),
                            ('/toparts', ManageTopArts),
                            ('/topart/(.*)/(.*)/(\d+)x(\d+).jpg', TopArtImage),
                            ('/topart/(.*)/(.*)/(\d+)x(\d+)', TopArtPage),
                            ('/permissions', Permissions),
                            ('/permission/delete/(\d+)', DeletePermission)
                        ],
                        debug=config.DEBUG)

# Application main function

def main():
    run_wsgi_app(application)


if __name__ == '__main__':
    main()
