# -*- coding: utf-8 -*-

"""The login handler for OpenID Connect Single Sign On with KIT institution

   Holds the login handling.
"""

from flask_openid import OpenID

from spz import app
from flask import g, session, flash, redirect, render_template, url_for
from spz.oidc.oidc_authentication import Oid


oid = OpenID(app)
request_handler = Oid()

@app.before_request
def lookup_current_user():
    g.user = None
    if 'openid' in session:
        openid = session['openid']
        flash('Successfully logged in to KIT OIDC')
    else:
        flash('Authentification not performed')


@oid.loginhandler
def oidc_login():
    if g.user is not None:
        return redirect(oid.get_next_url())
    #oid.try_login(request_handler.prepare_request(session={}, scope="openid", response_type="code", claims="aud",
          #                                send_parameters_via="request_object"))
    url = request_handler.prepare_request(session={}, scope="openid", response_type="code", claims="aud",
                                          send_parameters_via="request_object")
    return redirect(url)


@oid.after_login
def create_or_login(resp):
    session['openid'] = resp.identity_url
    user = User.query.filter_by(openid=resp.identity_url).first()
    if user is not None:
        flash(u'Successfully signed in')
        g.user = user
        return redirect(oid.get_next_url())
    return redirect(url_for('create_profile', next=oid.get_next_url(),
                            name=resp.fullname or resp.nickname,
                            email=resp.email))
