# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login and data exchange funcionality.
"""

from oauthlib.oauth2 import WebApplicationClient

client_id = 'anmeldung-spz-kit-edu'
client = WebApplicationClient(client_id)

authorization_url = 'https://oidc.scc.kit.edu/auth/realms/kit/protocol/openid-connect/auth'
end_session_url = 'https://oidc.scc.kit.edu/auth/realms/kit/protocol/openid-connect/logout'

url = client.prepare_request_uri(
    authorization_url,
    redirect_uri = 'https://localhost',
    scope = ['read:user'],
    state = 'D8VAo311AAl_49LAtM51HA'
)

def get_url():
    return url
