import os
import logging

import psycopg2
from psycopg2 import sql

import pickle
import random
import uno, unoparser

from plural import plural

from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from telegram.error import TelegramError, Unauthorized, BadRequest,  TimedOut, ChatMigrated, NetworkError

bot = None
conn, cur = None, None

def main():
	
	# Environment vars
	TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
	TELEGRAM_BOT_WEBHOOK = os.environ.get('TELEGRAM_BOT_WEBHOOK')
	DATABASE_URL = os.environ.get('DATABASE_URL')
	PORT = os.environ.get('PORT')

	# Enable logging
	logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
	logger = logging.getLogger(__name__)

	## Database setup
	global conn, cur
	conn = psycopg2.connect(DATABASE_URL)
	cur = conn.cursor()

	## Bot setup
	# Set up the Updater
	updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)

	global bot
	bot = updater.bot

	## Handlers
	dp = updater.dispatcher

	# Command handlers
	dp.add_handler(CommandHandler('start', handler_start))
	dp.add_handler(CommandHandler('help', handler_help))
	dp.add_handler(CommandHandler('settings', handler_settings))

	dp.add_handler(CommandHandler('status', handler_status))
	dp.add_handler(CommandHandler('new', handler_new))
	dp.add_handler(CommandHandler('join', handler_join))
	dp.add_handler(CommandHandler('leave', handler_leave))
	dp.add_handler(CommandHandler('begin', handler_begin))
	dp.add_handler(CommandHandler('end', handler_end))

	dp.add_handler(CommandHandler('chat', handler_chat))

	# secret
	dp.add_handler(CommandHandler('error', handler_error))

	# Message handlers
	dp.add_handler(MessageHandler(Filters.text & Filters.private, handler_text_message))

	dp.add_error_handler(error_handler)

	# Start the webhook
	updater.start_webhook(listen="0.0.0.0", port=int(PORT), url_path=TELEGRAM_BOT_TOKEN, clean=True, allowed_updates=["message"])
	updater.bot.set_webhook(TELEGRAM_BOT_WEBHOOK + TELEGRAM_BOT_TOKEN)
	updater.idle()

## Bot handlers

def handler_start(update, context):
	update.message.reply_text(help_text(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

def handler_help(update, context):
	update.message.reply_text(help_text(), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

def handler_settings(update, context):

	text = ''
	user_id = update.message.from_user.id

	# All possible settings and its possible values (first one is the default)
	all_settings = {
		'style': ('short', 'emoji', 'circle', 'heart', 'long'),
	}

	settings = get_user_settings(user_id)

	if len(context.args) == 0:
		
		text += 'Your current settings:\n'

		for setting in all_settings:
			default = all_settings[setting][0]
			text += setting + ': ' + str(settings.get(setting, default)) + '\n'

	elif len(context.args) == 1:

		setting = context.args[0].lower()

		if setting in all_settings:
			default = all_settings[setting][0]
			text += setting + ': ' + str(settings.get(setting, default)) + '\n'
		else:
			text += 'This setting does not exist!\n'

	elif len(context.args) >= 2:

		setting = context.args[0].lower()
		value = context.args[1].lower()

		if setting in all_settings:
			if value in all_settings[setting]:

				update_user_settings(user_id, setting, value)
				db_commit()

				text += 'Setting set.\n'
			else:
				text += 'This value is not allowed for this setting!\n'
		else:
			text += 'This setting does not exist!\n'

	update.message.reply_text(text)

def handler_status(update, context):

	user_id = update.message.from_user.id

	get_and_apply_user_settings(user_id)
	text = status(get_current_room(user_id), user_id)

	send_message_to_user(context, user_id, text)

def handler_new(update, context):
	
	text = ''
	user_id = update.message.from_user.id
	current_room_id = get_current_room(user_id)

	if current_room_id == None:
		room_id = insert_room()
		insert_user_to_room(room_id, user_id)
		db_commit()

		text += 'Created and joined room ' + str(room_id) + '.\n'
	
	else:
		text = 'You are already in room ' + str(current_room_id) + '! You must /leave that room first.\n'

	update.message.reply_text(text)

def handler_join(update, context):

	text, text_to_all = '', ''
	user_id = update.message.from_user.id
	user_name = update.message.from_user.name
	room_id = None

	if len(context.args) > 0:
		room_id = string_to_positive_integer(context.args[0])

		if room_id != None:

			current_room_id = get_current_room(user_id)
			room_exists = check_room_exists(room_id)
			game = None

			if current_room_id:
				text += 'You are already in room ' + str(current_room_id) + '! You must /leave that room first.\n'

			if not room_exists:
				text += 'This room does not exist!\n'
			else:
				game = select_game(room_id)

			if game:
				text += 'A game is being played in this room! They must /end it before anyone can join.\n'

			if not current_room_id and room_exists and not game:
				insert_user_to_room(room_id, user_id)
				db_commit()

				text += 'Joined room ' + str(room_id) + '.\n'
				text_to_all += user_name + ' joined the room.\n'
			
		else:
			text += 'This can\'t possibly be a room! Come on!\n'

	else:
		text += 'You have not said the room you want to join! Try /join <room number>\n'

	update.message.reply_text(text)
	send_message_to_room(context, room_id, text_to_all)

def handler_leave(update, context):
	
	text, text_to_all = '', ''
	user_id = update.message.from_user.id
	user_name = update.message.from_user.name
	room_id = get_current_room(user_id)

	if room_id:

		game = select_game(room_id)

		if not game:

			delete_user_from_room(user_id)

			text += 'You have left room number '+str(room_id)+'.\n'

			if check_room_empty(room_id):
				delete_room(room_id)

				text += 'The room was empty with your departure, so it has been deleted.\n'
			else:
				text_to_all += user_name + ' left the room.\n'

			db_commit()

		else:
			text += 'A game is being played in this room! Someone must /end it before anyone can leave.\n'
		
	else:
		text += 'You are not in any room right now!\n'

	update.message.reply_text(text)
	send_message_to_room(context, room_id, text_to_all)

def handler_begin(update, context):

	text, text_to_all = '', ''
	user_id = update.message.from_user.id
	user_name = update.message.from_user.name
	room_id = get_current_room(user_id)

	if room_id:
		users = select_users_info_in_room(room_id)

		game = select_game(room_id)
		if not game:
			text_to_all += user_name + ' has begun the game'
		else:
			text_to_all += user_name + ' has rebegun the game'

		game = uno.Game()
		game.begin(len(users))

		update_game(room_id, game)

		numbers = list(range(len(users)))
		random.shuffle(numbers)

		for for_player_number, for_user_id in users:
			update_player_number(room_id, for_user_id, numbers.pop())

		db_commit()

		send_message_to_room(context, room_id, text_to_all)
		send_message_to_room(context, room_id, lambda user_id: status(room_id, user_id, show_room_info=False))

	else:
		update.message.reply_text("You cannot begin the game if you are not in a room! Try /new or /join <room number>")

def handler_end(update, context):
	
	user_id = update.message.from_user.id
	user_name = update.message.from_user.name
	room_id = get_current_room(user_id)

	if room_id:

		game = select_game(room_id)

		if game:
			update_game(room_id, None)
			db_commit()

			send_message_to_room(context, room_id, user_name + ' has ended the game')

		else:
			update.message.reply_text("But there is no game going on!")

	else:
		update.message.reply_text("You cannot end the game if you are not in a room! Try /new or /join <room number>")

def handler_chat(update, context):

	text, text_to_all = '', ''
	user_id = update.message.from_user.id
	user_name = update.message.from_user.name
	room_id = get_current_room(user_id)

	message = ' '.join(context.args)

	if room_id:
		text_to_all += user_name + ': ' + message
	else:
		text += 'You cannot send chat messages if you are not in a room!\n'
		update.message.reply_text(text)

	send_message_to_room(context, room_id, text_to_all, not_me=user_id)

def handler_error(update, context):

	user_id = update.message.from_user.id
	send_message_to_user(context, user_id, get_error_message())

def handler_text_message(update, context):
	
	user_id = update.message.from_user.id
	user_name = update.message.from_user.name
	room_id = get_current_room(user_id)

	if room_id:

		message = update.message.text

		game = select_game(room_id)
		player_number = select_player_number(room_id, user_id)
	
		if game.winner == None:

			if game.current_player == player_number:

				try:
					play = unoparser.parse_play(message)
					play_result = game.play(player_number, play)

					if play_result.success:

						update_game(room_id, game)
						db_commit()

						send_message_to_room(context, room_id, lambda x: user_name + ' ' + unoparser.play_result_string(play_result))

						if game.winner == None:

							current_user_id = select_user_id_from_player_number(room_id, game.current_player)

							get_and_apply_user_settings(current_user_id)

							# send message to player that is current
							context.bot.send_message(chat_id=current_user_id, text='It is your turn.\n' + status(room_id, current_user_id, show_room_info=False))

						else:

							send_message_to_room(context, room_id, lambda x: user_name + ' won.')

					else:

						fail_reason = unoparser.fail_reason_string(play_result.fail_reason)
						update.message.reply_text(fail_reason)

				except unoparser.InputParsingError as e:
					update.message.reply_text('That is not how you play! ' + str(e) + ' And try reading /help')

			else:
				current_user_id = select_user_id_from_player_number(room_id, game.current_player)
				update.message.reply_text('It is not your turn! The current player is ' + get_user_name(current_user_id))

		else:
			winner_user_id = select_user_id_from_player_number(room_id, game.winner)
			update.message.reply_text(get_user_name(winner_user_id) + ' already won this game! You cannot play anymore. Try /begin')

	else:
		update.message.reply_text('You cannot play if you are not in a room! Try /new or /join <room number>')

def error_handler(update, context):
	try:
		raise context.error
	except Unauthorized:
		# remove update.message.chat_id from conversation list
		logging.exception('Uncaught')
	except BadRequest:
		# handle malformed requests - read more below!
		logging.exception('Uncaught')
	except TimedOut:
		# handle slow connection problems
		logging.exception('Uncaught')
	except NetworkError:
		# handle other connection problems
		logging.exception('Uncaught')
	except ChatMigrated as e:
		# the chat_id of a group has changed, use e.new_chat_id instead
		logging.exception('Uncaught')
	except TelegramError:
		# handle all other telegram related errors
		logging.exception('Uncaught')
	except Exception as e:
		send_message_to_user(context, update.message.from_user.id, get_error_message())
		logging.exception('Uncaught')

## Helper functions

def help_text():
	return (
		"*ZeroXis bot - made by* @luizeldorado\n"
		"\n"
		"/help - Shows this\n"
		"/status - Show what's going on\n"
		"/new - Create new room\n"
		"/join - Join a room\n"
		"/leave - Leave a room\n"
		"/begin - Begin game\n"
		"/end - End game\n"
		"/chat - Send a message to all in room\n"
		"/settings - Change user settings\n"
		"\n"
		"When in game, send a message to make a play.\n"
		"d - Draw card(s)\n"
		"p - Pass\n"
		"c - Call bluff\n"
		"<color><kind> - Play card of said color and kind.\n"
		"<color> can be b, g, r, y, or nothing in kinds that have no color.\n"
		"<kind> can be 0 to 9, r, s, +2, +4, or w\n"
		"+4 and w have no color, but you have to specify a color after it.\n"
		"Examples: g6, rr, +4y\n"
		"\n"
		"Github: https://github.com/luizeldorado/uno-telegram-bot\n"
	)

def string_to_positive_integer(string):
	try:
		number = int(string)
	except ValueError:
		return None

	if number >= 0:
		return number

def send_message_to_user(context, user_id, text):
	if text:
		context.bot.send_message(chat_id=user_id, text=text)

def send_message_to_room(context, room_id, text, not_me=None):
	if text and room_id:
		for user_id in select_users_ids_in_room(room_id):
			if user_id != not_me:

				if callable(text):
					get_and_apply_user_settings(user_id)
					context.bot.send_message(chat_id=user_id, disable_web_page_preview=True, text=text(user_id))
				else:
					context.bot.send_message(chat_id=user_id, disable_web_page_preview=True, text=text)

def status(room_id, user_id, show_room_info=True):

	text = ''

	if room_id:
		users = select_users_info_in_room(room_id)
		game = select_game(room_id)

		if show_room_info:
			num_users = len(users)
			text += ('You are currently in room number ' + str(room_id)
				+ ', which has ' + str(num_users) + ' ' + plural(num_users, 'user', 'users') + '.\n')

		for for_player_number, for_user_id in users:

			for_user_name = get_user_name(for_user_id)

			if game:
				num_cards = len(game.player_cards[for_player_number])
				text += (str(for_player_number) + ': ' + for_user_name
					+ ' (' + str(num_cards) + ' ' + plural(num_cards, 'card', 'cards') + ')')

				if game.winner == None and game.current_player == for_player_number:
					text += ' <- Current player'
				elif game.winner == for_player_number:
					text += ' <- Winner'

			else:
				text += '- ' + for_user_name

			text += '\n'

		if game:

			text += 'Current card: ' + unoparser.card_string(game.get_current_card()) + '\n'
			if game.current_color != game.get_current_card().color:
				text += 'Chosen color: ' + unoparser.card_color_string(game.current_color) + '\n'

			player_number = next((for_player_number for for_player_number, for_user_id in users if for_user_id == user_id))

			text += 'Your cards: '
			
			if len(game.player_cards[player_number]) != 0:
				text += unoparser.card_list_string(game.player_cards[player_number])
			else:
				text += 'None!'

			text += '\n'

	else:
		text += 'You are currently not joined in any room.\n'

	return text

def get_error_message():
	return random.choice((
		"Could you just not?",
		"Don't you have anything better to do?",
		"Excuse me for one second, I have to do something.",
		"I can't listen. I'm out of phone signal. Bye.",
		"I just don't wanna do it right now",
		"I'm not in the mood. Maybe later.",
		"Leave me alone at least for one second",
		"Please, you're annoying me",
		"Remind me later.",
		"Screw this, I don't want to work on this garbage.",
		"Sorry, my cat is suffering from dysentery now.",
		"Sure, I'm gonna do that.",
		"This action requires Telegram Gold.",
		"Will I be able to finally relax one day?",
		"You could be living your life but you are texting a lifeless bot. Nice.",
		"no u",
	))

def get_and_apply_user_settings(user_id):

	settings = get_user_settings(user_id)

	style = settings.get('style', 'short')

	if style == 'short':
		unoparser.COLOR_STRINGS = unoparser.COLOR_STRINGS_SHORT
		unoparser.KIND_STRINGS = unoparser.KIND_STRINGS_SHORT
	elif style == 'emoji':
		unoparser.COLOR_STRINGS = unoparser.COLOR_STRINGS_EMOJI
		unoparser.KIND_STRINGS = unoparser.KIND_STRINGS_SHORT
	elif style == 'circle':
		unoparser.COLOR_STRINGS = unoparser.COLOR_STRINGS_CIRCLE
		unoparser.KIND_STRINGS = unoparser.KIND_STRINGS_SHORT
	elif style == 'heart':
		unoparser.COLOR_STRINGS = unoparser.COLOR_STRINGS_HEART
		unoparser.KIND_STRINGS = unoparser.KIND_STRINGS_SHORT
	elif style == 'long':
		unoparser.COLOR_STRINGS = unoparser.COLOR_STRINGS_LONG
		unoparser.KIND_STRINGS = unoparser.KIND_STRINGS_LONG

	return settings

def get_user_name(user_id):

	chat = bot.get_chat(user_id)
	if chat.username:
		return '@{}'.format(chat.username)
	return chat.full_name

## Database functions

def get_current_room(user_id):
	cur.execute("select room_id from uno_joins where user_id=%s limit 1;", (user_id,))
	result = cur.fetchone()

	if result:
		return result[0]

	return None

def get_user_settings(user_id):
	cur.execute("select * from uno_users where user_id=%s limit 1;", (user_id,))
	result = cur.fetchone()

	if not result:
		return {}
	else:
		columns = (description.name for description in cur.description)
		settings = dict(zip(columns, result))

		for key, value in settings.items():
			if not value:
				del settings[key]

		return settings

def select_users_info_in_room(room_id):
	cur.execute("select player_number, user_id from uno_joins where room_id=%s order by player_number, user_id;", (room_id,))
	return [(row[0], row[1],) for row in cur]

def select_users_ids_in_room(room_id):
	cur.execute("select user_id from uno_joins where room_id=%s order by user_id;", (room_id,))
	return [row[0] for row in cur]

def select_player_number(room_id, user_id):
	cur.execute("select player_number from uno_joins where room_id=%s and user_id=%s limit 1;", (room_id, user_id))
	return cur.fetchone()[0]

def select_user_id_from_player_number(room_id, player_number):
	cur.execute("select user_id from uno_joins where room_id=%s and player_number=%s limit 1;", (room_id, player_number))
	return cur.fetchone()[0]

def select_game(room_id):
	cur.execute("select game_pickle from uno_rooms where id=%s limit 1;", (room_id,))
	result = cur.fetchone()[0]

	if result:
		return pickle.loads(result)
	else:
		return None

def check_room_empty(room_id):
	cur.execute("select room_id from uno_joins where room_id=%s limit 1;", (room_id,))
	result = cur.fetchone()

	if result:
		return False

	return True

def check_room_exists(room_id):
	cur.execute("select id from uno_rooms where id=%s limit 1;", (room_id,))
	result = cur.fetchone()

	if result:
		return True

	return False

def insert_room():
	cur.execute("insert into uno_rooms default values returning id;")
	room_id = cur.fetchone()[0]
	# conn.commit()

	return room_id

def insert_user_to_room(room_id, user_id):
	cur.execute("insert into uno_joins (room_id, user_id) values (%s, %s);", (room_id, user_id,))
	# conn.commit()

def update_game(room_id, game):
	cur.execute("update uno_rooms set game_pickle=%s where id=%s;", (pickle.dumps(game), room_id,))
	# conn.commit()

def update_player_number(room_id, user_id, player_number):
	cur.execute("update uno_joins set player_number=%s where room_id=%s and user_id=%s;", (player_number, room_id, user_id,))
	# conn.commit()

def update_user_settings(user_id, setting, value):

	cur.execute(
		sql.SQL("insert into uno_users (user_id, {settings}) values (%s, %s) "
			"on conflict (user_id) do update set {settings} = excluded.{settings};")
			.format(
				settings=sql.Identifier(setting)
			),
		(user_id, value,)
	)
	# conn.commit()

def delete_user_from_room(user_id):
	cur.execute("delete from uno_joins where user_id=%s;", (user_id,))
	# conn.commit()

def delete_room(room_id):
	cur.execute("delete from uno_rooms where id=%s;", (room_id,))
	# conn.commit()

def db_commit():
	conn.commit()

if __name__ == "__main__":
	main()