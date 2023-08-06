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

from flask_openid import OpenID

from spz import app
from flask import g, session, flash, redirect, render_template, request, url_for
from spz.oidc.oidc_authentication import Oid

oid = OpenID(app)
request_handler = Oid()

# a list of all used session parameters
session_parameters = ["state", "code_verifier", "session_state", "code", "access_token", "refresh_token",
                      "id_token"]


@app.before_request
def lookup_current_user():
    g.user = None
    if 'session_state' in session:
        flash('Successfully logged in to KIT OIDC :)')
    else:
        flash('Authentication not performed :(')


@oid.loginhandler
def oidc_login():
    if g.user is not None:
        return redirect(oid.get_next_url())
    # generate random keys
    session['state'] = request_handler.generate_state()
    session['code_verifier'] = request_handler.generate_code_verifier()

    # standard scope is openid, full name can be obtained with 'openid profile'
    url = request_handler.prepare_request(session={}, scope="openid", response_type="code", claims="aud",
                                          send_parameters_via="request_object", state=session['state'],
                                          code_verifier=session['code_verifier'])
    return redirect(url)


@oid.after_login
def oidc_callback(url):
    response_data = request_handler.link_extractor(url)
    # check equality of state which was sent from spz webserver and received from kit server
    if not response_data['state'] == session['state']:
        flash('Invalid Request -> session is being deleted, because ' + response_data['state'] +
              ' is different to ' + session['state'] + ", protection against CRFS attacks")
        oidc_logout()
    else:
        flash('Response Arguments ---------------------')
        for key, value in response_data.items():
            session[key] = value
            flash(key + ' : ' + value)

        token = request_handler.get_access_token(session['code'], session['code_verifier'])
        if 'access_token' and 'refresh_token' in token:
            session['access_token'] = token['access_token']
            session['refresh_token'] = token['refresh_token']

            flash("access token: " + session['access_token'])
            flash("refresh token: " + session['refresh_token'])
        if 'id_token' in token:
            session['id_token'] = token['id_token']

            flash("id token: " + session['id_token'])

            # decode id token
            decoded_id = request_handler.decode_id_token(session['id_token'])
            # save kit email in session for further use
            if 'eduperson_principal_name' in decoded_id:
                session['email'] = decoded_id['eduperson_principal_name']
                flash("Following Email saved in Session: " + session['email'])
                flash("eduperson_scoped_affiliation: " + decoded_id['eduperson_scoped_affiliation'][0])
                flash("preferred_username: " + decoded_id['preferred_username'])

        # ToDo: Do we need this, if we get the same information in id_token in request before?
        if 'access_token' in session:
            # get protected resources
            request_data = request_handler.request_data(session['access_token'])

            flash('Data transmitted: ' + str(request_data))
    return redirect(url_for("index"))


def oidc_logout():
    # delete all session parameters
    for param in session_parameters:
        if param in session:
            session.pop(param)
    # logout from kit oidc, activate if wished
    logout_url = request_handler.kit_config['end_session_endpoint']
    return redirect(url_for('index'))
