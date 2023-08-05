# -*- coding: utf-8 -*-

"""The request handler for OpenID Connect Single Sign On with KIT institution

   Holds the data exchange funcionality.
"""

import hashlib
import json
import ssl
import os
import time
import urllib.request
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError

import requests_oauthlib
import requests

from jwkest.jwk import KEYS
from jwkest.jws import JWS

import string
import random
import base64

ISSUER = 'https://oidc.scc.kit.edu/auth/realms/kit'


def make_request_object(request_args, jwk):
    keys = KEYS()
    jws = JWS(request_args)

    if jwk:
        keys.load_jwks(json.dumps(dict(keys=[jwk])))

    return jws.sign_compact(keys)


def base64_urlencode(s):
    return base64.urlsafe_b64encode(s).split('='.encode('utf-8'))[0]


def get_ssl_context(config):
    """
    :return a ssl context with verify and hostnames settings
    """
    ctx = ssl.create_default_context()

    if 'verify_ssl_server' in config and not bool(config['verify_ssl_server']):
        print('Not verifying ssl certificates')
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


class Oid:
    def __init__(self):
        self.credentials = {}
        self.kit_config = {}
        self.TempState = None
        self.TempCodeVerifier = None
        self.ctx = get_ssl_context(self.kit_config)
        self.meta_data_url = ISSUER + '/.well-known/openid-configuration'
        print('Fetching config from: %s' % self.meta_data_url)
        meta_data = urlopen(self.meta_data_url)
        if meta_data:
            self.kit_config.update(json.load(meta_data))
        else:
            print('Unexpected response on discovery document: %s' % meta_data)

        self.credentials['client_id'] = 'anmeldung-spz-kit-edu'
        # !!! Never upload secret to github !!! set to 'myclientsecret'
        self.credentials['secret_key'] = 'myclientsecret'

        # missing to check ssl context here

        self.client_data = None

        self.redirect_uri = "https://anmeldung.spz.kit.edu"

    def prepare_request(self, session, scope, response_type, claims, send_parameters_via,
                        ui_locales=None, forceConsent=None, max_age=None, acr=None,
                        allowConsentOptionDeselection=None, forceAuthN=None):
        N = 7
        # state is a random string
        state = ''.join(random.choices(string.ascii_uppercase + string.digits, k=N))
        session['state'] = state
        self.TempState = state
        # code_verifier is a string with 100 positions
        session['code_verifier'] = code_verifier = ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=100)).encode('utf-8')

        session["flow"] = response_type
        code_challenge = base64_urlencode(hashlib.sha256(code_verifier).digest())
        self.TempCodeVerifier = code_verifier

        request_args = {'scope': scope,
                        'response_type': response_type,
                        'client_id': self.credentials['client_id'],
                        'state': state,
                        'code_challenge': code_challenge,
                        'code_challenge_method': "S256",
                        'redirect_uri': self.redirect_uri}

        if acr:
            request_args["acr_values"] = acr

        if ui_locales:
            request_args["ui_locales"] = ui_locales

        if max_age:
            request_args["max_age"] = max_age

        if forceAuthN:
            request_args["prompt"] = "login"

        if claims:
            request_args["claims"] = claims

        if forceConsent:
            if allowConsentOptionDeselection:
                request_args["prompt"] = request_args.get("prompt", "") + " consent consent_allow_deselection"
            else:
                request_args["prompt"] = request_args.get("prompt", "") + " consent"

        delimiter = "?" if self.kit_config['authorization_endpoint'].find("?") < 0 else "&"

        if send_parameters_via == "request_object":
            request_object_claims = request_args
            request_args = dict(
                request=make_request_object(request_object_claims, self.credentials.get("request_object_key", None)),
                client_id=request_args["client_id"],
                code_challenge=request_args["code_challenge"],  # FIXME: Curity can't currently handle PCKE if not
                code_challenge_method=request_args["code_challenge_method"],  # provided on query string
                scope=request_args["scope"],
                response_type=request_args["response_type"],
                redirect_uri=request_args["redirect_uri"]  # FIXME: Curity requires this even if in request obj)
            )
        elif send_parameters_via == "request_uri":
            request_args = None

        login_url = "%s%s%s" % (self.kit_config['authorization_endpoint'], delimiter, urlencode(request_args))

        print("Redirect to %s" % login_url)

        return login_url

    def link_extractor(self, text):
        data = {}

        snippets = text.split('?')
        response_data = snippets[1].split('&')
        for entry in response_data:
            pair = entry.split('=')
            data[pair[0]] = pair[1]

        return data

    def get_access_token(self, code, code_verifier):
        """
        :param code: The code received with the authorization request
        :param code_verifier: The code challenge attribute sent in first url redirect
        :return the json response containing the tokens
        """
        token_url = self.kit_config['token_endpoint']

        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'code_verifier': code_verifier,
            'redirect_uri': self.redirect_uri,
            'client_id': self.credentials['client_id'],
            'client_secret': self.credentials['secret_key']
        }

        """
        # build request with data and headers
        params = urlencode(data).encode('utf-8')
        try:
            request = Request(token_url, data=params, headers=headers)
        except urllib.error.URLError as e:
            # Unable to create our request, here the reason
            print("Unable to create your request: {error}".format(error=str(e)))
        else:
            # give the code to receive tokens
            try:
                token_response = urlopen(request)
            except URLError as e:
                print("Could not exchange code for tokens")
                raise e
            return json.loads(token_response).read().decode('utf-8')
        """

        # use requests lib for post request to exchange code for token
        token_response = requests.post(token_url, data=data)
        return token_response.json()

    def request_data(self, access_token):
        header = {
            'Authorization': 'Bearer {}'.format(access_token),
            'claim': 'family_name'
        }
        request_url = self.kit_config['userinfo_endpoint']
        response = requests.get(request_url, headers=header)

        return response

    def decode_id_token(self, token: str):
        fragments = token.split(".")
        if len(fragments) != 3:
            raise Exception("Incorrect id token format: " + token)
        payload = fragments[1]
        padded = payload + '=' * (4 - len(payload) % 4)
        decoded = base64.b64decode(padded)
        return json.loads(decoded)

