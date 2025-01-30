from django.contrib import admin
from django.db import models
from django.db.models import F
from django.db.models.functions import Substr
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
    exclude = ('RemoteActor',)
    inlines = [ImageAttachmentInline]
    
    class Media:
        js = ("admin/js/template_dropdown.js",)

    def formfield_for_dbfield(self, db_field, **kwargs):
        """Customize the TextField to include a dynamic dropdown menu"""
        if db_field.name == "content":
            templates = NoteTemplate.objects.annotate(
                            substring_name=Substr('name', 3, 9999)  # Start from the 3rd character (1-based index)
                        ).order_by('substring_name')
            dropdown_html = '<select id="template-selector"><option value="">-- Choose a Template --</option>'
            for template in templates:
                dropdown_html += f'<option value="{template.content}">{template.name}</option>'
            dropdown_html += '</select>'

            formfield = super().formfield_for_dbfield(db_field, **kwargs)
            formfield.widget = Textarea(attrs={'rows': 5})
            formfield.help_text = mark_safe(dropdown_html)  # Append dropdown below field
            return formfield
        return super().formfield_for_dbfield(db_field, **kwargs)
    
@admin.register(LocalActor)
class LocalActorAdmin(admin.ModelAdmin):
    list_display = ('preferred_username', 'id')
    
@admin.register(RemoteActor)
class RemoteActorAdmin(admin.ModelAdmin):
    list_display = ('username', 'domain', 'id')