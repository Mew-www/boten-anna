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


async def handle_wuv(anna, message):
    author = message.author
    # Check author name
    if not author.name == os.environ['DISCORD_APP_ADMIN_NAME']:
        return None
    # Check author #<discriminator>
    if not str(author.discriminator) == os.environ['DISCORD_APP_ADMIN_DISCRIM']:
        return None
    # Check author is on an existing voice channel
    if author.voice.voice_channel is None:
        return None
    voice = await anna.join_voice_channel(author.voice.voice_channel)
    voice_loop = voice.loop
    player = voice.create_ffmpeg_player('../smile.mp3',
                                        use_avconv=True,
                                        after=lambda: asyncio.run_coroutine_threadsafe(voice.disconnect(), voice_loop))
    player.start()


class VoiceInterface:

    def __init__(self, anna, priorities=None):
        self._anna = anna
        self._voice_client = None
        self._espeak = ESpeakNG(speed=135, voice='mb-de3-en')
        # The following environment variable is intended to be JSON in format [["USERNAME", "DISCRIMINATOR"], [..], ...]
        self._those_permitted_to_activate = json.loads(os.environ['DISCORD_APP_PRIVILEGED_USER_DISCRIM_PAIRS'])
        self._those_additionally_permitted_to_control_voice = []
        self._is_active = False
        self._currently_active_in = None  # String, server name
        self._currently_activated_by = None  # String, username#discriminator
        self._is_speaking = False
        # TODO <not-implemented> Init message queue and make shallow copy of priorities argument
        if priorities is None:
            priorities = []
        self._priorities = list(priorities)  # ['LOWEST_PRIORITY_IDENTIFIER', ..., 'HIGHEST_PRIORITY_IDENTIFIER']
        self._queued_messages = []

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
        :param deactivation_message:
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

        iter_words = map(lambda w: w if not w.startswith('#') and len(w) > 1 else 'hashtag '+w[1:], phrase.split(' '))
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
                target_name, target_discriminator = grant_voice_control_message.split(' ')[1].split('#')
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
            return None
        elif not self._user_is_permitted_to_control_voice(speak_request_message.author):
            await self._anna.send_message(speak_request_message.channel,
                                          '{}, you do not have the permission to control voice'.format(
                                              speak_request_message.author.mention
                                          ))
        else:
            self._speak(' '.join(speak_request_message.split(' ')[1:]))

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


async def handle_talking(anna, message, state):
    author = message.author
    # Check author name
    if (
                not (author.name == os.environ['DISCORD_APP_ADMIN_NAME'] and str(author.discriminator) == os.environ['DISCORD_APP_ADMIN_DISCRIM'])
            and not (author.name == os.environ['DISCORD_APP_SO_NAME'] and str(author.discriminator) == os.environ['DISCORD_APP_SO_DISCRIM'])
    ):
        return None
    # Check author is on an existing voice channel
    if author.voice.voice_channel is None:
        return None
    # Check if is already talking
    if state['is_talking']:
        return None
    state['is_talking'] = True
    voice = await anna.join_voice_channel(author.voice.voice_channel)
    espeak = ESpeakNG(speed=135)

    def disconnect_voice():
        asyncio.run_coroutine_threadsafe(voice.disconnect(), voice.loop)
        state['is_talking'] = False

    while True:
        followup_message = await anna.wait_for_message(author=message.author)
        if followup_message.content.startswith('%thanksenough'):
            disconnect_voice()
            break
        elif followup_message.content.startswith('%speed'):
            new_speed_str = followup_message.content.split(' ')[1]
            if len(new_speed_str) > 0:
                new_speed = int(new_speed_str)
                espeak.speed = new_speed
        elif followup_message.content.startswith('%voice'):
            new_voice_str = followup_message.content.split(' ')[1]
            if len(new_voice_str) > 0:
                espeak.voice = new_voice_str
        elif followup_message.content.startswith('%say '):
            words = followup_message.content.split(' ')[1:]
            # Create the PCM, get its options via "wave" module, upsample it to 48'000 to accommodate Discord v-channels
            synthesized_wav_bytes = espeak.synth_wav(' '.join(words))
            with wave.open(BytesIO(synthesized_wav_bytes)) as wh:
                resampled, cvstate = audioop.ratecv(synthesized_wav_bytes, wh.getsampwidth(), wh.getnchannels(),
                                                    wh.getframerate(), 48000,
                                                    None)
                voice.encoder_options(sample_rate=48000, channels=wh.getnchannels())
            # Speak
            player = voice.create_stream_player(BytesIO(resampled))
            player.start()


def main():
    anna = discord.Client(max_messages=1000)

    greetings = ['Goeie dag', 'Tungjatjeta', 'Ahlan bik', 'Nomoskar', 'Selam', 'Mingala ba', 'Nín hao', 'Zdravo', 'Nazdar',
                 'Hallo', 'Rush B', 'Helo', 'Hei', 'Bonjour', 'Guten Tag', 'Geia!', 'Shalóm', 'Namasté', 'Szia', 'Hai',
                 'Kiana', 'Dia is muire dhuit', 'Buongiorno', 'Kónnichi wa', 'Annyeonghaseyo', 'Sabai dii', 'Ave',
                 'Es mīlu tevi', 'Selamat petang', 'sain baina uu', 'Namaste', 'Hallo.', 'Salâm', 'Witajcie', 'Olá',
                 'Salut', 'Privét', 'Talofa', 'ćao', 'Nazdar', 'Zdravo', 'Hola', 'Jambo', 'Hej', 'Halo', 'Sàwàtdee kráp',
                 'Merhaba', 'Pryvít', 'Adaab arz hai', 'Chào']
    aliases = get_aliases()
    annas_voice = VoiceInterface(anna)

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
        elif message.content.startswith('%wuv'):
            # Has restriction of mii-only
            await handle_wuv(anna, message)
        elif message.content.startswith('%cometalk'):
            activated = await annas_voice.request_activation(message)
            while activated:
                def speak_or_grant_or_deactivate(msg):
                    return (msg.content.startswith('%say')
                            or msg.content.startswith('%grant')
                            or msg.content.startswith('%thanksenough'))
                followup_message = await anna.wait_for_message(check=speak_or_grant_or_deactivate)
                if followup_message.content.startswith('%say'):
                    await annas_voice.request_speak(followup_message)
                elif followup_message.content.startswith('%grant'):
                    await annas_voice.grant_current_voice_control_permissions(followup_message)
                elif followup_message.content.startswith('%thanksenough'):
                    await annas_voice.request_deactivation(followup_message)

    anna.run(os.environ['DISCORD_APP_BOT_USER_TOKEN'])


if __name__ == '__main__':
    main()
