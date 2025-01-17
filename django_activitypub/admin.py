from django.contrib import admin

from django_activitypub.models import LocalActor, RemoteActor, Follower, Note


admin.site.register(Follower)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'content_url', 'updated_at')
    
@admin.register(LocalActor)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'preferred_username')
    
@admin.register(RemoteActor)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'domain')