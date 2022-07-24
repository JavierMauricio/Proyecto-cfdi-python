#!/usr/bin/env python
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTIBILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.

import base64
import datetime
import os
import re
import subprocess
import time
from uuid import UUID
from urllib import request
from xml.etree import ElementTree as ET
from dateutil import parser

from .db import connect
from .portal_sat import PortalSAT
from settings import (
    log,
    NAME_CER,
    PATH_OPENSSL,
    TRY_COUNT,
)


def _call(args):
    return subprocess.check_output(args, shell=True).decode()


def get_status_sat(data):
    webservice = 'https://consultaqr.facturaelectronica.sat.gob.mx/consultacfdiservice.svc'
    soap = """<?xml version="1.0" encoding="UTF-8"?>
    <soap:Envelope
        xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema"
        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
        <soap:Header/>
        <soap:Body>
        <Consulta xmlns="http://tempuri.org/">
            <expresionImpresa>
                ?re={emisor_rfc}&amp;rr={receptor_rfc}&amp;tt={total}&amp;id={uuid}
            </expresionImpresa>
        </Consulta>
        </soap:Body>
    </soap:Envelope>"""
    data = soap.format(**data).encode('utf-8')
    headers = {
        'SOAPAction': '"http://tempuri.org/IConsultaCFDIService/Consulta"',
        'Content-length': str(len(data)),
        'Content-type': 'text/xml; charset="UTF-8"'
    }
    req = request.Request(url=webservice, data=data, method='POST')
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with request.urlopen(req, timeout=5) as f:
            response = f.read().decode('utf-8')
        result = re.search("(?s)(?<=Estado>).+?(?=</a:)", response).group()
        return result
    except Exception as e:
        log.error(str(e))
        return ''


def sat_download(conectar=True, **opt):
    error = 'No se pudo conectar al SAT, en el intento {}'
    for i in range(TRY_COUNT):
        sat = PortalSAT(opt['rfc'], opt['folder'], opt['sin_subdirectorios'])
        sat.only_search = opt['sin_descargar']

        if opt['directorio_fiel']:
            if sat.login_fiel(opt['directorio_fiel']):
                time.sleep(1)
                break
        else:
            if sat.login(opt['ciec'], conectar):
                time.sleep(1)
                break
            else:
                msg = error.format(i + 1)
                log.debug(msg)
                time.sleep(1)
                if sat.not_network:
                    log.error(sat.error)
                    return

    if not sat.is_connect:
        sat.logout()
        log.error(sat.error)
        return

    del opt['ciec']
    del opt['folder']
    del opt['sin_descargar']

    if conectar:
        connect()

    sat.search(opt)
    sat.logout()

    return


def get_home_user():
    return os.path.expanduser('~')


def today(arg=''):
    t = datetime.datetime.now()
    if arg == 'd':
        return t.day
    elif arg == 'm':
        return t.month
    elif arg == 'y':
        return t.year
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


def join(*paths):
    return os.path.join(*paths)


def validate_date(year=0, month=0, day=0, date_str=''):
    msg = ''
    try:
        if date_str:
            parts = date_str.split('/')
            if len(parts) != 3:
                parts = date_str.split('-')
            if len(parts) != 3:
                return 'Fecha inválida'
            day = int(parts[0])
            month = int(parts[1])
            if len(parts[2]) == 2:
                year = int('20' + parts[2])
            else:
                year = int(parts[2])
        d = datetime.datetime(year, month, day, 0, 0, 0)
        return d
    except ValueError:
        msg = 'Fecha de búsqueda inválida'
        return msg

def validate_folder(path):
    msg = ''
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except PermissionError:
            msg = 'No se pudo crear el directorio destino'
            return msg
    if not os.access(path, os.W_OK):
        msg = 'No tienes derecho de escritura en el directorio destino'
    return msg


def _save(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(data)
    return


def _get_cer_serie(path_cer, path_serie):
    args = '"{}" x509 -inform DER -in {} -noout -serial'.format(
        PATH_OPENSSL, path_cer)
    try:
        serie = _call(args)
        serie = serie.split('=')[1].split('\n')[0][1::2]
        _save(path_serie, serie)
        return serie
    except Exception as e:
        log.error(e)
        return ''


def _get_cer_rfc(path_cer, path_rfc):
    args = '"{}" x509 -inform DER -in {} -noout -subject'.format(
        PATH_OPENSSL, path_cer)
    try:
        rfc = _call(args)
        rfc = rfc.split('=')[7].split(',')[0].strip()
        _save(path_rfc, rfc)
        return rfc
    except Exception as e:
        log.error(e)
        return ''


def _get_cer_fert(path_cer, path_fert):
    args = '"{}" x509 -inform DER -in {} -noout -enddate'.format(
        PATH_OPENSSL, path_cer)
    try:
        fert = _call(args)
        fert = parser.parse(fert.split('=')[1])
        fert = fert.strftime('%y%m%d%H%M%SZ')
        _save(path_fert, fert)
        return fert
    except Exception as e:
        log.error(e)
        return ''


def validate_folder_fiel(path):
    if not os.path.exists(path):
        msg = 'No se encontró el directorio'
        return msg

    if not os.access(path, os.R_OK):
        msg = 'No tienes derecho de lectura en el directorio'
        return msg

    path_cer = join(path, NAME_CER.format('cer'))
    path_pem = join(path, NAME_CER.format('pem'))
    path_serie = join(path, 'serie.txt')
    path_rfc = join(path, 'rfc.txt')
    path_fert = join(path, 'fert.txt')

    if not os.path.exists(path_cer):
        msg = 'No se encontró el archivo CER'
        return msg

    if not os.path.exists(path_serie):
        serie = _get_cer_serie(path_cer, path_serie)
        if not serie:
            msg = 'No se pudo obtener la serie de la FIEL'
            return msg

    if not os.path.exists(path_rfc):
        rfc = _get_cer_rfc(path_cer, path_rfc)
        if not rfc:
            msg = 'No se pudo obtener el RFC de la FIEL'
            return msg

    if not os.path.exists(path_fert):
        fert = _get_cer_fert(path_cer, path_fert)
        if not fert:
            msg = 'No se pudo obtener la fecha de la FIEL'
            return msg

    if not os.path.exists(path_pem):
        msg = 'No se encontró el archivo PEM'
        return msg

    return ''


def validate_rfc(value):
    msg = ''
    if len(value) < 12:
        msg = 'Longitud inválida del RFC'
        return msg
    l = 4
    if len(value)==12:
        l = 3
    s = value[0:l]
    r = re.match('[A-ZÑ&]{%s}' % l, s)
    msg = 'Caracteres inválidos al {} del RFC'
    if not r:
        return msg.format('inicio')
    s = value[-3:]
    r = re.match('[A-Z0-9]{3}', s)
    if not r:
        return msg.format('final')
    s = value[l:l+6]
    r = re.match('[0-9]{6}', s)
    msg = 'Fecha inválida en el RFC'
    if not r:
        return msg
    try:
        datetime.datetime.strptime(s, '%y%m%d')
        return ''
    except:
        return msg


def get_years():
    start = 2011
    n = datetime.datetime.now()
    return tuple(map(str, range(start, n.year + 1)))


def get_months():
    return ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')


def get_now():
    n = datetime.datetime.now()
    return n


def get_month():
    n = datetime.datetime.now()
    return n.month


def get_first_day():
    n = datetime.datetime.now()
    return datetime.datetime(n.year, 1, 1, 0, 0, 0)


def get_range_dates():
    return (datetime.datetime(2011,1,1,0,0,0), datetime.datetime.now())


def get_ciec(ciec):
    return base64.urlsafe_b64decode(base64.b64decode(ciec)).decode()


def get_datetime(date):
    date = datetime.datetime.combine(date, datetime.datetime.min.time())
    return date


def add_days(date, days):
    date += datetime.timedelta(days=days)
    return date


def validate_uuid(value):
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def get_name(path, template):
    PRE = {
        '2.0': '{http://www.sat.gob.mx/cfd/2}',
        '2.2': '{http://www.sat.gob.mx/cfd/2}',
        '3.0': '{http://www.sat.gob.mx/cfd/3}',
        '3.2': '{http://www.sat.gob.mx/cfd/3}',
        'TIMBRE': '{http://www.sat.gob.mx/TimbreFiscalDigital}',
        'NOM1.1': '{http://www.sat.gob.mx/nomina}',
        'NOM1.2': '{http://www.sat.gob.mx/nomina12}',
        'IMP_LOCAL': '{http://www.sat.gob.mx/implocal}',
        'IEDU': '{http://www.sat.gob.mx/iedu}',
        'DONATARIA': '{http://www.sat.gob.mx/donat}',
        'LEYENDAS': '{http://www.sat.gob.mx/leyendasFiscales}',
    }

    try:
        xml = ET.parse(path).getroot()
    except Exception as e:
        msg = 'Error al parsear: {}'.format(path)
        return False, msg

    data = xml.attrib.copy()
    pre = PRE[data['version']]
    del data['sello']
    del data['certificado']

    data['serie'] = data.get('serie', '')
    data['folio'] = int(data.get('folio', 0))
    data['fecha'] = data['fecha'].partition('T')[0]

    node = xml.find('{}Emisor'.format(pre))
    data['emisor'] = node.attrib.get('nombre', '')
    data['emisor_rfc'] = node.attrib['rfc']

    node = xml.find('{}Receptor'.format(pre))
    data['receptor'] = node.attrib.get('nombre', '')
    data['receptor_rfc'] = node.attrib['rfc']

    node = xml.find('{}Complemento/{}TimbreFiscalDigital'.format(
        pre, PRE['TIMBRE']))
    data.update(node.attrib.copy())

    pre_nom = PRE['NOM1.1']
    node = xml.find('{}Complemento/{}Nomina'.format(pre, pre_nom))
    if node is None:
        pre_nom = PRE['NOM1.2']
        node = xml.find('{}Complemento/{}Nomina'.format(pre, pre_nom))
    if not node is None:
        data.update(node.attrib.copy())
        node = node.find('{}Receptor'.format(pre_nom))
        data.update(node.attrib.copy())
        data['NumEmpleado'] = int(data.get('NumEmpleado', 0))

    name = template.format(**data)
    char = (' ', "'", ',', '.', '-', '/')
    for c in char:
        name = name.replace(c, '_')
    return True, '{}.xml'.format(name)


def file_rename(source, new_name):
    path, _ = os.path.split(source)
    new_path = os.path.join(path, new_name)
    try:
        os.rename(source, new_path)
        return True
    except:
        return False


def get_files(path):
    paths = []
    pattern = re.compile('\.xml', re.IGNORECASE)
    cwd = os.getcwd()
    for folder, _, files in os.walk(path):
        paths += [os.path.join(cwd, folder, f) for f in files if pattern.search(f)]
    return tuple(paths)

