#!/usr/bin/env python

import sys
import os
import logbook
from logbook import Logger, StreamHandler, RotatingFileHandler
logbook.set_datetime_format("local")

from conf import DB, DEBUG


PATH_PROYECT = os.path.dirname(__file__)

DB = DB
#~ Establece la ruta al archivo LOG de registros
LOG_PATH = 'cfdi.log'
LOG_NAME = 'CFDI'
LOG_LEVEL = 'INFO'


format_string = '[{record.time:%d-%b-%Y %H:%M:%S}] ' \
    '{record.level_name}: ' \
    '{record.channel}: ' \
    '{record.message}'
RotatingFileHandler(
    LOG_PATH,
    backup_count=10,
    max_size=1073741824,
    level=LOG_LEVEL,
    format_string=format_string).push_application()

if DEBUG:
    LOG_LEVEL = 'DEBUG'

StreamHandler(
    sys.stdout,
    level=LOG_LEVEL,
    format_string=format_string).push_application()

log = Logger(LOG_NAME)

#~ Aumenta el tiempo (segundos) de espera, solo si tienes una conexión muy lenta o inestable
TIMEOUT = 120

#~ Cantidad de veces que se intenta en:
#~ - Identificarse en el SAT
#~ - Descargar un CFDI si hay timeout
#~ - Descargar faltantes de la lista obtenida al buscar
TRY_COUNT = 3

#~ Ruta al ejecutable pdftotext, necesario para extraer la fecha de cancelación
#~ de los documentos emitidos
PDF_TO_TEXT = 'pdftotext'

WEBSITE = 'http://rlsistemas.com.mx'
W_DONATE = ''
W_FORUM = ''

HEADERS = {'Auth-Token': '', 'content-type': 'application/json'}
base = ''
if DEBUG:
    base = 'http://localhost:8000/{}'
URL = {
    'RESOLVE': base.format('resolveCaptcha'),
}

# Pon en False si tienes problemas con los certificados de la página del SAT
VERIFY_CERT = True

# Es el nombre como se buscará la FIEL en el directorio pasado, argumento -df
NAME_CER = 'fiel.{}'

OS = sys.platform
PATH_OPENSSL = 'openssl'
if 'win' in OS:
    PDF_TO_TEXT = 'pdftotext.exe'
    PATH_OPENSSL = os.path.join(PATH_PROYECT, 'bin', 'openssl.exe')
