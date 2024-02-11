# -*- coding: utf-8 -*-

"""Cacheable helpers for database fields that are not supposed to change often or quickly.

   Do not specify a timeout; so the default one (from the configuration) gets picked up.
"""

from datetime import datetime

from spz import models, cache, db

from sqlalchemy import distinct

from flask_babel import gettext as _


@cache.cached(key_prefix='degrees')
def degrees_to_choicelist():
    return [
        (x.id, x.name)
        for x
        in models.Degree.query.order_by(models.Degree.id.asc())
    ]


@cache.cached(key_prefix='graduations')
def graduations_to_choicelist():
    return [
        (x.id, x.name)
        for x
        in models.Graduation.query.order_by(models.Graduation.id.asc())
    ]


@cache.cached(key_prefix='origins')
def origins_to_choicelist():
    return [
        (x.id, '{0}'.format(x.name))
        for x
        in models.Origin.query.order_by(models.Origin.id.asc())
    ]


@cache.cached(key_prefix='internal_origins')
def internal_origins_to_choicelist():
    return [
        (x.id, '{0}'.format(x.name))
        for x
        in models.Origin.query.filter(models.Origin.is_internal == True).order_by(models.Origin.id.asc())
    ]


@cache.cached(key_prefix='external_origins')
def external_origins_to_choicelist():
    return [
        (x.id, '{0}'.format(x.name))
        for x
        in models.Origin.query.filter(models.Origin.is_internal == False).order_by(models.Origin.id.asc())
    ]


@cache.cached(key_prefix='languages')
def languages_to_choicelist():
    return [
        (x.id, '{0}'.format(x.full_name))
        for x
        in models.Language.query.order_by(models.Language.name.asc())
    ]


@cache.cached(key_prefix='language')
def language_to_choicelist(lang_id):  # shows only courses from selected language
    return [
        (x.id, '{0}'.format(x.full_name))
        for x
        in models.Course.query.filter(models.Course.language_id == lang_id).order_by(models.Course.id.asc())
    ]


@cache.cached(key_prefix='gers')
def gers_to_choicelist():
    return [
        (x[0], x[0])
        for x
        in db.session.query(distinct(models.Course.ger)).order_by(models.Course.ger.asc())
    ]


@cache.cached(key_prefix='course_status')
def course_status_to_choicelist():
    return [
        (x.value, _(x.name))
        for x
        in models.Course.Status
    ]


@cache.cached(key_prefix='upcoming_courses')
def upcoming_courses_to_choicelist():
    available = models.Course.query \
        .join(models.Language.courses) \
        .order_by(models.Language.name, models.Course.level, models.Course.alternative)

    time = datetime.utcnow()
    upcoming = [course for course in available if course.language.is_upcoming(time)]

    def generate_marker(course):
        if course.is_overbooked:
            return ' (Überbucht)'
        elif course.has_waiting_list:
            return ' (Warteliste)'
        else:
            return ''

    return [
        (course.id, '{0}{1}'.format(course.full_name, generate_marker(course)))
        for course in upcoming
    ]


@cache.cached(key_prefix='all_courses')
def all_courses_to_choicelist():
    courses = models.Course.query \
        .join(models.Language.courses) \
        .order_by(models.Language.name, models.Course.level, models.Course.alternative)

    return [
        (course.id, '{0}'.format(course.full_name))
        for course in courses
    ]


"""
@cache.cached(key_prefix='all_languages')
def all_languages_to_choicelist():
    languages = models.Language.query \
        .order_by(models.Language.name)

    return [
        (language.id, '{0}'.format(language.name))
        for language in languages
    ]
"""
