from django.contrib import admin
from django.db import models
from django.forms import Textarea
from django.utils.safestring import mark_safe

from django_activitypub.models import LocalActor, RemoteActor, Follower, Following, Note, ImageAttachment, NoteTemplate

class ImageAttachmentInline(admin.TabularInline):
    model = ImageAttachment
    extra = 1 

    class Media:
        css = {"all": ("admin/css/hide_clear_link.css",)} 

admin.site.register(Follower)
admin.site.register(Following)

@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'id', 'actor_handle', 'tombstone', 'ready', 'updated_at')
    inlines = [ImageAttachmentInline]
    
    class Media:
        js = ("admin/js/template_dropdown.js",)

    def formfield_for_dbfield(self, db_field, **kwargs):
        """Customize the TextField to include a dynamic dropdown menu"""
        if db_field.name == "content":
            templates = NoteTemplate.objects.all()
            dropdown_html = '<select id="template-selector"><option value="">-- Choose a Template --</option>'
            
            for template in templates:
                dropdown_html += f'<option value="{template.content}">{template.name}</option>'
            
            dropdown_html += '</select>'
            return models.TextField().formfield(widget=Textarea(attrs={'rows': 5})) + mark_safe(dropdown_html)
        return super().formfield_for_dbfield(db_field, **kwargs)
    
@admin.register(LocalActor)
class LocalActorAdmin(admin.ModelAdmin):
    list_display = ('preferred_username', 'id')
    
@admin.register(RemoteActor)
class RemoteActorAdmin(admin.ModelAdmin):
    list_display = ('username', 'domain', 'id')