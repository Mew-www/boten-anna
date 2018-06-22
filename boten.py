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
                resampled, state = audioop.ratecv(synthesized_wav_bytes, wh.getsampwidth(), wh.getnchannels(),
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
    state = {
        'is_talking': False
    }

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
            # Has restriction of mii-only
            await handle_talking(anna, message, state)

    anna.run(os.environ['DISCORD_APP_BOT_USER_TOKEN'])


if __name__ == '__main__':
    main()
