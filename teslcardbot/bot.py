import requests
import random
import json
import praw
import re
import os

from prawcore.exceptions import PrawcoreException

import praw.exceptions

def remove_duplicates(seq):
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]

class Card:
    CARD_IMAGE_BASE_URL = 'http://www.legends-decks.com/img_cards/{}.png'
    CARD_IMAGE_404_URL = 'http://imgur.com/1Lxy3DA'
    JSON_DATA = []
    KEYWORDS = ['Prophecy', 'Breakthrough', 'Guard', 'Regenerate', 'Charge', 'Ward', 'Shackle',
                'Lethal', 'Pilfer', 'Last Gasp', 'Summon', 'Drain', 'Assemble', 'Betray',
                'Exalt', 'Plot', 'Rally', 'Slay', 'Treasure Hunt']
    PARTIAL_MATCH_END_LENGTH = 20

    @staticmethod
    def preload_card_data(path='data/cards.json'):
        dir = os.path.dirname(__file__)
        filename = os.path.join(dir, path)

        with open(filename) as f:
            Card.JSON_DATA = json.load(f)

    @staticmethod
    def _escape_name(card):
        return re.sub(r'[\s_\-"\',;{\}]', '', card).lower()

    @staticmethod
    def _img_exists(url):
        req = requests.get(url)
        return req.headers['content-type'] == 'image/png'

    @staticmethod
    def _extract_keywords(text):
        expr = re.compile(r'((?<!Gasp:\s)\w+(?:\sGasp)?)', re.I)
        # If the card is an item, remove the +x/+y from its text.
        text = re.sub(r'\+\d/\+\d', '', text)
        words = expr.findall(text)
        # Keywords are extracted until a non-keyword word is found
        keywords = []
        for word in words:
            word = word.title()
            if word in Card.KEYWORDS:
                keywords.append(word)
            else:
                break
        return remove_duplicates(keywords)

    @staticmethod
    def _fetch_data_partial(name):
        i = 0
        matches = ['', '']
        while len(matches) > 1 and i <= Card.PARTIAL_MATCH_END_LENGTH:
            matches = [s for s in Card.JSON_DATA if Card._escape_name(s['name']).startswith(Card._escape_name(name[:i]))]
            i += 1

        if len(matches) == 0:
            return None

        match = matches[0]
        if Card._escape_name(match['name'])[:len(name)] == Card._escape_name(name):
            return match
        return None

    @staticmethod
    def get_info(name):
        name = Card._escape_name(name)

        if name == 'teslcardbot':  # I wonder...
            return Card('TESLCardBot', 'https://imgs.xkcd.com/comics/tabletop_roleplaying.png',
                        type='Bot',
                        attribute_1='Python',
                        attribute_2='JSON',
                        rarity='Legendary',
                        text='If your have more health than your opponent, win the game.',
                        cost='∞', power='∞', health='∞')

        # If JSON_DATA hasn't been populated yet, try to do it now or fail miserably.
        if len(Card.JSON_DATA) <= 0:
            Card.preload_card_data()
            assert (len(Card.JSON_DATA) > 0)

        data = Card._fetch_data_partial(name)

        if data is None:
            return None

        img_url = Card.CARD_IMAGE_BASE_URL.format(Card._escape_name(data['name']))
        # Unlikely, but possible?
        if not Card._img_exists(img_url):
            img_url = Card.CARD_IMAGE_404_URL

        name = data['name']
        type = data['type']
        attr_1 = data['attribute_1']
        if 'attribute_2' in data: 
            attr_2 = data['attribute_2']
        else:
            attr_2 = ''
        if 'attribute_3' in data: 
            attr_3 = data['attribute_3']
        else:
            attr_3 = ''
        rarity = data['rarity']
        unique = data['isunique'] == 'true'
        cost = int(data['cost'])
        text = data['text']
        power = ''
        health = ''
        if type == 'creature':
            power = int(data['attack'])
            health = int(data['health'])
        elif type == 'item':
            # Stats granted by items are extracted from their text
            stats = re.findall(r'\+(\d)/\+(\d)', text)
            power, health = stats[0]

        return Card(name=name,
                    img_url=img_url,
                    type=type,
                    attribute_1=attr_1,
                    attribute_2=attr_2,
                    attribute_3=attr_3,
                    rarity=rarity,
                    unique=unique,
                    cost=cost,
                    power=power,
                    health=health,
                    text=text)

    def __init__(self, name, img_url, type='Creature', attribute_1='neutral',
                 attribute_2='', attribute_3='', text='', rarity='Common', unique=False, cost=0, power=0, health=0):
        self.name = name
        self.img_url = img_url
        self.type = type
        if len(attribute_3) > 0:
            self.attributes = [attribute_1.title(), attribute_2.title(), attribute_3.title()]
        elif len(attribute_2) > 0:
            self.attributes = [attribute_1.title(), attribute_2.title()]   
        else:
            self.attributes = [attribute_1.title()]
        self.rarity = rarity
        self.unique = unique
        self.cost = cost
        self.power = power
        self.health = health
        self.text = text
        self.keywords = Card._extract_keywords(text)

    def __str__(self):
        template = '[📷]({url}) {name} ' \
                   '| {type} | {stats} | {keywords} | {attrs} | {unique}{rarity} | {text}'

        def _format_stats(t):
            if self.type == 'creature':
                return t.format(self.cost, self.power, self.health)
            elif self.type == 'item':
                return t.format(self.cost, '+{}'.format(self.power), '+{}'.format(self.health))
            else:
                return t.format(self.cost, '?', '?')

        return template.format(
            attrs='/'.join(map(str, self.attributes)),
            unique='' if not self.unique else 'Unique ',
            rarity=self.rarity.title(),
            name=self.name,
            url=self.img_url,
            type=self.type.title(),
            mana=self.cost,
            stats=_format_stats('{} - {}/{}'),
            keywords=', '.join(map(str, self.keywords)) + '' if len(self.keywords) > 0 else 'None',
            text=self.text if len(self.text) > 0 else 'This card has no text.'
        )

class TESLCardBot:
    CARD_MENTION_REGEX = re.compile(r'\{\{((?:.*?)+)\}\}')

    @staticmethod
    def find_card_mentions(s):
        return remove_duplicates(TESLCardBot.CARD_MENTION_REGEX.findall(s))

    def _get_praw_instance(self):
        r = praw.Reddit(client_id=os.environ['CLIENT_ID'], client_secret=os.environ['CLIENT_SECRET'], 
        user_agent='Python TESL Bot 9000.01 u/tesl-bot-9000', username=os.environ['REDDIT_USERNAME'], 
        password=os.environ['REDDIT_PASSWORD'])
        return r

    def _process_submission(self, s):
        cards = TESLCardBot.find_card_mentions(s.selftext)
        if len(cards) > 0 and not s.saved:
            try:
                self.log('Commenting in {} about the following cards: {}'.format(s.title, cards))
                response = self.build_response(cards)
                s.reply(response)
                s.save()
                self.log('Done commenting and saved thread.')
            except:
                self.log('There was an error while trying to leave a comment.')
                raise

    def _process_comment(self, c):
        cards = TESLCardBot.find_card_mentions(c.body)
        if len(cards) > 0 and not c.saved and c.author != os.environ['REDDIT_USERNAME']:
            try:
                self.log('Replying to {} about the following cards: {}'.format(c.id, cards))
                response = self.build_response(cards)
                c.reply(response)
                c.save()
                self.log('Done replying and saved comment.')
            except:
                self.log('There was an error while trying to reply.')
                raise

    # TODO: Make this template-able, maybe?
    def build_response(self, cards):
        response = 'Name | Type | Stats | Keywords | Attribute | ' \
                   'Rarity | Text \n--|--|--|--|--|--|--|--\n'

        cards_not_found = []

        for name in cards:
            card = Card.get_info(name)
            if card is None:
                cards_not_found.append(name)
            else:
                response += '{}\n'.format(str(card))

        did_you_know = random.choice(['You can hover the camera emoji to read a card\'s text!',
                                      'I can do partial matches!',
                                      'I was made in Python 🐍',
                                      'My code is open-source and anyone can contribute to it.',
                                      'I might hide a few easter eggs.',
                                      'You can send your suggestions to my maintainer, no matter how insignificant. '
                                      'Or you can open an issue on GitHub.',
                                      'My maintainer doesn\'t actively monitor this sub, or my replies, so PM him if you need anything.',
                                      ])
        auto_word = random.choice(['automatically', 'automagically'])

        if len(cards_not_found) == len(cards):
            response = 'I\'m sorry, but none of the cards you mentioned were matched. ' \
                       'Tokens and other generated cards may be included soon.\n'
        elif len(cards_not_found) > 0:
            response += '\n^(Some of the cards you mentioned were not matched: _{}._ ' \
                        'Tokens and other generated cards may be included soon.)\n'.format(', '.join(cards_not_found))

        response += '\n**Did you know?** _{}_\n\n' \
                    '\n\n&nbsp;\n\n^(_I am a bot, and this action was performed {}. Created by user G3Kappa. ' \
                    'Maintained by NotGooseFromTopGun. ' \
                    'Special thanks to Jeremy at legends-decks._)' \
                    '\n\n[^Source ^Code](https://github.com/jrwhitehead/TESLCardBot/) ^| [^Send ^PM](https://www.reddit.com/' \
                    'message/compose/?to={})'.format(did_you_know, auto_word, self.author)
        return response

    def log(self, msg):
        print('TESLCardBot # {}'.format(msg))

    def start(self, batch_limit=10, buffer_size=1000):
        r = None
        try:
            r = self._get_praw_instance()

        except PrawcoreException as e:
            self.log('Reddit seems to be down! Aborting.')
            self.log(e)
            return

        already_done = []
        subreddit = r.subreddit(self.target_sub)
        
        while True:
            try:
                new_submissions = [s for s in subreddit.new(limit=batch_limit) if s.id not in already_done]
                # new_submissions = subreddit.stream.submissions()

                # new_comments = [c for c in r.subreddit(self.target_sub).stream.comments() if c.id not in already_done]
                new_comments = r.subreddit(self.target_sub).stream.comments() 
                
            except PrawcoreException as e:
                # print(subreddit)
                # print(r.user.me())
                self.log('Reddit seems to be down! Aborting.')
                self.log(e)
                return

            for s in new_submissions:
                self._process_submission(s)
                # The bot will also save submissions it replies to to prevent double-posting.
                already_done.append(s.id)
            for c in new_comments:
                self._process_comment(c)
                # The bot will also save comments it replies to to prevent double-posting.
                already_done.append(c.id)

            # If we're using too much memory, remove the bottom elements
            if len(already_done) >= buffer_size:
                already_done = already_done[batch_limit:]

    def __init__(self, author='Anonymous', target_sub='all'):
        self.author = author
        self.target_sub = target_sub
