import os
import time
from datetime import datetime
from itertools import cycle

from django.core.exceptions import ObjectDoesNotExist
from django.utils.timezone import make_aware

from douban_group_spy.const import USER_AGENT, DATETIME_FORMAT

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'douban_group_spy.settings')
import django
django.setup()

import click
import requests
from threading import Thread
import logging

from douban_group_spy.settings import GROUP_TOPICS_BASE_URL, GROUP_INFO_BASE_URL, DOUBAN_BASE_HOST
from douban_group_spy.models import Group, Post


lg = logging.getLogger(__name__)
douban_base_host = cycle(DOUBAN_BASE_HOST)


def process_posts(posts, group, keywords, exclude):
    for t in posts['topics']:
        # ignore title or content including exclude keywords
        exclude_flag = False
        for e in exclude:
            if e in t['title'] or e in t['content']:
                exclude_flag = True
                break
        if exclude_flag:
            continue

        post = Post.objects.filter(post_id=t['id']).first()
        # ignore same id
        if post:
            post.updated = make_aware(datetime.strptime(t['updated'], DATETIME_FORMAT))
            post.save(force_update=['updated'])
            continue
        # ignore same title
        if Post.objects.filter(title=t['title']).exists():
            continue

        keyword_list = []
        is_matched = False
        for k in keywords:
            if k in t['title'] or k in t['content']:
                keyword_list.append(k)
                is_matched = True

        post = Post(
            post_id=t['id'], group=group,
            author_info=t['author'], alt=t['alt'],
            title=t['title'], content=t['content'],
            photo_list=[i['alt'] for i in t['photos']],
            # rent=0.0, subway='', contact='',
            is_matched=is_matched, keyword_list=keyword_list,
            created=make_aware(datetime.strptime(t['created'], DATETIME_FORMAT)),
            updated=make_aware(datetime.strptime(t['updated'], DATETIME_FORMAT))
        )
        post.save(force_insert=True)


def crawl(group_id, pages, keywords, exclude):
    lg.info(f'start crawling group: {group_id}')
    try:
        group = Group.objects.get(id=group_id)
    except ObjectDoesNotExist:
        g_info = requests.get(GROUP_INFO_BASE_URL.format(group_id)).json()
        lg.info(f'Getting group: {group_id} successful')
        group = Group(
            id=g_info['uid'],
            group_name=g_info['name'],
            alt=g_info['alt'],
            member_count=g_info['member_count'],
            created=make_aware(datetime.strptime(g_info['created'], DATETIME_FORMAT))
        )
        group.save(force_insert=True)

    for p in range(pages):
        time.sleep(1)
        kwargs = {
            'url': GROUP_TOPICS_BASE_URL.format(next(douban_base_host), group_id),
            'params': {'start': p},
            'headers': {'User-Agent': USER_AGENT}
        }
        req = getattr(requests, 'get')(**kwargs)
        lg.info(f'getting group: {group_id}, page: {p}, status: {req.status_code}')
        # if 400, switch host
        if req.status_code == 400:
            lg.info('Rate limit, switching host...')
            req = getattr(requests, 'get')(**kwargs)

        posts = req.json()
        process_posts(posts, group, keywords, exclude)


@click.command(help='example: python crawler_main.py -g 10086 -g 12345 -k xx花园 -k xx地铁 -e 求租')
@click.option('--groups', '-g', help='group id', required=True, multiple=True, type=str)
@click.option('--keywords', '-k',  help='search keywords', multiple=True, type=str)
@click.option('--exclude', '-e',  help='excluded keywords', multiple=True, type=str)
@click.option('--sleep', help='time sleep', default=60 * 30)
@click.option('--pages', help='crawl page range', default=20)
@click.option('-v', help='Show debug info', is_flag=True)
def main(groups: tuple, keywords: tuple, exclude: tuple, sleep, pages, v):
    logging.basicConfig(level=logging.DEBUG) if v else logging.basicConfig(level=logging.INFO)
    while True:
        threads = []
        for g_id in groups:
            process = Thread(target=crawl, args=[g_id, pages, keywords, exclude])
            process.start()
            threads.append(process)
        for process in threads:
            process.join()
        lg.info('Sleeping...')
        time.sleep(sleep)


if __name__ == '__main__':
    main()