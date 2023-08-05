# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login handling.
"""
import json

import requests
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
    # standard scope is openid
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

        token = request_handler.get_access_token(session['code'], session['code_verifier'])

        session['access_token'] = token['access_token']
        session['refresh_token'] = token['refresh_token']
        if 'id_token' in token:
            session['id_token'] = token['id_token']
            # decode id token
            decoded_id = request_handler.decode_id_token(session['id_token'])
            # save kit email in session for further use
            if 'eduperson_principal_name' in decoded_id:
                session['email'] = decoded_id['eduperson_principal_name']
                flash("Following Email saved in Session: " + session['email'])
                flash("eduperson_scoped_affiliation: " + decoded_id['eduperson_scoped_affiliation'][0])
                flash("preferred_username: " + decoded_id['preferred_username'])

        flash("access token: " + session['access_token'])
        flash("refresh token: " + session['refresh_token'])
        flash("id token: " + session['id_token'])

        # get protected ressources
        request_data = request_handler.request_data(session['access_token'])

        flash(
            'request status code: ' + str(request_data.status_code))
        headers = request_data.headers
        for header in headers:
            flash(header + " : " + headers[header])

        flash('Data transmitted: ' + request_data.text)
    return redirect(url_for("index"))


def oidc_logout():
    session.pop('state')
    if 'session_state' in session:
        session.pop('session_state')
    if 'code' in session:
        session.pop('code')
    return redirect(url_for("index"))
