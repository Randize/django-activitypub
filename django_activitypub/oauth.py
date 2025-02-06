from django.http import JsonResponse
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from urllib.parse import urljoin
from oauth2_provider.models import Application

import json, secrets

def oauth_authorization_server(request):
    """
    Returns the OAuth authorization server URL for ActivityPub authentication.
    """
    base_url = getattr(settings, 'SITE_URL', 'https://yourdomain.com')  # Ensure BASE_URL is set
    oauth_url = urljoin(base_url, '/oauth/authorize/')  # Allauth's OAuth login endpoint

    return JsonResponse({
        "issuer": settings.SITE_URL,
        "service_documentation": None,
        "authorization_endpoint": oauth_url,
        "token_endpoint": urljoin(base_url, '/oauth/token/'),  # Allauth token endpoint
        "app_registration_endpoint": urljoin(base_url, 'api/v1/apps'),
        "revocation_endpoint": urljoin(base_url, '/oauth/revoke_token/'),  # Optional
        "introspection_endpoint": urljoin(base_url, '/oauth/introspect/'),  # Optional
        "scopes_supported": [
            "read",
            "write",
            "write:accounts",
            "write:blocks",
            "write:bookmarks",
            "write:conversations",
            "write:favourites",
            "write:filters",
            "write:follows",
            "write:lists",
            "write:media",
            "write:mutes",
            "write:notifications",
            "write:reports",
            "write:statuses",
            "read:accounts",
            "read:blocks",
            "read:bookmarks",
            "read:favourites",
            "read:filters",
            "read:follows",
            "read:lists",
            "read:mutes",
            "read:notifications",
            "read:search",
            "read:statuses",
            "follow",
            "push",
            "profile",
        ],
        "grant_types_supported": [
            "authorization_code",
            "client_credentials"
        ],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post"
        ]
    })

@csrf_exempt
def register_oauth_client(request):
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))  # Parse JSON request body
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    try:
        client_name = data.get('client_name')
        redirect_uris = data.get('redirect_uris')
        scopes = data.get('scopes', 'read')
        website = data.get('website', '')

        if not client_name or not redirect_uris:
            return JsonResponse({'error': 'client_name and redirect_uris are required'}, status=400)

        # Generate client_id and client_secret
        client_id = secrets.token_urlsafe(32)
        client_secret = secrets.token_urlsafe(48)

        # Create the application in Django OAuth Toolkit
        application = Application.objects.create(
            name=client_name,
            redirect_uris=redirect_uris,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            user=None  # Optional: Assign a user if required
        )

        response = {
            "id": application.id,
            "name": application.name,
            "website": website,
            "scopes": scopes.split(' '),
            "redirect_uri": application.redirect_uris,
            "redirect_uris": list(application.redirect_uris),
            "client_id": client_id,
            "client_secret": client_secret,
            "vapid_key": secrets.token_urlsafe(64)  # Dummy VAPID key for Mastodon compatibility
        }
        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)