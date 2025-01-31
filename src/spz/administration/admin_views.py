# -*- coding: utf-8 -*-

"""The application's administration views.

   Manages the mapping between routes and their activities for the administrators.
"""
import json
import io
import os
import socket
from flask import request, redirect, url_for, flash, jsonify, make_response, send_from_directory
from flask_login import current_user, login_required, login_user, logout_user
from flask_mail import Message

from spz import app
from spz import models, db, log
from spz.administration import TeacherManagement, is_valid_float
from spz.decorators import templated
from spz.auth.password_reset import send_password_reset_to_user
import spz.forms as forms

from flask_babel import gettext as _

import math

from spz.export import export_course_list
from spz.util.Filetype import mime_from_filepointer


@templated('internal/administration/teacher_overview_base.html')
def administration_teacher():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))
    # Aliasing might be necessary if Role or User is joined through different paths
    # An outer join retrieves records that have matching values in one of the tables, and also those records from the
    # primary table that have no matches in the joined table.
    languages_info = db.session.query(
        models.Language.id,
        models.Language.name,
        db.func.count(models.Course.id).label('course_count'),
        db.func.count(db.distinct(models.Role.user_id)).label('teacher_count')
    ).outerjoin(
        models.Course, models.Language.id == models.Course.language_id  # Ensure all languages are included
    ).outerjoin(
        models.Role, (models.Role.course_id == models.Course.id) & (models.Role.role == models.Role.COURSE_TEACHER)
    ).group_by(
        models.Language.id, models.Language.name
    ).all()

    languages_data = [{
        'id': l_id,
        'name': name,
        'course_count': course_count if course_count else 0,
        'teacher_count': teacher_count if teacher_count else 0,
        'courses_per_teacher': course_count / teacher_count if teacher_count else 0,
    } for l_id, name, course_count, teacher_count in languages_info]

    return dict(language=languages_data)


@login_required
@templated('internal/administration/teacher_overview_base.html')
def teacher_export():
    teachers = (models.User.query
                .outerjoin(models.Role)
                .filter(
        (models.Role.id == None) |
        (models.Role.role == models.Role.COURSE_TEACHER) |
        (
            models.Role.role.notin_([
                models.Role.SUPERUSER,
                models.Role.COURSE_ADMIN
            ])))
                .group_by(models.User.id)
                .all()
                )

    teacher_dict = []
    for teacher in teachers:
        teacher_dict.append({
            'first_name': teacher.first_name,
            'last_name': teacher.last_name,
            'email': teacher.email,
            'tag': teacher.tag
        })

    # Convert to JSON string
    json_data = jsonify(teacher_dict)

    # Create a response object
    response = make_response(json_data)
    response.headers['Content-Disposition'] = 'attachment; filename=teachers.json'
    response.headers['Content-Type'] = 'application/json'

    return response


@login_required
@templated('internal/administration/teacher_overview_base.html')
def teacher_import():
    if request.method == 'POST':
        fp = request.files['file_name']
        if fp:
            mime = mime_from_filepointer(fp)
            if mime == 'application/json' or mime == 'text/plain':
                try:
                    json_data = json.load(fp)

                    if not isinstance(json_data, list):
                        raise ValueError("Loaded data is not a list")

                    for teacher in json_data:
                        new_teacher = models.User(
                            email=teacher["email"],
                            tag=teacher["tag"],
                            active=True
                        )
                        new_teacher.first_name = teacher["first_name"]
                        new_teacher.last_name = teacher["last_name"]
                        db.session.add(new_teacher)

                    db.session.commit()
                    flash(_('%(num)s Dozent(en) erfolgreich importiert', num=str(len(json_data))), 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(_('Konnte Dozenten nicht importieren, bitte neu einlesen: %(error)s', error=e), 'negative')
                return redirect(url_for('administration_teacher'))

            flash(_('Falscher Dateityp %(type)s, bitte nur Text oder json Dateien verwenden', type=mime), 'danger')
            return redirect(url_for('administration_teacher'))

    flash(_('Datei konnte nicht gelesen werden'), 'negative')
    return redirect(url_for('administration_teacher'))


@templated('internal/administration/teacher_overview_lang.html')
def administration_teacher_lang(id):
    lang = models.Language.query.get_or_404(id)
    form = forms.ResetLanguagePWs(lang)

    teacher = models.User.query \
        .join(models.Role, models.User.roles) \
        .join(models.Course, models.Role.course_id == models.Course.id) \
        .filter(models.Course.language_id == id) \
        .filter(models.Role.role == 'COURSE_TEACHER') \
        .distinct().all()

    # courses with assigned teachers
    unassigned_courses = TeacherManagement.unassigned_courses(id)

    if form.validate_on_submit():
        if len(teacher) == 0:
            flash(_('Es gibt keine Lehrbeauftragten für diese Sprache. Keine Emails wurden verschickt.'), 'info')
            return redirect(url_for('administration_teacher_lang', id=id))

        reset_pws = form.get_send_mail()
        # reset passwords for all teachers of the language
        if reset_pws:
            try:
                for t in teacher:
                    send_password_reset_to_user(t)
                flash(_('Emails mit Passwort Links wurden erfolgreich an alle Lehrbeauftragten verschickt.'), 'success')
            except (AssertionError, socket.error, ConnectionError) as e:
                flash(_('Emails zum Passwort Reset konnten nicht verschickt werden: %(error)s', error=e),
                      'negative')
        return redirect(url_for('administration_teacher_lang', id=id))

    return dict(language=lang, teacher=teacher, unassigned_courses=unassigned_courses, form=form)


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

        send_pw_mail = form.get_send_mail()
        if teacher is None:
            roles = []
            teacher_courses = form.get_courses()
            for course in teacher_courses:
                roles.append(models.Role(course=course, role=models.Role.COURSE_TEACHER))
            teacher = models.User(email=form.get_mail(),
                                  tag=form.get_tag(),
                                  active=True,
                                  roles=roles
                                  )
            teacher.first_name = form.get_first_name()
            teacher.last_name = form.get_last_name()
            try:
                db.session.add(teacher)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                flash(_('Es gab einen Fehler beim Hinzufügen des Lehrbeauftragten: %(error)s', error=e), 'negative')
                return dict(language=lang, form=form)

            if send_pw_mail:
                # send password reset mail, if writing to database was successfully
                try:
                    send_password_reset_to_user(teacher)
                except (AssertionError, socket.error, ConnectionError) as e:
                    flash(_('Eine Mail zum Passwort Reset konnte nicht verschickt werden: %(error)s', error=e),
                          'negative')

        return redirect(url_for('administration_teacher_lang', id=lang.id))

    # update course choices depending on the visited language page
    form.update_courses(id)
    return dict(language=lang, form=form)


@templated('internal/administration/edit_teacher.html')
def edit_teacher(id):
    teacher = models.User.query.get_or_404(id)
    form = forms.EditTeacherForm(teacher)

    if form.validate_on_submit():

        try:

            changes = False

            if teacher.first_name != form.first_name.data:
                teacher.first_name = form.first_name.data
                changes = True

            if teacher.last_name != form.last_name.data:
                teacher.last_name = form.last_name.data
                changes = True

            if teacher.email != form.mail.data:
                teacher.email = form.mail.data
                changes = True

            if teacher.tag != form.tag.data:
                teacher.tag = form.tag.data
                changes = True

            if changes:
                db.session.commit()
                flash(_('Der/die Lehrbeauftragte wurde aktualisiert (pers. Daten)'), 'success')
            else:
                flash(_('Es gab keine Änderung der persönlichen Daten.'), 'info')

            add_to_course = form.get_add_to_course()
            remove_from_course = form.get_remove_from_course()

            reset_password = form.get_send_mail()

            if remove_from_course:
                try:
                    success = TeacherManagement.remove_course(teacher, remove_from_course, teacher.id)
                    flash(
                        _('Der/die Lehrbeauftragte wurde vom Kurs %(name)s entfernt',
                          name=remove_from_course.full_name),
                        'success')
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(_('Der/die Lehrbeauftragte konnte nicht aus dem Kurs entfernt werden: %(error)s', error=e),
                          'negative')

            if add_to_course:
                try:
                    course_names = []
                    for course in add_to_course:
                        TeacherManagement.add_course(teacher, course)
                        course_names.append(course.full_name)
                    course_str = ', '.join(course_names)
                    flash(
                        _('Der/die Lehrbeauftragte wurde zu folgenden Kurs(en) {} hinzugefügt.'.format(course_str)),
                        'success'
                    )
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
                    flash(
                        _('Der/die Lehrbeauftragte konnte nicht für den Kurs eingetragen werden: %(error)s',
                          error=e),
                        'negative')

            if reset_password:
                try:
                    send_password_reset_to_user(teacher)
                    flash(
                        _('Eine Mail zum Passwort Zurücksetzen wurde an {} geschickt.'.format(teacher.full_name)),
                        'success')
                except (AssertionError, socket.error, ConnectionError) as e:
                    flash(_('Eine Mail zum Passwort Reset konnte nicht verschickt werden: %(error)s', error=e),
                          'negative')

            return redirect(url_for('edit_teacher', id=teacher.id))

        except Exception as e:
            db.session.rollback()
            flash(_('Der Bewerber konnte nicht aktualisiert werden: %(error)s', error=e), 'negative')
            return dict(form=form)

    form.populate()
    return dict(teacher=teacher, form=form)


@templated('internal/teacher.html')
def teacher():
    return dict(user=current_user)


@login_required
@templated('internal/administration/grade.html')
def grade(course_id):
    course = models.Course.query.get_or_404(course_id)

    exam_date = app.config['EXAM_DATE']

    return dict(course=course, exam_date=exam_date)


@login_required
@templated('internal/administration/edit_grade.html')
def edit_grade(course_id):
    course = models.Course.query.get_or_404(course_id)
    if not current_user.is_admin_or_superuser and not current_user.is_course_teacher(course):
        return redirect(url_for('internal'))
    # !!! course.course_list returns only active applicants (not on waiting list)
    # populate grade fields with applicant parameters
    grade_list = forms.create_grade_form(course.course_list, course_id)
    form = grade_list(request.form)

    exam_date = app.config['EXAM_DATE']

    if request.method == 'POST' and form.validate():
        try:
            changes = False
            for applicant in course.course_list:
                attendance = course.get_course_attendance(course.id, applicant.id)
                grade_field = getattr(form, f'grade_{applicant.id}', None)
                if grade_field and grade_field.data != attendance.grade:
                    attendance.grade = math.ceil(grade_field.data)
                    changes = True

                ects_field_name = f'ects_{applicant.id}'
                if ects_field_name in request.form:
                    submitted_ects = int(request.form[ects_field_name])
                    if submitted_ects != attendance.ects_points:
                        attendance.ects_points = submitted_ects
                        changes = True

            if changes:
                db.session.commit()
                flash('Noten wurden erfolgreich gespeichert!', 'success')
            else:
                flash('Es gab keine Änderungen zu speichern.', 'info')
        except Exception as e:
            db.session.rollback()
            flash(_('Es gab einen Fehler beim Speichern der Noten: %(error)s', error=e), 'negative')

        return redirect(url_for('edit_grade_view', course_id=course_id))

    return dict(course=course, form=form, exam_date=exam_date)


@login_required
@templated('internal/administration/edit_grade_view.html')
def edit_grade_view(course_id):
    course = models.Course.query.get_or_404(course_id)
    exam_date = app.config['EXAM_DATE']

    if request.method == 'POST':
        try:
            changes = False
            for applicant in course.course_list:
                attendance = course.get_course_attendance(course.id, applicant.id)
                view_field_name = f'view_{applicant.id}'
                submitted_view = request.form.get(view_field_name)
                if submitted_view is not None:
                    hide_view = (int(submitted_view) == 0)
                    if hide_view != attendance.hide_grade:
                        attendance.hide_grade = hide_view
                        changes = True
            if changes:
                db.session.commit()
                flash('Als bestanden eingetragene Noten wurden erfolgreich gespeichert!', 'success')
            else:
                flash('Es gab keine Änderungen zu speichern.', 'info')
        except Exception as e:
            db.session.rollback()
            flash(_('Es ist ein Fehler beim Abspeichern der Bestanden-Attribute aufgetreten: %(error)s', error=e),
                  'negative')

        return redirect(url_for('grade', course_id=course_id))

    return dict(course=course, exam_date=exam_date)


@login_required
@templated('internal/administration/import_grade.html')
def import_grade(course_id):
    course = models.Course.query.get_or_404(course_id)
    form = forms.ImportGradeForm()

    if form.validate_on_submit():
        try:
            file = form.file.data

            # create an in-memory copy of the file, so the original uploaded file stays untouched
            # during the grade import process (prevent file corruption)
            file_copy = io.BytesIO(file.read())
            file.seek(0)  # Reset file pointer to beginning

            # read the grades from the copied xlsx file
            n_success = TeacherManagement.import_grades(file_copy, course)

            # save file to database: first add the db entry to map to the file
            suffix = file.filename.split(".")[
                -1]  # only '.xlsx' files pass the form validation (.xls not compatible withopenpyxl)
            file_increment = len(course.grade_sheets) + 1
            course_name = course.full_name.replace(" ", "_").replace("/", "_")
            filename = course_name + "_version" + str(file_increment) + "." + suffix

            # in case there have been file deletions, a not used filename is chosen
            while os.path.exists(os.path.join(app.config['FILE_DIR'], filename)):
                file_increment += 1
                filename = course_name + "_version" + str(file_increment) + "." + suffix

            file_entry = models.GradeSheets(
                course_id=course.id,
                user_id=current_user.id,
                filename=filename
            )
            db.session.add(file_entry)

            # now save the file to the docker file volume
            file.save(file_entry.dir)

            db.session.commit()
            if n_success < 1:
                flash(
                    "<strong>Notenimport</strong><br>{} von {} Noten erfolgreich importiert.<br><strong>Datei erfolgreich gespeichert</strong>".format(
                        n_success, len(course.course_list)), "warning")
            else:
                flash(
                    "<strong>Notenimport</strong><br>{} von {} Noten erfolgreich importiert.<br><strong>Datei erfolgreich gespeichert</strong>".format(
                        n_success, len(course.course_list)), "success")
            return redirect(url_for('grade', course_id=course.id))
        except Exception as e:
            db.session.rollback()
            flash(_('Noten-Upload fehlgeschlagen: %(error)s', error=e), 'negative')

    return dict(form=form, course=course)


@login_required
def download_sheet(file_id):
    file = models.GradeSheets.query.get_or_404(file_id)

    if not os.path.exists(file.dir):
        flash(_('Die Datei existiert nicht oder wurde entfernt.'), 'negative')
        return redirect(url_for('grade', course_id=file.course_id))

    try:
        return send_from_directory(
            directory=app.config['FILE_DIR'],
            filename=file.filename,
            as_attachment=True
        )
    except IOError as e:
        flash(_('Datei konnte nicht heruntergeladen werden: %(error)s', error=str(e)), 'negative')
        return redirect(url_for('grade', course_id=file.course_id))


@login_required
@templated('internal/administration/delete_grade_sheet.html')
def delete_sheet(file_id):
    file = models.GradeSheets.query.get_or_404(file_id)

    if not os.path.exists(file.dir):
        flash(_('Die Datei "{}" existiert nicht oder wurde entfernt.'.format(file.filename)), 'negative')
        return redirect(url_for('grade', course_id=file.course_id))

    if request.method == 'POST':
        try:
            os.remove(file.dir)  # remove file from file system
            db.session.delete(file)  # remove file entry from database
            db.session.commit()
            flash(_('Datei "{}" erfolgreich gelöscht.'.format(file.filename)), 'success')
        except Exception as e:
            db.session.rollback()
            flash(_('Datei "{}" konnte nicht gelöscht werden: %(error)s'.format(file.filename), error=e), 'negative')
        return redirect(url_for('grade', course_id=file.course_id))

    return dict(file=file)


@login_required
def download_template(course_id):
    course = models.Course.query.get_or_404(course_id)
    if course.language.import_format_id:
        # specific, language dependent format
        import_export_name = course.language.import_format.name
    else:
        # default format
        import_export_name = app.config['DEFAULT_TEMPLATE_NAME']

    # check spanish template config
    if course.language.name == 'Spanisch' and course.level and not is_valid_float(course.level[-1]):
        import_export_name = 'Spanisch'

    export_format = models.ExportFormat.query.filter(models.ExportFormat.name == import_export_name).first()
    if export_format:
        return export_course_list(
            courses=[course],
            format=export_format
        )

    flash(
        _('Fehler: Es konnte kein passendes Exportformat gefunden werden. Bitte manuell unter Spalte Daten -> "Export" herunterladen. :/'),
        'negative')


@templated('internal/administration/attendances.html')
def attendances(id, course_id):
    teacher_db = models.User.query.get_or_404(id)
    course = models.Course.query.get_or_404(course_id)

    weeks = app.config['WEEKS']
    # weeks = [i for i in range(week_num)]
    return dict(teacher=teacher_db, course=course, weeks=int(weeks))


@templated('internal/administration/edit_attendances.html')
def edit_attendances(id, course_id, class_id):
    teacher_db = models.User.query.get_or_404(id)
    course = models.Course.query.get_or_404(course_id)

    return dict(teacher=teacher_db, course=course, class_id=class_id)


@templated('internal/administration/teacher_void.html')
def teacher_void():
    if current_user.is_teacher:
        return redirect(url_for('teacher'))

    all_users = models.User.query.all()

    # Filter users who do not have COURSE_TEACHER or SUPERUSER roles
    users_without_roles = [
        user for user in all_users
        if (
               not any(role.role == models.Role.COURSE_TEACHER for role in user.roles) and
               any(role.role == models.Role.COURSE_ADMIN for role in user.roles)
           ) or (
               not any(
                   role.role in [models.Role.COURSE_TEACHER, models.Role.COURSE_ADMIN, models.Role.SUPERUSER] for role
                   in user.roles)
           )
    ]

    return dict(users=users_without_roles)
