# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login handling.
"""

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
    return redirect(url)


@oid.after_login
def oidc_callback(url):
    response_data = request_handler.link_extractor(url)
    if response_data['state'] is not session['state']:
        flash('Invalid Request -> session is being deleted')
        session.pop('state')
        session.pop('session_state')
        session.pop('code')
    else:
        flash('Response Arguments ---------------------')
        for key, value in response_data.items():
            session[key] = value
            flash(key + ' : ' + value)
