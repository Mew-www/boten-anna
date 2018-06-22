#!/usr/bin/env python

import discord
import os

from bs4 import BeautifulSoup, NavigableString
import requests
import random
import time

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
    player = voice.create_ffmpeg_player('../smile.mp3', use_avconv=True, after=lambda: voice.disconnect())
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
            await handle_wuv(anna, message)

    anna.run(os.environ['DISCORD_APP_BOT_USER_TOKEN'])


if __name__ == '__main__':
    main()
