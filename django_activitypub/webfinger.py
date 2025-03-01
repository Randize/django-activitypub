from django_activitypub.signed_requests import signed_post
from functools import lru_cache

import requests

WEBFINGER_TIMEOUT = 10


class WebfingerException(Exception):
    def __init__(self, error):
        super().__init__()
        self.error = error


def finger(username, domain):
    try:
        res = requests.get(
            f'https://{domain}/.well-known/webfinger',
            params={
                'resource': f'acct:{username}@{domain}',
            },
            headers={
                'Accept': 'application/jrd+json',
            },
            timeout=WEBFINGER_TIMEOUT,
            verify=True
        )
        res.raise_for_status()
        webfinger_data = res.json()
    except requests.RequestException as e:
        raise WebfingerException(e)

    profile_link = next((rel for rel in webfinger_data.get('links', []) if
                         rel.get('rel') == 'self' and rel.get('type') == 'application/activity+json'), None)
    if profile_link is not None:
        profile_data = fetch_remote_profile(profile_link.get('href'))
    else:
        profile_data = None

    data = {
        'webfinger': webfinger_data,
        'profile': profile_data,
    }

    return data


@lru_cache(maxsize=256)
def fetch_remote_profile(url, actor=None):
    try:
        res = requests.get(url, headers={'Accept': 'application/activity+json'})
        # signed_post if profile is needs signing
        if 'error' in res.json() and res.json()['error'] == 'Request not signed' and actor:
            res = signed_post(
                url, 
                actor.private_key.encode('utf-8'), 
                f'{actor.account_url}#main-key', 
                method='get'
            )

        res.raise_for_status()
        return res.json()
    except requests.RequestException as e:
        raise WebfingerException(e)
