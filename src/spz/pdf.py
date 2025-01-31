# -*- coding: utf-8 -*-

"""Helper functions for pdf-generator.
"""

from datetime import datetime, timezone
import pytz
import fpdf
import os

from flask import make_response
from flask_login import login_required

from spz import app, models
from spz.pdf_zip import PdfZipWriter, html_response


class SPZPDF(fpdf.FPDF):
    """Base class used for ALL PDF generators here."""

    def __init__(self, orientation='L'):  # orientation: L=Landscape, P=Portrait
        super(SPZPDF, self).__init__(orientation=orientation, unit='mm', format='A4', font_cache_dir='/tmp')
        self.add_font('DejaVu', '', '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf', uni=True)
        self.add_font('DejaVu', 'B', '/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf', uni=True)

    def font_normal(self, size):
        """Set font to a normal one (no bold/italic).

           :param size: desired font size
        """
        self.set_font('DejaVu', '', size)

    def font_bold(self, size):
        """Set font to a bold one (no italic).

           :param size: desired font size
        """
        self.set_font('DejaVu', 'B', size)

    def gen_final_data(self):
        """Get final byte string data for PDF."""
        return self.output('', 'S')

    def gen_response(self, filename):
        """Generate HTTP response that download this PDF.

           :param filename: filename of the downloaded file, w/o '.pdf' extension
        """
        resp = make_response(self.gen_final_data())
        resp.headers['Content-Disposition'] = 'attachment; filename="{0}.pdf"'.format(filename)
        resp.mimetype = 'application/pdf'
        return resp


class TablePDF(SPZPDF):
    def header(self):
        self.font_normal(8)
        self.cell(0, 5, 'Karlsruher Institut für Technologie (KIT)', 0, 0)
        self.cell(0, 5, app.config['SEMESTER_NAME'], 0, 1, 'R')
        self.font_bold(10)
        self.cell(0, 5, 'Sprachenzentrum', 0)

    def get_column_size(self):
        return self.column_size

    def get_header_texts(self):
        return self.header_texts


class CourseGenerator(TablePDF):
    column_size = [7, 40, 40, 20, 70, 40, 15, 15, 15, 15]
    header_texts = ["Nr.", "Nachname", "Vorname", "Matr.", "E-Mail", "Telefon", "Tln.", "Prf.", "Note", "Prozent"]

    def header(self):
        super(CourseGenerator, self).header()
        self.cell(0, 5, 'Kursliste', 0, 0, 'R')
        self.ln()

    def footer(self):
        self.set_y(-20)
        self.font_normal(10)
        self.cell(
            0,
            7,
            'Datum _________________ Unterschrift ____________________________________',
            0,
            1,
            'R'
        )
        self.font_normal(6)
        self.cell(
            0,
            5,
            'Personen, die nicht auf der Liste stehen, '
            'haben nicht bezahlt und sind nicht zur Kursteilnahme berechtigt. '
            'Dementsprechend können Sie auch keine Teilnahme- oder Prüfungsscheine erhalten.',
            0,
            1,
            'C'
        )
        self.cell(
            0,
            5,
            'Nach Kursende bitte abhaken, ob der Teilnehmer regelmäßig anwesend war, '
            'ob er die Abschlussprüfung bestanden hat und dann die unterschriebene Liste wieder zurückgeben. Danke!',
            0,
            1,
            'C'
        )


class PresenceGenerator(TablePDF):
    column_size = [7, 40, 40, 20, 80, 6]
    header_texts = ["Nr.", "Nachname", "Vorname", "Matr.", "E-Mail", ""]

    def __init__(self, course=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course

    def header(self):
        super(PresenceGenerator, self).header()
        self.cell(0, 5, 'Anwesenheitsliste', 0, 0, 'R')
        self.ln()

    def footer(self):
        self.set_y(-10)
        self.font_normal(8)

        # Center-aligned text
        center_text = 'Diese Liste bildet lediglich eine Hilfe im Unterricht und verbleibt beim Dozenten.'

        # get the current time in the german timezone
        utc_now = datetime.now(timezone.utc)
        target_timezone = pytz.timezone("Europe/Berlin")

        if self.course == None:
            local_time = utc_now.astimezone(target_timezone)
            signup_signoff_str = 'Stand'
        else:
            # find applicant last registering
            last_registered = self.course.last_registered_at
            # check most recent action (signoff or signup)
            if last_registered and last_registered > self.course.last_signoff_at:
                local_time = last_registered.astimezone(target_timezone)
                signup_signoff_str = 'Letzte Anmeldung'
            else:
                local_time = self.course.last_signoff_at.astimezone(target_timezone)
                signup_signoff_str = 'Letzte Abmeldung'

        date_str = local_time.strftime('%d.%m.%Y %H:%M')
        date_text_width = self.get_string_width(f'{signup_signoff_str}: {date_str}')

        # Define the margin for spacing the center text properly
        self.multi_cell(self.w - date_text_width, 5, center_text, 0, 'C', 0)

        # Move to the right for the date and time text
        self.set_xy(self.w - date_text_width, -11)
        self.cell(0, 5, f'{signup_signoff_str}: {date_str}', 0, 0, 'R')


class BillGenerator(SPZPDF):
    def header(this):
        this.zwischenraum = 21
        this.teiler = ''
        this.rahmen = 0
        this.breite = 128
        now = datetime.now()
        if now.month < 3:
            semester = 'Wintersemester {0}/{1}'.format(now.year - 1, now.year)
        elif now.month < 9:
            semester = 'Sommersemester {0}'.format(now.year)
        else:
            semester = 'Wintersemester {0}/{1}'.format(now.year, now.year + 1)
        this.font_normal(8)
        this.cell(80, 5, 'Karlsruher Institut für Technologie (KIT)', 0, 0)
        this.cell(48, 5, semester, 0, 0, 'R')
        this.cell(this.zwischenraum, 5, this.teiler, this.rahmen, 0, 'C')
        this.cell(80, 5, 'Karlsruher Institut für Technologie (KIT)', 0, 0)
        this.cell(48, 5, semester, 0, 1, 'R')
        this.font_bold(8)
        this.cell(80, 5, 'Sprachenzentrum', 0, 0)
        this.font_normal(8)
        this.cell(48, 5, datetime.now().strftime("%d.%m.%Y"), 0, 0, 'R')
        this.cell(this.zwischenraum, 5, this.teiler, this.rahmen, 0, 'C')
        this.font_bold(8)
        this.cell(80, 5, 'Sprachenzentrum', 0, 0)
        this.font_normal(8)
        this.cell(48, 5, datetime.now().strftime("%d.%m.%Y"), 0, 1, 'R')

    def footer(this):
        this.set_y(-15)
        this.font_normal(8)
        this.cell(
            this.breite,
            4,
            'Diese Quittung wurde maschinell ausgestellt und ist ohne Unterschrift gültig.',
            0,
            0,
            'C'
        )
        this.cell(this.zwischenraum, 4, this.teiler, this.rahmen, 0, 'C')
        this.cell(
            this.breite,
            4,
            'Diese Quittung wurde maschinell ausgestellt und ist ohne Unterschrift gültig.',
            0,
            1,
            'C'
        )
        this.cell(this.breite, 4, 'Exemplar für den Teilnehmer.', 0, 0, 'C')
        this.cell(this.zwischenraum, 4, this.teiler, this.rahmen, 0, 'C')
        this.cell(this.breite, 4, 'Exemplar für das Sprachenzentrum.', 0, 1, 'C')


def list_presence(pdflist, course):
    column = pdflist.get_column_size()
    header = pdflist.get_header_texts()

    def maybe(x):
        return x if x else ''

    active_no_debt = course.course_list
    active_no_debt.sort()

    pdflist.add_page()

    pdflist.font_bold(14)
    pdflist.cell(0, 10, course.full_name, 0, 1, 'C')
    pdflist.font_normal(8)
    height = 6

    idx = 1
    for c, h in zip(column, header):
        pdflist.cell(c, height, h, 1)
    for i in range(13):
        pdflist.cell(column[-1], height, '', 1)
    pdflist.ln()
    for applicant in active_no_debt:
        content = [idx, applicant.last_name, applicant.first_name, maybe(applicant.tag), applicant.mail, '']
        for c, co in zip(column, content):
            pdflist.cell(c, height, str(co), 1)
        for i in range(13):
            pdflist.cell(column[-1], height, '', 1)
        pdflist.ln()

        idx += 1
    return


@login_required
def print_course_presence(course_id):
    course = models.Course.query.get_or_404(course_id)
    pdflist = PresenceGenerator(course)
    list_presence(pdflist, course)

    return pdflist.gen_response(course.full_name)


@login_required
def print_language_presence_zip(language_id):
    language = models.Language.query.get_or_404(language_id)
    zip_writer = PdfZipWriter()
    for course in language.courses:
        pdflist = PresenceGenerator(course)
        list_presence(pdflist, course)
        zip_writer.write_to_zip(pdflist.gen_final_data(), course.full_name)

    return html_response(zip_writer, language.name)

@login_required
def print_language_presence(language_id):
    language = models.Language.query.get_or_404(language_id)
    pdflist = PresenceGenerator()
    for course in language.courses:
        list_presence(pdflist, course)

    return pdflist.gen_response(language.name)


def list_course(pdflist, course):
    column = pdflist.get_column_size()
    header = pdflist.get_header_texts()

    def maybe(x):
        return x if x else ''

    active_no_debt = course.course_list
    active_no_debt.sort()

    pdflist.add_page()
    course_str = '{0}'.format(course.full_name)
    pdflist.font_bold(14)
    pdflist.cell(0, 10, course_str, 0, 1, 'C')

    pdflist.font_normal(8)
    height = 6

    idx = 1
    for c, h in zip(column, header):
        pdflist.cell(c, height, h, 1)
    pdflist.ln()
    for applicant in active_no_debt:
        content = [
            idx,
            applicant.last_name,
            applicant.first_name,
            maybe(applicant.tag),
            applicant.mail,
            applicant.phone,
            "",
            "",
            "",
            ""
        ]
        for c, co in zip(column, content):
            pdflist.cell(c, height, '{0}'.format(co), 1)
        pdflist.ln()
        idx += 1


@login_required
def print_course(course_id):
    pdflist = CourseGenerator()
    course = models.Course.query.get_or_404(course_id)
    list_course(pdflist, course)

    return pdflist.gen_response(course.full_name)


@login_required
def print_language(language_id):
    language = models.Language.query.get_or_404(language_id)
    pdflist = CourseGenerator('L')
    for course in language.courses:
        list_course(pdflist, course)

    return pdflist.gen_response(language.name)


@login_required
def print_bill(applicant_id, course_id):
    attendance = models.Attendance.query.get_or_404((applicant_id, course_id))

    bill = BillGenerator()
    bill.add_page()
    title = 'Quittung'
    applicant_str = '{0} {1}'.format(attendance.applicant.first_name, attendance.applicant.last_name)
    tag_str = 'Matrikelnummer {0}'.format(attendance.applicant.tag) if attendance.applicant.tag else ''
    now = datetime.now()
    str1 = 'für die Teilnahme am Kurs:'
    course_str = attendance.course.full_name
    amount_str = '{0} Euro'.format(attendance.amountpaid)
    str2 = 'bezahlt.'
    str3 = 'Stempel'
    code = 'A{0}C{1}'.format(applicant_id, course_id)
    bill.cell(bill.breite, 6, code, 0, 0, 'R')
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, code, 0, 1, 'R')
    bill.ln(20)
    bill.font_bold(14)
    bill.cell(bill.breite, 8, title, 0, 0, 'C')
    bill.cell(bill.zwischenraum, 8, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 8, title, 0, 1, 'C')
    bill.ln(20)

    bill.font_normal(10)
    bill.cell(bill.breite, 6, applicant_str, 0, 0)
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, applicant_str, 0, 1)
    bill.cell(bill.breite, 6, tag_str, 0, 0)
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, tag_str, 0, 1)
    bill.cell(bill.breite, 6, 'hat am {0}'.format(now.strftime("%d.%m.%Y")), 0, 0)
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, 'hat am {0}'.format(now.strftime("%d.%m.%Y")), 0, 1)
    bill.cell(bill.breite, 6, str1, 0, 0)
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, str1, 0, 1)
    bill.font_bold(10)
    bill.cell(bill.breite, 6, course_str, 0, 0, 'C')
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, course_str, 0, 1, 'C')
    bill.cell(bill.breite, 6, amount_str, 0, 0, 'C')
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, amount_str, 0, 1, 'C')
    bill.font_normal(10)
    bill.cell(bill.breite, 6, str2, 0, 0)
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, str2, 0, 1)

    bill.ln(30)
    bill.cell(bill.breite, 6, str3, 0, 0, 'C')
    bill.cell(bill.zwischenraum, 6, bill.teiler, bill.rahmen, 0, 'C')
    bill.cell(bill.breite, 6, str3, 0, 1, 'C')

    return bill.gen_response('Quittung {0}'.format(attendance.applicant.last_name))


class ParticipationCertGenerator(SPZPDF):
    def header(this):
        this.width = 40
        this.height = 10
        now = datetime.now()
        if now.month < 3:
            this.semester = 'Wintersemester {0}/{1}'.format(now.year - 1, now.year)
            this.weeks = 14
        elif now.month < 9:
            this.semester = 'Sommersemester {0}'.format(now.year)
            this.weeks = 13
        else:
            this.semester = 'Wintersemester {0}/{1}'.format(now.year, now.year + 1)
            this.weeks = 14
        this.weeks = 14
        this.set_font('Helvetica', '', size=36)
        path = os.path.join(os.getcwd(), 'spz/', 'static/img/kit-logo.png')
        this.image(path, x=15, y=16, w=40)
        this.text(x=160, y=30, txt='SpZ')
        this.set_font(size=10, style='B')
        this.text(x=160, y=37, txt='Sprachenzentrum')

    def gen_final_data(self):
        """Get final byte string data for PDF."""
        return self.output(dest='S')


@login_required
def generate_participation_cert(full_name, tag, course, ects, ger, date):
    if tag is None:
        tag = ""
    participation_cert = ParticipationCertGenerator('P')
    participation_cert.add_page()
    participation_cert.set_font('Helvetica', '', size=16)
    participation_cert.set_font(style="B" "U")
    participation_cert.text(x=45, y=55, txt="Teilnahmeschein")
    participation_cert.set_font(style="U", size=15)
    participation_cert.text(x=90, y=55, txt=" (keine ECTS-Berechtigung)")
    participation_cert.set_font(style='', size=13)
    participation_cert.set_y(65)
    participation_cert.set_x(15)
    participation_cert.cell(participation_cert.width, participation_cert.height, 'Frau/Herr', 0, 0)
    participation_cert.cell(200, participation_cert.height, full_name, 0, 1)
    participation_cert.set_x(15)
    participation_cert.cell(participation_cert.width, participation_cert.height, 'Matr.-Nr.', 0, 0)
    participation_cert.cell(200, participation_cert.height, str(tag), 0, 1)
    participation_cert.set_x(15)
    participation_cert.cell(participation_cert.width, 12, 'hat im', 0, 0)
    participation_cert.cell(200, participation_cert.height, participation_cert.semester, 0, 1)
    participation_cert.set_x(15)
    participation_cert.cell(participation_cert.width, participation_cert.height, 'am Sprachkurs', 0, 0)
    participation_cert.cell(200, participation_cert.height, course, 0, 1)
    participation_cert.set_x(55)
    participation_cert.cell(2, participation_cert.height, '( ', 0, 0)
    participation_cert.set_font(style='B')
    participation_cert.cell(7, participation_cert.height, str(participation_cert.weeks), 0, 0)
    participation_cert.set_font(style='')
    participation_cert.cell(25, participation_cert.height, 'Wochen zu', 0, 0)
    participation_cert.set_font(style='B')
    participation_cert.cell(3, participation_cert.height, str(ects), 0, 0)
    participation_cert.set_font(style='')
    participation_cert.cell(150, participation_cert.height, ' SWS) regelm\u00e4\u00DFig teilgenommen.', 0, 1)
    participation_cert.set_x(15)
    if ger is not None:
        participation_cert.cell(150, participation_cert.height, 'Dieser Kurs entspricht dem Niveau ' + ger
                            + ' des GER (Gem.Europ.Referenzrahmen)', 0, 1)
    participation_cert.set_x(15)
    participation_cert.cell(75, 30, 'Karlsruhe, den ' + str(date), 0, 0)
    participation_cert.cell(200, 30, '___________________________', 0, 2)
    participation_cert.set_font(size=10)
    participation_cert.cell(w=62, h=-20, txt='Unterschrift', align='C')

    return participation_cert.gen_final_data()
