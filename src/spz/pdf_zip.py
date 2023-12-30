# -*- coding: utf-8 -*-

from zipfile import ZipFile
from tempfile import NamedTemporaryFile

from flask_login import login_required
from flask import make_response


class PdfZipWriter:
    mimetype = 'application/zip'
    extension = 'zip'

    def __init__(self):
        self.tempfile = NamedTemporaryFile()
        self.zip = ZipFile(self.tempfile, 'w')

    def write_to_zip(self, pdf_file, file_name):
        self.zip.writestr("{}.pdf".format(file_name), pdf_file)

    def get_data(self):
        self.zip.close()
        self.tempfile.seek(0)
        return self.tempfile.read()


@login_required
def html_response(file, file_name):
    resp = make_response(file.get_data())
    resp.headers['Content-Disposition'] = 'attachment; filename="{0}.{1}"'.format(file_name,
                                                                                  PdfZipWriter.extension)
    resp.mimetype = PdfZipWriter.mimetype
    return resp
