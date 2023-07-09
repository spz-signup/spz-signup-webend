# -*- coding: utf-8 -*-

"""The request handler for OpenID Connect Single Sign On with KIT institution

   Holds the data exchange funcionality.
"""

import hashlib
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError
from urllib.request import Request

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


class Oid:
    def __init__(self):
        self.credentials = {}
        self.kit_config = {}
        meta_data_url = ISSUER + '/.well-known/openid-configuration'
        print('Fetching config from: %s' % meta_data_url)
        meta_data = urlopen(meta_data_url)
        if meta_data:
            self.kit_config.update(json.load(meta_data))
        else:
            print('Unexpected response on discovery document: %s' % meta_data)

        self.credentials['client_id'] = 'anmeldung-spz-kit-edu'
        self.credentials['secret'] = 'myclientsecret'

        # missing to check ssl context here

        self.client_data = None

    client_id = 'anmeldung-spz-kit-edu'

    authorization_url = 'https://oidc.scc.kit.edu/auth/realms/kit/protocol/openid-connect/auth'
    end_session_url = 'https://oidc.scc.kit.edu/auth/realms/kit/protocol/openid-connect/logout'

    def prepare_request(self, session, scope, response_type, claims, send_parameters_via,
                        ui_locales=None, forceConsent=None, max_age=None, acr=None,
                        allowConsentOptionDeselection=None, forceAuthN=None):
        N = 7
        # state is a random string
        state = ''.join(random.choices(string.ascii_uppercase + string.digits, k=N))
        session['state'] = state
        # code_verifier is a string with 100 positions
        session['code_verifier'] = code_verifier = ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=100)).encode('utf-8')
        session["flow"] = response_type

        code_challenge = base64_urlencode(hashlib.sha256(code_verifier).digest())

        request_args = {'scope': scope,
                        'response_type': response_type,
                        'client_id': self.credentials['client_id'],
                        'state': state,
                        'code_challenge': code_challenge,
                        'code_challenge_method': "S256",
                        'redirect_uri': "https://anmeldung.spz.kit.edu"}

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


    def get_access_token(self):
        pass

    def request_data(self):
        pass
