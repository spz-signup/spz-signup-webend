# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login and data exchange funcionality.
"""

from oauthlib.oauth2 import WebApplicationClient
from flask import render_template

client_id = 'anmeldung-spz-kit-edu'
client = WebApplicationClient(client_id)

authorization_url = 'https://oidc.scc.kit.edu/auth/realms/kit/protocol/openid-connect/auth'
end_session_url = 'https://oidc.scc.kit.edu/auth/realms/kit/protocol/openid-connect/logout'

url = client.prepare_request_uri(
    authorization_url,
    redirect_uri='https://localhost',
    scope=['authorization_code'],
    state='D8VAo311AAl_49LAtM51HA'
)


def prepare_request():
    return render_template('signup.html', url=url)
