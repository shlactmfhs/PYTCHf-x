from bs4 import BeautifulSoup
import requests
import pandas as pd
from itertools import chain
import re
import gc
from django.utils.encoding import iri_to_uri


def rename_keys(xml_data):
    """
    Rename attributes with duplicate names across different tags

    :param xml_data:
    :return:
    """

    searches = {'inning': ['num'],
                'atbat': ['num', 'des', 'des_es', 'event', 'b', 's', 'o', 'score'],
                'pitch': ['des', 'des_es', 'id', 'tfs', 'tfs_zulu'],
                'runner': ['id', 'event', 'score'],
                'action': ['b', 's', 'o', 'des', 'des_es', 'event', 'tfs', 'tfs_zulu'],
                'po': ['des']
    }

    for tag in searches.keys():
        for instance in xml_data.find_all(tag):
            for attr in searches[tag]:
                if attr in instance.attrs.keys():
                    instance.attrs[tag+'_'+attr] = instance.attrs.pop(attr)

    return xml_data


def build_count(game_rows):
    """
    Build count prior to event for every event

    :param game_rows:
    :return:
    """

    if 'type' in game_rows[0]:
        game_rows[0]['balls'] = 0
        game_rows[0]['strikes'] = 0
    else:
        prev_event = {'atbat_num': 0}

    for i, event in enumerate(game_rows):
        if i == 0:
            continue

        if 'type' in game_rows[i-1]:
            prev_event = game_rows[i-1]
        try:
            if event['atbat_num'] != prev_event['atbat_num']:
                event['balls'] = 0
                event['strikes'] = 0
            elif prev_event['type'] == 'B':
                event['balls'] = prev_event['balls'] + 1
                event['strikes'] = prev_event['strikes']
            elif prev_event['type'] == 'S':
                if (prev_event['pitch_des'] == 'Foul') and (prev_event['strikes'] == 2):
                    event['balls'] = prev_event['balls']
                    event['strikes'] = prev_event['strikes']
                else:
                    event['balls'] = prev_event['balls']
                    event['strikes'] = prev_event['strikes'] + 1
        except KeyError:
            continue

    return game_rows


def fill_in_score(game_rows):
    """
    Build score after event for every event

    :param game_rows:
    :return:
    """

    home = 0
    away = 0

    for event in game_rows:

        if 'runner_score' in event:
            if event['runner_score'] == 'T':
                try:
                    if int(event['home_team_runs']) > home:
                        home += 1
                    elif int(event['away_team_runs']) > away:
                        away += 1
                except KeyError:
                    if int(prev_event['home_team_runs']) > home:
                        home += 1
                    elif int(prev_event['away_team_runs']) > away:
                        away += 1

        event['home_team_runs'] = home
        event['away_team_runs'] = away

        prev_event = event

    return game_rows


def flatten_game_xml(xml_data, gid):
    """
    Build dataframe of pitches/actions/runner events

    :param xml_data:
    :return:
    """

    attr = {}
    rows = []


    def get_attributes(xml_source, attr_dict):
        """
        Pull out all attributes from each path through the tree

        :param xml_source:
        :param attr_dict:
        :return:
        """

        for tag in xml_source.children:
            try:
                new_attr = dict(chain(attr_dict.iteritems(), tag.attrs.iteritems()))
                if len(tag.contents) > 0:
                    get_attributes(tag, new_attr)
                else:
                    rows.append(new_attr)
            except AttributeError:
                pass

    get_attributes(xml_data, attr)
    c = 1
    for event in rows:
        event['game_id'] = gid
        event['event_index'] = c
        c += 1

    list_with_count = build_count(rows)

    list_with_scores = fill_in_score(list_with_count)

    return list_with_scores


def get_game(gid, year, month, day):
    """
    Get data for an individual game

    :return:
    """

    print gid
    game_events = None
    error = []

    try:
        response = requests.get('http://gd2.mlb.com/components/game/mlb/year_'+year+'/month_'+month+'/day_'+day+'/gid_'+gid+'/inning/inning_all.xml')
        xml = BeautifulSoup(response.content, 'xml')

        if xml.game is not None:
            # print "renaming"
            renamed_xml = rename_keys(xml)
            # print "flattening"
            game_events = flatten_game_xml(renamed_xml, gid)
        else:
            error.append(gid)

    except KeyError:
        error.append(gid)

    gc.collect()

    return game_events, error


def to_unicode(text):
    """

    :param text:
    :return:
    """
    if isinstance(text, unicode):
        return text

    try:
        text_unicode = unicode(text)
        return text_unicode
    except UnicodeDecodeError:
        try:
            text_unicode = text.decode('latin1')
            return text_unicode
        except:
            text_unicode = text.decode('utf-8')
            return text_unicode


def df_to_unicode(df):
    """

    :param df:
    :return:
    """

    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(to_unicode)

    return df


def df_to_ascii(df):
    """

    :param df:
    :return:
    """

    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(iri_to_uri)

    return df


if __name__ == '__main__':

    parsed_games = []
    error_games = []

    for year in range(2010, 2011):

        for mo in range(3, 11):

            month = str(mo)
            if len(month) == 1:
                month = '0'+month

            for i in range(1, 32):

                day = str(i)
                if len(day) == 1:
                    day = '0'+day

                response = requests.get('http://gd2.mlb.com/components/game/mlb/year_'+str(year)+'/month_'+month+'/day_'+day+'/')
                games_list = list(set(re.findall(r'gid_(\w+_+\d)', str(response.content))))

                for game in games_list:
                    # print game
                    type_response = requests.get('http://gd2.mlb.com/components/game/mlb/year_'+str(year)+'/month_'+month+'/day_'+day+'/gid_'+game+'/game.xml')
                    # print response
                    xml = BeautifulSoup(type_response.content, 'xml')
                    # print xml

                    if xml.game is None:
                        # print "xml.game is none"
                        continue

                    if xml.game.attrs['type'] == 'R':
                        temp_events, temp_err = get_game(game, str(year), month, day)
                        # print temp_events
                        # print temp_err
                        if temp_events is not None:
                            parsed_games += temp_events
                        error_games += temp_err
                        # print "done with game"

                    gc.collect()

    reg_games = pd.DataFrame(parsed_games)
    reg_games = df_to_ascii(reg_games)
    reg_games.to_csv("pitch_fx/pitches.csv")

    # pitcher_df = pd.DataFrame()
    # for gid, game_df in reg_games.groupby('game_id'):
    #     if '477132' in game_df['pitcher'].values:
    #         pitcher_df = pitcher_df.append(game_df)
    # pitcher_df.to_csv("pitch_fx/pitch_sequence/kershaw.csv")

    print "all of us with wings!"