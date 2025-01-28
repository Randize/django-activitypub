from django.contrib import admin

from django_activitypub.models import LocalActor, RemoteActor, Follower, Following, Note


admin.site.register(Follower)
admin.site.register(Following)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'id', 'tombstone', 'updated_at')
    
@admin.register(LocalActor)
class LocalActorAdmin(admin.ModelAdmin):
    list_display = ('preferred_username', 'id')
    
@admin.register(RemoteActor)
class RemoteActorAdmin(admin.ModelAdmin):
    list_display = ('username', 'domain', 'id')