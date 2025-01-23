import json
import urllib.parse
import uuid, re

import requests
from django.urls import resolve, reverse
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from tree_queries.models import TreeNode, TreeQuerySet

from django_activitypub.signed_requests import signed_post
from django_activitypub.utils.dates import format_datetime, parse_datetime
from django_activitypub.webfinger import fetch_remote_profile, finger


class ActorChoices(models.TextChoices):
    PERSON = 'P', 'Person'
    SERVICE = 'S', 'Service'


class LocalActorManager(models.Manager):
    def get_by_url(self, url):
        parsed = urllib.parse.urlparse(url)
        match = resolve(parsed.path)
        if match.url_name == 'activitypub-profile':
            return self.get(preferred_username=match.kwargs['username'], domain=parsed.netloc)
        else:
            return None


class LocalActor(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)
    private_key = models.TextField(blank=True, editable=False)
    public_key = models.TextField(blank=True, editable=False)
    actor_type = models.CharField(max_length=1, choices=ActorChoices, default=ActorChoices.PERSON)
    preferred_username = models.SlugField(max_length=255)
    domain = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    icon = models.ImageField(upload_to='actor-media', null=True, blank=True)
    image = models.ImageField(upload_to='actor-media', null=True, blank=True)
    followers = models.ManyToManyField(
        'RemoteActor', through='Follower', related_name='followers',
        through_fields=('following', 'remote_actor'),
    )

    objects = LocalActorManager()

    class Meta:
        indexes = [
            models.Index(fields=['preferred_username', 'domain'], name='activitypub_local_actor_idx')
        ]

    @property
    def handle(self):
        return f'{self.user.username}@{self.domain}'

    @property
    def account_url(self):
        return f'https://{self.domain}{self.get_absolute_url()}'

    @property
    def icon_url(self):
        return self.icon.url if self.icon else None

    def __str__(self):
        return self.preferred_username

    def get_absolute_url(self):
        return reverse('activitypub-profile', kwargs={'username': self.preferred_username})

    def save(self, *args, **kwargs):
        if not self.id:
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            self.private_key = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode('utf-8')
            self.public_key = private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            ).decode('utf-8')
        super().save(*args, **kwargs)

    def private_key_obj(self):
        return serialization.load_pem_private_key(
            self.private_key.encode('utf-8'),
            password=None,
        )

    def public_key_obj(self):
        return serialization.load_pem_public_key(
            self.public_key.encode('utf-8')
        )


class RemoteActorManager(models.Manager):
    def get_or_create_with_url(self, url, actor = None):
        try:
            return self.get(url=url)  # TODO: check cache expiry
        except RemoteActor.DoesNotExist:
            if actor:
                data = fetch_remote_profile(url, actor)
            else:
                data = fetch_remote_profile(url, actor)
            parsed = urllib.parse.urlparse(url)
            return self.create(
                username=data.get('preferredUsername'),
                domain=parsed.netloc,
                url=url,
                profile=data,
            )

    def get_or_create_with_username_domain(self, username, domain):
        try:
            return self.get(username=username, domain=domain)
        except RemoteActor.DoesNotExist:
            data = finger(username, domain)
            if 'profile' not in data:
                return None
            url = data['profile'].get('id')
            try:
                return self.get(url=url)
            except RemoteActor.DoesNotExist:
                return self.create(
                    username=username,
                    domain=domain,
                    url=url,
                    profile=data['profile'],
                )


class RemoteActor(models.Model):
    username = models.CharField(max_length=255)
    domain = models.CharField(max_length=255)
    url = models.URLField(db_index=True, unique=True)
    profile = models.JSONField(blank=True, default=dict)
    following = models.ManyToManyField(
        LocalActor, through='Follower', related_name='following',
        through_fields=('remote_actor', 'following'),
    )

    objects = RemoteActorManager()

    class Meta:
        indexes = [
            models.Index(fields=['username', 'domain'], name='activitypub_remote_actor_idx')
        ]

    def __str__(self):
        return f'{self.username}@{self.domain}'

    @property
    def handle(self):
        return f'{self.username}@{self.domain}'

    @property
    def account_url(self):
        return self.profile.get('url', '#')

    @property
    def icon_url(self):
        return self.profile.get('icon', {}).get('url', None)


class Follower(models.Model):
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE)
    following = models.ForeignKey(LocalActor, on_delete=models.CASCADE)
    follow_date = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['remote_actor', 'following'], name='activitypub_unique_followers')
        ]
        indexes = [
            models.Index(fields=['following', 'follow_date'], name='activitypub_followers_date_idx')
        ]

    def __str__(self):
        return f'{self.remote_actor} -> {self.following}'


class NoteManager(TreeQuerySet):
    def upsert(self, base_uri, local_actor, content, content_url):
        try:
            note = self.get(content_url=content_url)
            note.updated_at = timezone.now()
            note.content = content
            note.save()
            send_update_note_to_followers(base_uri, note)
        except Note.DoesNotExist:
            note = super().create(local_actor=local_actor, content=content, content_url=content_url)
            send_create_note_to_followers(base_uri, note)
        return note

    def delete_local(self, base_uri, content_url):
        try:
            note = self.get(content_url=content_url)
            send_delete_note_to_followers(base_uri, note)
        except Note.DoesNotExist:
            pass

    def upsert_remote(self, base_uri, obj):
        full_obj = get_object(obj['id'])
        try:
            note = self.get(content_url=full_obj['id'])
        except Note.DoesNotExist:
            note = Note()
        note.remote_actor = RemoteActor.objects.get_or_create_with_url(full_obj['attributedTo'])
        note.published_at = parse_datetime(full_obj['published'])
        if updated_str := full_obj.get('updated', None):
            note.updated_at = parse_datetime(updated_str)
        note.content = full_obj['content']
        note.content_url = obj['id']
        if reply_url := full_obj.get('inReplyTo', None):
            if reply_url.startswith(base_uri):
                note.parent = self.get(content_url=reply_url)
            else:
                note.parent = Note.objects.upsert_remote(base_uri, get_object(reply_url))
        note.save()
        return note


class Note(TreeNode):
    local_actor = models.ForeignKey(LocalActor, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    content = models.TextField()
    content_url = models.URLField(db_index=True)
    content_id = models.CharField(max_length=18, unique=True, default=str(uuid.uuid4().int)[:18], editable=False)
    likes = models.ManyToManyField(RemoteActor, blank=True, related_name='likes')
    announces = models.ManyToManyField(RemoteActor, blank=True, related_name='announces')
    sensitive = models.BooleanField(default=False)

    objects = NoteManager.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=['local_actor', 'published_at'], name='activitypub_notes_by_date_idx')
        ]

    def __str__(self):
        return self.get_absolute_url()

    def get_absolute_url(self):
        if self.local_actor:
            return f'https://{self.local_actor.domain}' + reverse('activitypub-notes-statuses', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id})
        return self.content_url

    def as_json(self, base_uri, mode = 'activity'):
        if self.local_actor:
            attributed = self.local_actor.get_absolute_url()
        else:
            attributed = self.remote_actor.url
        object = {
            'id': self.get_absolute_url(), # TODO: handle remote & local content_url
            'type': 'Note',
            'url': self.content_url,
            'summary': None,
            'inReplyTo': None,
            'published': format_datetime(self.published_at),
            'updated': format_datetime(self.updated_at),
            'attributedTo': attributed,
            'to': 'https://www.w3.org/ns/activitystreams#Public',
            'cc': f'https://{self.local_actor.domain}' + reverse('activitypub-followers', kwargs={'username': self.local_actor.preferred_username}),
            'sensitive': self.sensitive,
            'atomUri': self.content_url,
            'inReplyToAtomUri': None,
            'conversation': None,
            'content': self.content,
            'contentMap': {},
            'tag': list(parse_mentions(self.content)) + list(parse_hashtags(self.content, base_uri)),
            'attachment': [],
            'replies': {}, # TODO: Need to add inbox support for replies
            'likes': {},
            'shares': {},
        }
        if self.parent:
            object['inReplyTo'] = self.parent.content_url
        if mode == 'activity':
            data = {
                'id': f'https://{self.local_actor.domain}' + reverse('activitypub-notes-statuses', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id}),
                'type': 'Create',
                'actor': self.local_actor.account_url,
                'published': format_datetime(self.published_at),
                'to': 'https://www.w3.org/ns/activitystreams#Public',
                'cc': f'https://{self.local_actor.domain}' + reverse('activitypub-followers', kwargs={'username': self.local_actor.preferred_username}),
                'object': object
            }
        elif mode == 'statuses':
            data = object
            if self.children:
                replies_url = f'https://{self.local_actor.domain}' + reverse('activitypub-notes-replies', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id})
                data['replies'] = {
                    'id': replies_url,
                    'type': 'Collection',
                    'first': {
                        'id': replies_url + '?page=1',
                        'type': 'CollectionPage',
                        'next': replies_url + '?page=1',
                        'partOf': replies_url,
                        'items': []
                    }
                }
            
            data['likes'] = {
                'id': f'https://{self.local_actor.domain}' + reverse('activitypub-notes-likes', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id}),
                'type': 'Collection',
                'totalItems': self.likes.count()
            }
            data['shares'] = {
                'id': f'https://{self.local_actor.domain}' + reverse('activitypub-notes-shares', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id}),
                'type': 'Collection',
                'totalItems': self.announces.count()
            }
        return data

    @property
    def actor(self):
        return self.local_actor or self.remote_actor

    @property
    def max_depth(self):
        return min(getattr(self, 'tree_depth', 1), 5)

def parse_hashtags(content, base_url):
    for t in re.findall(r'#\w+', content):
        yield {
            'type': 'Hashtag',
            'href': f'https://{base_url}/tags/{t}',
            'name': t,
        }
    
def parse_mentions(content):
    """
    Parse a note's content for mentions and return a generator of mention objects
    """
    from django_activitypub.custom_markdown import mention_pattern

    mentioned = {}
    for m in mention_pattern.finditer(content):
        key = (m.group('username'), m.group('domain'))
        if key in mentioned:
            continue
        actor = RemoteActor.objects.get_or_create_with_username_domain(*key)
        yield {
            'type': 'Mention',
            'href': actor.url,
            'name': f'{key[0]}@{key[1]}',
        }


def send_create_note_to_followers(base_url, note):
    actor_url = f'{base_url}{note.local_actor.get_absolute_url()}'
    data = {'@context' : [
        'https://www.w3.org/ns/activitystreams',
        'https://w3id.org/security/v1'
    ]}
    data.update(note.as_json(base_url, mode='activity'))

    for follower in note.local_actor.followers.all():
        try:
            resp = signed_post(
                follower.profile.get('inbox'),
                note.local_actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(data)
            )
            resp.raise_for_status()
        except Exception as e:  # TODO: handle 404 and delete followers 
            print(str(e))

def send_update_note_to_followers(base_url, note):
    actor_url = f'{base_url}{note.local_actor.get_absolute_url()}'
    update_msg = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
        ],
        'type': 'Update',
        'id': f'{note.content_url}#updates/{note.updated_at.timestamp()}',
        'actor': actor_url,
        'object': note.as_json(base_url),
        'published': format_datetime(note.published_at),
    }

    for follower in note.local_actor.followers.all():
        try:
            resp = signed_post(
                follower.profile.get('inbox'),
                note.local_actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(update_msg)
            )
            resp.raise_for_status()
        except Exception as e:  # TODO: handle 404 and delete followers 
            print(str(e))


def send_delete_note_to_followers(base_url, note):
    actor_url = f'{base_url}{note.local_actor.get_absolute_url()}'
    delete_msg = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
        ],
        'type': 'Delete',
        'actor': actor_url,
        'object': {
            'id': note.content_url,
            'type': 'Tombstone',
        },
    }

    for follower in note.local_actor.followers.all():
        try:
            resp = signed_post(
                follower.profile.get('inbox'),
                note.local_actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(delete_msg)
            )
            resp.raise_for_status()
        except Exception as e:
            print(str(e))


def get_object(url):
    resp = requests.get(url, headers={'Accept': 'application/activity+json'})
    resp.raise_for_status()
    return resp.json()
