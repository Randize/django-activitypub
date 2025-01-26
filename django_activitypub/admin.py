from django.contrib import admin

from django_activitypub.models import LocalActor, RemoteActor, Follower, Following, Note


admin.site.register(Follower)
admin.site.register(Following)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', '__str__', 'updated_at')
    
@admin.register(LocalActor)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'preferred_username')
    
@admin.register(RemoteActor)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'domain')