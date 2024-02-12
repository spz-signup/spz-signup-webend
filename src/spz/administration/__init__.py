# -*- coding: utf-8 -*-
"""static functions related to administration tasks

This module contains methods for:
    - teacher management
    - course management
"""

from flask import flash
from spz import models, db, tasks
from spz.mail import generate_status_mail

from flask_babel import gettext as _

#from spz.models import Teacher


class TeacherManagement:
    @staticmethod
    def remove_course(teacher, course, notify):
        success = teacher.roles.remove(course)
        if not success:
            raise ValueError(_('Folgender Kurs "{}" war kein Kurs des/der Lehrbeauftragten.'
                               ' Wurde der richtige Kurs ausgewählt?'.format(course.full_name)))

        # ToDO: update Mailform for teachers
        """
        if notify and success:
            try:
                # TODO: send mail for teachers -> own template needed
                tasks.send_slow.delay(generate_status_mail(applicant, course))
                flash(_('Bestätigungsmail wurde versendet'), 'success')
            except (AssertionError, socket.error, ConnectionError) as e:
                flash(_('Bestätigungsmail konnte nicht versendet werden: %(error)s', error=e), 'negative')
        """
        return success

    @staticmethod
    def add_course(teacher, course, notify):
        course_ids = db.session.query(models.Role.course_id).filter(models.Role.course_id.isnot(None)).distinct().all()
        if course.id in course_ids:
            raise ValueError(
                _('Der/die Lehrbeauftragte hat diesen Kurs schon zugewiesen. Doppelzuweisung nicht möglich!'))
        TeacherManagement.check_availability(course)
        teacher.roles.append(course)

        # ToDO: update Mailform for teachers
        """
        if notify:
            try:
                tasks.send_slow.delay(generate_status_mail(applicant, course, restock=True))
                flash(_('Bestätigungsmail wurde versendet'), 'success')
            except (AssertionError, socket.error, ConnectionError) as e:
                flash(_('Bestätigungsmail konnte nicht versendet werden: %(error)s', error=e), 'negative')

        """

    @staticmethod
    def check_availability(course):
        teachers = models.User.query.order_by(models.User.id).all()
        course_ids = db.session.query(models.Role.course_id).filter(models.Role.course_id.isnot(None)).distinct().all()
        for teacher in teachers:
            if course.id in course_ids:
                raise ValueError('{0} ist schon vergeben an {1}.'.format(course.full_name, teacher.full_name))
