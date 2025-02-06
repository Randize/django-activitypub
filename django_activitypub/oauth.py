from django.http import JsonResponse
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from urllib.parse import urljoin
from oauth2_provider.models import Application

import json

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
        "app_registration_endpoint": urljoin(base_url, 'oauth/applications/'),
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
        data = json.loads(request.body)
        user = User.objects.get(username=data["username"])  # Ensure user exists

        app = Application.objects.create(
            name=data.get("name", "New OAuth App"),
            user=user,
            client_type=data.get("client_type", "confidential"),
            authorization_grant_type=data.get("grant_type", "authorization-code"),
            redirect_uris=data.get("redirect_uri", ""),
        )

        return JsonResponse({
            "client_id": app.client_id,
            "client_secret": app.client_secret,
            "redirect_uris": app.redirect_uris,
            "grant_type": app.authorization_grant_type,
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)