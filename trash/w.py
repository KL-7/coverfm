from libs import pylast

LASTFM_API_KEY = '0429cda1804dd4d7b1922aa90a1af646'

net = pylast.get_lastfm_network(api_key = LASTFM_API_KEY)
open('q.txt', 'w').write(net.get_album('Krypteria', 'My Fatal Kiss').get_cover_image(pylast.COVER_LARGE))