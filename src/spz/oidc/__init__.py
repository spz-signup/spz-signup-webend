# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login handling.
"""
from requests_oauthlib import OAuth2Session
from flask_openid import OpenID

from spz import app
from flask import g, session, flash, redirect, render_template, request, url_for
from spz.oidc.oidc_authentication import Oid

oid = OpenID(app)
request_handler = Oid()


@app.before_request
def lookup_current_user():
    g.user = None
    if 'state' in session:
        flash(session['state'])
    if 'session_state' in session:
        flash('Successfully logged in to KIT OIDC :)')
    else:
        flash('Authentification not performed :(')


@oid.loginhandler
def oidc_login():
    if g.user is not None:
        return redirect(oid.get_next_url())
    url = request_handler.prepare_request(session={}, scope="openid", response_type="code", claims="aud",
                                          send_parameters_via="request_object")
    session['state'] = request_handler.TempState
    session['code_verifier'] = request_handler.TempCodeVerifier
    return redirect(url)


@oid.after_login
def oidc_callback(url):
    response_data = request_handler.link_extractor(url)
    # check equality of state which was sent from spz webserver and received from kit server
    if not response_data['state'] == session['state']:
        flash('Invalid Request -> session is being deleted, because ' + response_data['state'] +
              ' is different to ' + session['state'])
        oidc_logout()
    else:
        flash('Response Arguments ---------------------')
        for key, value in response_data.items():
            session[key] = value
            flash(key + ' : ' + value)
        """
        kit = OAuth2Session(request_handler.credentials['client_id'])
        token = kit.fetch_token(request_handler.kit_config['token_endpoint'],
                                code=session['code'],
                                client_secret=request_handler.credentials['secret_key'])
        #save the received acces token in the session
        """
        token = request_handler.get_access_token(session['code'], session['code_verifier'])

        session['access_token'] = token[0]
        session['refresh_token'] = token[2]
        flash('SUCCESS! -> ' + token)
        #--------------- funzt bis hier -----------------
        request_data = request_handler.request_data(session['access_token'])
        flash('profile data: ' + request_data) # response error 405 :/ TODO: make work next time
    return redirect(url_for("index"))


def oidc_logout():
    session.pop('state')
    if 'session_state' in session:
        session.pop('session_state')
    if 'code' in session:
        session.pop('code')
    return redirect(url_for("index"))
