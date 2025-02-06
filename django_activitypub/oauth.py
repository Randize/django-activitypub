from django.http import JsonResponse
from django.conf import settings
from urllib.parse import urljoin

def oauth_authorization_server(request):
    """
    Returns the OAuth authorization server URL for ActivityPub authentication.
    """
    base_url = getattr(settings, 'SITE_URL', 'https://yourdomain.com')  # Ensure BASE_URL is set
    oauth_url = urljoin(base_url, '/oauth/authorize/')  # Allauth's OAuth login endpoint

    return JsonResponse({
        "authorization_endpoint": oauth_url,
        "token_endpoint": urljoin(base_url, '/oauth/token/'),  # Allauth token endpoint
        "revocation_endpoint": urljoin(base_url, '/oauth/revoke_token/'),  # Optional
        "introspection_endpoint": urljoin(base_url, '/oauth/introspect/'),  # Optional
    })
