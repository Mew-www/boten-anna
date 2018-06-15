#!/usr/bin/env python

import discord
import os

from bs4 import BeautifulSoup, NavigableString
import requests
import random


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
        print('On servers: {}'.format(list(s.name for s in anna.servers)))

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
            new_alias = pick_alias(aliases)
            await anna.change_nickname(message.server.me, new_alias[0])
            await anna.send_message(message.channel, 'Of {} origin.'.format('/'.join(new_alias[1])))

    anna.run(os.environ['DISCORD_APP_BOT_USER_TOKEN'])


if __name__ == '__main__':
    main()
