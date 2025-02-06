from django.http import JsonResponse
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from django.conf import settings

from urllib.parse import urljoin
from oauth2_provider.models import Application, AccessToken
from oauth2_provider.views import AuthorizationView

import json, secrets

def oauth_authorization_server(request):
    """
    Returns the OAuth authorization server URL for ActivityPub authentication.
    """
    base_url = getattr(settings, 'SITE_URL', 'https://yourdomain.com')  # Ensure BASE_URL is set

    return JsonResponse({
        "issuer": settings.SITE_URL,
        "service_documentation": None,
        "authorization_endpoint": urljoin(base_url, '/oauth/authorize/'),
        "token_endpoint": urljoin(base_url, '/oauth/token/'),  # Allauth token endpoint
        "app_registration_endpoint": urljoin(base_url, '/api/v1/apps'),
        "revocation_endpoint": urljoin(base_url, '/oauth/revoke_token/'),  # Optional
        "introspection_endpoint": urljoin(base_url, '/oauth/introspect/'),  # Optional
        "scopes_supported": [
            "read",
            "write",
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
        redirect_uris = []
        redirect_uris.append(data.get('redirect_uris'))
        client_name = data.get('client_name')
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
            redirect_uris=" ".join(redirect_uris),
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            user=None  # Optional: Assign a user if required
        )

        response = {
            "id": application.id,
            "name": application.name,
            "website": website,
            "scopes": scopes.split(' '),
            "redirect_uris": application.redirect_uris,
            "client_id": client_id,
            "client_secret": client_secret,
            "vapid_key": secrets.token_urlsafe(64)  # Dummy VAPID key for Mastodon compatibility
        }
        return JsonResponse(response)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
    

class CustomAuthorizationView(AuthorizationView):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_anonymous:
            # Find the application by client_id
            client_id = request.GET.get("client_id")
            app = Application.objects.get(client_id=client_id)

            # Generate an access token
            token = AccessToken.objects.create(
                user=None,  # No user required
                application=app,
                token=secrets.token_urlsafe(32),
                expires=timezone.now() + timezone.timedelta(days=1),
                scope="read write follow profile",
            )

            return JsonResponse({
                "access_token": token.token,
                "token_type": "Bearer",
                "expires_in": 86400,
                "scope": token.scope,
            })

        return super().dispatch(request, *args, **kwargs)