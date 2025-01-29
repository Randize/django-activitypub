from django.contrib import admin

from django_activitypub.models import LocalActor, RemoteActor, Follower, Following, Note, ImageAttachment

class ImageAttachmentInline(admin.TabularInline):
    model = ImageAttachment
    extra = 1 

    def formfield_for_dbfield(self, db_field, **kwargs):
        field = super().formfield_for_dbfield(db_field, **kwargs)
        if db_field.name == "file":
            field.widget.attrs.update({"class": "no-clearable-file"})  # Custom CSS
        return field

    class Media:
        css = {"all": ("admin/css/hide_clear_link.css",)}  # Custom CSS file

admin.site.register(Follower)
admin.site.register(Following)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'id', 'tombstone', 'updated_at')
    inlines = [ImageAttachmentInline]
    
@admin.register(LocalActor)
class LocalActorAdmin(admin.ModelAdmin):
    list_display = ('preferred_username', 'id')
    
@admin.register(RemoteActor)
class RemoteActorAdmin(admin.ModelAdmin):
    list_display = ('username', 'domain', 'id')