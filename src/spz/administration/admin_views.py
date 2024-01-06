# -*- coding: utf-8 -*-

"""The application's administration views.

   Manages the mapping between routes and their activities for the administrators.
"""

import socket
import re
import csv
import json
from datetime import datetime

from redis import ConnectionError

from sqlalchemy import and_, func, not_

from flask import request, redirect, render_template, url_for, flash
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message

from spz import models, db
from spz.administration import TeacherManagement
from spz.decorators import templated
import spz.forms as forms
from spz.util.Filetype import mime_from_filepointer
from spz.mail import generate_status_mail

from flask_babel import gettext as _


@templated('internal/administration/teacher_overview_base.html')
def administration_teacher():
    # list of tuple (lang, aggregated number of courses, aggregated number of seats)
    '''lang_misc = db.session.query(models.Language, func.count(models.Language.courses), func.sum(models.Course.limit)) \
        .join(models.Course, models.Language.courses) \
        .group_by(models.Language) \
        .order_by(models.Language.name) \
        .from_self() '''
    # TODO: show statistics, code above can be helpful
    languages = db.session.query(models.Language)

    return dict(language=languages)


@templated('internal/administration/teacher_overview_lang.html')
def administration_teacher_lang(id):
    lang = models.Language.query.get_or_404(id)
    teacher = models.Teacher.query.join(models.Teacher.courses).filter(models.Course.language_id == lang.id)
    return dict(language=lang, teacher=teacher)


@templated('internal/administration/add_teacher.html')
def add_teacher(id):
    lang = models.Language.query.get_or_404(id)
    form = forms.AddTeacherForm(id)

    if form.validate_on_submit():
        teacher = form.get_teacher()

        # check, if course is already assigned to a teacher
        courses = form.get_courses()
        try:
            for course in courses:
                # if course is not available, error is thrown
                TeacherManagement.check_availability(course)
        except Exception as e:
            flash(_('Der Kurs ist schon vergeben. Es kann nur eine*n Lehrbeauftragte*n je Kurs geben: %(error)s',
                    error=e), 'negative')
            return dict(language=lang, form=form)

        if teacher is None:
            teacher = models.Teacher(email=form.get_mail(),
                                     first_name=form.get_first_name(),
                                     last_name=form.get_last_name(),
                                     active=True,
                                     courses=form.get_courses(),
                                     )

            try:
                db.session.add(teacher)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                flash(_('Es gab einen Fehler beim Hinzufügen des Lehrbeauftragten: %(error)s', error=e), 'negative')
                return dict(form=form)

        return render_template('internal/administration/teacher_overview_lang.html', language=lang)

    return dict(language=lang, form=form)


@templated('internal/administration/edit_teacher.html')
def edit_teacher(id):
    teacher = models.Teacher.query.get_or_404(id)
    form = forms.EditTeacherForm()

    if form.validate_on_submit():

        try:
            teacher.first_name = form.first_name.data
            teacher.last_name = form.last_name.data
            teacher.mail = form.mail.data
            teacher.tag = form.tag.data

            db.session.commit()
            flash(_('Der/die Lehrbeauftragte wurde aktualisiert'), 'success')

            add_to_course = form.get_add_to_course()
            remove_from_course = form.get_remove_from_course()

            notify = form.get_send_mail()

            if remove_from_course:
                try:
                    success = TeacherManagement.remove_course(teacher, remove_from_course, notify)
                    flash(
                        _('Der/die Lehrbeauftragte wurde vom Kurs "(%(name)s)" entfernt',
                          name=remove_from_course.full_name),
                        'success')
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(_('Der/die Lehrbeauftragte konnte nicht aus dem Kurs entfernt werden: %(error)s', error=e),
                          'negative')

            if add_to_course:
                try:
                    TeacherManagement.add_course(teacher, add_to_course, notify)
                    flash(
                        _('Der/die Lehrbeauftragte wurde zum Kurs {} hinzugefügt.'.format(add_to_course.full_name)),
                        'success'
                    )
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(
                        _('Der/die Lehrbeauftragte konnte nicht für den Kurs eingetragen werden: %(error)s',
                          error=e),
                        'negative')

            return redirect(url_for('edit_teacher', id=teacher.id))

        except Exception as e:
            db.session.rollback()
            flash(_('Der Bewerber konnte nicht aktualisiert werden: %(error)s', error=e), 'negative')
            return dict(form=form)

    form.populate(teacher)
    return dict(teacher=teacher, form=form)


@templated('internal/teacher.html')
def teacher(id):
    teacher_db = models.Teacher.query.get_or_404(id)

    return dict(teacher=teacher_db)


@templated('internal/administration/grade.html')
def grade(id, course_id):
    teacher_db = models.Teacher.query.get_or_404(id)
    course = models.Course.query.get_or_404(course_id)

    return dict(teacher=teacher_db, course=course)


@templated('internal/administration/attendances.html')
def attendances(id, course_id):
    teacher_db = models.Teacher.query.get_or_404(id)
    course = models.Course.query.get_or_404(course_id)

    return dict(teacher=teacher_db, course=course)
