# -*- coding: utf-8 -*-

"""The application's views.

   Manages the mapping between routes and their activities.

   Notice: administration_views contains the views for teacher administration
"""
import io
import socket
import re
import csv
import json
from datetime import datetime

from redis import ConnectionError

from sqlalchemy import and_, func, not_

from flask import request, redirect, render_template, url_for, flash, jsonify, make_response
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message

from spz import app, models, db, token, tasks
from spz.decorators import templated
import spz.forms as forms
from spz.util.Filetype import mime_from_filepointer
from spz.mail import generate_status_mail
from spz.export import export_course_list, export_overview_list
from spz.administration import TeacherManagement

from flask_babel import gettext as _

from spz.oidc import oidc_callback, oidc_url, oidc_get_resources

from spz.pdf_zip import PdfZipWriter, html_response
from spz.pdf import generate_participation_cert
from spz.auth.password_reset import validate_reset_token_and_get_user_id

from spz.administration import TeacherManagement

from spz.campusportal.export_token import generate_export_token_for_courses, get_courses_from_export_token


def check_precondition_with_auth(cond, msg, auth=False):
    """Check precondition and flash message if not satisfied.

    Returns True (=error) when the condition is not satisfied.

    Condition check can be overwritten when `auth` is True in which case no
    error is returned and only a warning will be shown to the user.
    """
    if not cond:
        if auth:
            flash(_('%(message)s (Überschrieben durch Fachleiterzugang!)', message=msg), 'warning')
            return False
        else:
            flash(msg, 'negative')
            return True
    else:
        return False


@templated('presignup.html')
def index():
    one_time_token = request.args.get('token', None)

    # token_payload will contain the linked mail address if valid or None otherwise
    token_payload = token.validate_once(
        token=one_time_token,
        payload_wanted=None,
        namespace='preterm',
        db_model=models.Applicant,
        db_column=models.Applicant.mail
    ) if one_time_token else None

    # show all forms to authenticated users (normal or via one_time_token)
    form = forms.PreSignupForm(show_all_courses=(current_user.is_authenticated or token_payload))
    time = datetime.utcnow()

    if current_user.is_authenticated:
        flash(_('Angemeldet: Vorzeitige Registrierung möglich. Falls unerwünscht, bitte abmelden.'), 'info')
    if token_payload:
        flash(_('Prioritäranmeldung aktiv!'), 'info')
    elif one_time_token:
        flash(_('Token für Prioritäranmeldung ungültig!'), 'negative')

    if form.validate_on_submit():
        course = form.get_course()
        user_has_special_rights = current_user.is_authenticated and current_user.can_edit_course(course)
        preterm = token_payload

        # signup at all times only with token or privileged users
        err = check_precondition_with_auth(
            course.language.is_open_for_signup(time) or preterm,
            _(
                'Bitte gedulden Sie sich, die Anmeldung für diese Sprache ist erst möglich in %(date)s',
                date=course.language.until_signup_fmt()
            ),
            user_has_special_rights
        )

        if err:
            return dict(form=form)

        if form.get_is_internal():
            oidc_redirect_url = app.config['SPZ_URL'] + url_for('signupinternal', course_id=course.id,
                                                                token=one_time_token)
            oidc_redirect_config = oidc_url(oidc_redirect_url)

            oauth_token = models.OAuthToken(
                state=oidc_redirect_config['state'],
                code_verifier=oidc_redirect_config['code_verifier']
            )
            db.session.add(oauth_token)
            db.session.commit()

            return redirect(oidc_redirect_config['url'])

        return redirect(url_for('signupexternal', course_id=course.id, token=one_time_token))

    return dict(form=form)


@templated('signupinternal.html')
def signupinternal(course_id):
    course = models.Course.query.get_or_404(course_id)
    form = forms.SignupFormInternal(course_id)
    is_student = True

    time = datetime.utcnow()
    one_time_token = request.args.get('token', None)

    # token_payload will contain the linked mail address if valid or None otherwise
    token_payload = token.validate_once(
        token=one_time_token,
        payload_wanted=None,
        namespace='preterm',
        db_model=models.Applicant,
        db_column=models.Applicant.mail
    ) if one_time_token else None

    if current_user.is_authenticated:
        flash(_('Angemeldet: Vorzeitige Registrierung möglich. Falls unerwünscht, bitte abmelden.'), 'info')
    if token_payload:
        flash(_('Prioritäranmeldung aktiv!'), 'info')
    elif one_time_token:
        flash(_('Token für Prioritäranmeldung ungültig!'), 'negative')

    if not 'state' in request.args:
        return redirect(url_for('index'))

    o_auth_state = request.args['state']
    o_auth_token = models.OAuthToken.query.filter(models.OAuthToken.state == o_auth_state).one()

    if not o_auth_token.request_has_been_made:
        o_auth_access_token = oidc_callback(
            url=request.url,
            state=o_auth_token.state,
            code_verifier=o_auth_token.code_verifier,
            redirect_uri=app.config['SPZ_URL'] + url_for('signupinternal', course_id=course.id, token=one_time_token)
        )
        o_auth_token.request_has_been_made = True
        o_auth_user_data = oidc_get_resources(o_auth_access_token['access_token'])

        o_auth_token.user_data = json.dumps(o_auth_user_data)
        db.session.commit()

        # Check that o_auth_user_data contains all data we need
        err = check_precondition_with_auth(
            all(attribute in o_auth_user_data for attribute in
                ['eduperson_scoped_affiliation', 'given_name', 'family_name', 'eduperson_principal_name']),
            _('Bei der Anmeldung für KIT-Angehörige ist ein Fehler aufgetreten. Bitte nutzen Sie die Anmeldung für Externe.')
        )

        # Check that user is either employee or student
        err |= check_precondition_with_auth(
            any(affiliation in o_auth_user_data['eduperson_scoped_affiliation'] for affiliation in
                ['employee@kit.edu', 'student@kit.edu']),
            _('Die Anmeldung für KIT-Angehörige ist nur für Studierende und Mitarbeiter*innnen des KIT möglich. Angehörige anderer Hochschulen und Gasthörer*innen nutzen die Anmeldung für Externe.')
        )

        # Check that we have a matriculation number for students or a username for employees
        err |= check_precondition_with_auth(
            ('student@kit.edu' in o_auth_user_data[
                'eduperson_scoped_affiliation'] and 'matriculationNumber' in o_auth_user_data) or (
                'employee@kit.edu' in o_auth_user_data[
                'eduperson_scoped_affiliation'] and 'preferred_username' in o_auth_user_data),
            _('Bei der Anmeldung für KIT-Angehörige ist ein Fehler aufgetreten. Bitte nutzen Sie die Anmeldung für Externe.')
        )

        if err:
            return redirect(url_for('index'))

        form.state.data = o_auth_token.state
        form.first_name.data = o_auth_user_data['given_name']
        form.last_name.data = o_auth_user_data['family_name']
        form.mail.data = o_auth_user_data['eduperson_principal_name']
        form.confirm_mail.data = o_auth_user_data['eduperson_principal_name']
        form.tag.data = o_auth_user_data['matriculationNumber'] if 'student@kit.edu' in o_auth_user_data[
            'eduperson_scoped_affiliation'] else o_auth_user_data['preferred_username']

        # get information if requester is employee or student
        for affiliation in o_auth_user_data['eduperson_scoped_affiliation']:
            if affiliation == 'student@kit.edu':
                # save information in temporary session token
                o_auth_token.is_student = True
                db.session.commit()
        if not o_auth_token.is_student and not current_user.is_authenticated:
            # preselect employee option in origin field
            # ToDo: make dynamic not hardcoded
            form.origin.choices = [(12, 'KIT (Mitarbeiter*in)')]
            """for num, key in form.origin.choices:
                if key == 'KIT (Mitarbeiter*in)':
                    form.origin.process_data(num)"""

    # set is_student value
    is_student = o_auth_token.is_student

    if form.validate_on_submit():
        o_auth_state = form.get_state()
        o_auth_token = models.OAuthToken.query.filter(models.OAuthToken.state == o_auth_state).one()
        o_auth_user_data = json.loads(o_auth_token.user_data)
        applicant = form.get_applicant()
        course = form.get_course()
        user_has_special_rights = current_user.is_authenticated and current_user.can_edit_course(course)
        preterm = applicant.mail and token_payload

        # check, if applicant is kit student (qualifies for one course free of charge)
        for affiliation in o_auth_user_data['eduperson_scoped_affiliation']:
            if affiliation == 'student@kit.edu':
                applicant.is_student = True

        err = check_precondition_with_auth(
            all(attribute in o_auth_user_data for attribute in
                ['eduperson_scoped_affiliation', 'given_name', 'family_name', 'eduperson_principal_name']),
            _('Bei der Anmeldung für KIT-Angehörige ist ein Fehler aufgetreten. Bitte nutzen Sie die Anmeldung für Externe.')
        )

        # Check that user is either employee or student
        err |= check_precondition_with_auth(
            any(affiliation in o_auth_user_data['eduperson_scoped_affiliation'] for affiliation in
                ['employee@kit.edu', 'student@kit.edu']),
            _('Die Anmeldung für KIT-Angehörige ist nur für Studierende und Mitarbeiter*innnen des KIT möglich. Angehörige anderer Hochschulen und Gasthörer*innen nutzen die Anmeldung für Externe.')
        )

        # Check that we have a matriculation number for students or a username for employees
        err |= check_precondition_with_auth(
            ('student@kit.edu' in o_auth_user_data[
                'eduperson_scoped_affiliation'] and 'matriculationNumber' in o_auth_user_data) or (
                'employee@kit.edu' in o_auth_user_data[
                'eduperson_scoped_affiliation'] and 'preferred_username' in o_auth_user_data),
            _('Bei der Anmeldung für KIT-Angehörige ist ein Fehler aufgetreten. Bitte nutzen Sie die Anmeldung für Externe.')
        )

        # signup at all times only with token or privileged users
        err = check_precondition_with_auth(
            course.language.is_open_for_signup(time) or preterm,
            _(
                'Bitte gedulden Sie sich, die Anmeldung für diese Sprache ist erst möglich in %(date)s',
                date=course.language.until_signup_fmt()
            ),
            user_has_special_rights
        )
        # when using a token, submitted mail address has to match the one stored in payload
        err |= check_precondition_with_auth(
            not preterm or token_payload.lower() == applicant.mail.lower(),
            _('Die eingegebene E-Mail-Adresse entspricht nicht der hinterlegten. '
              'Bitte verwenden Sie die Adresse, an welche Sie auch die Einladung zur prioritären '
              'Anmeldung erhalten haben!'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not course.has_rating_restrictions() or applicant.has_submitted_tag(),
            _('Bei Kursen mit Zugangsbeschränkungen kann die Matrikelnummer nicht nachgereicht werden. '
              'Bitte geben Sie eine Matrikelnummer an.'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            course.allows(applicant),
            _('Sie haben nicht die vorausgesetzten Sprachtest-Ergebnisse um diesen Kurs zu wählen! '
              '(Hinweis: Der Datenabgleich mit Ilias erfolgt automatisch alle 15 Minuten.)'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not applicant.in_course(course) and not applicant.active_in_parallel_course(course),
            _('Sie sind bereits für diesen Kurs oder einem Parallelkurs angemeldet!'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not applicant.over_limit(),
            _('Sie haben das Limit an Bewerbungen bereits erreicht!'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            len(applicant.doppelgangers) == 0,
            _('Sie haben sich bereits mit einer anderen E-Mailadresse für einen Kurs angemeldet. '
              'Benutzen Sie dieselbe Adresse wie bei Ihrer ersten Anmeldung erneut. '
              'Bei Fragen oder Problemen kontaktieren Sie bitte Ihren Fachleiter.'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not course.is_overbooked,  # no transaction guarantees here, but overbooking is some sort of soft limit
            _('Der Kurs ist hoffnungslos überbelegt. Darum werden keine Registrierungen mehr entgegengenommen!'),
            user_has_special_rights
        )
        if err:
            db.session.rollback()
            return redirect(url_for('index'))

        # Run the final insert isolated in a transaction, with rollback semantics
        # As of 2015, we simply put everyone into the waiting list by default and then randomly insert, see #39
        try:
            waiting = not preterm
            informed_about_rejection = waiting and course.language.is_open_for_signup_fcfs(time)
            applicant.add_course_attendance(
                course,
                form.get_graduation(),
                waiting=waiting,
                discount=applicant.current_discount(),
                informed_about_rejection=informed_about_rejection
            )
            # set course ects to applicant
            db.session.add(applicant)
            db.session.delete(o_auth_token)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(_('Ihre Kurswahl konnte nicht registriert werden: %(error)s', error=e), 'negative')
            return dict(form=form)

        # Preterm signups are in by default and management wants us to send mail immediately
        try:
            tasks.send_slow.delay(generate_status_mail(applicant, course, time))
        except (AssertionError, socket.error, ConnectionError) as e:
            flash(_('Eine Bestätigungsmail konnte nicht verschickt werden: %(error)s', error=e), 'negative')

        # Finally redirect the user to an confirmation page, too
        return render_template('confirm.html', applicant=applicant, course=course)

    return dict(course=course, form=form, is_student=is_student)


@templated('signupexternal.html')
def signupexternal(course_id):
    course = models.Course.query.get_or_404(course_id)
    form = forms.SignupFormExternal(course_id)
    time = datetime.utcnow()
    one_time_token = request.args.get('token', None)

    # token_payload will contain the linked mail address if valid or None otherwise
    token_payload = token.validate_once(
        token=one_time_token,
        payload_wanted=None,
        namespace='preterm',
        db_model=models.Applicant,
        db_column=models.Applicant.mail
    ) if one_time_token else None

    if current_user.is_authenticated:
        flash(_('Angemeldet: Vorzeitige Registrierung möglich. Falls unerwünscht, bitte abmelden.'), 'info')
    if token_payload:
        flash(_('Prioritäranmeldung aktiv!'), 'info')
    elif one_time_token:
        flash(_('Token für Prioritäranmeldung ungültig!'), 'negative')

    if form.validate_on_submit():
        applicant = form.get_applicant()
        user_has_special_rights = current_user.is_authenticated and current_user.can_edit_course(course)
        preterm = applicant.mail and token_payload

        # signup at all times only with token or privileged users
        err = check_precondition_with_auth(
            course.language.is_open_for_signup(time) or preterm,
            _(
                'Bitte gedulden Sie sich, die Anmeldung für diese Sprache ist erst möglich in %(date)s',
                date=course.language.until_signup_fmt()
            ),
            user_has_special_rights
        )
        # when using a token, submitted mail address has to match the one stored in payload
        err |= check_precondition_with_auth(
            not preterm or token_payload.lower() == applicant.mail.lower(),
            _('Die eingegebene E-Mail-Adresse entspricht nicht der hinterlegten. '
              'Bitte verwenden Sie die Adresse, an welche Sie auch die Einladung zur prioritären '
              'Anmeldung erhalten haben!'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not course.has_rating_restrictions() or applicant.has_submitted_tag(),
            _('Bitte geben Sie eine Sprachenzentrum ID an.'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            course.allows(applicant),
            _('Sie haben nicht die vorausgesetzten Sprachtest-Ergebnisse um diesen Kurs zu wählen! '
              '(Hinweis: Der Datenabgleich mit Ilias erfolgt automatisch alle 15 Minuten.)'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not applicant.in_course(course) and not applicant.active_in_parallel_course(course),
            _('Sie sind bereits für diesen Kurs oder einem Parallelkurs angemeldet!'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not applicant.over_limit(),
            _('Sie haben das Limit an Bewerbungen bereits erreicht!'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            len(applicant.doppelgangers) == 0,
            _('Sie haben sich bereits mit einer anderen E-Mailadresse für einen Kurs angemeldet. '
              'Benutzen Sie dieselbe Adresse wie bei Ihrer ersten Anmeldung erneut. '
              'Bei Fragen oder Problemen kontaktieren Sie bitte Ihren Fachleiter.'),
            user_has_special_rights
        )
        err |= check_precondition_with_auth(
            not course.is_overbooked,  # no transaction guarantees here, but overbooking is some sort of soft limit
            _('Der Kurs ist hoffnungslos überbelegt. Darum werden keine Registrierungen mehr entgegengenommen!'),
            user_has_special_rights
        )
        if err:
            db.session.rollback()
            return dict(form=form, course=course)

        # Run the final insert isolated in a transaction, with rollback semantics
        # As of 2015, we simply put everyone into the waiting list by default and then randomly insert, see #39
        try:
            waiting = not preterm
            informed_about_rejection = waiting and course.language.is_open_for_signup_fcfs(time)
            applicant.add_course_attendance(
                course=course,
                graduation=None,
                waiting=waiting,
                discount=applicant.current_discount(),
                informed_about_rejection=informed_about_rejection
            )
            # add course ects to applicant
            db.session.add(applicant)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(_('Ihre Kurswahl konnte nicht registriert werden: %(error)s', error=e), 'negative')
            return dict(form=form, course=course)

        # Preterm signups are in by default and management wants us to send mail immediately
        try:
            tasks.send_slow.delay(generate_status_mail(applicant, course, time))
        except (AssertionError, socket.error, ConnectionError) as e:
            flash(_('Eine Bestätigungsmail konnte nicht verschickt werden: %(error)s', error=e), 'negative')

        # Finally redirect the user to a confirmation page, too
        return render_template('confirm.html', applicant=applicant, course=course)

    return dict(course=course, form=form)


@templated('vacancies.html')
def vacancies():
    form = forms.VacanciesForm()

    return dict(form=form)


@templated('licenses.html')
def licenses():
    return None


@templated('signoff.html')
def signoff():
    form = forms.SignoffForm()
    if form.validate_on_submit():
        applicant = form.get_applicant()
        course = form.get_course()
        signoff_id = form.get_signoff_id()

        err = check_precondition_with_auth(
            applicant is not None,
            _('Abmeldung fehlgeschlagen: E-Mailadresse nicht vorhanden.')
        )
        if not err:
            err |= check_precondition_with_auth(
                applicant.matches_signoff_id(signoff_id),
                _('Abmeldung fehlgeschlagen: Ungültige Abmelde-ID!')
            )
            err |= check_precondition_with_auth(
                applicant.in_course(course),
                _('Abmeldung fehlgeschlagen: Sie können sich nicht von einem Kurs abmelden, '
                  'für den Sie nicht angemeldet waren!')
            )
            err |= check_precondition_with_auth(
                applicant.is_in_signoff_window(course) or (datetime.utcnow() < course.language.signup_fcfs_begin),
                _('Abmeldefrist abgelaufen: Zur Abmeldung bitte bei Ihrem Fachbereichsleiter melden!')
            )

            if not err:
                try:
                    remove_attendance(applicant, course, True)
                    db.session.commit()
                    flash(_('Abmeldung erfolgreich!'), 'positive')
                except Exception as e:
                    db.session.rollback()
                    flash(
                        _('Konnte nicht erfolgreich abmelden, bitte erneut versuchen: %(error)s',
                          error=e), 'negative')

    return dict(form=form)


@login_required
@templated('internal/overview.html')
def internal():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    logs = models.LogEntry.get_visible_log(current_user, 200)
    return dict(logs=logs)


@login_required
@templated('internal/registrations.html')
def registrations():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    form = forms.TagForm()
    return dict(form=form)


@login_required
@templated('internal/registrations.html')
def registrations_import():
    form = forms.TagForm()
    if request.method == 'POST':

        fp = request.files['file_name']

        if fp:
            mime = mime_from_filepointer(fp)
            if mime == 'text/plain':
                # strip all known endings ('\r', '\n', '\r\n') and remove empty lines
                # and duplicates
                stripped_lines = (
                    line.decode('utf-8', 'ignore').rstrip('\r').rstrip('\n').rstrip('\r').strip()
                    for line in fp.readlines()
                )
                filtered_lines = (
                    line
                    for line in stripped_lines
                    if line
                )
                unique_registrations = {
                    models.Registration.from_cleartext(line)
                    for line in filtered_lines
                }

                try:
                    num_deleted = models.Registration.query.delete()
                    db.session.add_all(unique_registrations)
                    db.session.commit()
                    flash(
                        _('Import OK: %(deleted)s Einträge gelöscht, %(added)s Einträge hinzugefügt',
                          deleted=num_deleted,
                          added=len(unique_registrations)),
                        'success')
                except Exception as e:
                    db.session.rollback()
                    flash(_('Konnte Einträge nicht speichern, bitte neu einlesen: %(error)s', error=e), 'negative')

                return redirect(url_for('registrations'))

            flash(_('Falscher Dateityp %(type)s, bitte nur Text oder CSV Dateien verwenden', type=mime), 'danger')
            return None

    flash(_('Datei konnte nicht gelesen werden'), 'negative')
    return dict(form=form)


@login_required
@templated('internal/registrations.html')
def registrations_verify():
    form = forms.TagForm()

    if form.validate_on_submit():
        tag = form.get_tag()
        tag_exists = models.verify_tag(tag)

    return dict(form=form, tag_exists=tag_exists, tag=tag)


@login_required
@templated('internal/approvals.html')
def approvals():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    form = forms.TagForm()
    return dict(form=form)


@login_required
@templated('internal/approvals.html')
def approvals_import():
    if request.method == 'POST':
        fp = request.files['file_name']
        if fp:
            mime = mime_from_filepointer(fp)
            if mime == 'text/plain':
                try:
                    priority = bool(request.form.getlist("priority"))
                    approvals = extract_approvals(fp, priority)

                    num_deleted = 0
                    if request.form.getlist("delete_old"):
                        # only remove sticky entries because
                        num_deleted = models.Approval.query.filter(and_(
                            models.Approval.sticky == True,  # NOQA
                            models.Approval.priority == priority
                        )).delete()
                    # add approvals
                    db.session.add_all(approvals)
                    db.session.commit()
                    flash(
                        _('Import OK: %(deleted)s Einträge gelöscht, %(added)s Einträge hinzugefügt',
                          deleted=num_deleted,
                          added=len(approvals)),
                        'success')
                except Exception as e:  # csv, index or db could go wrong here..
                    db.session.rollback()
                    flash(_('Konnte Einträge nicht speichern, bitte neu einlesen: %(error)s', error=e), 'negative')
                return dict(form=forms.TagForm())

            flash(_('Falscher Dateityp %(type)s, bitte nur Text oder CSV Dateien verwenden', type=mime), 'danger')
            return redirect(url_for('approvals'))

    flash(_('Datei konnte nicht gelesen werden'), 'negative')
    return redirect(url_for('approvals'))


def extract_approvals(fp, priority):
    """Extracts approvals of a file

       :param fp: filepointe to the file
       :param priority: if the approval entries are priority entries
    """
    # strip all known endings ('\r', '\n', '\r\n') and remove empty lines
    # and duplicates and header lines
    stripped_lines = (
        line.decode('utf-8', 'ignore').rstrip('\r').rstrip('\n').rstrip('\r').strip()
        for line in fp.readlines()
    )
    filtered_lines = (
        line
        for line in stripped_lines
        if line and not line.startswith('"Name";"Benutzername";"Matrikelnummer"') and
           not line.startswith('"Name";"Login";"Matriculation number"')
    )
    filecontent = csv.reader(filtered_lines, delimiter=';')  # XXX: hardcoded?

    # set columns indices depending on file type (ILIAS or selfmade)
    ilias_export = bool(request.form.getlist("ilias_export"))
    # create list of sticky Approvals, so that background jobs don't remove them
    approvals = []
    for line in filecontent:
        # set rating and tag depending on file type (ILIAS or selfmade)
        if ilias_export:
            # test if all params are existent, if not skip entry
            if line[1] == '' or line[3] == '' or line[4] == '':
                continue
            # calc params
            rating = max(
                0,
                min(
                    int(100 * int(line[3]) / int(line[4])),
                    100
                )
            )
            # set tag depending if an immatriculation number is existing. If not set tag to account name
            if not line[2] == '':
                tag = line[2]
            else:
                tag = line[1]
        else:
            rating = int(line[1])
            tag = line[0]
        approvals.append(
            models.Approval(
                tag=tag,
                percent=rating,
                sticky=True,
                priority=priority
            )
        )
    return approvals


@login_required
@templated('internal/approvals.html')
def approvals_check():
    form = forms.TagForm()

    if form.validate_on_submit():
        tag = form.get_tag()
        approvals = models.Approval.get_for_tag(tag)
    return dict(form=form, tag=tag, approvals=approvals)


@login_required
@templated('internal/approvals.html')
def approvals_export():
    if request.method == 'POST':
        english_courses = models.Language.query.filter(models.Language.name == 'Englisch').first().courses

        tags_seen = set()  # append tags to this set to avoid duplicates
        export_data = []
        for course in english_courses:
            for applicant in course.course_list:
                if applicant.tag and applicant.tag not in tags_seen:
                    tags_seen.add(applicant.tag)
                    export_data.append((applicant.tag, applicant.best_rating()))
        # sort by tag (remains untested)
        export_data.sort(key=lambda x: x[0])
        # create a buffer
        with io.StringIO() as buffer:
            writer = csv.writer(buffer, delimiter=';')
            for line in export_data:
                writer.writerow(line)
            csv_out = buffer.getvalue()

        resp = make_response(csv_out)
        resp.headers['Content-Disposition'] = 'attachment; filename="returners.csv"'
        resp.mimetype = "text/csv"
        return resp

    flash(_('Export-Datei konnte nicht generiert werden'), 'negative')
    return redirect(url_for('approvals'))


@login_required
@templated('internal/approvals_edit.html')
def approvals_edit(tag):
    form = forms.TagForm()
    form.tag.data = tag

    approval_list = forms.create_approval_form(tag)
    edit_form = approval_list(request.form)
    approvals = models.Approval.get_for_tag(tag)
    if request.method == 'POST' and edit_form.validate():
        try:
            changes = False
            for approval in approvals:
                approval_field = getattr(edit_form, f'approval_{approval.id}', None)
                priority_field = getattr(edit_form, f'priority_{approval.id}', None)
                prio = approval.priority
                if approval_field and approval_field.data != approval.percent:
                    approval.percent = approval_field.data
                    prio = True
                    changes = True
                if priority_field and priority_field.data != approval.priority:
                    prio = priority_field.data
                    changes = True
                if changes:
                    # manual change of approval, so it is a sticky entry and should not be removed by ilias syncing
                    approval.sticky = True
                    approval.priority = prio

            if changes:
                db.session.commit()
                flash('Ilias-Testergebnis(se) wurden erfolgreich gespeichert!', 'success')
            else:
                flash('Es gab keine Änderungen zu speichern.', 'info')
        except Exception as e:
            db.session.rollback()
            flash(_('Es gab einen Fehler beim Speichern der Ilias-Testergebnis(se): %(error)s', error=e), 'negative')

        return redirect(url_for('approvals'))

    return dict(form=form, edit_form=edit_form, approvals=approvals)


@login_required
@templated('internal/notifications.html')
def notifications():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    form = forms.NotificationForm()

    if form.validate_on_submit():
        # get attachement data once
        at_mime = ''
        at_data = None
        at_name = ''
        if form.get_attachments():
            # detect MIME data since browser tend to send messy data,
            # e.g. https://bugzilla.mozilla.org/show_bug.cgi?id=373621
            at_mime = []
            at_data = []
            at_name = []
            for att in form.get_attachments():
                if att:
                    at_mime.append(mime_from_filepointer(att))
                    at_data.append(att.read())
                    at_name.append(att.filename)

        try:
            has_sent_cc = False
            recipients = form.get_recipients()
            for recipient in recipients:
                cc_cached = None
                bcc_cached = None
                if not has_sent_cc:
                    cc_cached = form.get_cc()
                    bcc_cached = form.get_bcc()
                    has_sent_cc = True
                msg = Message(
                    sender=form.get_sender(),
                    recipients=[recipient],
                    subject=form.get_subject(),
                    html=form.get_body(),
                    cc=cc_cached,
                    bcc=bcc_cached,
                    charset='utf-8'
                )
                if form.get_attachments():
                    for (mime, data, name) in zip(at_mime, at_data, at_name):
                        msg.attach(name, mime, data)
                tasks.send_slow.delay(msg)

            flash(_('Mail erfolgreich verschickt'), 'success')
            return redirect(url_for('internal'))

        except (AssertionError, socket.error) as e:
            flash(_('Mail wurde nicht verschickt: %(error)s', error=e), 'negative')

    return dict(form=form)


@login_required
@templated('internal/export.html')
def export(type, id):
    form = forms.ExportCourseForm(languages=models.Language.query.all())

    if form.validate_on_submit():
        return export_course_list(
            courses=form.get_selected(),
            format=form.get_format()
        )
    else:
        form.format.data = models.ExportFormat.query.first().id
        if type == 'course':
            form.courses.data = id
        elif type == 'language':
            language = models.Language.query.get(id)
            form.courses.data = [course.id for course in language.courses]

    # update course multi-select based on assigned courses to user
    # if teacher, then only own courses in multi-select selectable
    # if superuser or course admin, then all courses can be downloaded
    form.update_course_list(current_user)
    return dict(form=form, user=current_user)


@login_required
@templated('internal/lists.html')
def lists():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    # list of tuple (lang, aggregated number of courses, aggregated number of seats)
    lang_misc = db.session.query(models.Language, func.count(models.Language.courses), func.sum(models.Course.limit)) \
        .join(models.Course, models.Language.courses) \
        .group_by(models.Language) \
        .order_by(models.Language.name) \
        .from_self()  # b/c of eager loading, see: http://thread.gmane.org/gmane.comp.python.sqlalchemy.user/36757


    return dict(lang_misc=lang_misc)


@login_required
@templated('internal/language.html')
def language(id):
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    return dict(language=models.Language.query.get_or_404(id))


@login_required
@templated('internal/course.html')
def course(id):
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    course = models.Course.query.get_or_404(id)
    form = forms.CourseForm()
    form_delete = forms.DeleteCourseForm()

    # check if a teacher has been assigned to the course
    teacher = (
        models.User.query
        .join(models.Role, models.User.roles)
        .filter(models.Role.course_id == course.id)
        .filter(models.Role.role == 'COURSE_TEACHER')
        .distinct()
        .all()
    )
    if len(teacher) > 1:
        flash(
            _('Achtung: Der Kurs hat mehr als nur einen Dozenten zugewiesen. Das ist ungültig', ),
            'error')

    # we have two forms on this page, to differ between them a hidden identifier tag is used

    if form.identifier.data == 'form-select' and form.validate_on_submit() and current_user.is_authenticated:
        if len(request.form.getlist('applicants')) == 0:
            flash('Mindestens ein/e Kursteilnehmer/in muss zum PDF-Erstellen ausgewählt sein.')
        else:
            # the checkbox value tag 'applicants' holds the mail of selected students
            # value tag is used for identification of applicant in db
            requested = request.form.getlist('applicants')
            applicants = []
            for entry in requested:
                for applicant in course.course_list:
                    if entry == applicant.mail:
                        applicants.append(applicant)
            # TODO flash warning, if it is tried to create certificate for student(s) on waiting list
            zip_file = PdfZipWriter()
            for a in applicants:
                pdf = generate_participation_cert(
                    full_name=a.full_name,
                    tag=a.tag,
                    course=course.full_name,
                    ects=course.ects_points,
                    ger=course.ger,
                    date=app.config['EXAM_DATE']
                )
                # write created pdf-cert to zip file
                zip_file.write_to_zip(pdf, "T_{0}_{1}".format(course.full_name, a.full_name))

            return html_response(zip_file, "Teilnahmescheine_{}".format(course.full_name))

    if form.identifier.data == 'form-delete' and form_delete.validate_on_submit() and current_user.is_superuser:
        try:
            deleted = 0
            name = course.full_name
            for attendance in course.attendances:
                if attendance.waiting:
                    db.session.delete(attendance)
                    deleted += 1
                    # TODO: notify attendants
                else:
                    # TODO: handle active attendances automatically or make deleting them easier
                    flash(_('Der Kurs kann nicht gelöscht werden, weil aktive Teilnahmen bestehen.'), 'error')
                    db.session.rollback()
                return dict(course=course)

            # Delete roles associated with the course before deleting the course
            models.Role.query.filter_by(course_id=course.id).delete()
            # Delete Logentrys
            models.LogEntry.query.filter_by(course_id=course.id).delete()

            db.session.delete(course)
            db.session.commit()
            flash(
                _('Kurs "%(name)s" wurde gelöscht, %(deleted)s wartende Teilnahme(n) wurden entfernt.',
                  name=name,
                  deleted=deleted),
                'success')
            return redirect(url_for('lists'))

        except Exception as e:
            db.session.rollback()
            flash(
                _('Der Kurs konnte nicht gelöscht werden: %(error)s', error=e),
                'error'
            )
    return dict(course=course, form=form, form_delete=form_delete, teacher=teacher)


@login_required
@templated('internal/applicant.html')
def applicant(id):
    applicant = models.Applicant.query.get_or_404(id)
    form = forms.ApplicantForm()

    if form.validate_on_submit():

        try:
            applicant.first_name = form.first_name.data
            applicant.last_name = form.last_name.data
            applicant.phone = form.phone.data
            applicant.mail = form.mail.data
            applicant.tag = form.tag.data
            applicant.origin = form.get_origin()
            applicant.degree = form.get_degree()
            applicant.semester = form.get_semester()

            db.session.commit()
            flash(_('Der Bewerber wurde aktualisiert'), 'success')

            add_to = form.get_add_to()
            remove_from = form.get_remove_from()
            notify = form.get_send_mail()

            if remove_from:
                try:
                    remove_attendance(applicant, remove_from, notify)
                    flash(
                        _('Der Bewerber wurde aus dem Kurs "(%(name)s)" genommen',
                          name=remove_from.full_name),
                        'success')
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(_('Der Bewerber konnte nicht aus dem Kurs genommen werden: %(error)s', error=e), 'negative')

            if add_to:
                try:
                    add_attendance(applicant, add_to, notify)
                    flash(
                        _('Der Bewerber wurde in den Kurs eingetragen. Bitte jetzt Status setzen und überprüfen.'),
                        'success'
                    )
                    db.session.commit()
                    return redirect(url_for('status', applicant_id=applicant.id, course_id=add_to.id))
                except Exception as e:
                    db.session.rollback()
                    flash(
                        _('Der Bewerber konnte nicht für den Kurs eingetragen werden: %(error)s',
                          error=e),
                        'negative')

            return redirect(url_for('applicant', id=applicant.id))

        except Exception as e:
            db.session.rollback()
            flash(_('Der Bewerber konnte nicht aktualisiert werden: %(error)s', error=e), 'negative')
            return dict(form=form)

    form.populate(applicant)
    return dict(form=form)


@login_required
@templated('internal/applicants/search_applicant.html')
def search_applicant():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    form = forms.SearchForm()

    applicants = []

    if form.validate_on_submit():
        # split query into words, each word has to match at least one of the following attributes:
        #  - first name
        #  - second name
        #  - mail address
        #  - tag
        parts = form.query.data.split(' ')
        query = None
        for p in parts:
            p = p.strip()
            if p:
                ilike_str = '%{0}%'.format(p.replace('\\', '\\\\').replace('%', '\\%'))
                subquery = (
                    models.Applicant.first_name.ilike(ilike_str)
                    | models.Applicant.last_name.ilike(ilike_str)
                    | models.Applicant.mail.ilike(ilike_str)
                    | models.Applicant.tag.ilike(ilike_str)
                )
                if query is None:
                    query = subquery
                else:
                    query = query & subquery
        if query is not None:
            applicants = models.Applicant.query.filter(query)

    return dict(form=form, applicants=applicants)


def add_attendance(applicant, course, notify):
    if applicant.in_course(course) or applicant.active_in_parallel_course(course):
        raise ValueError(
            _('Der Teilnehmer ist bereits im Kurs oder nimmt aktiv an einem Parallelkurs teil!'),
            'warning')

    applicant.add_course_attendance(
        course=course,
        graduation=None,
        waiting=False,
        discount=applicant.current_discount()
    )
    db.session.commit()

    if not course.allows(applicant):
        flash(
            _('Der Teilnehmer hat eigentlich nicht die entsprechenden Sprachtest-Ergebnisse. '
              'Teilnehmer wurde trotzdem eingetragen.'),
            'warning'
        )

    if notify:
        try:
            tasks.send_slow.delay(generate_status_mail(applicant, course, restock=True))
            flash(_('Bestätigungsmail wurde versendet'), 'success')
        except (AssertionError, socket.error, ConnectionError) as e:
            flash(_('Bestätigungsmail konnte nicht versendet werden: %(error)s', error=e), 'negative')


def remove_attendance(applicant, course, notify):
    success = applicant.remove_course_attendance(course)
    if success:
        if applicant.is_student:  # transfer free attendance
            active_courses = [a for a in applicant.attendances if not a.waiting]
            free_courses = [a for a in active_courses if a.discount >= 1]
            if active_courses and not free_courses:
                active_courses[0].discount = models.Attendance.MAX_DISCOUNT

    if notify and success:
        try:
            tasks.send_slow.delay(generate_status_mail(applicant, course))
            flash(_('Bestätigungsmail wurde versendet'), 'success')
        except (AssertionError, socket.error, ConnectionError) as e:
            flash(_('Bestätigungsmail konnte nicht versendet werden: %(error)s', error=e), 'negative')

    return success


@login_required
@templated('internal/applicants/applicant_attendances.html')
def applicant_attendances(id):
    return dict(applicant=models.Applicant.query.get_or_404(id))


@login_required
@templated('internal/payments.html')
def payments():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    form = forms.PaymentForm()

    if form.validate_on_submit():
        code = form.confirmation_code.data
        match = re.search(r'^A(?P<a_id>\d{1,})C(?P<c_id>\d{1,})$', code)  # 'A#C#'

        if match:
            a_id, c_id = match.group('a_id', 'c_id')
            return redirect(url_for('status', applicant_id=a_id, course_id=c_id))

        flash(_('Belegungsnummer ungültig'), 'negative')

    stat_list = db.session.query(models.Attendance.paidbycash,
                                 func.sum(models.Attendance.amountpaid),
                                 func.count(),
                                 func.avg(models.Attendance.amountpaid),
                                 func.min(models.Attendance.amountpaid),
                                 func.max(models.Attendance.amountpaid)) \
        .filter(not_(models.Attendance.waiting), models.Attendance.discount != 1) \
        .group_by(models.Attendance.paidbycash)

    desc = ['cash', 'sum', 'count', 'avg', 'min', 'max']
    stats = [dict(list(zip(desc, tup))) for tup in stat_list]

    return dict(form=form, stats=stats)


@login_required
@templated('internal/outstanding.html')
def outstanding():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    outstanding = db.session.query(models.Attendance) \
        .join(models.Course, models.Applicant) \
        .filter(not_(models.Attendance.waiting),
                models.Attendance.is_unpaid)

    return dict(outstanding=outstanding)


@login_required
@templated('internal/status.html')
def status(applicant_id, course_id):
    attendance = models.Attendance.query.get_or_404((applicant_id, course_id))
    form = forms.StatusForm()

    if form.validate_on_submit():
        try:
            attendance.graduation = form.get_graduation()
            attendance.payingdate = datetime.utcnow()
            attendance.discount = form.discount.data
            # attendance.applicant.discounted = form.discounted.data
            attendance.paidbycash = form.paidbycash.data
            attendance.amountpaid = form.amountpaid.data
            attendance.set_waiting_status(form.waiting.data)
            db.session.commit()
            flash(_('Der Status wurde aktualisiert'), 'success')
        except Exception as e:
            db.session.rollback()
            flash(_('Der Status konnte nicht aktualisiert werden: %(error)s', error=e), 'negative')
            return dict(form=form, attendance=attendance)

        if form.notify_change.data:
            try:
                course = attendance.course
                applicant = attendance.applicant
                tasks.send_quick.delay(generate_status_mail(applicant, course))
                flash(_('Mail erfolgreich verschickt'), 'success')
            except (AssertionError, socket.error, ConnectionError) as e:
                flash(_('Mail konnte nicht verschickt werden: %(error)s', error=e), 'negative')

    form.populate(attendance)
    return dict(form=form, attendance=attendance)


@login_required
@templated('internal/statistics.html')
def statistics():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    return None


@login_required
@templated('internal/statistics/free_courses.html')
def free_courses():
    rv = models.Course.query.join(models.Language.courses) \
        .order_by(models.Language.name, models.Course.level, models.Course.alternative)

    return dict(courses=rv)


@login_required
@templated('internal/statistics/origins_breakdown.html')
def origins_breakdown():
    rv = db.session.query(models.Origin, func.count()) \
        .join(models.Applicant, models.Attendance) \
        .filter(not_(models.Attendance.waiting)) \
        .group_by(models.Origin) \
        .order_by(models.Origin.name)

    return dict(origins_breakdown=rv)


@login_required
@templated('internal/statistics/task_queue.html')
def task_queue():
    jobs = []
    try:
        i = tasks.cel.control.inspect()
        everything = i.scheduled()
        jobs = everything[next(iter(everything.keys()))]
    except ConnectionError as e:
        flash(_('Jobabfrage nicht möglich: %(error)s', error=e), 'warning')

    work = []
    for job in jobs:
        request = job['request']
        payload = '{}({}, {})'.format(request['name'], request['args'], request['kwargs'])

        task = {'id': request['id'], 'started': request['time_start'], 'payload': payload, 'priority': job['priority']}
        work.append(task)

    return dict(tasks=work)


@login_required
@templated('internal/preterm.html')
def preterm():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    form = forms.PretermForm()

    token = None

    if form.validate_on_submit() and current_user.is_superuser:
        token = form.get_token()

        try:
            tasks.send_quick.delay(
                Message(
                    sender=app.config['PRIMARY_MAIL'],
                    recipients=[form.mail.data],
                    subject=_('[Sprachenzentrum] URL für prioritäre Anmeldung'),
                    body='{0}'.format(url_for('index', token=token, _external=True)),
                    charset='utf-8'
                )
            )

            flash(_('Eine Mail mit der Token URL wurde an %(receiver)s verschickt', receiver=form.mail.data), 'success')

        except (AssertionError, socket.error) as e:
            flash(_('Eine Bestätigungsmail konnte nicht verschickt werden: %(error)s', error=e), 'negative')

    # always show preterm signups in this view
    attendances = models.Attendance.query \
        .join(models.Course, models.Language, models.Applicant) \
        .filter(models.Attendance.registered < models.Language.signup_begin) \
        .order_by(models.Applicant.last_name, models.Applicant.first_name)

    return dict(form=form, token=token, preterm_signups=attendances)


@login_required
@templated('internal/duplicates.html')
def duplicates():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    taglist = db.session.query(models.Applicant.tag) \
        .filter(models.Applicant.tag is not None, models.Applicant.tag != '') \
        .group_by(models.Applicant.tag) \
        .having(func.count(models.Applicant.id) > 1)

    doppelganger = [models.Applicant.query.filter_by(tag=duptag) for duptag in [tup[0] for tup in taglist]]

    return dict(doppelganger=doppelganger)


@login_required
@templated('internal/unique.html')
def unique():
    form = forms.UniqueForm()

    if form.validate_on_submit():
        courses = form.get_courses()
        deleted = 0

        try:
            waiting_but_active_parallel = [
                attendance
                for course
                in courses
                for attendance
                in course.filter_attendances(waiting=True)
                if attendance.applicant.active_in_parallel_course(course)
            ]

            for attendance in waiting_but_active_parallel:
                db.session.delete(attendance)
                deleted += 1

            db.session.commit()
            flash(
                _('Kurse von %(deleted)s wartenden Teilnehmern mit aktivem Parallelkurs bereinigt', deleted=deleted),
                'success')
        except Exception as e:
            db.session.rollback()
            flash(
                _('Die Kurse konnten nicht von wartenden Teilnehmern mit aktivem Parallelkurs bereinigt werden:'
                  ' %(error)s', error=e),
                'negative'
            )
            return redirect(url_for('unique'))

    return dict(form=form)


@templated('internal/login.html')
def login():
    form = forms.LoginForm()

    if form.validate_on_submit():
        cleaned_email = form.user.data.strip()
        user = models.User.get_by_login(cleaned_email, form.password.data)
        if user:
            login_user(user, remember=True)
            if current_user.is_teacher:
                return redirect(url_for('teacher'))
            return redirect(url_for('internal'))
        flash(_('Login war nicht erfolgreich.'), 'negative')

    return dict(form=form)


def logout():
    logout_user()
    flash(_('Tschau!'), 'success')
    return redirect(url_for('login'))


@templated('internal/auth/reset_password.html')
def reset_password(reset_token):
    form = forms.PasswordResetForm()

    if form.validate_on_submit():
        userId = validate_reset_token_and_get_user_id(reset_token)

        if userId is False:
            flash(_('Das Passwort konnte nicht festgelegt werden. Bitte konraktieren Sie das Sprachenzentrum.'),
                  'negative')

            return dict(form=form)

        user = models.User.query.filter(models.User.id == userId).first()

        if not user:
            flash(_('Das Passwort konnte nicht festgelegt werden. Bitte konraktieren Sie das Sprachenzentrum.'),
                  'negative')

            return dict(form=form)

        user.update_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        flash(_('Das Passwort wurde festgelegt. Sie können sich nun anmelden.'), 'success')

        return redirect(url_for('login'))

    form.reset_token.data = reset_token

    return dict(form=form)


def campus_portal_grades(export_token):
    course_ids = get_courses_from_export_token(export_token)

    if not course_ids:
        return jsonify(error="Invalid export token.")

    courses = models.Course.query.filter(models.Course.id.in_(course_ids)).all()

    if len(courses) != len(course_ids):
        return jsonify(error="Course not found.")

    # Example of expected json structure
    # the json holds an array
    # each entry of the array is an object containing the student information
    """
    [
      {
        matriculationId: 123456,
        title: "Kurs 1",
        titleEn: "Course 1",
        examDate: "2024-03-01",
        ects: 3,
        grade: "2,7",
        sqUnit: "STK"
      }, ...
    ]
    """

    # convert internal exam date format (DD.MM.YYYY) to ISO 8601 standard (YYYY-MM-DD)
    date_object = datetime.strptime(app.config['EXAM_DATE'], '%d.%m.%Y')
    exam_date_iso = date_object.strftime('%Y-%m-%d')  # convert date to ISO 8601 standard

    grade_objects = []
    for course in courses:
        for student in course.course_list:
            attendance = course.get_course_attendance(course.id, student.id)
            # check for valid matriculation id -> tag and if the grade was set and course is passed
            if student.tag_is_digit and attendance.full_grade not in ["-", "nicht bestanden"]:
                if attendance.hide_grade:
                    grade = "bestanden"
                else:
                    grade = attendance.full_grade
                grade_objects.append(
                    {
                        "matriculationId": int(student.tag),  # required
                        # "title": course.name,  # name without alternatives a, b, c, ...
                        # "titleEn": course.name_english,
                        "examDate": exam_date_iso,
                        "ects": attendance.ects_points,  # required
                        "grade": grade,  # required
                        "sqUnit": "SPZ"
                    }
                )

    return jsonify(grade_objects)


@templated('internal/campusportal/campus_export_language.html')
def campus_export_language():
    languages = models.Language.query.all()

    return dict(language=languages)


@templated('internal/campusportal/campus_export.html')
def campus_export_course(id, link=""):
    language = models.Language.query.get_or_404(id)

    courses = language.courses

    grouped_by_level = {}
    for course in courses:
        if course.level not in grouped_by_level:
            grouped_by_level[course.level] = []
        grouped_by_level[course.level].append(course)

    form = forms.CampusExportForm(grouped_by_level)
    form.update_course(grouped_by_level)

    if form.validate_on_submit():
        selected_level = form.get_courses()
        # flash(selected_level)
        courses_of_one_level = grouped_by_level[selected_level]
        # flash(courses_of_one_level)

        course_ids = [course.id for course in courses_of_one_level]

        link = app.config['SPZ_URL'] + "/api/campus_portal/export/" + generate_export_token_for_courses(course_ids)

        return dict(form=form, language=language, link=link)

    return dict(form=form, language=language, link=link)


@templated('internal/overviewExportList.html')
def overview_export_list():
    form = forms.ExportOverviewForm(languages=models.Language.query.all())
    semester = app.config['SEMESTER_NAME']

    if form.validate_on_submit():
        language = form.get_selected()
        only_passed = form.get_passed()

        return export_overview_list(
            language=language,
            format=form.get_format(),
            passed=only_passed
        )

    return dict(form=form, semester=semester)
