# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login handling.

   The authentication process consists of 3 steps.

   Step 1: Redirect to the institution to perform the login (oidc_login)

   Step 2: After the login is performed and the institution redirects back,
           with the client secret an access token is requested and received

   Step 3: In this step the protected user data is requested using the received access token from step 2

   Step 2 and 3 are included in the oidc_callback method
"""

from flask import session, flash, redirect, url_for
from spz.oidc.oid_handler import Oid_handler

request_handler = Oid_handler()


def oidc_url(redirect_uri):
    """
    Generates a request url for an openid connect login at KIT server.

    Redirect to this url to be able to log in via KIT credentials.

    :param redirect_uri: redirect to anmeldung.spz.kit.edu or a subpage of this base url
    :return dictionary with state, code_verifier and the url itself
    """
    # generate random keys
    state = request_handler.generate_state()
    code_verifier = request_handler.generate_code_verifier()
    # standard scope is openid, full info can be obtained with 'openid profile'
    url = request_handler.prepare_request(session={}, scope="openid profile", response_type="code",
                                          send_parameters_via="request_object", state=state,
                                          code_verifier=code_verifier, redirect_uri=redirect_uri)
    args = {
        "state": state,
        "code_verifier": code_verifier,
        "url": url
    }
    return args


def oidc_callback(url, state, code_verifier, redirect_uri):
    """
    After performing the login at KIT server, the user gets redirected back to our web page

    This method receives the url, where the KIT server has redirected to (current url in the browser window).

    Then it requests an access token at the kit server using the client credentials (client name, secret key)
    and some tokens exchanged in the first request.

    If the authentication is successfully, an access token is returned to our web page

    After completing this step, the method oidc_get_resources can be called using the received access token

    :param url: the url, where the kit server has redirected back
    :param state: the state received in the oidc_url method
    :param code: the code token
    :param code_verifier: the code_verifier received in the oidc_url method
    :param redirect_uri: give the KIT server a redirect url starting with anmeldung.spz.kit.edu
    :return a dictionary of the received data from KIT server
    """
    response_data = request_handler.link_extractor(url)
    # check equality of state which was sent from spz webserver and received from kit server
    if not response_data['state'] == state:
        return ('Invalid Request, because ' + response_data['state'] +
                ' is different to ' + state + ", protection against CRFS attacks")
    else:
        token = request_handler.get_access_token(response_data['code'], code_verifier, redirect_uri)
        return token


def oidc_get_resources(access_token):
    """
    Receive protected user data using the access token obtained in the step before

    :param access_token: access token received in the oidc_callback function
    :return received user data
    """
    request_data = request_handler.request_data(access_token)
    return request_data
