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
	DEFAULT_USER_AGENT = 'Mozilla/5.0 (iPad; CPU OS 8_1 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12B410 Safari/600.1.4'
	NETWORK_ERR_NON_200 = 'Received a non-200 HTTP response.'

	STREAM_TYPE_LIVE       = 'live'
	STREAM_TYPE_CONDENSED  = 'condensed'
	STREAM_TYPE_HIGHLIGHTS = 'highlights'

	PERSPECTIVE_HOME = '2'
	PERSPECTIVE_AWAY = '4'
	PERSPECTIVE_FRENCH = '8'

	PRESEASON  = '01'
	REGSEASON  = '02'
	POSTSEASON = '03'

	FRENCH_STREAM_TEAMS = {
		'MON': True, # Montreal Canadiens
		'OTT': True, # Ottawa Senators
	}

	# NOTE: The server that hosts the 2009 and earlier seasons doesn't allow
	# access to the videos (HTTP 403 code). I'm unsure if there is anything
	# that can be done to fix this.
	#
	# Sample URLs:
	# - http://snhlced.cdnak.neulion.net/s/nhl/svod/flv/2009/2_1_wsh_bos_0910_20091001_FINAL_hd.mp4
	# - http://snhlced.cdnak.neulion.net/s/nhl/svod/flv/2_1_nyr_tbl_0809c_Whole_h264_sd.mp4
	MIN_ARCHIVED_SEASON = 2010

	def __init__(self, username, password, rogers_login, proxy_config, cookies_file):
		self.urls = {
			'scoreboard':       'http://live.nhle.com/GameData/GCScoreboard/',
			'login':            'https://gamecenter.nhl.com/nhlgc/secure/login',
			'console':          'https://gamecenter.nhl.com/nhlgc/servlets/simpleconsole',
			'games-list':       'https://gamecenter.nhl.com/nhlgc/servlets/games',
			'publish-point':    'https://gamecenter.nhl.com/nhlgc/servlets/publishpoint',
			'archived-seasons': 'https://gamecenter.nhl.com/nhlgc/servlets/allarchives',
			'archives':         'https://gamecenter.nhl.com/nhlgc/servlets/archives',
			'highlights':       'http://video.nhl.com/videocenter/servlets/playlist',
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
		self.session.headers.update({'User-Agent': self.DEFAULT_USER_AGENT})

		if proxy_config is not None:
			proxy_url = self.build_proxy_url(proxy_config)
			self.session.proxies = {
				'http': proxy_url,
				'https': proxy_url,
			}

		# NOTE: The following is required to get a semi-valid RFC3339 timestamp.
		try:
			self.session.post(self.urls['console'], data={'isFlex': 'true'})
		except requests.exceptions.ProxyError as error:
			raise self.LogicError('__init__', '%s[CR]%s' % (str(error[0][0]), str(error[0][1])))
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError('__init__', str(error))
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

	def build_proxy_url(self, config):
		fn_name = 'build_proxy_url'

		proxy_url = ''

		if 'scheme' in config:
			scheme = config['scheme'].lower().strip()
			if scheme != 'http' and scheme != 'https':
				raise self.LogicError(fn_name, 'Unsupported scheme "%s".' % scheme)
			proxy_url += scheme + '://'

		if 'auth' in config and config['auth'] is not None:
			try:
				username = config['auth']['username']
				password = config['auth']['password']
				if username == '' or password == '':
					raise self.LogicError(fn_name, 'Auth does not contain a valid username and/or password.')
				proxy_url += '%s:%s@' % (urllib.quote(username), urllib.quote(password))
			except KeyError:
				raise self.LogicError(fn_name, 'Auth does not contain a valid username and/or password.')

		if 'host' not in config or config['host'].strip() == '':
			raise self.LogicError(fn_name, 'Host is not valid.')
		proxy_url += config['host'].strip()

		if 'port' in config:
			try:
				port = int(config['port'])
				if port <= 0 or port > 65535:
					raise self.LogicError(fn_name, 'Port must be a number between 1 and 65535.')
				proxy_url += ':' + str(port)
			except ValueError:
				raise self.LogicError(fn_name, 'Port must be a number between 1 and 65535.')

		return proxy_url

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
			# - xx is the season type (pre, regular, post)
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
			if type(r_xml['result']['games']['game']) == type(dict()):
				r_xml['result']['games']['game'] = [r_xml['result']['games']['game']]
			for key, game in enumerate(r_xml['result']['games']['game']):
				# Sanitize homeTeam and awayTeam.
				if type(game['homeTeam']) == type(list()):
					r_xml['result']['games']['game'][key]['homeTeam'] = game['homeTeam'][0]
				if type(game['awayTeam']) == type(list()):
					r_xml['result']['games']['game'][key]['awayTeam'] = game['awayTeam'][0]

				# Sanitize publishPoint.
				publish_point = {
					'home': None,
					'away': None,
					'french': None,
				}
				if 'program' not in game:
					r_xml['result']['games']['game'][key]['program'] = {
						'publishPoint': publish_point,
					}
				elif 'publishPoint' not in game['program']:
					r_xml['result']['games']['game'][key]['program']['publishPoint'] = publish_point
				else:
					pub_point = game['program']['publishPoint']
					pub_point = pub_point.replace('adaptive://', 'http://')
					pub_point = pub_point.replace('_pc.mp4', '.mp4.m3u8')
					publish_point['home'] = pub_point
					publish_point['away'] = pub_point.replace('_h_', '_a_')
					if game['homeTeam'] in self.FRENCH_STREAM_TEAMS or game['awayTeam'] in self.FRENCH_STREAM_TEAMS:
						pub_point = pub_point.replace('/nlds_vod/nhl/', '/nlds_vod/nhlfr/')
						pub_point = pub_point.replace('_h_', '_fr_')
						publish_point['french'] = pub_point
					r_xml['result']['games']['game'][key]['program']['publishPoint'] = publish_point
			return r_xml['result']['games']['game']
		except KeyError:
			raise self.LogicError(fn_name, 'No games found.')

	def get_video_playlists(self, season, game_id, stream_type, perspective, retry=True):
		fn_name = 'get_video_playlists'

		params = {
			'type': 'game',
			'gs': stream_type,
			'ft': perspective,
			# FIXME: self.REGSEASON shouldn't be hardcoded.
			'id': season + self.REGSEASON + game_id.zfill(4),
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
				return self.get_video_playlists(season, game_id, stream_type, perspective, retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text)

		try:
			m3u8_url = r_xml['result']['path'].replace('_ipad', '')
			return self.get_playlists_from_m3u8_url(m3u8_url, fn_name)
		except KeyError:
			raise self.LogicError(fn_name, 'No playlists found.')

	def get_playlists_from_m3u8_url(self, m3u8_url, fn_name=None):
		if fn_name is None:
			fn_name = 'get_playlists_from_m3u8_url'

		playlists = {}
		try:
			r = self.session.get(m3u8_url)
			if r.status_code != 200:
				raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
			m3u8_obj = m3u8.loads(r.text)
			if m3u8_obj.is_variant:
				for playlist in m3u8_obj.playlists:
					bitrate = str(int(playlist.stream_info.bandwidth) / 1000)
					playlists[bitrate] = m3u8_url[:m3u8_url.rfind('/') + 1] + playlist.uri + '?' + m3u8_url.split('?', 1)[1]
			else:
				playlists['0'] = m3u8_url
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		return playlists

	def get_game_highlights(self, season, game_id):
		fn_name = 'get_game_highlights'

		# FIXME: self.REGSEASON shouldn't be hardcoded.
		base_id = season + self.REGSEASON + game_id.zfill(4)
		home_suffix, away_suffix, french_suffix = '-X-h', '-X-a', '-X-fr'
		params = {
			'format': 'json',
			'ids': base_id + home_suffix + ',' + base_id + away_suffix + ',' + base_id + french_suffix,
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
			elif details['id'] == base_id + french_suffix:
				highlights_dict['french'] = details

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
				headers = {
					'Cookie': '',
					'User-Agent': self.DEFAULT_USER_AGENT,
				}
				for cookie in r.cookies:
					headers['Cookie'] += '%s=%s; ' % (cookie.name, cookie.value)
				headers['Cookie'] += 'nlqptid=' + m3u8_url.split('?', 1)[1]
				m3u8_url += '|' + urllib.urlencode(headers)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		return m3u8_url

	def get_archived_seasons(self, retry=True):
		fn_name = 'get_archived_seasons'

		params = {
			'date': 'true',
			'isFlex': 'true',
		}
		try:
			r = self.session.post(self.urls['archived-seasons'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_archived_seasons(retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text.strip())
		if 'code' in r_xml['result'] and r_xml['result']['code'] == 'noaccess':
			if retry == True:
				self.login(self.username, self.password, self.rogers_login)
				return self.get_archived_seasons(retry=False)
			raise self.LogicError(fn_name, 'Access denied.')

		archives = []
		try:
			for archive_season in r_xml['result']['season']:
				if int(archive_season['@id']) < self.MIN_ARCHIVED_SEASON:
					continue
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

		return sorted(archives, key=lambda seasons: seasons['season'], reverse=True)

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
		if season < self.MIN_ARCHIVED_SEASON:
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
				orig_url, qs = game['program']['publishPoint'].split('?', 1)

				if season >= 2012:
					host = 'http://nlds150.cdnak.neulion.com/'
					base_url = orig_url[orig_url.find('/nlds_vod/') + 1:]
					url = host + base_url + '.m3u8'
					french_url = url.replace('/nlds_vod/nhl/', '/nlds_vod/nhlfr/')
					french_url = french_url.replace('_h_', '_fr_')
					french_url = french_url.replace('_whole_2', '_whole_1')
				elif season >= 2010:
					if season == 2011:
						host = 'http://nhl.cdn.neulion.net/'
					else:
						host = 'http://nhl.cdnllnwnl.neulion.net/'
					base_url = orig_url[orig_url.find('u/nhlmobile/'):]
					base_url = base_url.replace('/pc/', '/ced/')
					base_url = base_url.replace('.mp4', '')
					url = host + base_url + '/v1/playlist.m3u8'
					french_url = url.replace('/vod/nhl/', '/vod/nhlfr/')
					french_url = french_url.replace('_h_', '_fr_')
				r_xml['result']['games']['game'][key]['program']['publishPoint'] = {
					'home': url + '?' + qs,
					'away': url.replace('_h_', '_a_') + '?' + qs,
					'french': None,
				}
				if game['homeTeam'] in self.FRENCH_STREAM_TEAMS or game['awayTeam'] in self.FRENCH_STREAM_TEAMS:
					r_xml['result']['games']['game'][key]['program']['publishPoint']['french'] = french_url
			return r_xml['result']['games']['game']
		except KeyError:
			raise self.LogicError(fn_name, 'No archived games found.')
