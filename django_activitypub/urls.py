from django.urls import path
from django_activitypub.views import webfinger, profile, followers, inbox, outbox, hostmeta

urlpatterns = [
    path('.well-known/webfinger', webfinger, name='activitypub-webfinger'),
    path('.well-known/host-meta', hostmeta, name='activitypub-hostmeta'),
    path('pub/<slug:username>', profile, name='activitypub-profile'),
    path('@<slug:username>', profile, name='activitypub-profile-short'),
    path('pub/<slug:username>/followers', followers, name='activitypub-followers'),
    path('pub/<slug:username>/inbox', inbox, name='activitypub-inbox'),
    path('pub/<slug:username>/outbox', outbox, name='activitypub-outbox'),
]
