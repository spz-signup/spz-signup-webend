from datetime import datetime, timedelta, timezone
from spz import app, tasks
from flask import render_template, url_for, flash
from flask_mail import Message

import jwt


def send_password_reset_to_user(user):
    message = Message(
        sender=app.config['PRIMARY_MAIL'],
        recipients=[user.email],
        subject='[Sprachenzentrum] Passwort festlegen',
        body=render_template(
            'mails/auth/passwordresetmail.html',
            password_reset_link=app.config['SPZ_URL'] + url_for('reset_password',
                                                                reset_token=get_password_reset_token_for_user(user))
        ),
        charset='utf-8'
    )

    tasks.send_quick.delay(message)


def get_password_reset_token_for_user(user):
    return jwt.encode({'reset_password': user.id, 'exp': datetime.now(timezone.utc) + timedelta(days=3)},
                      key=app.config['SECRET_KEY'], algorithm="HS256")


def validate_reset_token_and_get_user_id(reset_token):
    try:
        user_id = jwt.decode(reset_token, key=app.config['SECRET_KEY'], algorithms="HS256")['reset_password']

        if isinstance(user_id, int):
            return user_id

        return False
    except Exception as e:
        return False
