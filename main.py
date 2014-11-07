import os, sys, urllib, urlparse
import xbmc, xbmcaddon, xbmcgui, xbmcplugin
try:
	import simplejson as json
except ImportError:
	import json
# http://mail.python.org/pipermail/python-list/2009-June/540579.html
import _strptime
from datetime import datetime
from dateutil import parser, tz
from resources.lib.nhlgc import nhlgc

__addon__       = xbmcaddon.Addon()
__addonurl__    = sys.argv[0]
__addonhandle__ = int(sys.argv[1])
__addonargs__   = urlparse.parse_qs(sys.argv[2][1:])
__addonicon__   = __addon__.getAddonInfo('icon')
__addonname__   = __addon__.getAddonInfo('name')
__cwd__         = __addon__.getAddonInfo('path').decode('utf-8')
__profile__     = __addon__.getAddonInfo('profile').decode('utf-8')
__language__    = __addon__.getLocalizedString
__teams_json__  = os.path.join(__cwd__, 'teams.json')
__cookiesfile__ = xbmc.translatePath(os.path.join(__profile__, 'cookies.lwp'))

game_time_format = xbmc.getRegion('dateshort') + ' ' + xbmc.getRegion('time').replace(':%S', '')

class XBMC_NHL_GameCenter(object):
	# This is the list of bitrates defined in settings.xml. These two sources
	# should be kept in sync!
	SETTINGS_BITRATES = [
# The following are for reference only, and should remain commented out:
#		'Always ask',   # 0
#		'Best quality', # 1
		'5000',         # 2
		'4500',         # 3
		'3000',         # 4
		'1600',         # 5
		'1200',         # 6
		'800',          # 7
		'400',          # 8
		'240',          # 9
		'150',          # 10
	]
	def __init__(self):
		username    = __addon__.getSetting('gc_username')
		password    = __addon__.getSetting('gc_password')
		rogerslogin = __addon__.getSetting('gc_rogerslogin') == 'true'

		proxy_config = None
		if __addon__.getSetting('proxy_enabled') == 'true':
			proxy_config = {
				'scheme': __addon__.getSetting('proxy_scheme'),
				'host': __addon__.getSetting('proxy_host'),
				'port': __addon__.getSetting('proxy_port'),
				'auth': {
					'username': __addon__.getSetting('proxy_username'),
					'password': __addon__.getSetting('proxy_password'),
				},
			}
			if proxy_config['auth']['username'] == '' and proxy_config['auth']['password'] == '':
				proxy_config['auth'] = None

		try:
			self.game_center = nhlgc(username, password, rogerslogin, proxy_config, __cookiesfile__)
		except nhlgc.LogicError as error:
			self.display_notification(error)
			raise RuntimeError(error)
		except nhlgc.NetworkError as error:
			self.display_notification(error)
			raise RuntimeError(error)

		self.preferred_bitrate  = int(__addon__.getSetting('preferred_bitrate'))
		self.always_ask_bitrate = self.preferred_bitrate == 0

		self.team_info = self.parse_teams_json(__teams_json__)
		team_names_setting = int(__addon__.getSetting('team_names'))
		if team_names_setting == 1:
			self.team_info_key = 'team'
		elif team_names_setting == 2:
			self.team_info_key = 'full-name'
		elif team_names_setting == 3:
			self.team_info_key = None
		else:
			self.team_info_key = 'city'
		self.show_scores = __addon__.getSetting('show_scores') == 'true'
		self.at_instead_of_vs = __addon__.getSetting('at_instead_of_vs') == 'true'

	def parse_teams_json(self, teams_file):
		with open(teams_file) as file_obj:
			teams_json = file_obj.read()
		return json.loads(teams_json)

	def display_notification(self, msg):
		xbmcgui.Dialog().ok(__language__(30035), str(msg))

	def add_folder(self, label, params):
		xbmcplugin.addDirectoryItem(
			isFolder=True,
			handle=__addonhandle__,
			url=__addonurl__ + '?' + urllib.urlencode(params),
			listitem=xbmcgui.ListItem(label, iconImage='DefaultFolder.png')
		)

	def add_item(self, label, url, params=None):
		if params is not None:
			url += '?' + urllib.urlencode(params)
		xbmcplugin.addDirectoryItem(
			isFolder=False,
			handle=__addonhandle__,
			url=url,
			listitem=xbmcgui.ListItem(label, iconImage='DefaultVideo.png')
		)

	def select_bitrate(self, streams):
		sorted_streams = sorted(streams, key=int, reverse=True)

		# Pick the best quality stream.
		if self.preferred_bitrate == 1:
			return sorted_streams[0]
		# Pick a specific stream quality.
		if self.preferred_bitrate > 1:
			for bitrate in sorted_streams:
				if bitrate == self.SETTINGS_BITRATES[self.preferred_bitrate]:
					return bitrate
		# Ask what bitrate the user wants.
		dialog = xbmcgui.Dialog()
		xbmc.executebuiltin('Dialog.Close(busydialog)')
		ret = dialog.select(__language__(30005), sorted_streams)
		return sorted_streams[ret]

	def game_title(self, game, scoreboard):
		# Get the team names.
		home_team = game['homeTeam']
		away_team = game['awayTeam']
		if self.team_info_key is not None:
			if home_team in self.team_info:
				home_team = self.team_info[home_team][self.team_info_key]
			if away_team in self.team_info:
				away_team = self.team_info[away_team][self.team_info_key]

		# Get the score for the game.
		home_team_score, away_team_score = None, None
		game['id'] = game['id'].zfill(4)
		# First check the game info itself.
		if 'awayGoals' in game and 'homeGoals' in game:
			home_team_score = game['homeGoals']
			away_team_score = game['awayGoals']
		# Fall back to checking the scoreboard.
		elif scoreboard is not None and game['id'] in scoreboard:
			if str(scoreboard[game['id']]['hts']) != '' and str(scoreboard[game['id']]['ats']) != '':
				home_team_score = str(scoreboard[game['id']]['hts'])
				away_team_score = str(scoreboard[game['id']]['ats'])

		# Get the required dates and times.
		current_time_utc = datetime.utcnow().replace(tzinfo=tz.tzutc())
		if 'gameTimeGMT' in game:
			start_time_gmt = parser.parse(game['gameTimeGMT']).replace(tzinfo=tz.tzutc())
			start_time_local = start_time_gmt.astimezone(tz.tzlocal()).strftime(game_time_format)
		else:
			start_time_local = parser.parse(game['date']).strftime(xbmc.getRegion('dateshort'))

		# Start with the basic title of "Team vs Team".
		lang_id = 30027
		if self.at_instead_of_vs == True:
			home_team, away_team = away_team, home_team
			home_team_score, away_team_score = away_team_score, home_team_score
			lang_id = 30028
		title = home_team + __language__(lang_id) + away_team

		# Handle game status flags.
		if 'blocked' in game:
			title = __language__(30022) + ' ' + title
		else:
			game_ended = False
			if 'gameEndTimeGMT' in game:
				endTimeGMT = parser.parse(game['gameEndTimeGMT']).replace(tzinfo=tz.tzutc())
				if current_time_utc >= endTimeGMT:
					# Game has ended.
					game_ended = True
					time_delta = current_time_utc - endTimeGMT
					if time_delta.days < 1:
						title = __language__(30024) + ' ' + title
			if game_ended == False and 'isLive' in game and current_time_utc >= start_time_gmt:
				# Game is in progress.
				title = __language__(30023) + ' ' + title

		# Handle showing the game score.
		if self.show_scores and home_team_score is not None and away_team_score is not None:
			title += ' (%s-%s)' % (home_team_score, away_team_score)

		# Prepend the game start time.
		return start_time_local + ': ' + title

	def MODE_list(self, today_only):
		retry_args = {'mode': 'list'}
		if today_only == True:
			retry_args['type'] = 'today'
		else:
			retry_args['type'] = 'recent'

		scoreboard = None
		try:
			scoreboard = self.game_center.get_current_scoreboard()
		except nhlgc.NetworkError:
			pass

		try:
			games = self.game_center.get_games_list(today_only)
			for game in games:
				params = {
					'mode': 'view_options',
					'season': game['season'],
					'game_id': game['id'].zfill(4),
					'french_stream': game['frenchStream'],
					'publish_point_home': game['program']['publishPoint']['home'],
					'publish_point_away': game['program']['publishPoint']['away'],
					'publish_point_french': game['program']['publishPoint']['french'],
					'game_ended': False,
				}
				if 'gameEndTimeGMT' in game:
					params['game_ended'] = True
				else:
					params['mode'] = 'watch'
					params['stream_type'] = self.game_center.STREAM_TYPE_LIVE
				self.add_folder(self.game_title(game, scoreboard), params)
			return
		except nhlgc.NetworkError as error:
			self.display_notification(error)
		except nhlgc.LoginError as error:
			self.display_notification(error)
		except nhlgc.LogicError as error:
			self.display_notification(error)
		self.add_item(__language__(30030), __addonurl__, retry_args)

	def MODE_view_options(self, season, game_id, french_stream, publish_point, game_ended):
		game_id = game_id.zfill(4)
		view_options = [
			(__language__(30059), self.game_center.STREAM_TYPE_LIVE),
		]
		if game_ended == True:
			view_options += [
				(__language__(30060), self.game_center.STREAM_TYPE_CONDENSED),
				(__language__(30061), self.game_center.STREAM_TYPE_HIGHLIGHTS),
			]
		for label, stream_type in view_options:
			self.add_folder(label, {
				'mode': 'watch',
				'season': season,
				'game_id': game_id,
				'french_stream': french_stream,
				'stream_type': stream_type,
				'publish_point_home': publish_point['home'],
				'publish_point_away': publish_point['away'],
				'publish_point_french': publish_point['french'],
			})

	def MODE_watch(self, season, game_id, french_stream, stream_type, publish_point):
		game_id = game_id.zfill(4)
		retry_args = {
			'mode': 'watch',
			'season': season,
			'game_id': game_id,
			'french_stream': french_stream,
			'stream_type': stream_type,
			'publish_point_home': publish_point['home'],
			'publish_point_away': publish_point['away'],
			'publish_point_french': publish_point['french'],
		}

		if stream_type == self.game_center.STREAM_TYPE_HIGHLIGHTS:
			highlights = self.game_center.get_game_highlights(season, game_id)
			if 'home' in highlights and 'publishPoint' in highlights['home']:
				self.add_item(__language__(30025), highlights['home']['publishPoint'])
			if 'away' in highlights and 'publishPoint' in highlights['away']:
				self.add_item(__language__(30026), highlights['away']['publishPoint'])
			if 'french' in highlights and 'publishPoint' in highlights['away']:
				self.add_item(__language__(30062), highlights['french']['publishPoint'])
			return

		perspectives = [
			(__language__(30025), 'home', self.game_center.PERSPECTIVE_HOME),
			(__language__(30026), 'away', self.game_center.PERSPECTIVE_AWAY),
		]
		if french_stream == True:
			perspectives += [(__language__(30062), 'french', self.game_center.PERSPECTIVE_FRENCH)]

		seen_urls = {}
		use_bitrate = None
		for label, pub_point_key, perspective in perspectives:
			try:
				if stream_type == self.game_center.STREAM_TYPE_LIVE and publish_point[pub_point_key] is not None:
					playlists = self.game_center.get_playlists_from_m3u8_url(publish_point[pub_point_key])
				else:
					playlists = self.game_center.get_video_playlists(season, game_id, stream_type, perspective)

				if len(playlists) == 1:
					stream_url = playlists.values()[0]
				else:
					if use_bitrate is None or use_bitrate not in playlists:
						use_bitrate = self.select_bitrate(playlists)
					stream_url = playlists[use_bitrate]
				if stream_url not in seen_urls:
					self.add_item(label, self.game_center.get_authorized_stream_url(stream_url))
					seen_urls[stream_url] = True
			except nhlgc.NetworkError as error:
				if error.status_code != 404:
					self.display_notification(error)
					self.add_item(__language__(30030), __addonurl__, retry_args)
			except nhlgc.LoginError as error:
				self.display_notification(error)
				self.add_item(__language__(30030), __addonurl__, retry_args)

	def MODE_archives(self, season):
		retry_args = {
			'mode': 'archives',
			'season': season,
		}

		try:
			archives = self.game_center.get_archived_seasons()
			if season is None:
				for archive in archives:
					title = '%d - %d' % (int(archive['season']), int(archive['season']) + 1)
					self.add_folder(title, {
						'mode': 'archives',
						'season': archive['season'],
					})
			else:
				title = '%d - %d: ' % (int(season), int(season) + 1)
				for archive in archives:
					if archive['season'] != season:
						continue
					for month in archive['months']:
						self.add_folder(title + __language__(30037 + int(month) - 1), {
							'mode': 'archives_month',
							'season': season,
							'month': month,
						})
			return
		except nhlgc.NetworkError as error:
			self.display_notification(error)
		except nhlgc.LoginError as error:
			self.display_notification(error)
		except nhlgc.LogicError as error:
			self.display_notification(error)
		self.add_item(__language__(30030), __addonurl__, retry_args)

	def MODE_archives_month(self, season, month):
		retry_args = {
			'mode': 'archives_month',
			'season': season,
			'month': month,
		}

		try:
			games = self.game_center.get_archived_month(season, month)
			for game in games:
				if not 'publishPoint' in game['program']:
					continue
				self.add_folder(self.game_title(game, None), {
					'mode': 'view_options',
					'season': season,
					'game_id': game['id'].zfill(4),
					'french_stream': game['frenchStream'],
					'publish_point_home': game['program']['publishPoint']['home'],
					'publish_point_away': game['program']['publishPoint']['away'],
					'publish_point_french': game['program']['publishPoint']['french'],
					'game_ended': True,
				})
			return
		except nhlgc.NetworkError as error:
			self.display_notification(error)
		except nhlgc.LoginError as error:
			self.display_notification(error)
		except nhlgc.LogicError as error:
			self.display_notification(error)
		self.add_item(__language__(30030), __addonurl__, retry_args)

##
# Addon menu system.
##

try:
	game_center = XBMC_NHL_GameCenter()
	mode = __addonargs__.get('mode', None)
	if mode is None:
		game_center.add_folder(__language__(30029), {'mode': 'list', 'type': 'today'})
		game_center.add_folder(__language__(30032), {'mode': 'list', 'type': 'recent'})
		game_center.add_folder(__language__(30036), {'mode': 'archives', 'season': None})
	elif mode[0] == 'list':
		today_only = __addonargs__.get('type')[0] == 'today'
		game_center.MODE_list(today_only)
	elif mode[0] == 'view_options' or mode[0] == 'watch':
		season        = __addonargs__.get('season')[0]
		game_id       = __addonargs__.get('game_id')[0]
		french_stream = __addonargs__.get('french_stream')[0] == 'True'
		pub_point     = {
			'home':   __addonargs__.get('publish_point_home')[0],
			'away':   __addonargs__.get('publish_point_away')[0],
			'french': __addonargs__.get('publish_point_french')[0],
		}
		if pub_point['home'] == 'None':
			pub_point['home'] = None
		if pub_point['away'] == 'None':
			pub_point['away'] = None
		if pub_point['french'] == 'None':
			pub_point['french'] = None
		if mode[0] == 'view_options':
			game_ended = __addonargs__.get('game_ended')[0] == 'True'
			game_center.MODE_view_options(season, game_id, french_stream, pub_point, game_ended)
		else:
			stream_type = __addonargs__.get('stream_type')[0]
			game_center.MODE_watch(season, game_id, french_stream, stream_type, pub_point)
	elif mode[0] == 'archives':
		season = __addonargs__.get('season')[0]
		if season == 'None':
			season = None
		game_center.MODE_archives(season)
	elif mode[0] == 'archives_month':
		season = __addonargs__.get('season')[0]
		month  = __addonargs__.get('month')[0]
		game_center.MODE_archives_month(season, month)
except RuntimeError:
	pass

xbmcplugin.endOfDirectory(__addonhandle__)
