import json
import re
import uuid, requests
from urllib.parse import quote, urlparse

from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse, resolve
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from django_activitypub.models import ActorChoices, LocalActor, RemoteActor, Follower, Following, Note, get_with_url, parse_hashtags
from django_activitypub.signed_requests import signed_post, SignatureChecker
from django_activitypub.webfinger import fetch_remote_profile, WebfingerException
from django.utils.safestring import mark_safe


def webfinger(request):
    resource = request.GET.get('resource')
    acct_m = re.match(r'^acct:(?P<username>.+?)@(?P<domain>.+)$', resource)
    if acct_m:
        username = acct_m.group('username')
        domain = acct_m.group('domain')
    elif resource.startswith('http'):
        parsed = urlparse(resource)
        if parsed.scheme != request.scheme or parsed.netloc != request.get_host():
            return JsonResponse({'error': 'invalid resource'}, status=404)
        url = resolve(parsed.path)
        if url.url_name != 'activitypub-profile':
            return JsonResponse({'error': 'unknown resource'}, status=404)
        username = url.kwargs.get('username')
        domain = request.get_host()
    else:
        return JsonResponse({'error': 'unsupported resource'}, status=404)

    try:
        actor = LocalActor.objects.get(preferred_username=username, domain=domain)
    except LocalActor.DoesNotExist:
        return JsonResponse({'error': 'no actor by that name'}, status=404)

    data = {
        'subject': f'acct:{actor.preferred_username}@{actor.domain}',
        'links': [
            {
                'rel': 'self',
                'type': 'application/activity+json',
                'href': request.build_absolute_uri(reverse('activitypub-profile', kwargs={'username': actor.preferred_username})),
            }
        ]
    }

    if actor.icon:
        data['links'].append({
            'rel': 'http://webfinger.net/rel/avatar',
            'type': 'image/jpeg',  # todo make this dynamic
            'href': request.build_absolute_uri(actor.icon.url),
        })

    return JsonResponse(data, content_type="application/jrd+json")


def hostmeta(request):
    data = {
        "Link": {
            "rel": "lrdd",
            "template": request.build_absolute_uri(reverse('activitypub-webfinger')) + "?resource={uri}"
        }
    }

    xrd = Element("XRD", xmlns="http://docs.oasis-open.org/ns/xri/xrd-1.0")
    for tag, attributes in data.items():
        element = SubElement(xrd, tag)
        for attr, value in attributes.items():
            element.set(attr, value)
            
    raw_xml = tostring(xrd, encoding="utf-8")
    xml_content  = parseString(raw_xml).toprettyxml(indent="  ", encoding="utf-8")
    return HttpResponse(xml_content, content_type="application/xml")


def nodeinfo_links(request):
    base_url = request.build_absolute_uri('/')
    data = {
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": f"{base_url}nodeinfo/2.0"
            }
        ]
    }
    return JsonResponse(data)


#TODO: Get settings from models
def nodeinfo(request, version):
    if version == '2.0':
        data = {
                "version": "2.0",
                "software": {
                    "name": "finalboss",
                    "version": "1.0",
                    "homepage": "https://iamthefinalboss.com"
                },
                "protocols": ["activitypub"],
                "services": {
                    "inbound": [],
                    "outbound": []
                },
                "openRegistrations": False,
                "usage": {
                    "users": {
                    "total": 0,
                    "activeHalfyear": 0,
                    "activeMonth": 0
                    },
                    "localPosts": 0, #TO: get total posts and replies from Notes
                    "localComments": 0
                },
                "metadata": {
                    "nodeName": "I am the Final Boss",
                    "nodeDescription": "Just another #webcomic site #webtoon #漫画"
                },
                "nodeAdmins": [
                    {
                        "name": "rensensei",
                        "email": "rensensei@outlook.com"
                    }
                ],
                "maintainer": [
                    {
                        "name": "rensensei",
                        "email": "rensensei@outlook.com"
                    }
                ],
                "langs": [],
                "tosUrl": "https://iamthefinalboss.com/terms/",
                "privacyPolicyUrl": None,
                "inquiryUrl": None,
                "impressumUrl": None,
                "repositoryUrl": None,
                "feedbackUrl": None,
                "disableRegistration": True,
                "disableLocalTimeline": False,
                "disableGlobalTimeline": True,
                "emailRequiredForSignup": True,
                "enableHcaptcha": False,
                "enableRecaptcha": False,
                "enableMcaptcha": False,
                "enableTurnstile": False,
                "maxNoteTextLength": 3000,
                "enableEmail": False,
                "enableServiceWorker": False,
                "proxyAccountName": "proxy",
                "themeColor": "#000000"
        }
        return JsonResponse(data)
    else:
        return JsonResponse({'error': 'Unsupported version'}, status=404)


def profile(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    data = {
        '@context': [
            'https://www.w3.org/ns/activitystreams',
            'https://w3id.org/security/v1',
            "https://join-lemmy.org/context.json",
        ]
    }
    data.update(actor.as_json())

    # TODO: featuredTags is in collection pagination
    url_pattern = re.compile(r'(https?://www\.|https?://)([^\s]+?\.[^\s]+?\b)')
    domain = url_pattern.findall(request.headers.get("User-Agent", '')) or url_pattern.findall(request.headers.get("Signature", ''))
    if domain and type(domain) is list and type(domain[0]) is tuple and len(domain[0]) > 1:
        data['featuredTags'] = list(parse_hashtags('#IndieComics #Gamer #DigitalArt #ArtistOnMastodon', domain[0][1]))

    return JsonResponse(data, content_type="application/activity+json")


def notes(request, username, id, mode = 'statuses'):
    data = {"@context": "https://www.w3.org/ns/activitystreams"}
    try:
        note = Note.objects.get(content_id=id)
    except:
        return JsonResponse({'error': 'Not Found'}, status=404)
    if mode == 'statuses':
        data.update(note.as_json(mode='statuses'))
    elif mode == 'activity':
        data.update(note.as_json(mode='activity'))
    elif mode == 'likes':
        data.update({
            "id": request.build_absolute_uri(reverse('activitypub-notes-likes', kwargs={'username': username, 'id': id})),
            "type": "Collection",
            "totalItems": note.likes.count()
        })
    elif mode == 'shares':
        data.update({
            'id': request.build_absolute_uri(reverse('activitypub-notes-shares', kwargs={'username': username, 'id': id})),
            'type': 'Collection',
            'totalItems': note.announces.count()
        })
    elif mode == 'delete':
        data = {}
    elif mode == 'replies':
        query = note.children.order_by('-published_at')
        paginator = Paginator(query, 10)
        page_num_arg = request.GET.get('page', None)
        replies_url = request.build_absolute_uri(reverse('activitypub-notes-replies', kwargs={'username': username, 'id': id}))
        data.update({
            'id': replies_url,
            'type': 'Collection',
        })

        if page_num_arg is None:
            data['first'] = {
                'id': replies_url + '?page=1',
                'type': 'CollectionPage',
                'next': replies_url + '?page=1',
                'partOf': replies_url,
                'items': []
            }
        else:
            page_num = int(page_num_arg)

            if 1 <= page_num <= paginator.num_pages:
                page = paginator.page(page_num)
                if page.has_next():
                    data['next'] = replies_url + f'?page={page.next_page_number()}'
                data['id'] = replies_url + f'?page={page_num}'
                data['type'] = 'CollectionPage'
                data['partOf'] = replies_url
                data['items'] = [note.get_absolute_url() for note in page.object_list]
            else:
                return JsonResponse({'error': f'invalid page number {page_num}'}, status=404)
    return JsonResponse(data, content_type="application/activity+json")


@csrf_exempt
def remote_redirect(request, username, domain):
    webfinger_url = f"https://{domain}/.well-known/webfinger"
    resource = f"acct:{username}@{domain}"
    handle = f"@{username}@{domain}"
    params = {'resource': resource}

    try:
        RemoteActor.objects.get_or_create_with_username_domain(username, domain)
        uri = request.GET.get('uri', handle)
        # Request WebFinger data
        response = requests.get(webfinger_url, params=params, timeout=5)
        response.raise_for_status()  # Raise error for non-200 responses
        data = response.json()

        # Find the "subscribe" URL template
        subscribe_template = None
        for link in data.get('links', []):
            if link.get('rel') == "http://ostatus.org/schema/1.0/subscribe":
                subscribe_template = link.get('template')
                break
        if not subscribe_template:
            return JsonResponse({'error': 'Subscribe template not found'}, status=404)

        # Format the subscribe URL for the given user
        subscribe_url = subscribe_template.replace('{uri}', uri)

        return JsonResponse({'url': subscribe_url})
    except Http404:
        return JsonResponse({'error': 'Invalid server domain'}, status=404)
    except requests.RequestException as e:
        return JsonResponse({'error': str(e)}, status=500)
    

@csrf_exempt
def remote_handle_redirect(request):
    if request.method == "POST":
        try:
            actor = LocalActor.objects.get(preferred_username=request.POST.get('attributed', ''))
            handle = request.POST.get('handle', '')
            handle_pattern = re.compile(r'\b(?P<username>[a-zA-Z0-9-]+)@(?P<domain>[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b')
            if handle:
                handle_m = handle_pattern.match(handle)
                if handle_m:
                    username = handle_m.group('username')
                    domain = handle_m.group('domain')
                    remote_actor = RemoteActor.objects.get_or_create_with_username_domain(username, domain)
                    parse = urlparse(remote_actor.get_absolute_url())
                    return JsonResponse({'redirect': f'{parse.scheme}://{parse.netloc}/@{actor.handle}'}, content_type="application/activity+json")
        except Exception as e:
            # with open('/var/www/static/debug.html', 'w') as f:
            #     f.write(request.body.decode('utf-8'))
            return JsonResponse({'error': str(e), 'attributed': request.POST.get('attributed', ''), 'handle': request.POST.get('handle', '')}, status=500)
    return JsonResponse({}, status=405)

def followers(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    query = Follower.objects.order_by('-follow_date').select_related('remote_actor').filter(following=actor)
    paginator = Paginator(query, 10)
    page_num_arg = request.GET.get('page', None)
    followers_url = request.build_absolute_uri(reverse('activitypub-followers', kwargs={'username': actor.preferred_username}))
    data = {
        '@context': 'https://www.w3.org/ns/activitystreams',
        'type': 'OrderedCollection',
        'totalItems': paginator.count,
        'id': followers_url,
    }

    if page_num_arg is None:
        data['first'] = followers_url + '?page=1'
        return JsonResponse(data, content_type="application/activity+json")

    page_num = int(page_num_arg)

    if 1 <= page_num <= paginator.num_pages:
        page = paginator.page(page_num)
        if page.has_next():
            data['next'] = followers_url + f'?page={page.next_page_number()}'
        data['id'] = followers_url + f'?page={page_num}'
        data['type'] = 'OrderedCollectionPage'
        data['orderedItems'] = [follower.remote_actor.url for follower in page.object_list]
        data['partOf'] = followers_url
        return JsonResponse(data, content_type="application/activity+json")
    else:
        return JsonResponse({'error': f'invalid page number {page_num}'}, status=404)


def followings(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    query = Following.objects.order_by('-follow_date').select_related('remote_actor').filter(following=actor)
    paginator = Paginator(query, 10)
    page_num_arg = request.GET.get('page', None)
    followers_url = request.build_absolute_uri(reverse('activitypub-following', kwargs={'username': actor.preferred_username}))
    data = {
        '@context': 'https://www.w3.org/ns/activitystreams',
        'type': 'OrderedCollection',
        'totalItems': paginator.count,
        'id': followers_url,
    }

    if page_num_arg is None:
        data['first'] = followers_url + '?page=1'
        return JsonResponse(data, content_type="application/activity+json")

    page_num = int(page_num_arg)

    if 1 <= page_num <= paginator.num_pages:
        page = paginator.page(page_num)
        if page.has_next():
            data['next'] = followers_url + f'?page={page.next_page_number()}'
        data['id'] = followers_url + f'?page={page_num}'
        data['type'] = 'OrderedCollectionPage'
        data['orderedItems'] = [follower.remote_actor.url for follower in page.object_list]
        data['partOf'] = followers_url
        return JsonResponse(data, content_type="application/activity+json")
    else:
        return JsonResponse({'error': f'invalid page number {page_num}'}, status=404)


@csrf_exempt
def inbox(request, username):
    response = {}

    if request.method == 'POST':
        base_url = f'{request.scheme}://{request.get_host()}'
        activity = json.loads(request.body)

        try:
            actor = LocalActor.objects.get(preferred_username=username)
        except LocalActor.DoesNotExist:
            return JsonResponse({}, status=404)

        if validate_resp := validate_post_request(request, activity, actor):
            return validate_resp

        if activity['type'] == 'Follow':
            # validate the 'object' is the actor
            local_actor = LocalActor.objects.get_by_url(activity['object'])
            if local_actor.id != actor.id:
                return JsonResponse({'error': f'follow object does not match actor: {activity["object"]}'}, status=400)

            # find or create a remote actor
            remote_actor = RemoteActor.objects.get_or_create_with_url(url=activity['actor'], actor=actor)

            Follower.objects.get_or_create(
                remote_actor=remote_actor,
                following=actor,
            )

            # send an Accept activity
            accept_data = {
                '@context': [
                    'https://www.w3.org/ns/activitystreams',
                    'https://w3id.org/security/v1',
                ],
                'id': request.build_absolute_uri(f'/{uuid.uuid4()}'),
                'type': 'Accept',
                'actor': request.build_absolute_uri(reverse('activitypub-profile', kwargs={'username': actor.preferred_username})),
                'object': activity,
            }

            sign_resp = signed_post(
                url=remote_actor.profile.get('inbox'),
                private_key=actor.private_key.encode('utf-8'),
                public_key_url=accept_data['actor'] + '#main-key',
                body=json.dumps(accept_data),
            )
            sign_resp.raise_for_status()

            response['ok'] = True

        elif activity['type'] == 'Like':
            note = None
            if type(activity['object']) is not dict: 
                if activity['object'].startswith(base_url):
                    note = get_with_url(activity['object'])
                else:
                    try:
                        note = get_object_or_404(Note, content_url=activity['object'])
                    except Http404:
                        pass
            if not note:
                return JsonResponse({'error': f'like object is not a note: {activity["object"]}'}, status=400)

            remote_actor = RemoteActor.objects.get_or_create_with_url(url=activity['actor'], actor=actor)
            note.likes.add(remote_actor)

            response['ok'] = True

        elif activity['type'] == 'Announce':
            note = None
            if type(activity['object']) is not dict:
                if activity['object'].startswith(base_url):
                    note = get_with_url(activity['object'])
                else:
                    try:
                        note = get_object_or_404(Note, content_url=activity['object'])
                    except Http404:
                        pass
            if not note:
                return JsonResponse({'error': f'announce object is not a note: {activity["object"]}'}, status=400)

            remote_actor = RemoteActor.objects.get_or_create_with_url(url=activity['actor'], actor=actor)
            note.announces.add(remote_actor)

            response['ok'] = True

        elif activity['type'] == 'Create':
            if activity['object']['id'].startswith(base_url):
                pass  # there is nothing to do, this is our note
            else:
                # TODO: only record in db if the notes are replies
                Note.objects.upsert_remote(base_url, activity['object'])
            response['ok'] = True

        elif activity['type'] == 'Undo':
            to_undo = activity['object']
            if to_undo['type'] == 'Follow':
                # validate the 'object' is the actor
                local_actor = LocalActor.objects.get_by_url(to_undo['object'])
                if local_actor.id != actor.id:
                    return JsonResponse({'error': f'undo follow object does not match actor: {to_undo["object"]}'}, status=400)

                remote_actor = get_object_or_404(RemoteActor, url=to_undo['actor'])

                local_actor.followers.remove(remote_actor)

                response['ok'] = True

            elif to_undo['type'] == 'Like':
                if to_undo['object'].startswith(base_url):
                    note = get_with_url(to_undo['object'])
                else:
                    try:
                        note = get_object_or_404(Note, content_url=activity['object'])
                    except Http404:
                        note = None
                if not note:
                    return JsonResponse({'error': f'undo like object is not a note: {to_undo["object"]}'}, status=400)

                remote_actor = get_object_or_404(RemoteActor, url=to_undo['actor'])
                note.likes.remove(remote_actor)

                response['ok'] = True

            elif to_undo['type'] == 'Announce':
                if to_undo['object'].startswith(base_url):
                    note = get_with_url(to_undo['object'])
                else:
                    try:
                        note = get_object_or_404(Note, content_url=activity['object'])
                    except Http404:
                        note = None
                if not note:
                    return JsonResponse({'error': f'undo announce object is not a note: {to_undo["object"]}'}, status=400)

                remote_actor = get_object_or_404(RemoteActor, url=to_undo['actor'])
                note.announces.remove(remote_actor)

                response['ok'] = True

            else:
                return JsonResponse({'error': f'unsupported undo type: {to_undo["type"]}'}, status=400)

        elif activity['type'] == 'Delete':
            response['ok'] = True  # TODO: support deletes for notes and actors

        elif activity['type'] == 'Accept':
            response['ok'] = True  

        elif activity['type'] == 'Update':
            response['ok'] = True 

        else:
            return JsonResponse({'error': f'unsupported activity type: {activity["type"]}'}, status=400)

        return JsonResponse(response, content_type="application/activity+json")
    else:
        return JsonResponse({}, status=405)


def outbox(request, username):
    try:
        actor = LocalActor.objects.get(preferred_username=username)
    except LocalActor.DoesNotExist:
        return JsonResponse({}, status=404)

    query = Note.objects.order_by('-published_at').filter(local_actor=actor, tombstone=False)

    paginator = Paginator(query, 10)
    page_num_arg = request.GET.get('page', None)
    outbox_url = request.build_absolute_uri(reverse('activitypub-outbox', kwargs={'username': actor.preferred_username}))
    data = {
        '@context': 'https://www.w3.org/ns/activitystreams',
        'type': 'OrderedCollection',
        'totalItems': paginator.count,
        'id': outbox_url,
    }

    if page_num_arg is None:
        data['first'] = outbox_url + '?page=1'
        return JsonResponse(data, content_type="application/activity+json")

    page_num = int(page_num_arg)

    if 1 <= page_num <= paginator.num_pages:
        page = paginator.page(page_num)
        base_url = f'{request.scheme}://{request.get_host()}'
        if page.has_next():
            data['next'] = outbox_url + f'?page={page.next_page_number()}'
        data['id'] = outbox_url + f'?page={page_num}'
        data['type'] = 'OrderedCollectionPage'
        data['orderedItems'] = [note.as_json(mode='activity') for note in page.object_list]
        data['partOf'] = outbox_url
        return JsonResponse(data, content_type="application/activity+json")
    else:
        return JsonResponse({'error': f'invalid page number: {page_num}'}, status=404)


def validate_post_request(request, activity, actor = None):
    if request.method != 'POST':
        raise Exception('Invalid method')

    if 'actor' not in activity:
        return JsonResponse({'error': f'no actor in activity: {activity}'}, status=400)

    try:
        actor_data = fetch_remote_profile(activity['actor'], actor)
    except WebfingerException:
        return JsonResponse({'error': 'validate - error fetching remote profile'}, status=400)

    checker = SignatureChecker(actor_data.get('publicKey'))
    result = checker.validate(
        method=request.method.lower(),
        url=request.build_absolute_uri(),
        headers=request.headers,
        body=request.body,
    )

    if not result.success:
        return JsonResponse({'error': 'invalid signature'}, status=401)

    return None
