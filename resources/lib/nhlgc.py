import cookielib
import m3u8
import requests
import urllib
import xmltodict
try:
	import simplejson as json
except ImportError:
	import json
from datetime import date
from datetime import timedelta
from dateutil import parser, tz
from TLSAdapter import TLSAdapter

import xbmc

class nhlgc(object):
	DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:45.0) Gecko/20100101 Firefox/45.0'
	NETWORK_ERR_NON_200 = 'Received a non-200 HTTP response.'

	STREAM_TYPE_LIVE       = 'live'
	STREAM_TYPE_CONDENSED  = 'condensed'
	STREAM_TYPE_HIGHLIGHTS = 'highlights'

	PERSPECTIVE_HOME        = str(1 << 1)	# '2'
	PERSPECTIVE_AWAY        = str(1 << 2)	# '4'
	PERSPECTIVE_FRENCH      = str(1 << 3)	# '8'
	PERSPECTIVE_HOME_GOALIE = str(1 << 6)	# '64'
	PERSPECTIVE_AWAY_GOALIE = str(1 << 7)	# '128'

	PRESEASON  = '01'
	REGSEASON  = '02'
	POSTSEASON = '03'

	FRENCH_STREAM_TEAMS = {
		'MON': True, # Montreal Canadiens
		'OTT': True, # Ottawa Senators
	}

	##
	# New system consts.
	##

	# NOTE: This token is from the meta tag "control_plane_client_token" on https://www.nhl.com/login
	CLIENT_TOKEN = 'd2ViX25obC12MS4wLjA6MmQxZDg0NmVhM2IxOTRhMThlZjQwYWM5ZmJjZTk3ZTM='

	AUTH_STATUS_LOGIN_REQUIRED = 'LoginRequiredStatus'
	AUTH_STATUS_NOT_AUTHORIZED = 'NotAuthorizedStatus'
	AUTH_STATUS_SUCCESS        = 'SuccessStatus'

	GAME_STATUS_SCHEDULED   = '1'
	GAME_STATUS_PREGAME     = '2'
	GAME_STATUS_IN_PROGRESS = '3'
	GAME_STATUS_UNKNOWN4    = '4'
	GAME_STATUS_UNKNOWN5    = '5'
	GAME_STATUS_FINAL6      = '6'
	GAME_STATUS_FINAL7      = '7'

	MEDIA_FEED_TITLE_CONDENSED  = 'Extended Highlights'
	MEDIA_FEED_TITLE_FULL       = 'NHLTV'
	MEDIA_FEED_TITLE_HIGHLIGHTS = 'Recap'

	MEDIA_FEED_TYPE_AWAY     = 'AWAY'
	MEDIA_FEED_TYPE_FRENCH   = 'FRENCH'
	MEDIA_FEED_TYPE_HOME     = 'HOME'
	MEDIA_FEED_TYPE_NATIONAL = 'NATIONAL'

	PLAYBACK_SCENARIO_MOBILE        = 'HTTP_CLOUD_MOBILE'
	PLAYBACK_SCENARIO_TABLET        = 'HTTP_CLOUD_TABLET'
	PLAYBACK_SCENARIO_TABLET_60     = 'HTTP_CLOUD_TABLET_60'
	PLAYBACK_SCENARIO_TABLET_60_ADS = 'HTTP_CLOUD_TABLET_60_ADS'
	PLAYBACK_SCENARIO_TABLET_ADS    = 'HTTP_CLOUD_TABLET_ADS'
	PLAYBACK_SCENARIO_WIRED         = 'HTTP_CLOUD_WIRED'
	PLAYBACK_SCENARIO_WIRED_60      = 'HTTP_CLOUD_WIRED_60'
	PLAYBACK_SCENARIO_WIRED_60_ADS  = 'HTTP_CLOUD_WIRED_60_ADS'
	PLAYBACK_SCENARIO_WIRED_ADS     = 'HTTP_CLOUD_WIRED_ADS'
	PLAYBACK_SCENARIO_WIRED_WEB     = 'HTTP_CLOUD_WIRED_WEB'

	STATUS_CODE_OK                  = 1
	STATUS_CODE_MEDIA_NOT_FOUND     = -1000
	STATUS_CODE_INVALID_CREDENTIALS = -3000
	STATUS_CODE_LOGIN_THROTTLED     = -3500
	STATUS_CODE_SYSTEM_ERROR        = -4000

	# NOTE: The server that hosts the 2009 and earlier seasons doesn't allow
	# access to the videos (HTTP 403 code). I'm unsure if there is anything
	# that can be done to fix this.
	#
	# Sample URLs:
	# - http://snhlced.cdnak.neulion.net/s/nhl/svod/flv/2009/2_1_wsh_bos_0910_20091001_FINAL_hd.mp4
	# - http://snhlced.cdnak.neulion.net/s/nhl/svod/flv/2_1_nyr_tbl_0809c_Whole_h264_sd.mp4
	MIN_ARCHIVED_SEASON = 2010

	def __init__(self, username, password, rogers_login, proxy_config, hls_server, cookies_file, skip_networking=False):
		self.__urls = {
			# Old system
			'archived-seasons': 'https://gamecenter.nhl.com/nhlgc/servlets/allarchives',
			'archives':         'https://gamecenter.nhl.com/nhlgc/servlets/archives',
			'highlights':       'http://video.nhl.com/videocenter/servlets/playlist',

			# New system
			'login-basic':  'https://web-secure.nhl.com/authenticate.do',
			'login-oauth':  'https://user.svc.nhl.com/oauth/token?grant_type=client_credentials',
			'login-nhl':    'https://gateway.web.nhl.com/ws/subscription/flow/nhlPurchase.login',
			'login-rogers': 'https://activation-rogers.svc.nhl.com/ws/subscription/flow/rogers.login-check',
			'game-info':    'http://statsapi.web.nhl.com/api/v1/schedule',
			'stream-info':  'https://mf.svc.nhl.com/ws/media/mf/v2.4/stream',
		}

		# Initialize common variables.
		self.__access_token = None
		self.__session_key  = None
		self.__username     = username
		self.__password     = password
		self.__rogers_login = rogers_login
		self.__hls_server = None
		if hls_server is not None:
			self.__hls_server = 'http://%s:%d' % (hls_server['host'], hls_server['port'])

		# Load any saved cookies, if possible.
		cookiejar = cookielib.LWPCookieJar(cookies_file)
		try:
			cookiejar.load(ignore_discard=True)
			cookie_dict = requests.utils.dict_from_cookiejar(cookiejar)
			if 'Authorization' in cookie_dict:
				self.__access_token = cookie_dict['Authorization']
			if 'SavedSessionKey' in cookie_dict:
				self.__session_key = cookie_dict['SavedSessionKey']
		except IOError:
			pass
		self.__set_playlist_headers()

		# Configure the default request session.
		self.__session = requests.Session()
		self.__session.mount('https://', TLSAdapter())
		self.__session.cookies = cookiejar
		self.__session.headers = {'User-Agent': self.DEFAULT_USER_AGENT}
		if proxy_config is not None:
			proxy_url = self.__build_proxy_url(proxy_config)
			self.__session.proxies = {
				'http': proxy_url,
				'https': proxy_url,
			}

	class LogicError(Exception):
		def __init__(self, fn_name, message):
			self.fn_name = str(fn_name)
			self.message = str(message)
		def __str__(self):
			return '%s[CR](function: %s)' % (self.message, self.fn_name)

	class NetworkError(Exception):
		def __init__(self, fn_name, message, status_code=-1):
			if type(message) is requests.exceptions.ConnectionError:
				message = message.args[0]
				if type(message) is requests.packages.urllib3.exceptions.MaxRetryError:
					message = message.reason
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

	def __build_proxy_url(self, config):
		fn_name = '__build_proxy_url'

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

	def __save_cookies(self):
		cookiejar = self.__session.cookies
		cookiejar.save(ignore_discard=True)

	def __set_playlist_headers(self, cookies=''):
		self.__playlist_headers = {
			'Authorization': self.__access_token,
			'Cookie':        cookies,
			'User-Agent':    self.DEFAULT_USER_AGENT,
		}

	def __get_access_token(self):
		if self.__access_token is None:
			self.__retry_login()
		return self.__access_token

	def __retry_login(self):
		self.login(self.__username, self.__password, self.__rogers_login)

	def __login_basic(self, username, password, rogers_login=False):
		fn_name = '__login_basic'

		session_1 = cookielib.Cookie(
			version            = 0,
			name               = 'SESSION_1',
			value              = '"referrer===https://subscribe.nhl.com/?&affiliateId=NHLTVREDIRECT~wf_flowId===subscriptions.updatesubscriptionv1~stage===5~flowId===subscriptions.updatesubscriptionv1"',
			port               = None,
			port_specified     = False,
			domain             = '.nhl.com',
			domain_specified   = True,
			domain_initial_dot = True,
			path               = '/',
			path_specified     = True,
			secure             = True,
			expires            = None,
			discard            = False,
			comment            = None,
			comment_url        = None,
			rest               = {},
		)
		self.__session.cookies.set_cookie(session_1)

		params = {
			'uri':                '/campaign/login_register.jsp',
			'registrationAction': 'identify',
			'emailAddress':       username,
			'password':           password,
		}
		try:
			r = self.__session.post(self.__urls['login-basic'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		cookie_dict = requests.utils.dict_from_cookiejar(self.__session.cookies)
		if 'Authorization' not in cookie_dict:
			raise self.LoginError()

		self.__save_cookies()
		self.__access_token = cookie_dict['Authorization']
		self.__username     = username
		self.__password     = password
		self.__rogers_login = rogers_login

	def login(self, username, password, rogers_login=False):
		fn_name = 'login'

		# Obtain an OAUTH token, if required.
#		if self.__access_token is None:
#			headers = {
#				'Authorization': 'Basic ' + self.CLIENT_TOKEN,
#			}
#			try:
#				r = self.__session.post(self.__urls['login-oauth'], headers=headers)
#			except requests.exceptions.ConnectionError as error:
#				raise self.NetworkError(fn_name, error)

			# Error handling.
#			if r.status_code != 200:
#				raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
#			r_json = json.loads(r.text)
#			if 'access_token' not in r_json:
#				raise self.LoginError()
#			self.__access_token = r_json['access_token']

		# Perform the actual login.
		if rogers_login == True:
			req_url    = self.__urls['login-rogers']
			params_key = 'rogersCredentials'
		else:
			req_url    = self.__urls['login-nhl']
			params_key = 'nhlCredentials'
		params = {}
		params[params_key] = {
			'email':    username,
			'password': password,
		}
		try:
			r = self.__session.post(req_url, cookies=None, json=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		cookie_dict = requests.utils.dict_from_cookiejar(self.__session.cookies)
		if 'Authorization' not in cookie_dict:
			raise self.LoginError()

		self.__save_cookies()
		self.__access_token = cookie_dict['Authorization']
		self.__username     = username
		self.__password     = password
		self.__rogers_login = rogers_login

	def get_game_list(self, today_only=True):
		fn_name = 'get_game_list'

		# NOTE: If we also expand schedule.game.content.media.milestones, we
		# gain access to BROADCAST_START, which could be helpful for getting
		# live rewinding to work again.
		params = {
#			'expand': 'schedule.game.content.media.milestones,schedule.game.content.media.epg,schedule.teams',
			'expand': 'schedule.game.content.media.epg,schedule.teams',
		}
		today = date.today()
		if today_only == True:
			params['date'] = today.isoformat()
		else:
			params['startDate'] = (today - timedelta(days=8)).isoformat()
			params['endDate']   = (today - timedelta(days=1)).isoformat()

		return self.__common_game_info(fn_name, params)

	def get_game_info(self, game_id):
		fn_name = 'get_game_info'

		params = {
			'gamePk': game_id,
			'expand': 'schedule.game.content.media.epg,schedule.teams',
		}
		return self.__common_game_info(fn_name, params)

	def __is_game_live(self, status_code):
		if status_code == self.GAME_STATUS_IN_PROGRESS or status_code == self.GAME_STATUS_UNKNOWN4 or status_code == self.GAME_STATUS_UNKNOWN5:
			return True
		return False

	def __common_game_info(self, fn_name, params):
		try:
			r = requests.get(self.__urls['game-info'], params=params, cookies=None)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)

		r_json = json.loads(r.text)
		try:
			dates_list = sorted(r_json['dates'], key=lambda date: parser.parse(date['date']), reverse=True)
		except KeyError:
			raise self.LogicError(fn_name, 'No games found.')

		all_games = []
		for current_date in dates_list:
			day_games = []
			games_list = current_date['games']
			for game in games_list:
				info = {
					'season':      game['season'],
					'season_type': game['gameType'],
					'id':          game['gamePk'],
					'event_id':    None,
					'blocked':     False, # FIXME: What does a blocked game look like?
					'live':        self.__is_game_live(game['status']['statusCode']),
					'date':        current_date['date'],
					'start_time':  parser.parse(game['gameDate']).replace(tzinfo=tz.tzutc()),
					'end_time':    None,
					'home_team':   game['teams']['home']['team']['abbreviation'],
					'away_team':   game['teams']['away']['team']['abbreviation'],
					'home_goals':  game['teams']['home']['score'],
					'away_goals':  game['teams']['away']['score'],
					'french_game': False,
					'streams':     {
						'live': {
							'home':   None,
							'away':   None,
							'french': None,
						},
						'condensed':  None,
						'highlights': None,
					},
				}

				# Set the streams.
				# FIXME: This check could probably be handled better?
				if 'media' not in game['content']:
					continue
				for epg_media in game['content']['media']['epg']:
					if 'title' not in epg_media or 'items' not in epg_media:
						continue

					if epg_media['title'] == self.MEDIA_FEED_TITLE_FULL:
						for epg_item in epg_media['items']:
							# FIXME: I'm pretty sure treating home and national
							# the same is incorrect.
							if epg_item['mediaFeedType'] == self.MEDIA_FEED_TYPE_HOME or epg_item['mediaFeedType'] == self.MEDIA_FEED_TYPE_NATIONAL:
								info['event_id']                = epg_item['eventId']
								info['streams']['live']['home'] = epg_item['mediaPlaybackId']
							elif epg_item['mediaFeedType'] == self.MEDIA_FEED_TYPE_AWAY:
								info['event_id']                = epg_item['eventId']
								info['streams']['live']['away'] = epg_item['mediaPlaybackId']
							elif epg_item['mediaFeedType'] == self.MEDIA_FEED_TYPE_FRENCH:
								info['event_id']                  = epg_item['eventId']
								info['french_game']               = True
								info['streams']['live']['french'] = epg_item['mediaPlaybackId']
					elif epg_media['title'] == self.MEDIA_FEED_TITLE_CONDENSED:
						for epg_item in epg_media['items']:
							if 'type' in epg_item and epg_item['type'] == 'video':
								info['streams']['condensed'] = epg_item['mediaPlaybackId']
					elif epg_media['title'] == self.MEDIA_FEED_TITLE_HIGHLIGHTS:
						for epg_item in epg_media['items']:
							if 'type' in epg_item and epg_item['type'] == 'video':
								info['streams']['highlights'] = epg_item['mediaPlaybackId']

				day_games.append(info)
			# Sort the games for the day by the game's start time.
			for game in sorted(day_games, key=lambda game: game['start_time']):
				all_games.append(game)
		return all_games

	def __get_session_key(self, event_id, retry=True):
		fn_name = '__get_session_key'

		# If we already have a session key, don't try to get another one so
		# that we don't end up getting locked out due to throttling.
		if self.__session_key != None:
			return self.__session_key

		headers = {
			'Authorization': self.__get_access_token(),
		}
		params = {
			'eventId': event_id,
			'format':  'json',
			'subject': 'NHLTV',
		}
		try:
			r = requests.get(self.__urls['stream-info'], cookies=None, headers=headers, params=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_json = json.loads(r.text)
		if r_json['status_code'] != self.STATUS_CODE_OK or 'session_key' not in r_json:
			if retry == True and self.__can_retry_playlist_request(r_json['status_code']):
				self.__retry_login()
				return self.__get_session_key(event_id, retry=False)
			raise self.LogicError(fn_name, 'Unable to retrieve session key')

		# We have a session key, and we want to save it for reuse.  We will
		# (ab)use the cookie store to persist it.
		self.__set_session_key(r_json['session_key'])
		return self.__session_key

	def __set_session_key(self, session_key):
		self.__session_key = session_key
		session_key_cookie = cookielib.Cookie(
			version            = 0,
			name               = 'SavedSessionKey',
			value              = self.__session_key,
			port               = None,
			port_specified     = False,
			domain             = '.example.com',
			domain_specified   = True,
			domain_initial_dot = True,
			path               = '/',
			path_specified     = True,
			secure             = True,
			expires            = None,
			discard            = False,
			comment            = None,
			comment_url        = None,
			rest               = {},
		)
		self.__session.cookies.set_cookie(session_key_cookie)
		self.__save_cookies()

	def __can_retry_playlist_request(self, status_code):
		if status_code == self.STATUS_CODE_MEDIA_NOT_FOUND or status_code == self.STATUS_CODE_LOGIN_THROTTLED:
			return False
		return True

	def get_master_playlist(self, event_id, game_id, retry=True):
		fn_name = 'get_master_playlist'

		headers = {
			'Authorization': self.__get_access_token(),
		}
		params = {
			'contentId':        game_id,
			'playbackScenario': self.PLAYBACK_SCENARIO_WIRED_60,
			'sessionKey':       self.__get_session_key(event_id),
			'auth':             'response',
			'format':           'json',
#			'platform':         'WEB_MEDIAPLAYER',
		}
		try:
			r = requests.get(self.__urls['stream-info'], headers=headers, params=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_json = json.loads(r.text)
		if r_json['status_code'] != self.STATUS_CODE_OK:
			if retry == True and self.__can_retry_playlist_request(r_json['status_code']):
				self.__retry_login()
				return self.get_master_playlist(event_id, game_id, retry=False)
			raise self.LogicError(fn_name, r_json['status_message'])

		# FIXME: Everything after this is ugly.  There has to be some better
		# way to handle all this.
		playlist_cookies = ''
		if 'session_info' in r_json:
			for session_attribute in r_json['session_info']['sessionAttributes']:
				playlist_cookies += '%s=%s; ' % (session_attribute['attributeName'], session_attribute['attributeValue'])

		url = None
		self.__set_playlist_headers()
		for user_verified_event in r_json['user_verified_event']:
			for user_verified_content in user_verified_event['user_verified_content']:
				for user_verified_media_item in user_verified_content['user_verified_media_item']:
					if user_verified_media_item['auth_status'] == self.AUTH_STATUS_LOGIN_REQUIRED:
						if retry == True:
							self.__retry_login()
							return self.get_master_playlist(event_id, game_id, retry=False)
						raise self.LogicError(fn_name, 'Access denied.')
					elif user_verified_media_item['auth_status'] == self.AUTH_STATUS_SUCCESS:
						url = user_verified_media_item['url']
						self.__set_playlist_headers(cookies=playlist_cookies)
		return url

	def get_stream_playlist(self, master_url):
		fn_name = 'get_stream_playlist'

		playlists = {}
		try:
			r = self.__session.get(master_url)
			if r.status_code != 200:
				raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
			playlist_obj = m3u8.loads(r.text)
			if playlist_obj.is_variant:
				for playlist in playlist_obj.playlists:
					bitrate = str(int(playlist.stream_info.bandwidth) / 1000)
					playlists[bitrate] = master_url[:master_url.rfind('/') + 1] + playlist.uri + '|' + urllib.urlencode(self.__playlist_headers)
			else:
				playlists['0'] = master_url + '|' + urllib.urlencode(self.__playlist_headers)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		return playlists

	def get_authorized_stream_url(self, game, m3u8_url, from_start=False):
		fn_name = 'get_authorized_stream_url'

		try:
			r = requests.get(m3u8_url)
			if r.status_code != 200:
				raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
			m3u8_obj = m3u8.loads(r.text)
			protocol_headers = {}
			if m3u8_obj.key is not None:
				r = requests.get(m3u8_obj.key.uri, cookies=r.cookies)
				if r.status_code != 200:
					raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
				protocol_headers = {
					'Cookie': '',
					'User-Agent': self.DEFAULT_USER_AGENT,
				}
				for cookie in r.cookies:
					protocol_headers['Cookie'] += '%s=%s; ' % (cookie.name, cookie.value)
				protocol_headers['Cookie'] += 'nlqptid=' + m3u8_url.split('?', 1)[1]
			if from_start and game['start_time'] is not None and self.__hls_server is not None:
				m3u8_url = self.__hls_server + \
					'/playlist?url=' + urllib.quote_plus(m3u8_url) + \
					'&start_at=' + game['start_time'].strftime('%Y%m%d%H%M%S')
				if len(protocol_headers) > 0:
					m3u8_url += '&headers=' + urllib.quote(urllib.urlencode(protocol_headers))
			elif len(protocol_headers) > 0:
				m3u8_url += '|' + urllib.urlencode(protocol_headers)
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
			r = self.__session.post(self.__urls['archived-seasons'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.__retry_login()
				return self.get_archived_seasons(retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text.strip())
		if 'code' in r_xml['result'] and r_xml['result']['code'] == 'noaccess':
			if retry == True:
				self.__retry_login()
				return self.get_archived_seasons(retry=False)
			raise self.LogicError(fn_name, 'Access denied.')

		archives = []
		try:
			for archive_season in r_xml['result']['season']:
				if int(archive_season['@id']) < self.MIN_ARCHIVED_SEASON or not 'g' in archive_season:
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
			r = self.__session.post(self.__urls['archives'], data=params)
		except requests.exceptions.ConnectionError as error:
			raise self.NetworkError(fn_name, error)

		# Error handling.
		if r.status_code != 200:
			if r.status_code == 401 and retry == True:
				self.__retry_login()
				return self.get_archived_month(season, month, retry=False)
			raise self.NetworkError(fn_name, self.NETWORK_ERR_NON_200, r.status_code)
		r_xml = xmltodict.parse(r.text.strip())
		if 'code' in r_xml['result'] and r_xml['result']['code'] == 'noaccess':
			if retry == True:
				self.__retry_login()
				return self.get_archived_month(season, month, retry=False)
			raise self.LogicError(fn_name, 'Access denied.')

		try:
			games_list = r_xml['result']['games']['game']
			if not isinstance(games_list, list):
				games_list = [games_list]
		except KeyError:
			raise self.LogicError(fn_name, 'No games found.')

		games = []
		for game in games_list:
			if 'program' not in game or 'publishPoint' not in game['program']:
				continue
			info = {
				'season':      game['season'],
				'season_type': game['type'],
				'id':          game['id'].zfill(4),
				'blocked':     'blocked' in game,
				'live':        'isLive' in game,
				'date':        parser.parse(game['date']).replace(tzinfo=tz.tzutc()),
				'start_time':  None,
				'end_time':    parser.parse(game['date']).replace(tzinfo=tz.tzutc()),
				'home_team':   game['homeTeam'],
				'away_team':   game['awayTeam'],
				'home_goals':  game['homeGoals'],
				'away_goals':  game['awayGoals'],
				'french_game': False,
				'streams':     {
					'home':   None,
					'away':   None,
					'french': None,
				},
			}

			# Flag as a French game.
			if info['home_team'] in self.FRENCH_STREAM_TEAMS or info['away_team'] in self.FRENCH_STREAM_TEAMS:
				info['french_game'] = True

			# Set the streams.
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
			info['streams']['home'] = url + '?' + qs
			info['streams']['away'] = url.replace('_h_', '_a_') + '?' + qs
			if info['french_game'] == True:
				info['streams']['french'] = french_url + '?' + qs

			games.append(info)
		return games
