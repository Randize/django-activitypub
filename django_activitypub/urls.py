from django.urls import path
from django_activitypub.views import webfinger, profile, followers, inbox, outbox, hostmeta, nodeinfo, nodeinfo_links, notes

urlpatterns = [
    path('.well-known/webfinger', webfinger, name='activitypub-webfinger'),
    path('.well-known/host-meta', hostmeta, name='activitypub-hostmeta'),
    path('.well-known/nodeinfo', nodeinfo_links, name='activitypub-nodeinfo'),
    path('nodeinfo/<str:version>', nodeinfo, name='activitypub-nodeinfo'),
    path('pub/<slug:username>', profile, name='activitypub-profile'),
    path('@<slug:username>', profile, name='activitypub-profile-short'),
    path('pub/<slug:username>/statuses/<str:id>', notes, \
         kwargs={'mode': 'statuses'}, name='activitypub-notes-statuses'),
    path('pub/<slug:username>/statuses/<str:id>/replies', notes, \
         kwargs={'mode': 'replies'}, name='activitypub-notes-replies'),
    path('pub/<slug:username>/statuses/<str:id>/activity', notes, \
        kwargs={'mode': 'activity'}, name='activitypub-notes-activity'),
    path('pub/<slug:username>/statuses/<str:id>/likes', notes, \
        kwargs={'mode': 'likes'}, name='activitypub-notes-likes'),
    path('pub/<slug:username>/statuses/<str:id>/shares', notes, \
        kwargs={'mode': 'shares'}, name='activitypub-notes-shares'),
    path('pub/<slug:username>/followers', followers, name='activitypub-followers'),
    path('pub/<slug:username>/inbox', inbox, name='activitypub-inbox'),
    path('pub/<slug:username>/outbox', outbox, name='activitypub-outbox'),
]
