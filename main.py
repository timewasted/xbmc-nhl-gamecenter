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
gameTimeFormat  = xbmc.getRegion('dateshort') + ' ' + xbmc.getRegion('time').replace(':%S', '')

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
		rogerslogin = __addon__.getSetting('gc_rogerslogin')
		self.game_center = nhlgc(username, password, rogerslogin, __cookiesfile__)

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
			team_names = 'city'
		self.show_scores = __addon__.getSetting('show_scores') == 'true'
		self.at_instead_of_vs = __addon__.getSetting('at_instead_of_vs') == 'true'

	def parse_teams_json(self, teams_file):
		with open(teams_file) as file_obj:
			teams_json = file_obj.read()
		return json.loads(teams_json)

	def display_notification(self, msg):
		# FIXME: This notification is sort of worthless. Maybe make it a dialog
		# that needs to be manually dismissed?
		xbmc.executebuiltin('Notification(%s, %s, %d, %s' % (__addonname__, msg, 5000, __addonicon__))

	def add_folder(self, label, params):
		xbmcplugin.addDirectoryItem(
			isFolder=True,
			handle=__addonhandle__,
			url=__addonurl__ + '?' + urllib.urlencode(params),
			listitem=xbmcgui.ListItem(label, iconImage='DefaultFolder.png')
		)

	def add_item(self, label, url):
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
		home_team = game['homeTeam']
		if type(home_team) == type(list()):
			home_team = home_team[0]
		away_team = game['awayTeam']
		if type(away_team) == type(list()):
			away_team = away_team[0]
		home_team_score, away_team_score = None, None
		game['id'] = game['id'].zfill(4)
		if game['id'] in scoreboard:
			home_team_score = scoreboard[game['id']]['hts']
			away_team_score = scoreboard[game['id']]['ats']
		if self.team_info_key is not None:
			home_team = self.team_info[home_team][self.team_info_key]
			away_team = self.team_info[away_team][self.team_info_key]

		currentTimeUTC = datetime.utcnow().replace(tzinfo=tz.tzutc())
		startTimeGMT = parser.parse(game['gameTimeGMT']).replace(tzinfo=tz.tzutc())
		startTimeLocal = startTimeGMT.astimezone(tz.tzlocal()).strftime(gameTimeFormat)

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
			gameEnded = False
			if 'gameEndTimeGMT' in game:
				endTimeGMT = parser.parse(game['gameEndTimeGMT']).replace(tzinfo=tz.tzutc())
				if currentTimeUTC >= endTimeGMT:
					# Game has ended.
					gameEnded = True
					title = __language__(30024) + ' ' + title
			if gameEnded == False and 'isLive' in game and currentTimeUTC >= startTimeGMT:
				# Game is in progress.
				title = __language__(30023) + ' ' + title

		# Handle showing the game score.
		if self.show_scores and home_team_score is not None and away_team_score is not None:
			title += ' (%d-%d)' % (home_team_score, away_team_score)

		# Prepend the game start time.
		return startTimeLocal + ': ' + title

	def MODE_list(self, today_only):
		retry_args = {'mode': 'live'}

		scoreboard = None
		try:
			scoreboard = self.game_center.get_current_scoreboard()
		except nhlgc.NetworkError:
			pass

		try:
			games = self.game_center.get_games_list(today_only)
			for game in games:
				params = {
					'mode': 'watch',
					'season': game['season'],
					'game_id': game['id'].zfill(4),
				}
				self.add_folder(self.game_title(game, scoreboard), params)
			return
		except nhlgc.NetworkError as error:
			self.display_notification(error)
		except nhlgc.LoginError as error:
			self.display_notification(error)
		except nhlgc.LogicError as error:
			self.display_notification(error)
		self.add_folder(__language__(30030), retry_args)

	def MODE_watch(self, season, game_id):
		game_id = game_id.zfill(4)
		retry_args = {
			'mode': 'watch',
			'season': season,
			'game_id': game_id,
		}
		perspectives = [
			(__language__(30025), '2'), # Home stream
			(__language__(30026), '4'), # Away stream
		]

		use_bitrate = None
		for label, perspective in perspectives:
			try:
				playlists = self.game_center.get_video_playlists(season, game_id, perspective)
				if len(playlists) == 1:
					stream = playlists.values()[0]
					self.add_item(label, self.game_center.get_authorized_stream_url(stream))
				else:
					if use_bitrate is None:
						use_bitrate = self.select_bitrate(playlists)
					self.add_item(label, self.game_center.get_authorized_stream_url(playlists[use_bitrate]))
			except nhlgc.NetworkError as error:
				self.display_notification(error)
				self.add_folder(__language__(30030), retry_args)
			except nhlgc.LoginError as error:
				self.display_notification(error)
				self.add_folder(__language__(30030), retry_args)

##
# Addon menu system.
##

game_center = XBMC_NHL_GameCenter()
mode = __addonargs__.get('mode', None)
if mode is None:
	game_center.add_folder(__language__(30029), {'mode': 'list', 'type': 'today'})
	game_center.add_folder(__language__(30032), {'mode': 'list', 'type': 'recent'})
elif mode[0] == 'list':
	today_only = __addonargs__.get('type')[0] == 'today'
	game_center.MODE_list(today_only)
elif mode[0] == 'watch':
	season      = __addonargs__.get('season')[0]
	game_id     = __addonargs__.get('game_id')[0]
	game_center.MODE_watch(season, game_id)

xbmcplugin.endOfDirectory(__addonhandle__)
