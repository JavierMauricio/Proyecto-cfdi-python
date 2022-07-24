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
import calendar
import datetime
import os
import subprocess
import sys
import threading
from collections import deque
from copy import deepcopy
from html.parser import HTMLParser
from uuid import UUID
from xml.etree import ElementTree as ET

import requests
from requests import Session, exceptions, adapters

from .db import previous_download, update_date_download, save_search
from settings import (
    log,
    NAME_CER,
    OS,
    PATH_OPENSSL,
    TIMEOUT,
    TRY_COUNT,
    VERIFY_CERT,
)


class FormValues(HTMLParser):

    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag in ('input', 'select'):
            attrib = dict(attrs)
            if 'type' in attrib \
                and attrib['type'] == 'hidden' \
                and 'value' in attrib \
                and not 'hfInicialBool' in attrib['name']:
                self.values[attrib['name']] = attrib['value']


class FormLoginValues(HTMLParser):

    def __init__(self):
        super().__init__()
        self.values = {}

    def handle_starttag(self, tag, attrs):
        if tag == 'input':
            attrib = dict(attrs)
            try:
                self.values[attrib['id']] = attrib['value']
            except:
                pass


class ImageCaptcha(HTMLParser):

    def __init__(self):
        super().__init__()
        self.image = ''

    def handle_starttag(self, tag, attrs):
        attrib = dict(attrs)
        info = 'data:image/jpeg;base64,'
        if tag == 'img'and attrib['src'].startswith(info):
            self.image = attrib['src'][len(info):]


class Filters(object):

    def __init__(self, args):
        self.date_from = args['date_from']
        self.day = args.get('day', False)
        self.emitidas = args['emitidas']
        self.date_to = None
        if self.date_from:
            self.date_to = args.get('date_to', self._now()).replace(
                hour=23, minute=59, second=59, microsecond=0)
        self.uuid = str(args.get('uuid', ''))
        self.stop = False
        self.hour = False
        self.minute = False
        self._init_values(args)

    def __str__(self):
        if self.uuid:
            msg = 'Descargar por UUID'
        elif self.hour:
            msg = 'Descargar por HORA'
        elif self.day:
            msg = 'Descargar por DIA'
        else:
            msg = 'Descargar por MES'
        tipo = 'Recibidas'
        if self.emitidas:
            tipo = 'Emitidas'
        if self.uuid:
            return '{} - {} - {}'.format(msg, self.uuid, tipo)
        else:
            return '{} - {} - {} - {}'.format(msg, self.date_from, self.date_to, tipo)

    def _now(self):
        if self.day:
            n = self.date_from
        else:
            last_day = calendar.monthrange(
                self.date_from.year, self.date_from.month)[1]
            n = datetime.datetime(self.date_from.year, self.date_from.month, last_day)
        return n

    def _init_values(self, args):
        #~ print ('ARGS', args)
        status = '-1'
        type_cfdi = args.get('type_cfdi', '-1')
        center_filter = 'RdoFechas'
        if self.uuid:
            center_filter = 'RdoFolioFiscal'
        rfc_receptor = args.get('rfc_emisor', '')
        if self.emitidas:
            rfc_receptor = args.get('rfc_receptor', '')

        script_manager = 'ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$BtnBusqueda'
        self._post = {
            '__ASYNCPOST': 'true',
            '__EVENTTARGET': '',
            '__EVENTARGUMENT': '',
            '__LASTFOCUS': '',
            '__VIEWSTATEENCRYPTED': '',
            'ctl00$ScriptManager1': script_manager,
            'ctl00$MainContent$hfInicialBool': 'false',
            'ctl00$MainContent$BtnBusqueda': 'Buscar CFDI',
            'ctl00$MainContent$TxtUUID': self.uuid,
            'ctl00$MainContent$FiltroCentral': center_filter,
            'ctl00$MainContent$TxtRfcReceptor': rfc_receptor,
            'ctl00$MainContent$DdlEstadoComprobante': status,
            'ctl00$MainContent$ddlComplementos': type_cfdi,
        }
        return

    def get_post(self):
        start_hour = '0'
        start_minute = '0'
        start_second = '0'
        end_hour = '0'
        end_minute = '0'
        end_second = '0'

        if self.date_from:
            start_hour = str(self.date_from.hour)
            start_minute = str(self.date_from.minute)
            start_second = str(self.date_from.second)
            end_hour = str(self.date_to.hour)
            end_minute = str(self.date_to.minute)
            end_second = str(self.date_to.second)

        if self.emitidas:
            year1 = '0'
            year2 = '0'
            start = ''
            end = ''
            if self.date_from:
                year1 = str(self.date_from.year)
                year2 = str(self.date_to.year)
                start = self.date_from.strftime('%d/%m/%Y')
                end = self.date_to.strftime('%d/%m/%Y')
            data = {
                'ctl00$MainContent$hfInicial': year1,
                'ctl00$MainContent$CldFechaInicial2$Calendario_text': start,
                'ctl00$MainContent$CldFechaInicial2$DdlHora': start_hour,
                'ctl00$MainContent$CldFechaInicial2$DdlMinuto': start_minute,
                'ctl00$MainContent$CldFechaInicial2$DdlSegundo': start_second,
                'ctl00$MainContent$hfFinal': year2,
                'ctl00$MainContent$CldFechaFinal2$Calendario_text': end,
                'ctl00$MainContent$CldFechaFinal2$DdlHora': end_hour,
                'ctl00$MainContent$CldFechaFinal2$DdlMinuto': end_minute,
                'ctl00$MainContent$CldFechaFinal2$DdlSegundo': end_second,
            }
        else:
            year = '0'
            month = '0'
            if self.date_from:
                year = str(self.date_from.year)
                month = str(self.date_from.month)
            day = '00'
            if self.day:
                day = '{:02d}'.format(self.date_from.day)
            data = {
                'ctl00$MainContent$CldFecha$DdlAnio': year,
                'ctl00$MainContent$CldFecha$DdlMes': month,
                'ctl00$MainContent$CldFecha$DdlDia': day,
                'ctl00$MainContent$CldFecha$DdlHora': start_hour,
                'ctl00$MainContent$CldFecha$DdlMinuto': start_minute,
                'ctl00$MainContent$CldFecha$DdlSegundo': start_second,
                'ctl00$MainContent$CldFecha$DdlHoraFin': end_hour,
                'ctl00$MainContent$CldFecha$DdlMinutoFin': end_minute,
                'ctl00$MainContent$CldFecha$DdlSegundoFin': end_second,
            }
        self._post.update(data)
        return self._post


class Invoice(HTMLParser):
    START_PAGE = 'ContenedorDinamico'
    URL = 'https://portalcfdi.facturaelectronica.sat.gob.mx/'
    END_PAGE = 'ctl00_MainContent_pageNavPosition'
    LIMIT_RECORDS = 'ctl00_MainContent_PnlLimiteRegistros'
    NOT_RECORDS = 'ctl00_MainContent_PnlNoResultados'
    TEMPLATE_DATE = '%Y-%m-%dT%H:%M:%S'

    def __init__(self):
        super().__init__()
        self._is_div_page = False
        self._col = 0
        self._current_tag = ''
        self._last_link = ''
        self._last_link_pdf = ''
        self._last_uuid = ''
        self._last_status = ''
        self._last_date_cfdi = ''
        self._last_date_timbre = ''
        self._last_pac = ''
        self._last_total = ''
        self._last_type = ''
        self._last_date_cancel = ''
        self._last_emisor_rfc = ''
        self._last_emisor = ''
        self._last_receptor_rfc = ''
        self._last_receptor = ''
        self.invoices = []
        self.not_found = False
        self.limit = False

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag
        if tag == 'div':
            attrib = dict(attrs)
            if 'id' in attrib and attrib['id'] == self.NOT_RECORDS \
                and 'inline' in attrib['style']:
                self.not_found = True
            elif 'id' in attrib and attrib['id'] == self.LIMIT_RECORDS:
                self.limit = True
            elif 'id' in attrib and attrib['id'] == self.START_PAGE:
                self._is_div_page = True
            elif 'id' in attrib and attrib['id'] == self.END_PAGE:
                self._is_div_page = False
        elif self._is_div_page and tag == 'td':
            self._col +=1
        elif tag == 'img':
            attrib = dict(attrs)
            if 'class' in attrib and attrib['class'] == 'BtnDescarga' and \
                'name' in attrib and attrib['name'] == 'BtnDescarga':
                self._last_link = attrib['onclick'].split("'")[1]
            elif 'class' in attrib and attrib['class'] == 'BtnRecuperaAcuse':
                self._last_link_pdf = attrib['onclick'].split("'")[1]

    def handle_endtag(self, tag):
        if self._is_div_page and tag == 'tr':
            if self._last_uuid:
                url_xml = ''
                if self._last_link:
                    url_xml = '{}{}'.format(self.URL, self._last_link)
                url_pdf = ''
                if self._last_link_pdf:
                    url_pdf = '{}{}'.format(self.URL, self._last_link_pdf)

                date_cancel = None
                if self._last_date_cancel:
                    date_cancel = datetime.datetime.strptime(
                        self._last_date_cancel, self.TEMPLATE_DATE)
                invoice = (self._last_uuid,
                    {
                        'url': url_xml,
                        'acuse': url_pdf,
                        'estatus': self._last_status,
                        'date_cfdi': datetime.datetime.strptime(
                            self._last_date_cfdi, self.TEMPLATE_DATE),
                        'date_timbre': datetime.datetime.strptime(
                            self._last_date_timbre, self.TEMPLATE_DATE),
                        'date_cancel': date_cancel,
                        'rfc_pac': self._last_pac,
                        'total': float(self._last_total),
                        'tipo': self._last_type,
                        'emisor': self._last_emisor,
                        'rfc_emisor': self._last_emisor_rfc,
                        'receptor': self._last_receptor,
                        'rfc_receptor': self._last_receptor_rfc,
                    }
                )
                self.invoices.append(invoice)
            self._last_link = ''
            self._last_link_pdf = ''
            self._last_uuid = ''
            self._last_status = ''
            self._last_date_cancel = ''
            self._last_emisor_rfc = ''
            self._last_emisor = ''
            self._last_receptor_rfc = ''
            self._last_receptor = ''
            self._last_date_cfdi = ''
            self._last_date_timbre = ''
            self._last_pac = ''
            self._last_total = ''
            self._last_type = ''
            self._col = 0

    def handle_data(self, data):
        if self._is_div_page and self._current_tag == 'span':
            if self._col == 2:
                try:
                    UUID(data)
                    self._last_uuid = data
                except ValueError:
                    pass
            elif self._col == 3 and data.split():
                self._last_emisor_rfc = data.strip()
            elif self._col == 4 and data.split():
                self._last_emisor = data.strip()
            elif self._col == 5 and data.split():
                self._last_receptor_rfc = data.strip()
            elif self._col == 6 and data.split():
                self._last_receptor = data.strip()
            elif self._col == 7 and data.split():
                self._last_date_cfdi = data.strip()
            elif self._col == 8 and data.split():
                self._last_date_timbre = data.strip()
            elif self._col == 9 and data.split():
                self._last_pac = data.strip()
            elif self._col == 10 and data.split():
                self._last_total = data.strip().replace('$', '').replace(',', '')
            elif self._col == 11 and data.split():
                self._last_type = data.strip().lower()
            elif self._col == 12 and data.split():
                self._last_status = data.strip()
            elif self._col == 13 and data.split():
                self._last_date_cancel = data.strip()


class PortalSAT(object):
    URL_MAIN = 'https://portalcfdi.facturaelectronica.sat.gob.mx/'
    HOST = 'cfdiau.sat.gob.mx'
    BROWSER = 'Mozilla/5.0 (X11; Linux x86_64; rv:55.0) Gecko/20100101 Firefox/55.0'
    REFERER = 'https://cfdiau.sat.gob.mx/nidp/app/login?id=SATUPCFDiCon&sid=0&option=credential&sid=0'

    PORTAL = 'portalcfdi.facturaelectronica.sat.gob.mx'
    URL_LOGIN = 'https://{}/nidp/app/login'.format(HOST)
    #~ URL_LOGIN = 'https://{}/nidp/wsfed/ep'.format(HOST)
    URL_FORM = 'https://{}/nidp/app/login?sid=0&sid=0'.format(HOST)
    URL_PORTAL = 'https://portalcfdi.facturaelectronica.sat.gob.mx/'
    URL_CONTROL = 'https://cfdicontribuyentes.accesscontrol.windows.net/v2/wsfederation'
    URL_CONSULTA = URL_PORTAL + 'Consulta.aspx'
    URL_RECEPTOR = URL_PORTAL + 'ConsultaReceptor.aspx'
    URL_EMISOR = URL_PORTAL + 'ConsultaEmisor.aspx'
    URL_LOGOUT = URL_PORTAL + 'logout.aspx?salir=y'
    DIR_EMITIDAS = 'emitidas'
    DIR_RECIBIDAS = 'recibidas'

    def __init__(self, rfc, target, sin):
        self._rfc = rfc
        self.error = ''
        self.is_connect = False
        self.not_network = False
        self.only_search = False
        self.only_test = False
        self.sin_sub = sin
        self._init_values(target)

    def _init_values(self, target):
        self._folder = target
        if target and not self.sin_sub:
            self._folder = self._create_folders(target)
        self._emitidas = False
        self._current_year = datetime.datetime.now().year
        self._session = Session()
        a = adapters.HTTPAdapter(pool_connections=512, pool_maxsize=512, max_retries=5)
        self._session.mount('https://', a)
        return

    def _create_folders(self, target):
        folder = os.path.join(target, self._rfc)
        if not os.path.exists(folder):
            os.makedirs(folder)
        path = os.path.join(folder, self.DIR_EMITIDAS)
        if not os.path.exists(path):
            os.makedirs(path)
        path = os.path.join(folder, self.DIR_RECIBIDAS)
        if not os.path.exists(path):
            os.makedirs(path)
        return folder

    def _get_post_form_dates(self):
        post = {}
        post['__ASYNCPOST'] = 'true'
        post['__EVENTARGUMENT'] = ''
        post['__EVENTTARGET'] = 'ctl00$MainContent$RdoFechas'
        post['__LASTFOCUS'] = ''
        post['ctl00$MainContent$CldFecha$DdlAnio'] = str(self._current_year)
        post['ctl00$MainContent$CldFecha$DdlDia'] = '0'
        post['ctl00$MainContent$CldFecha$DdlHora'] = '0'
        post['ctl00$MainContent$CldFecha$DdlHoraFin'] = '23'
        post['ctl00$MainContent$CldFecha$DdlMes'] = '1'
        post['ctl00$MainContent$CldFecha$DdlMinuto'] = '0'
        post['ctl00$MainContent$CldFecha$DdlMinutoFin'] = '59'
        post['ctl00$MainContent$CldFecha$DdlSegundo'] = '0'
        post['ctl00$MainContent$CldFecha$DdlSegundoFin'] = '59'
        post['ctl00$MainContent$DdlEstadoComprobante'] = '-1'
        post['ctl00$MainContent$FiltroCentral'] = 'RdoFechas'
        post['ctl00$MainContent$TxtRfcReceptor'] = ''
        post['ctl00$MainContent$TxtUUID'] = ''
        post['ctl00$MainContent$ddlComplementos'] = '-1'
        post['ctl00$MainContent$hfInicialBool'] = 'true'
        post['ctl00$ScriptManager1'] = \
            'ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$RdoFechas'
        return post

    def _response(self, url, method='get', headers={}, data={}):
        #~ log.debug('URL: {}'.format(url))
        try:
            if method == 'get':
                result = self._session.get(url, timeout=TIMEOUT,
                    verify=VERIFY_CERT)
            else:
                result = self._session.post(url, data=data,
                    timeout=TIMEOUT, verify=VERIFY_CERT)
            msg = '{} {} {}'.format(result.status_code, method.upper(), url)
            log.debug(msg)
            return result.text
        except exceptions.Timeout:
            msg = 'Tiempo de espera agotado'
            self.not_network = True
            log.error(msg)
            self.error = msg
            return ''
        except exceptions.ConnectionError:
            msg = 'Revisa la conexión a Internet'
            self.not_network = True
            log.error(msg)
            self.error = msg
            return ''

    def _read_form(self, html, form=''):
        if form == 'login':
            parser = FormLoginValues()
        else:
            parser = FormValues()
        parser.feed(html)
        return parser.values

    def _get_headers(self, host, referer, ajax=False):
        user_agent = 'Mozilla/5.0 (X11; Linux x86_64; rv:49.0) Gecko/20100101 Firefox/49.0'
        acept = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'

        headers = {
            'Accept': acept,
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Host': host,
            'Referer': referer,
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': self.BROWSER,
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        if ajax:
            headers.update({
                'Cache-Control': 'no-cache',
                'X-MicrosoftAjax': 'Delta=true',
                'x-requested-with': 'XMLHttpRequest',
                'Pragma': 'no-cache',
            })
        return headers

    def _get_post_type_search(self, html):
        tipo_busqueda = 'RdoTipoBusquedaReceptor'
        if self._emitidas:
            tipo_busqueda = 'RdoTipoBusquedaEmisor'
        sm = 'ctl00$MainContent$UpnlBusqueda|ctl00$MainContent$BtnBusqueda'
        post = self._read_form(html)
        post['ctl00$MainContent$TipoBusqueda'] = tipo_busqueda
        post['__ASYNCPOST'] = 'true'
        post['__EVENTTARGET'] = ''
        post['__EVENTARGUMENT'] = ''
        post['ctl00$ScriptManager1'] = sm
        return post

    def _get_captcha(self, from_script):
        from .captcha import resolve

        URL_LOGIN = 'https://cfdiau.sat.gob.mx/nidp/wsfed/ep?id=SATUPCFDiCon&sid=0&option=credential&sid=0'
        REFERER = 'https://cfdiau.sat.gob.mx/nidp/wsfed_redir_cont_portalcfdi.jsp?wa=wsignin1.0&wtrealm={}'
        result = self._session.get(self.URL_MAIN)

        url_redirect = result.history[-1].headers['Location']
        self._session.headers['Host'] = self.HOST
        result = self._response(url_redirect)

        self._session.headers['User-Agent'] = self.BROWSER
        self._session.headers['Referer'] = REFERER.format(url_redirect)
        result = self._response(URL_LOGIN, 'post')

        url = 'https://cfdiau.sat.gob.mx/nidp/jcaptcha.jpg'
        result = self._session.get(url, timeout=TIMEOUT)

        return resolve(result.content, from_script)

    def login(self, ciec, from_script):
        HOST = 'cfdicontribuyentes.accesscontrol.windows.net'
        URL_CONTROL1 = 'https://cfdiau.sat.gob.mx/nidp/wsfed/ep?sid=0'
        ERROR = '¡Error de registro!'

        msg = 'Identificandose en el SAT'
        log.info(msg)

        captcha = self._get_captcha(from_script)
        if not captcha:
            return False

        data = {
            'option': 'credential',
            'Ecom_User_ID': self._rfc,
            'Ecom_Password': ciec,
            'submit': 'Enviar',
            'jcaptcha': captcha,
        }
        headers = self._get_headers(self.HOST, self.REFERER)
        response = self._response(self.URL_FORM, 'post', headers, data)

        if ERROR in response:
            msg = 'RFC o CIEC no validos o CAPTCHA erroneo'
            self.error = msg
            log.error(msg)
            return False

        if self.error:
            return False

        #~ data = self._read_form(self._response(self.URL_PORTAL, 'get'))
        data = self._read_form(self._response(URL_CONTROL1))

        # Access control
        self._session.headers['Host'] = HOST
        self._session.headers['Referer'] = URL_CONTROL1

        response = self._response(self.URL_CONTROL, 'post', data=data)
        data = self._read_form(response)

        # Inicio
        response = self._response(self.URL_PORTAL, 'post', data=data)
        data = self._get_post_type_search(response)
        headers = self._get_headers(self.HOST, self.URL_PORTAL)

        # Consulta
        response = self._response(self.URL_CONSULTA, 'post', headers, data)
        msg = 'Se ha identificado en el SAT'
        log.info(msg)
        self.is_connect = True
        return True

    def _get_data_cert(self, path_fiel, name):
        path = os.path.join(path_fiel, '{}.txt'.format(name))
        return open(path).read()

    def _get_token(self, path_fiel, co):
        path_pem = os.path.join(path_fiel, NAME_CER.format('pem'))
        path_co = os.path.join(path_fiel, 'tmp')
        with open(path_co, 'w', encoding='utf-8') as f:
            f.write(co)

        cmd = 'cat'
        if 'win' in OS:
            cmd = 'type'
        args = '{3} "{0}" | "{1}" dgst -sha1 -sign "{2}" | ' \
            '"{1}" enc -base64 -A'.format(path_co, PATH_OPENSSL, path_pem, cmd)

        firma = subprocess.check_output(args, shell=True).decode()
        firma = base64.b64encode(firma.encode('utf-8')).decode('utf-8')
        co = base64.b64encode(co.encode('utf-8')).decode('utf-8')
        data = '{}#{}'.format(co, firma).encode('utf-8')
        token = base64.b64encode(data).decode('utf-8')

        try:
            os.remove(path_co)
        except:
            pass

        return token

    def _make_data_form(self, path_fiel, values):
        rfc = self._get_data_cert(path_fiel, 'rfc')
        serie = self._get_data_cert(path_fiel, 'serie')
        fert = self._get_data_cert(path_fiel, 'fert')
        co = '{}|{}|{}'.format(values['tokenuuid'], rfc, serie)
        token = self._get_token(path_fiel, co)
        keys = ('credentialsRequired', 'guid', 'ks', 'urlApplet')
        data = {k: values[k] for k in keys}
        data['fert'] = fert
        data['token'] = token
        return data

    def login_fiel(self, path_fiel):
        HOST = 'cfdicontribuyentes.accesscontrol.windows.net'
        REFERER = 'https://cfdiau.sat.gob.mx/nidp/wsfed/ep?id=SATUPCFDiCon&sid=0&option=credential&sid=0'

        url_login = 'https://cfdiau.sat.gob.mx/nidp/app/login?id=SATx509Custom&sid=0&option=credential&sid=0'
        result = self._session.get(self.URL_MAIN)

        url_redirect = result.history[-1].headers['Location']
        self._session.headers['Host'] = self.HOST
        result = self._response(url_redirect)

        self._session.headers['User-Agent'] = self.BROWSER
        self._session.headers['Referer'] = REFERER.format(url_redirect)
        result = self._response(url_login, 'post')

        values = self._read_form(result, 'login')
        data = self._make_data_form(path_fiel, values)
        headers = self._get_headers(self.HOST, self.REFERER)
        self._session.headers.update(headers)
        result = self._response(url_login, 'post', data=data)
        data = self._read_form(result)

        # Access control
        self._session.headers['Host'] = HOST
        self._session.headers['Referer'] = self.REFERER
        response = self._response(self.URL_CONTROL, 'post', data=data)
        data = self._read_form(response)

        # Inicio
        response = self._response(self.URL_MAIN, 'post', data=data)
        data = self._get_post_type_search(response)
        headers = self._get_headers(self.HOST, self.URL_MAIN)

        # Consulta
        response = self._response(self.URL_CONSULTA, 'post', headers, data)
        msg = 'Se ha identificado en el SAT'
        log.info(msg)
        self.is_connect = True
        return True

    def _merge(self, list1, list2):
        result = list1.copy()
        result.update(list2)
        return result

    def _last_day(self, date):
        last_day = calendar.monthrange(date.year, date.month)[1]
        return datetime.datetime(date.year, date.month, last_day)

    def _get_dates(self, d1, d2):
        end = d2
        dates = []
        while True:
            d2 = self._last_day(d1)
            if d2 >= end:
                dates.append((d1, end))
                break
            dates.append((d1, d2))
            d1 = d2 + datetime.timedelta(days=1)
        return dates

    def _get_dates_recibidas(self, d1, d2):
        days = (d2 - d1).days + 1
        return [d1 + datetime.timedelta(days=d) for d in range(days)]

    def _time_delta(self, days):
        now = datetime.datetime.now()
        date_from = now.replace(
            hour=0, minute=0, second=0, microsecond=0) - datetime.timedelta(days=days)
        date_to = now.replace(hour=23, minute=59, second=59, microsecond=0)
        return date_from, date_to

    def _time_delta_recibidas(self, days):
        now = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return [now - datetime.timedelta(days=d) for d in range(days)]

    def _get_filters(self, args, emitidas):
        filters = []
        data = {}
        data['day'] = bool(args['dia'])
        data['uuid'] = ''
        if args['uuid']:
            data['uuid'] = str(args['uuid'])
        data['emitidas'] = emitidas
        data['rfc_emisor'] = args.get('rfc_emisor', '')
        data['rfc_receptor'] = args.get('rfc_receptor', '')
        data['type_cfdi'] = args.get('tipo_complemento', '-1')

        if args['fecha_inicial'] and args['fecha_final'] and emitidas:
            dates = self._get_dates(args['fecha_inicial'], args['fecha_final'])
            for start, end in dates:
                data['date_from'] = start
                data['date_to'] = end
                filters.append(Filters(data))
        elif args['fecha_inicial'] and args['fecha_final']:
            dates = self._get_dates_recibidas(args['fecha_inicial'], args['fecha_final'])
            for d in dates:
                data['date_from'] = d
                data['day'] = True
                filters.append(Filters(data))
        elif args['intervalo_dias'] and emitidas:
            data['date_from'], data['date_to'] = self._time_delta(args['intervalo_dias'])
            filters.append(Filters(data))
        elif args['intervalo_dias']:
            dates = self._time_delta_recibidas(args['intervalo_dias'])
            for d in dates:
                data['date_from'] = d
                data['day'] = True
                filters.append(Filters(data))
        elif args['uuid']:
            data['date_from'] = None
            filters.append(Filters(data))
        else:
            day = args['dia'] or 1
            data['date_from'] = datetime.datetime(args['año'], args['mes'], day)
            filters.append(Filters(data))

        return tuple(filters)

    def _segment_filter(self, filters):
        new_filters = []
        if filters.stop:
            return new_filters
        date = filters.date_from
        date_to = filters.date_to

        if filters.minute:
            for m in range(10):
                nf = deepcopy(filters)
                nf.stop = True
                nf.date_from = date + datetime.timedelta(minutes=m)
                nf.date_to = date + datetime.timedelta(minutes=m+1)
                new_filters.append(nf)
        elif filters.hour:
            minutes = tuple(range(0, 60, 10)) + (0,)
            minutes = tuple(zip(minutes, minutes[1:]))
            for m in minutes:
                nf = deepcopy(filters)
                nf.minute = True
                nf.date_from = date + datetime.timedelta(minutes=m[0])
                nf.date_to = date + datetime.timedelta(minutes=m[1])
                if m[0] == 50:
                    nf.date_to = nf.date_to.replace(
                        hour=nf.date_to.hour+1, minute=0, second=0)
                new_filters.append(nf)
        elif filters.day:
            hours = (0,) + tuple(range(4,22)) + (23,)
            hours = tuple(zip(hours, hours[1:]))
            for h in hours:
                nf = deepcopy(filters)
                nf.hour = True
                nf.date_from = date + datetime.timedelta(hours=h[0])
                nf.date_to = date + datetime.timedelta(hours=h[1])
                if h[1] == 23:
                    nf.date_to = nf.date_to.replace(
                        hour=23, minute=59, second=59, microsecond=0)
                new_filters.append(nf)
        else:
            last_day = calendar.monthrange(date.year, date.month)[1]
            for d in range(last_day):
                nf = deepcopy(filters)
                nf.day = True
                nf.date_from = date + datetime.timedelta(days=d)
                nf.date_to = nf.date_from.replace(
                    hour=23, minute=59, second=59, microsecond=0)
                new_filters.append(nf)
                if date_to == nf.date_to:
                    break
        return new_filters

    def _get_post(self, html):
        validos = ('EVENTTARGET', '__EVENTARGUMENT', '__LASTFOCUS', '__VIEWSTATE')
        values = html.split('|')
        post = {v: values[i+1]  for i, v in enumerate(values) if v in validos}
        return post

    def _search_by_uuid(self, filters):
        for f in filters:
            log.info(str(f))
            url_search = self.URL_RECEPTOR
            folder = self.DIR_RECIBIDAS
            if f.emitidas:
                url_search = self.URL_EMISOR
                folder = self.DIR_EMITIDAS

            result = self._response(url_search, 'get')
            post = self._read_form(result)
            post = self._merge(post, f.get_post())
            headers = self._get_headers(self.PORTAL, url_search)
            html = self._response(url_search, 'post', headers, post)
            not_found, limit, invoices = self._get_download_links(html)
            if not_found:
                msg = '\n\tNo se encontraron documentos en el filtro:' \
                    '\n\t{}'.format(str(f))
                log.info(msg)
            else:
                return self._download(invoices, folder=folder)
        return

    def _change_to_date(self, url_search):
        result = self._response(url_search, 'get')
        values = self._read_form(result)
        post = self._merge(values, self._get_post_form_dates())
        headers = self._get_headers(self.PORTAL, url_search, True)
        result = self._response(url_search, 'post', headers, post)
        post = self._get_post(result)
        return values, post

    def _search_recibidas(self, filters):
        url_search = self.URL_RECEPTOR
        values, post_source = self._change_to_date(url_search)

        for f in filters:
            log.info(str(f))
            post = self._merge(values, f.get_post())
            post = self._merge(post, post_source)
            headers = self._get_headers(self.PORTAL, url_search, True)
            html = self._response(url_search, 'post', headers, post)
            not_found, limit, invoices = self._get_download_links(html)
            if not_found or not invoices:
                msg = '\n\tNo se encontraron documentos en el filtro:' \
                    '\n\t{}'.format(str(f))
                log.info(msg)
            else:
                self._download(invoices, limit, f)
        return

    def _search_emitidas(self, filters):
        url_search = self.URL_EMISOR
        values, post_source = self._change_to_date(url_search)

        for f in filters:
            log.info(str(f))
            post = self._merge(values, f.get_post())
            post = self._merge(post, post_source)
            headers = self._get_headers(self.PORTAL, url_search, True)
            html = self._response(url_search, 'post', headers, post)
            not_found, limit, invoices = self._get_download_links(html)
            if not_found or not invoices:
                msg = '\n\tNo se encontraron documentos en el filtro:' \
                    '\n\t{}'.format(str(f))
                log.info(msg)
            else:
                self._download(invoices, limit, f, self.DIR_EMITIDAS)
        return

    def search(self, opt):
        filters_e = ()
        filters_r = ()

        if opt['tipo'] == 'e' and not opt['uuid']:
            filters_e = self._get_filters(opt, True)
            self._search_emitidas(filters_e)
            return
        if opt['tipo'] == 'e' and opt['uuid']:
            filters_e = self._get_filters(opt, True)
            self._search_by_uuid(filters_e)
            return
        elif opt['tipo'] == 'r' and not opt['uuid']:
            filters_r = self._get_filters(opt, False)
            self._search_recibidas(filters_r)
            return
        if opt['tipo'] == 'r' and opt['uuid']:
            filters_r = self._get_filters(opt, False)
            self._search_by_uuid(filters_r)
            return

        filters_e = self._get_filters(opt, True)
        filters_r = self._get_filters(opt, False)
        te = threading.Thread(target=self._search_emitidas, args=(filters_e,))
        tr = threading.Thread(target=self._search_recibidas, args=(filters_r,))
        te.start()
        tr.start()
        te.join()
        tr.join()
        return

    def _download(self, invoices, limit=False, filters=None, folder=DIR_RECIBIDAS):
        if filters is not None and not filters.uuid:
            save_search(
                self._rfc, folder == self.DIR_RECIBIDAS,
                filters.date_from, filters.date_to, len(invoices))

        if filters is not None and not filters.uuid:
            invoices = previous_download(invoices)

        if not invoices and not limit:
            msg = '\n\tTodos los documentos han sido previamente ' \
                'descargados para el filtro.\n\t{}'.format(str(filters))
            log.info(msg)

            path = ''
            if folder == self.DIR_EMITIDAS:
                path = os.path.join(self._folder, folder)
            update_date_download([], path, self._rfc)
            return

        if invoices and not self.only_search:
            self._thread_download(invoices, folder, filters)

        if limit:
            sf = self._segment_filter(filters)
            if folder == self.DIR_RECIBIDAS:
                self._search_recibidas(sf)
            else:
                self._search_emitidas(sf)
        return

    def _make_path_xml(self, uuid, folder, date):
        name = '{}.xml'.format(uuid)
        path = self._folder
        if not self.sin_sub:
            path = os.path.join(self._folder, folder,
                str(date.year), str(date.month).zfill(2))
            if not os.path.exists(path):
                os.makedirs(path)
        return os.path.join(path, name)

    def _parse_xml(self, path):
        try:
            xml = ET.parse(path).getroot()
            return True
        except Exception as e:
            msg = 'Error al parsear: {}'.format(path)
        return False

    def _thread_download(self, invoices, folder, filters):
        threads = []
        paths = {}
        for_download = invoices[:]
        current = 1
        total = len(for_download)

        for i in range(TRY_COUNT):
            for uuid, values in for_download:
                #~ name = '{}.xml'.format(uuid)
                #~ path_xml = os.path.join(self._folder, folder, name)
                path_xml = self._make_path_xml(uuid, folder, values['date_cfdi'])
                paths[uuid] = path_xml
                data = {
                    'url': values['url'],
                    'path_xml': path_xml,
                    'acuse': values['acuse'],
                }
                th = threading.Thread(
                    target=self._get_xml, args=(uuid, data, current, total))
                th.start()
                threads.append(th)
                current += 1

            for t in threads:
                t.join()

            #~ Valid download
            not_saved = []
            uuids = []
            for uuid, values in for_download:
                p = paths[uuid]
                #~ if os.path.exists(p) and os.path.getsize(p):
                if self._parse_xml(p):
                    uuids.append(uuid)
                else:
                    not_saved.append((uuid, values))
            path = ''
            if folder == self.DIR_EMITIDAS:
                path = os.path.join(self._folder, folder)
            update_date_download(uuids, path, self._rfc)
            for_download = not_saved[:]
            current = 1
            total = len(for_download)
            if not for_download:
                break

        if total:
            msg = '{} documentos por descargar en: {}'.format(total, str(filters))
            log.info(msg)
        return

    def _get_xml(self, uuid, values, current, count):
        msg = 'Descargando UUID: {} - {} de {}'.format(uuid, current, count)
        log.info(msg)

        for i in range(TRY_COUNT):
            try:
                r = self._session.get(values['url'], stream=True, timeout=TIMEOUT)
                if r.status_code == 200:
                    with open(values['path_xml'], 'wb') as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)
                if values['acuse']:
                    self._save_acuse(uuid, values['acuse'])
                return
            except exceptions.Timeout:
                log.debug('Timeout')
                continue
            except Exception as e:
                log.error(str(e))
                return
        msg = 'Tiempo de espera agotado para el documento: {}'.format(uuid)
        log.error(msg)
        return

    def _save_acuse(self, uuid, url_pdf):
        msg = 'Descargando acuse del UUID: {}'.format(uuid)
        log.info(msg)

        name = '{}.pdf'.format(uuid)
        path_pdf = os.path.join(self._folder, self.DIR_EMITIDAS, name)

        for i in range(2):
            with open(path_pdf, 'wb') as handle:
                try:
                    response = self._session.get(url_pdf, stream=True, timeout=TIMEOUT)
                    if not response.ok:
                        return
                    for block in response.iter_content(1024):
                        if not block:
                            break
                        handle.write(block)
                    return
                except exceptions.Timeout:
                    log.debug('Timeout')
                    continue
                except Exception as e:
                    log.error(str(e))
                    return
        return

    def _get_download_links(self, html):
        parser = Invoice()
        parser.feed(html)
        return parser.not_found, parser.limit, parser.invoices

    def logout(self):
        msg = 'Cerrando sessión en el SAT'
        log.debug(msg)
        respuesta = self._response(self.URL_LOGOUT)
        self.is_connect = False
        msg = 'Sesión cerrada en el SAT'
        log.info(msg)
        return
