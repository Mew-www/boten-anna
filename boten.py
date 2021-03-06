#!/usr/bin/env python

import discord
import os

from bs4 import BeautifulSoup, NavigableString
import requests

import random
import time
import asyncio

from espeakng import ESpeakNG
from io import BytesIO
import wave
import audioop
import json
import re

from pyvirtualdisplay import Display
from selenium import webdriver


def get_aliases():
    soup = BeautifulSoup(requests.get('https://en.wikipedia.org/wiki/Anna_(given_name)').text, 'html.parser')
    content = soup.find('div', {'class': "mw-parser-output"})
    names_countries = []
    for content_child in content.children:
        if not isinstance(content_child, NavigableString) and content_child.name == 'ul':
            for list_child in content_child.children:
                if not isinstance(list_child, NavigableString):
                    name_country = list_child.text.split(u'\u2013')
                    if len(name_country) < 2:
                        name_country = list_child.text.split(u'\u002D')
                    name_country[0] = name_country[0].strip()
                    name_country[1] = list(map(lambda country: country.strip(), name_country[1].split(',')))
                    names_countries.append(name_country)
            break
    return names_countries


def get_some_tweets(selenium_driver, on_topic):
    selenium_driver.get('https://twitter.com/search?q=' + on_topic)
    time.sleep(2)
    soup = BeautifulSoup(selenium_driver.page_source, 'html.parser')
    tweets = [re.sub(r'pic\.twitter\.com\S+', '',
                     re.sub(r'http\S+', '', p.text))
              for p in soup.findAll('p', class_='tweet-text')]
    image_links = list(filter(lambda group: group is not None,
                              map(lambda m_obj: m_obj.group(1) if m_obj else None,
                                  [re.search(r'(pic\.twitter\.com\S+)', p.text)
                                   for p in soup.findAll('p', class_='tweet-text')])))
    return list(filter(lambda t: len(t) > 0, tweets)), image_links


def pick_alias(names_countries):
    choice = random.choice(names_countries)
    return choice


async def handle_changename(anna, message, aliases):
    new_alias = pick_alias(aliases)
    await anna.change_nickname(message.server.me, new_alias[0])
    await anna.send_message(message.channel, 'Of {} origin.'.format('/'.join(new_alias[1])))


async def handle_wheremii(anna, message):
    fh = open('locations_mii.txt', 'r')
    lines = fh.readlines()
    fh.close()
    last_line_content = lines[-1].split(',')
    timedelta = int(time.time()) - int(last_line_content[0])
    time_str = '{} seconds'.format(timedelta)
    if timedelta >= 60:
        minutes, seconds = divmod(timedelta, 60)
        time_str = '{} minutes {} seconds'.format(minutes, seconds)
        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            time_str = '{} hours {} minutes {} seconds'.format(hours, minutes, seconds)
    await anna.send_message(message.channel, '{},{} ({} ago)'.format(last_line_content[4][0:8],
                                                                     last_line_content[5][0:8],
                                                                     time_str))


class VoiceInterface:

    def __init__(self, anna, priorities=None):
        self._anna = anna
        self._voice_client = None
        self._espeak = ESpeakNG(voice='mb-en1', speed=135, volume=50, word_gap=1, pitch=50)  # volume -> -a amplitude
        # Hardcoded voice options (since dependent on the system / espeak installation)
        self._voice_configurations = {
            'alfred_like': {
                'voice': 'mb-en1',
                'speed': 135,
                'amplitude': 50,
                'gap': 1,
                'pitch': 50
            },
            'jarvis_like': {
                'voice': 'mb-en1',
                'speed': 135,
                'amplitude': 50,
                'gap': 1,
                'pitch': 70
            },
            # ♥♥
            'anna': {
                'voice': 'mb-de3-en',
                'speed': 100,
                'amplitude': 50,
                'gap': 1,
                'pitch': 50
            },
            'pronounced_female': {
                'voice': 'mb-fr4-en',
                'speed': 135,
                'amplitude': 50,
                'gap': 1,
                'pitch': 50
            },
            'soft_robotic_female': {
                'voice': 'mb-sw2-en',
                'speed': 135,
                'amplitude': 50,
                'gap': 1,
                'pitch': 50
            },
            'robotic_female': {
                'voice': 'mb-us1',
                'speed': 100,
                'amplitude': 50,
                'gap': 1,
                'pitch': 50
            }
        }
        # The following environment variable is intended to be JSON in format [["USERNAME", "DISCRIMINATOR"], [..], ...]
        self._those_permitted_to_activate = json.loads(os.environ['DISCORD_APP_PRIVILEGED_USER_DISCRIM_PAIRS'])
        self._those_additionally_permitted_to_control_voice = []
        self._is_active = False
        self._currently_active_in = None  # String, server name
        self._currently_activated_by = None  # String, username#discriminator
        self._is_speaking = False
        # Init message queue and make shallow copy of priorities argument
        if priorities is None:
            priorities = []
        self._priorities = list(priorities)  # ['LOWEST_PRIORITY_IDENTIFIER', ..., 'HIGHEST_PRIORITY_IDENTIFIER']
        self._queued_messages = []  # [[phrase, priority_integer, time_added_int], ...]

    def _user_is_permitted_to_activate(self, user):
        """
        :param user: discord <User> (or superclass <Member>)
        :return: boolean, indicating if permitted to activate
        """
        for user_discriminator_pair in self._those_permitted_to_activate:
            if user.name == user_discriminator_pair[0] and str(user.discriminator) == user_discriminator_pair[1]:
                return True
        return False

    def _user_is_permitted_to_control_voice(self, user):
        """
        :param user: discord <User> (or superclass <Member>)
        :return: boolean, indicating if permitted to control voice
        """
        activator_name, activator_discriminator = self._currently_activated_by.split('#')
        if user.name == activator_name and str(user.discriminator) == activator_discriminator:
            return True
        for user_discriminator_pair in self._those_additionally_permitted_to_control_voice:
            if user.name == user_discriminator_pair[0] and str(user.discriminator) == user_discriminator_pair[1]:
                return True
        return False

    async def _activate(self, activation_message):
        """
        Sets a boolean flag self._is_active in addition to the self._voice_client.
        Voice client is instantiated async, so we need an additional (immediate) flag in case of subsequent calls.

        :param activation_message: discord <Message>
        :return: discord <VoiceClient>
        """
        requester = activation_message.author
        self._is_active = True
        self._currently_activated_by = '{}#{}'.format(requester.name, requester.discriminator)
        self._currently_active_in = activation_message.channel.server
        voice_client = await self._anna.join_voice_channel(requester.voice.voice_channel)
        self._voice_client = voice_client
        return voice_client

    def _deactivate(self):
        """
        :return: only-assert-able concurrent.futures.Future
        """
        future = asyncio.run_coroutine_threadsafe(self._voice_client.disconnect(), self._voice_client.loop)
        self._voice_client = None
        self._those_additionally_permitted_to_control_voice = []
        self._currently_activated_by = None
        self._currently_activate_in = None
        self._is_active = None
        return future

    def _speak(self, phrase):
        """
        :param phrase: String containing the words to speak.
        :return: None
        """
        self._is_speaking = True

        def finished_speaking():
            self._is_speaking = False

        iter_words = map(lambda w: w if not w.startswith('#') or len(w) == 1 else 'hashtag '+w[1:], phrase.split(' '))
        # Create PCM as-bytes
        synthesized_wav_bytes = self._espeak.synth_wav(' '.join(iter_words))
        # Upsample bytes to the frequency discord normally uses (48'000 Hz)
        with wave.open(BytesIO(synthesized_wav_bytes)) as wh:
            resampled_bytes, convert_state = audioop.ratecv(synthesized_wav_bytes, wh.getsampwidth(), wh.getnchannels(),
                                                            wh.getframerate(), 48000,
                                                            None)
            self._voice_client.encoder_options(sample_rate=48000, channels=wh.getnchannels())
        # Speak
        player = self._voice_client.create_stream_player(BytesIO(resampled_bytes), after=finished_speaking)
        player.start()

    async def request_activation(self, activation_message):
        """
        :param activation_message: discord <Message>
        :return: boolean, indicating if successfully activated
        """
        if not self._user_is_permitted_to_activate(activation_message.author):
            await self._anna.send_message(activation_message.channel,
                                          '{}, you do not have the permission to activate voice capabilities'.format(
                                              activation_message.author.mention
                                          ))
        elif activation_message.author.voice.voice_channel is None:
            await self._anna.send_message(activation_message.channel,
                                          '{}, you must be in a voice channel to request voice capabilities'.format(
                                              activation_message.author.mention
                                          ))
        elif self._is_active:
            await self._anna.send_message(activation_message.channel,
                                          'I have already been activated by {} in server {}.'.format(
                                              self._currently_activated_by,
                                              self._currently_active_in
                                          ))
        else:
            the_voice_client = await self._activate(activation_message)
            return True
        return False

    async def grant_current_voice_control_permissions(self, grant_voice_control_message):
        """
        :param grant_voice_control_message: discord <Message>
        :return: None
        """
        if not self._is_active:
            await self._anna.send_message(grant_voice_control_message.channel,
                                          'Not currently active.')
        elif self._voice_client is None:
            await self._anna.send_message(grant_voice_control_message.channel,
                                          'In middle of instantiating voice connection, try again later.')
        else:
            requester = grant_voice_control_message.author
            activator_name, activator_discriminator = self._currently_activated_by.split('#')
            if requester.name != activator_name or requester.discriminator != activator_discriminator:
                await self._anna.send_message(grant_voice_control_message.channel,
                                              'Activated by {}, only that user can grant voice permissions.'.format(
                                                  self._currently_activated_by
                                              ))
            else:
                target_name, target_discriminator = grant_voice_control_message.content.split(' ')[1].split('#')
                self._those_additionally_permitted_to_control_voice.append([target_name, target_discriminator])
                await self._anna.send_message(grant_voice_control_message.channel,
                                              '{}#{} now has voice control permission.'.format(
                                                  target_name,
                                                  target_discriminator
                                              ))

    async def request_speak(self, speak_request_message):
        """
        Implemented using else-s in case the logic changes from "returning Nones" to anything else (i.e. send_message)

        :param speak_request_message: discord <Message>
        :return: None
        """
        if not self._is_active:
            return None
        elif self._voice_client is None:
            return None
        elif self._is_speaking:
            phrase = ' '.join(speak_request_message.content.split(' ')[1:])
            self.add_to_queue(phrase, lowest_priority=True)
            return None
        elif not self._user_is_permitted_to_control_voice(speak_request_message.author):
            await self._anna.send_message(speak_request_message.channel,
                                          '{}, you do not have the permission to control voice'.format(
                                              speak_request_message.author.mention
                                          ))
        else:
            self._speak(' '.join(speak_request_message.content.split(' ')[1:]))

    async def add_tweets(self, voice_request_message, selenium_driver, event_loop):
        """
        TODO refactor this (essentially same mechanic as with grant_permission/set_voice) to a wrapper/decorator
        """
        if not self._is_active:
            await self._anna.send_message(voice_request_message.channel,
                                          'Not currently active.')
        elif self._voice_client is None:
            await self._anna.send_message(voice_request_message.channel,
                                          'In middle of instantiating voice connection, try again later.')
        else:
            requester = voice_request_message.author
            activator_name, activator_discriminator = self._currently_activated_by.split('#')
            if requester.name != activator_name or requester.discriminator != activator_discriminator:
                await self._anna.send_message(voice_request_message.channel,
                                              'Activated by {}, only that user can add messages to queue.'.format(
                                                  self._currently_activated_by
                                              ))
            else:
                keywords = voice_request_message.content.split(' ')[1:]
                if len(keywords) == 0:
                    await self._anna.send_message(voice_request_message.channel, 'No keywords given.')
                else:
                    limit = None
                    if len(keywords) > 1 and keywords[-1].isdigit():
                        limit = int(keywords[-1])
                        keywords = keywords[:-1]
                    query = '+'.join(keywords)
                    tweets, image_refs = await event_loop.run_in_executor(None, get_some_tweets, selenium_driver, query)
                    if limit is not None and limit > 0:
                        tweets = tweets[:limit]
                    for tweet in tweets:
                        self.add_to_queue(tweet)
                    await self._anna.send_message(voice_request_message.channel,
                                                  '{} tweets found via {}'.format(
                                                      len(tweets),
                                                      'twitter.com/search?q='+query
                                                  ))
                    for link in image_refs[:limit]:
                        pass
                        # await self._anna.send_message(voice_request_message.channel, 'http://{}'.format(link))

    async def set_voice(self, voice_request_message):
        """
        TODO refactor this (essentially same mechanic as with grant_permission/add_tweets) to a wrapper/decorator
        """
        if not self._is_active:
            await self._anna.send_message(voice_request_message.channel,
                                          'Not currently active.')
        elif self._voice_client is None:
            await self._anna.send_message(voice_request_message.channel,
                                          'In middle of instantiating voice connection, try again later.')
        else:
            requester = voice_request_message.author
            activator_name, activator_discriminator = self._currently_activated_by.split('#')
            if requester.name != activator_name or requester.discriminator != activator_discriminator:
                await self._anna.send_message(voice_request_message.channel,
                                              'Activated by {}, only that user can change voice attributes.'.format(
                                                  self._currently_activated_by
                                              ))
            else:
                options = voice_request_message.content.split(' ')[1:]
                if len(options) == 0:
                    await self._anna.send_message(voice_request_message.channel,
                                                  'No options given. <voice name> Available: {}'.format(
                                                      ', '.join(list(self._voice_configurations.keys()))
                                                  ))
                else:
                    voice_name = options[0]
                    if voice_name not in list(self._voice_configurations.keys()):
                        await self._anna.send_message(voice_request_message.channel,
                                                      'Invalid voice name. Available: {}'.format(
                                                          ', '.join(list(self._voice_configurations.keys()))
                                                      ))
                    else:
                        voice_configuration = self._voice_configurations[voice_name]
                        self._espeak.voice = voice_configuration['voice']
                        self._espeak.speed = voice_configuration['speed']
                        self._espeak.volume = voice_configuration['amplitude']
                        self._espeak.word_gap = voice_configuration['gap']
                        self._espeak.pitch = voice_configuration['pitch']

    def add_to_queue(self, phrase, priority=None, lowest_priority=False, highest_priority=False):
        """
        Intended to be used by background processes directly (i.e. no user involved)

        :param phrase: A string to add in queued messages. If no priority is indicated it will be set to 0
        :param priority: A string to lookup from self._priorities, and use its index as the value to pass as priority.
        :param lowest_priority: A flag to set True if message should have lowest priority (overrides arg "priority")
        :param highest_priority: A flag to set True if message should have highest priority (overrides all other args)
        :return: None
        """
        interpreted_priority = 0
        if highest_priority:
            interpreted_priority = max(map(lambda m: m[1], self._queued_messages))
        elif lowest_priority:
            pass  # The default, presumably no "< 0" priorities (unless programmatically set, but those are exceptions)
        elif priority is not None and priority in self._priorities:
            interpreted_priority = self._priorities.index(priority)
        self._queued_messages.append([phrase, interpreted_priority, int(time.time())])

    def speak_if_next_in_queue(self):
        """
        :return: The message content that was spoken, or None if no content to speak.
        """
        if len(self._queued_messages) == 0:
            return None
        elif not self._is_active:
            return None
        elif self._voice_client is None:
            return None
        elif self._is_speaking:
            return None  # In future can print or speak the number of queued messages here
        else:
            self._queued_messages = sorted(self._queued_messages, key=lambda m: (m[1], -1*m[2]))
            next_in_queue = self._queued_messages.pop()
            content = next_in_queue[0]
            self._speak(content)
            return content

    async def request_deactivation(self, deactivation_message):
        """
        :param deactivation_message: discord <Message>
        :return: boolean, indicating if successfully deactivated
        """
        if not self._is_active:
            await self._anna.send_message(deactivation_message.channel,
                                          'Not currently active.')
        elif self._voice_client is None:
            await self._anna.send_message(deactivation_message.channel,
                                          'In middle of instantiating voice connection, try again later.')
        else:
            requester = deactivation_message.author
            activator_name, activator_discriminator = self._currently_activated_by.split('#')
            if requester.name != activator_name or requester.discriminator != activator_discriminator:
                await self._anna.send_message(deactivation_message.channel,
                                              'Activated by {}, only that user is able to deactivate the voice.'.format(
                                                  self._currently_activated_by
                                              ))
            else:
                assert_able_future = self._deactivate()
                return True
        return False


def main():
    display = None
    driver = None
    try:
        print('Starting virtual display and selenium webdriver')
        display = Display(backend='xvfb', visible=False, size=(1920, 1080))
        display.start()
        ff_profile = webdriver.FirefoxProfile()
        ff_profile.set_preference("general.useragent.override", os.environ['WEBDRIVER_USERAGENT'])
        driver = webdriver.Firefox(ff_profile)

        print('Starting discord client')
        anna = discord.Client(max_messages=1000)

        greetings = ['Goeie dag', 'Tungjatjeta', 'Ahlan bik', 'Nomoskar', 'Selam', 'Mingala ba', 'Nín hao', 'Zdravo', 'Nazdar',
                     'Hallo', 'Rush B', 'Helo', 'Hei', 'Bonjour', 'Guten Tag', 'Geia!', 'Shalóm', 'Namasté', 'Szia', 'Hai',
                     'Kiana', 'Dia is muire dhuit', 'Buongiorno', 'Kónnichi wa', 'Annyeonghaseyo', 'Sabai dii', 'Ave',
                     'Es mīlu tevi', 'Selamat petang', 'sain baina uu', 'Namaste', 'Hallo.', 'Salâm', 'Witajcie', 'Olá',
                     'Salut', 'Privét', 'Talofa', 'ćao', 'Nazdar', 'Zdravo', 'Hola', 'Jambo', 'Hej', 'Halo', 'Sàwàtdee kráp',
                     'Merhaba', 'Pryvít', 'Adaab arz hai', 'Chào']
        aliases = get_aliases()
        annas_voice = VoiceInterface(anna)

        # Background task, TODO implement speak_if_next_in_queue in same manner as await client.wait_for_message
        async def speak_message_queue():
            await anna.wait_until_ready()
            while not anna.is_closed:
                annas_voice.speak_if_next_in_queue()
                await asyncio.sleep(5)  # Check for queued messages every 5 seconds

        @anna.event
        async def on_ready():
            print('Online, connected ^__^')
            print('Having username {}#{} (UID: {})'.format(anna.user.name, anna.user.discriminator, anna.user.id))
            print('On servers: {}'.format(', '.join(list(s.name for s in anna.servers))))

        @anna.event
        async def on_server_join(server):
            print('Joined server {}'.format(server.name))

        @anna.event
        async def on_server_remove(server):
            print('Vacated from server {}'.format(server.name))

        @anna.event
        async def on_message(message):
            if message.content.startswith('%hello'):
                await anna.send_message(message.channel, random.choice(greetings))
            elif message.content.startswith('%changename'):
                await handle_changename(anna, message, aliases)
            elif message.content.startswith('%wheremii'):
                await handle_wheremii(anna, message)
            elif message.content.startswith('%cometalk'):
                activated = await annas_voice.request_activation(message)
                while activated:
                    def speak_or_grant_or_deactivate(msg):
                        return (msg.content.startswith('%say')
                                or msg.content.startswith('%grant')
                                or msg.content.startswith('%voice')
                                or msg.content.startswith('%twitter')
                                or msg.content.startswith('%thanksenough'))
                    followup_message = await anna.wait_for_message(check=speak_or_grant_or_deactivate)
                    if followup_message.content.startswith('%say'):
                        await annas_voice.request_speak(followup_message)
                    elif followup_message.content.startswith('%grant'):
                        await annas_voice.grant_current_voice_control_permissions(followup_message)
                    elif followup_message.content.startswith('%voice'):
                        await annas_voice.set_voice(followup_message)
                    elif followup_message.content.startswith('%twitter'):
                        await annas_voice.add_tweets(followup_message, driver, anna.loop)
                    elif followup_message.content.startswith('%thanksenough'):
                        deactivated = await annas_voice.request_deactivation(followup_message)
                        if deactivated:
                            break

        anna.loop.create_task(speak_message_queue())
        anna.run(os.environ['DISCORD_APP_BOT_USER_TOKEN'])

    finally:
        if driver is not None:
            driver.quit()
        if display is not None:
            display.stop()


if __name__ == '__main__':
    main()