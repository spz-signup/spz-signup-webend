from spz import app
from spz.models import User
from spz.auth.password_reset import send_password_reset_to_user


if __name__ == '__main__':
    print('Sending password reset mail to all users.')

    users = User.query.all()

    with app.app_context(), app.test_request_context():
        for user in users:
            send_password_reset_to_user(user)

    print('Done.')

