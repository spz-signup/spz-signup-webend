from datetime import datetime, timedelta
from spz import app, tasks

import jwt

def generate_export_token_for_courses(courses):
    return jwt.encode({'courses': courses, 'exp': datetime.utcnow() + timedelta(hours=1)},
                      key=app.config['SECRET_KEY'], algorithm="HS256")

def get_courses_from_export_token(export_token):
    try:
        courses = jwt.decode(export_token, key=app.config['SECRET_KEY'], algorithms="HS256")['courses']

        if isinstance(courses, list):
            return courses

        return False
    except Exception as e:
        return False
