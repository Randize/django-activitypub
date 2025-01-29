import json
import urllib.parse
import uuid, re, os

import requests
from django.urls import resolve, reverse
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.conf import settings
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.utils.html import escape
from django.utils.safestring import mark_safe

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from tree_queries.models import TreeNode, TreeQuerySet
from datetime import datetime
from PIL import Image

from django_activitypub.signed_requests import signed_post
from django_activitypub.utils.dates import format_datetime, parse_datetime
from django_activitypub.webfinger import fetch_remote_profile, finger


def content_id_generator():
    while True:
        content_id = str(uuid.uuid4().int)[:18]  # Generate a unique ID
        if not Note.objects.filter(content_id=content_id).exists():
            return content_id  # Return only if unique


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
        'RemoteActor', through='Follower', related_name='localactor_followers',
        through_fields=('following', 'remote_actor'),
    )
    followings = models.ManyToManyField(
        'RemoteActor', through='Following', related_name='localactor_followings',
        through_fields=('following', 'remote_actor'),
    )

    objects = LocalActorManager()

    class Meta:
        indexes = [
            models.Index(fields=['preferred_username', 'domain'], name='ap_local_actor_idx')
        ]

    @property
    def handle(self):
        return f'{self.user.username}@{self.domain}'

    @property
    def account_url(self):
        return self.get_absolute_url()

    @property
    def icon_url(self):
        return self.icon.url if self.icon else None

    def __str__(self):
        return self.preferred_username

    def get_absolute_url(self):
        return f'https://{self.domain}' + reverse('activitypub-profile', kwargs={'username': self.preferred_username})

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
            data = fetch_remote_profile(url, actor)
            if self.filter(url=data['id']):
                return self.get(url=data['id'])
            parsed = urllib.parse.urlparse(url)
            return self.create(
                username=data.get('preferredUsername'),
                domain=parsed.netloc,
                url=data.get('id'),
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
    followings = models.ManyToManyField(
        LocalActor, through='Follower', related_name='remoteactor_followings',
        through_fields=('remote_actor', 'following'),
    )

    objects = RemoteActorManager()

    class Meta:
        indexes = [
            models.Index(fields=['username', 'domain'], name='ap_remote_actor_idx')
        ]

    def __str__(self):
        return f'{self.username}@{self.domain}'

    @property
    def handle(self):
        return f'{self.username}@{self.domain}'

    @property
    def account_url(self):
        return self.profile.get('id', '#')

    @property
    def icon_url(self):
        return self.profile.get('icon', {}).get('url', None)

    @property
    def preferred_username(self):
        return self.profile.get('preferredUsername', self.username)
    
    def get_absolute_url(self):
        return self.account_url


class Follower(models.Model):
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE)
    following = models.ForeignKey(LocalActor, on_delete=models.CASCADE)
    follow_date = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['remote_actor', 'following'], name='ap_unique_followers')
        ]
        indexes = [
            models.Index(fields=['following', 'follow_date'], name='ap_follower_date_idx')
        ]

    def __str__(self):
        return f'{self.remote_actor} -> {self.following}'
    

class Following(models.Model):
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE)
    following = models.ForeignKey(LocalActor, on_delete=models.CASCADE)
    follow_date = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['following', 'remote_actor'], name='ap_unique_followings')
        ]
        indexes = [
            models.Index(fields=['following', 'follow_date'], name='ap_following_date_idx')
        ]

    def __str__(self):
        return f'{self.following} -> {self.remote_actor}'


class NoteManager(TreeQuerySet):
    def upsert(self, base_url, local_actor, content, content_url):
        try:
            note = self.get(content_url=content_url)
            note.updated_at = timezone.now()
            note.content = content
        except Note.DoesNotExist:
            note = Note(local_actor=local_actor, content=content, content_url=content_url)
        note.save(url=base_url, note=note)
        return note

    def delete_local(self, base_url, content_url):
        try:
            note = self.get(content_url=content_url)
            send_delete_note_to_followers(base_url, note)
        except Note.DoesNotExist:
            pass

    def upsert_remote(self, base_url, obj):
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
            if reply_url.startswith(base_url):
                note.parent = get_with_url(reply_url)
            else:
                note.parent = Note.objects.upsert_remote(base_url, get_object(reply_url))
        note.save(url=base_url, note=note)
        return note
    

class Note(TreeNode):
    local_actor = models.ForeignKey(LocalActor, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    remote_actor = models.ForeignKey(RemoteActor, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    content = models.TextField()
    content_url = models.URLField(db_index=True, help_text="The absolute URL of the content to be published.")
    content_id = models.CharField(max_length=18, unique=True, default=content_id_generator, editable=False)
    likes = models.ManyToManyField(RemoteActor, blank=True, related_name='likes')
    announces = models.ManyToManyField(RemoteActor, blank=True, related_name='announces')
    sensitive = models.BooleanField(default=False)
    tombstone = models.BooleanField(default=False)
    attachments = models.ManyToManyField('ImageAttachment', blank=True, related_name='attachments')

    objects = NoteManager.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=['local_actor', 'published_at'], name='ap_notes_by_date_idx')
        ]

    def __str__(self):
        return self.get_absolute_url()

    def get_absolute_url(self):
        if self.local_actor:
            return f'https://{self.local_actor.domain}' + reverse('activitypub-notes-statuses', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id})
        return self.content_url
    
    def content_html(self):
        return parse_html(self.content)

    def as_json(self, mode = 'activity'):
        if self.published_at:
            published = self.published_at
        else:
            published = timezone.now()
        object = {
            'id': self.get_absolute_url(), # TODO: handle remote & local content_url
            'type': 'Note',
            'url': self.content_url + f'?id={self.content_id}',
            'summary': None,
            'published': format_datetime(published),
            'attributedTo': self.actor.get_absolute_url(),
            'to': ['https://www.w3.org/ns/activitystreams#Public'],
            'cc': [f'https://{self.actor.domain}' + reverse('activitypub-followers', kwargs={'username': self.actor.preferred_username})],
            'sensitive': self.sensitive,
            'atomUri': f'https://{self.local_actor.domain}' + reverse('activitypub-notes-statuses', kwargs={'username': self.local_actor.preferred_username, 'id': self.content_id}),
            'conversation': None,
            'content': self.content_html(), 
            'contentMap': {}, # TODO: Auto translation to other languages e.g. {"en":"<p>厚塗り好きです！人型多め。異形も描けます:blobartist:</p>"}
            'attachment': [], # TODO: Image attachment
            'tag': [],
            'replies': {}, 
            'likes': {
                'id': f'https://{self.actor.domain}' + reverse('activitypub-notes-likes', kwargs={'username': self.actor.preferred_username, 'id': self.content_id}),
                'type': 'Collection',
                'totalItems': self.likes.count()
            },
            'shares': {
                'id': f'https://{self.actor.domain}' + reverse('activitypub-notes-shares', kwargs={'username': self.actor.preferred_username, 'id': self.content_id}),
                'type': 'Collection',
                'totalItems': self.announces.count()
            },
        }
        if self.images:
            for image in self.images.all():
                with Image.open(os.path.join(settings.MEDIA_ROOT, image.attachment.name)) as img:
                    object['attachment'] += [{
                        "type": "Image",
                        "mediaType": Image.MIME[img.format],
                        "url": f'https://{self.actor.domain}{image.attachment.url}',
                        "name": image.caption,
                        # "blurhash": "UuNw+oS3_NkCR:ayM|oMyDoLIBj[t7ofaLay",
                        "focalPoint": [0.5, 0.5],
                        "width": img.size[0],
                        "height": img.size[1]
                    }]
        if self.children:
            replies_url = f'https://{self.actor.domain}' + reverse('activitypub-notes-replies', kwargs={'username': self.actor.preferred_username, 'id': self.content_id})
            object['replies'] = {
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
        if self.parent:
            object['inReplyTo'] = self.parent.content_url
            object['inReplyToAtomUri'] = self.parent.content_url
        if mode == 'activity' or mode == 'update':
            data = {
                'id': f'https://{self.actor.domain}' + reverse('activitypub-notes-activity', kwargs={'username': self.actor.preferred_username, 'id': self.content_id}),
                'type': 'Create',
                'actor': self.actor.account_url,
                'published': format_datetime(published),
                'to': ['https://www.w3.org/ns/activitystreams#Public'],
                'cc': [f'https://{self.actor.domain}' + reverse('activitypub-followers', kwargs={'username': self.actor.preferred_username})],
                'object': object
            }
            if mode == 'update':
                data.update({
                    'id': f'https://{self.actor.domain}' + reverse('activitypub-notes-activity', kwargs={'username': self.actor.preferred_username, 'id': self.content_id}) + f'?update={str(uuid.uuid4().int)[:10]}',
                    'type': 'Update',
                })
                object.update({
                    'updated': format_datetime(self.updated_at)
                })
        elif mode == 'statuses':
            data = object
        return data

    @property
    def actor(self):
        return self.local_actor or self.remote_actor

    @property
    def max_depth(self):
        return min(getattr(self, 'tree_depth', 1), 5)
    

class ImageAttachment(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='images')
    attachment = models.ImageField(upload_to='img', blank=True, null=True)
    caption = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.attachment.name

    
def parse_hashtags(content, domain):
    for t in re.findall(r'#\w+', content):
        yield {
            'type': 'Hashtag',
            'href': f'https://{domain}/tags/{t}',
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


def parse_html(content):
    if not content:
        return ''
    content = escape(content)
    url_pattern = re.compile(r'(https?://www\.|https?://)([^\s]+)')
    content = url_pattern.sub(
        r'<a href="\1\2" target="_blank" rel="noopener noreferrer">'
        r'<span class="invisible">\1</span>\2</a>',
        content
    )
    hashtag_pattern = re.compile(r'#(\w+)')
    content = hashtag_pattern.sub(r'<a href="/hashtags/\1" class="mention hashtag status-link" rel="tag">#\1</a>', content)
    paragraphs = content.split('\n')
    formatted_text = ''.join(f'<p>{para.strip()}</p>' for para in paragraphs if para.strip())
    return mark_safe(formatted_text)


def send_create_note_to_followers(note):
    if note.local_actor:
        actor = note.local_actor
    elif note.parent and note.parent.local_actor:
        actor = note.parent.local_actor
    actor_url = actor.get_absolute_url()
    followers = actor.followers.all()
    data = {'@context' : [
        'https://www.w3.org/ns/activitystreams',
        "https://w3id.org/security/v1"
    ]}
    data.update(note.as_json(mode='activity'))

    for follower in followers:
        inbox = follower.profile.get('inbox')
        domain = follower.domain
        data['object']['tag'] = list(parse_mentions(note.content)) + list(parse_hashtags(note.content, domain))
        try:
            resp = signed_post(
                inbox,
                actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(data)
            )
            resp.raise_for_status()
            print(f'send_create_note_to_followers - {follower.__str__()} - {resp.status_code}')
        except Exception as e: 
            # TODO: gracefully handle deleted followers so replies stay
            # if re.findall(r'Not Found', str(e)):
            #     follower.delete()
            print(str(e))

def send_update_note_to_followers(note):
    if note.local_actor:
        actor = note.local_actor
    elif note.parent and note.parent.local_actor:
        actor = note.parent.local_actor
    actor_url = actor.get_absolute_url()
    data = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
            "https://w3id.org/security/v1"
        ],
    }
    data.update(note.as_json(mode='update'))

    for follower in note.local_actor.followers.all():
        inbox = follower.profile.get('inbox')
        domain = follower.domain
        data['object']['tag'] = list(parse_mentions(note.content)) + list(parse_hashtags(note.content, domain))
        try:
            resp = signed_post(
                inbox,
                note.local_actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(data)
            )
            resp.raise_for_status()
            print(f'send_update_note_to_followers - {follower.__str__()}')
        except Exception as e:  # TODO: handle 404 and delete followers 
            print(str(e))


def send_delete_note_to_followers(note):
    actor_url = note.actor.get_absolute_url()
    data = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
        ],
        'id': f'https://{note.actor.domain}' + reverse('activitypub-notes-delete', kwargs={'username': note.actor.preferred_username, 'id': note.content_id}),
        'type': 'Delete',
        'actor': actor_url,
        "to": [
            "https://www.w3.org/ns/activitystreams#Public"
        ],
        'object': {
            'id': note.get_absolute_url(),
            'type': 'Tombstone',
            'atomUri': note.get_absolute_url()
        },
    }

    for follower in note.local_actor.followers.all():
        try:
            resp = signed_post(
                follower.profile.get('inbox'),
                note.local_actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(data)
            )
            if resp.status_code == 404:
                try:
                    if 'error' in resp.json():
                        follower.delete()
                        print(f'{follower.__str__()} deleted')
                except Exception as e:
                    print(f'resp.json - {str(e)}')
            resp.raise_for_status()
        except Exception as e:
            print(f'signed_post - {str(e)}')
        if resp.status_code != 404:
            print(f'{follower.__str__()} - tombstoned')
            note.tombstone = True
            note.save()


def delete_all_notes():
    for note in Note.objects.all():
        if not note.parent and note.local_actor and not note.tombstone:
            send_delete_note_to_followers(note)


def send_old_notes(local_actor, remote_actor): 
    # TODO: get all public notes and then send to the actor, check if domain exists > check on get or create level
    actor = local_actor
    actor_url = local_actor.get_absolute_url()
    domain = remote_actor.domain
    inbox = remote_actor.profile.get('inbox')
    data = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
            "https://w3id.org/security/v1"
        ],
    }
    notes = Note.objects.order_by('-published_at').filter(local_actor=local_actor)
    for note in notes:
        data.update(note.as_json(mode='update'))
        data['object']['tag'] = list(parse_mentions(note.content)) + list(parse_hashtags(note.content, domain))
        try:
            resp = signed_post(
                inbox,
                actor.private_key.encode('utf-8'),
                f'{actor_url}#main-key',
                body=json.dumps(data)
            )
            resp.raise_for_status()
            print(f'send_old_notes - {remote_actor.__str__()} - {resp.status_code}')
        except Exception as e: 
            # TODO: gracefully handle deleted followers so replies stay
            # if re.findall(r'Not Found', str(e)):
            #     follower.delete()
            print(str(e))


def send_follow(local_actor, remote_actor):
    data = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"https://{local_actor.domain}/{uuid.uuid4()}", 
        "type": "Follow",
        "actor": local_actor.get_absolute_url(),
        "object": remote_actor.get_absolute_url(),
    }
    resp = signed_post(
        remote_actor.profile.get('inbox'),
        local_actor.private_key.encode('utf-8'),
        f'{local_actor.get_absolute_url()}#main-key',
        body=json.dumps(data)
    )
    resp.raise_for_status()
    Following.objects.get_or_create(remote_actor=remote_actor, following=local_actor)


def send_unfollow(local_actor, remote_actor):
    data = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"https://{local_actor.domain}/{uuid.uuid4()}",
        "type": "Undo",
        "actor": local_actor.get_absolute_url(),
        "object": {
            "id": "https://activitypub.academy/b6459eb4-97d9-4e61-9a26-8a777ba1d2e0",
            "type": "Follow",
            "actor": local_actor.get_absolute_url(),
            "object": remote_actor.get_absolute_url()
        }
    }
    resp = signed_post(
        remote_actor.profile.get('inbox'),
        local_actor.private_key.encode('utf-8'),
        f'{local_actor.get_absolute_url()}#main-key',
        body=json.dumps(data)
    )
    resp.raise_for_status()
    if Following.objects.filter(following=local_actor, remote_actor=remote_actor):
        Following.objects.get(following=local_actor, remote_actor=remote_actor).delete()


def get_object(url):
    resp = requests.get(url, headers={'Accept': 'application/activity+json'})
    resp.raise_for_status()
    return resp.json()

    
def get_with_url(url):
    parsed = urllib.parse.urlparse(url)
    match = resolve(parsed.path)
    return Note.objects.get(content_id=match.kwargs['id'])


@receiver(post_save, sender=Note)
def note_dispatch(sender, instance, created, **kwargs):
    note = instance
    # if not note.tombstone:
    #     if created:
    #         send_create_note_to_followers(note)
    #     else:
    #         send_update_note_to_followers(note)


@receiver(m2m_changed, sender=Note.attachments.through)
def imageAttachment_note(sender, instance, action, reverse, pk_set, **kwargs):
    if action == "post_add":
        print(f"Attachments {pk_set} added to Note {instance.id}")
        if not instance.tombstone:
            send_create_note_to_followers(instance)
    elif action == "post_remove":
        print(f"Attachments {pk_set} removed from Note {instance.id}")
    elif action == "post_clear":
        print(f"All attachments removed from Note {instance.id}")