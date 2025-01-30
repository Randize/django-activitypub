from django.contrib import admin

from django_activitypub.models import LocalActor, RemoteActor, Follower, Following, Note, ImageAttachment

class ImageAttachmentInline(admin.TabularInline):
    model = ImageAttachment
    extra = 1 

    class Media:
        css = {"all": ("admin/css/hide_clear_link.css",)}  # Custom CSS file

admin.site.register(Follower)
admin.site.register(Following)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'id', 'actor.handle' 'tombstone', 'ready', 'updated_at')
    inlines = [ImageAttachmentInline]
    
@admin.register(LocalActor)
class LocalActorAdmin(admin.ModelAdmin):
    list_display = ('preferred_username', 'id')
    
@admin.register(RemoteActor)
class RemoteActorAdmin(admin.ModelAdmin):
    list_display = ('username', 'domain', 'id')