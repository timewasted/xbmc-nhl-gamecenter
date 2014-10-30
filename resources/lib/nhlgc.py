import binascii
import cookielib
import m3u8
import os
import requests
import urllib
import xmltodict
try:
	import simplejson as json
except ImportError:
	import json
from datetime import date

class nhlgc(object):
	NETWORK_ERR_NON_200 = 'Received a non-200 HTTP response.'

	def __init__(self, username, password, rogers_login, cookies_file):
		self.urls = {
			'scoreboard':    'http://live.nhle.com/GameData/GCScoreboard/',
			'login':         'https://gamecenter.nhl.com/nhlgc/secure/login',
			'console':       'https://gamecenter.nhl.com/nhlgc/servlets/simpleconsole',
			'games-list':    'https://gamecenter.nhl.com/nhlgc/servlets/games',
			'publish-point': 'https://gamecenter.nhl.com/nhlgc/servlets/publishpoint',
			'archives-list': 'https://gamecenter.nhl.com/nhlgc/servlets/allarchives',
			'archives':      'https://gamecenter.nhl.com/nhlgc/servlets/archives',
			'highlights':    'http://video.nhl.com/videocenter/servlets/playlist',
		}
		self.username = username
		self.password = password
		self.rogers_login = rogers_login

		cookiejar = cookielib.LWPCookieJar(cookies_file)
		try:
			cookiejar.load(ignore_discard=True)
		except IOError:
			pass
		self.session = requests.Session()
		self.session.cookies = cookiejar
		self.session.headers.update({'User-Agent': 'iPad'})

		# NOTE: The following is required to get a semi-valid RFC3339 timestamp.
		try:
			self.session.post(self.urls['console'], data={'isFlex': 'true'})
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError('__init__', error)
		self.save_cookies()

	class LogicError(Exception):
		def __init__(self, fn_name, message):
			self.fn_name = str(fn_name)
			self.message = str(message)
		def __str__(self):
			return '%s[CR](function: %s)' % (self.message, self.fn_name)

	class NetworkError(Exception):
		def __init__(self, fn_name, message, status_code=-1):
			self.fn_name = str(fn_name)
			self.message = str(message)
			self.status_code = int(status_code)
		def __str__(self):
			if self.status_code != -1:
				return '%s[CR](status: %d, function: %s)' % (self.message, self.status_code, self.fn_name)
			return '%s[CR](function: %s)' % (self.message, self.fn_name)

	class LoginError(Exception):
		def __str__(self):
			return 'Login failed. Check your login credentials.'

	def save_cookies(self):
		cookiejar = self.session.cookies
		cookiejar.save(ignore_discard=True)

	def login(self, username, password, rogers_login=False):
		fn_name = 'login'

		params = {
			'username': username,
			'password': password,
		}
		if rogers_login == True:
			params['rogers'] = 'true'
		try:
			r = self.session.post(self.urls['login'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text)
		if r_xml['result']['code'] == 'loginfailed':
			raise self.LoginError()

		self.save_cookies()
		self.username = username
		self.password = password
		self.rogers_login = rogers_login

	def get_current_scoreboard(self):
		try:
			r = requests.get(self.urls['scoreboard'] + date.today().isoformat() + '.jsonp')
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)

		# This is normally a JSONP request, so we need to strip off the leading
		# function name, as well as the trailing ')'.
		scoreboard = json.loads(r.text[r.text.find('(') + 1:r.text.rfind(')')])

		scoreboard_dict = {}
		for details in scoreboard['games']:
			# 'id' is YYYYxxIIII where:
			# - YYYY is the year
			# - xx is the magic string '02'
			# - IIII is the actual game ID
			#
			# We are going to key off the actual game ID.
			game_id = str(details['id'])
			scoreboard_dict[game_id[len(game_id) - 4:]] = details
		return scoreboard_dict

	def get_games_list(self, today_only=True, retry=True):
		fn_name = 'get_games_list'

		params = {
			'format': 'xml',
			'isFlex': 'true',
		}
		if today_only == True:
			params['app'] = 'true'
		try:
			r = self.session.post(self.urls['games-list'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_games_list(today_only, retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text)
		if 'code' in r_xml['result'] and r_xml['result']['code'] == 'noaccess':
			if retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_games_list(today_only, retry=False)
			raise self.LogicError(fn_name, 'Access denied.')

		try:
			for key, game in enumerate(r_xml['result']['games']['game']):
				# Sanitize homeTeam and awayTeam.
				if type(game['homeTeam']) == type(list()):
					r_xml['result']['games']['game'][key]['homeTeam'] = game['homeTeam'][0]
				if type(game['awayTeam']) == type(list()):
					r_xml['result']['games']['game'][key]['awayTeam'] = game['awayTeam'][0]

				# Sanitize publishPoint.
				if 'program' in game and 'publishPoint' in game['program']:
					pub_point = game['program']['publishPoint']
					pub_point = pub_point.replace('adaptive://', 'http://')
					pub_point = pub_point.replace('_pc.mp4', '.mp4.m3u8')
					r_xml['result']['games']['game'][key]['program']['publishPoint'] = {
						'home': pub_point,
						'away': pub_point.replace('_h_', '_a_'),
					}
			return r_xml['result']['games']['game']
		except KeyError:
			raise self.LogicError(fn_name, 'No games found.')

	def get_video_playlists(self, season, game_id, perspective, retry=True):
		fn_name = 'get_video_playlists'

		params = {
			'type': 'game',
			'gs': 'live',
			'ft': perspective,
			'id': season + "02" + game_id.zfill(4),
			'plid': binascii.hexlify(os.urandom(16)),
		}
		try:
			r = self.session.post(self.urls['publish-point'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_video_playlists(season, game_id, perspective, retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text)

		playlists = {}
		try:
			m3u8_url = r_xml['result']['path'].replace('_ipad', '_ced')
			r = self.session.get(m3u8_url)
			if r.status_code != 200:
				raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
			m3u8_obj = m3u8.loads(r.text)
			if m3u8_obj.is_variant:
				for playlist in m3u8_obj.playlists:
					bitrate = str(int(playlist.stream_info.bandwidth) / 1000)
					playlists[bitrate] = m3u8_url[:m3u8_url.rfind('/') + 1] + playlist.uri + '?' + m3u8_url.split('?')[1]
			else:
				playlists['0'] = playlist_url
		except KeyError:
			raise self.LogicError(fn_name, 'No playlists found.')
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		return playlists

	def get_game_highlights(self, season, game_id):
		fn_name = 'get_game_highlights'

		base_id = season + '02' + game_id.zfill(4)
		home_suffix, away_suffix = '-X-h', '-X-a'
		params = {
			'format': 'json',
			'ids': base_id + home_suffix + ',' + base_id + away_suffix,
		}
		try:
			r = requests.get(self.urls['highlights'], params=params, cookies=None)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		if r.text.strip() == '':
			return {}
		highlights = json.loads(r.text)

		highlights_dict = {}
		for details in highlights:
			if details['id'] == base_id + home_suffix:
				highlights_dict['home'] = details
			elif details['id'] == base_id + away_suffix:
				highlights_dict['away'] = details

		return highlights_dict

	def get_authorized_stream_url(self, m3u8_url):
		fn_name = 'get_authorized_stream_url'

		try:
			r = requests.get(m3u8_url)
			if r.status_code != 200:
				raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
			m3u8_obj = m3u8.loads(r.text)
			if m3u8_obj.key is not None:
				r = requests.get(m3u8_obj.key.uri, cookies=r.cookies)
				if r.status_code != 200:
					raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
				enc_cookies = urllib.urlencode(r.cookies)
				m3u8_url += '&' + enc_cookies + '|Cookie=' + enc_cookies
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		return m3u8_url

	def get_archives_list(self, retry=True):
		fn_name = 'get_archive_listings'

		params = {
			'date': 'true',
			'isFlex': 'true',
		}
		try:
			r = self.session.post(self.urls['archives-list'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_archives_list(retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text.strip())
		if 'code' in r_xml['result'] and r_xml['result']['code'] == 'noaccess':
			if retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_archives_list(retry=False)
			raise self.LogicError(fn_name, 'Access denied.')

		archives = []
		try:
			for archive_season in r_xml['result']['season']:
				season = {}
				season['season'] = archive_season['@id']
				season['months'] = []
				for date in archive_season['g']:
					month = date.split('/', 1)[0]
					if month not in season['months']:
						season['months'].append(month)
				archives.append(season)
		except KeyError:
			raise self.LogicError(fn_name, 'No archived games found.')

		return archives

	def get_archived_month(self, season, month, retry=True):
		fn_name = 'get_archived_month'

		##
		# The following are useful data sources:
		# - http://feeds.cdnak.neulion.com/fs/nhl/mobile/feeds/data/YYYYMMDD.xml
		# - http://smb.cdnak.neulion.com/fs/nhl/mobile/feed_new/data/streams/YYYY/ipad/02_IIII.json
		#
		# - YYYY = year
		# - MM   = month
		# - DD   = day
		# - IIII = zero padded game ID
		##

		season = int(season)
		if season <= 2009:
			# NOTE: The server that hosts the 2009 and earlier seasons doesn't
			# allow access to the videos (HTTP 403 code). I'm unsure if there
			# is anything that can be done to fix this.
			#
			# Sample URLs:
			# - http://snhlced.cdnak.neulion.net/s/nhl/svod/flv/2009/2_1_wsh_bos_0910_20091001_FINAL_hd.mp4
			# - http://snhlced.cdnak.neulion.net/s/nhl/svod/flv/2_1_nyr_tbl_0809c_Whole_h264_sd.mp4
			return []

		params = {
			'season': str(season),
			'month': month,
			'isFlex': 'true',
		}
		try:
			r = self.session.post(self.urls['archives'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_archived_month(season, month, retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text.strip())
		if 'code' in r_xml['result'] and r_xml['result']['code'] == 'noaccess':
			if retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_archived_month(season, month, retry=False)
			raise self.LogicError(fn_name, 'Access denied.')

		try:
			if type(r_xml['result']['games']['game']) == type(dict()):
				r_xml['result']['games']['game'] = [r_xml['result']['games']['game']]
			for key, game in enumerate(r_xml['result']['games']['game']):
				if not 'publishPoint' in game['program']:
					continue
				url, qs = game['program']['publishPoint'].split('?', 1)

				if season >= 2012:
					host = 'http://nlds150.cdnak.neulion.com/'
					base_url = url[url.find('/nlds_vod/') + 1:]
					new_url = host + base_url + '.m3u8'
				elif season >= 2010:
					if season == 2011:
						host = 'http://nhl.cdn.neulion.net/'
					else:
						host = 'http://nhl.cdnllnwnl.neulion.net/'
					base_url = url[url.find('u/nhlmobile/'):]
					base_url = base_url.replace('/pc/', '/ced/')
					base_url = base_url.replace('.mp4', '')
					new_url = host + base_url + '/v1/playlist.m3u8'
				r_xml['result']['games']['game'][key]['program']['publishPoint'] = new_url + '?' + qs
			return r_xml['result']['games']['game']
		except KeyError:
			raise self.LogicError(fn_name, 'No archived games found.')
