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
import os
import subprocess
from datetime import datetime
from peewee import *

from settings import (
    log,
    DB,
    DEBUG,
    PDF_TO_TEXT,
)


TEMPLATE_DATE = '%d/%m/%Y %H:%M:%S'


if DB['TYPE'] == 'sqlite':
    #database = SqliteDatabase(DB['NAME'], threadlocals=True)
    database = SqliteDatabase(DB['NAME'])
elif DB['TYPE'] == 'mysql':
    database = MySQLDatabase(DB['NAME'],
        user=DB['USER'], password=DB['PWD'], host=DB['HOST'], port=DB['PORT'])
elif DB['TYPE'] == 'postgres':
    database = PostgresqlDatabase(DB['NAME'],
        user=DB['USER'], password=DB['PWD'], host=DB['HOST'], port=DB['PORT'])


class BaseModel(Model):
    class Meta:
        database = database


class Company(BaseModel):
    rfc = CharField(max_length=13, unique=True)
    name = CharField(max_length=250)
    ciec = CharField(max_length=50)
    folder = TextField()

    class Meta:
        order_by = ('name',)


class Search(BaseModel):
    rfc = CharField(max_length=15)
    recibidas = BooleanField(default=True)
    date_start = DateTimeField()
    date_end = DateTimeField()
    count = IntegerField(default=0)
    verify = IntegerField(default=1)

    class Meta:
        order_by = ('rfc', 'date_start')
        indexes = (
            (('rfc', 'recibidas', 'date_start', 'date_end'), True),
        )


class Invoice(BaseModel):
    uuid = UUIDField(unique=True)
    xml = TextField(null=True)
    path = CharField(max_length=2000, null=True)
    date_download = DateTimeField(null=True)
    date_cfdi = DateTimeField(null=True)
    date_timbre = DateTimeField(null=True)
    date_cancel = DateTimeField(null=True)
    emisor = CharField(null=True)
    receptor = CharField(null=True)
    rfc_emisor = CharField(max_length=15, null=True)
    rfc_receptor = CharField(max_length=15, null=True)
    rfc_pac = CharField(max_length=15, null=True)
    tipo = CharField(max_length=10, null=True)
    estatus = CharField(max_length=10, null=True)
    total = DecimalField(default=0.0, decimal_places=4, auto_round=True, null=True)
    acuse = BooleanField(default=False)
    pagada = BooleanField(default=False)

    class Meta:
        order_by = ('date_cfdi',)


class Template(BaseModel):
    name = CharField(max_length=190, unique=True)
    fields = CharField(max_length=500)

    class Meta:
        order_by = ('name',)


def connect():
    global database
    msg = 'Intentando conectarse a la base de datos'
    log.debug(msg)
    if database.is_closed():
        database.connect()
    msg = 'Conectado correctamente a la base de datos'
    log.debug(msg)
    return


def create_tables():
    global database
    connect()
    msg = 'Creando tablas...'
    log.info(msg)
    #database.create_tables([Company, Search, Invoice, Template], True)
    database.create_tables([Company, Search, Invoice, Template])
    msg = 'Tablas creadas correctamente...'
    log.info(msg)
    return


def previous_download(invoices):
    for_download = []
    with database.atomic():
        for uuid, values in invoices:
            data = values.copy()
            data['acuse'] = bool(data['acuse'])
            #~ Fix in Windows, ToDo
            #~ obj, created = Invoice.create_or_get(uuid=uuid)
            created = True
            try:
                obj = Invoice.create(uuid=uuid)
            except IntegrityError:
                created = False
                obj = Invoice.get(uuid=uuid)
            if created:
                del data['url']
                q = Invoice.update(**data).where(Invoice.uuid==uuid)
                q.execute()
                if values['url']:
                    for_download.append((uuid, values))
            else:
                if data['date_cancel'] is not None:
                    new_data = {
                        'date_cancel': data['date_cancel'],
                        'estatus': data['estatus'],
                        'acuse': data['acuse'],
                    }
                    q = Invoice.update(**new_data).where(Invoice.uuid==uuid)
                    q.execute()
                if obj.date_download is None and values['url']:
                    for_download.append((uuid, values))
    return for_download


def update_date_download(uuids=[], path='', rfc=''):
    if uuids:
        with database.atomic():
            q = Invoice.update(
                date_download=datetime.now()).where(Invoice.uuid.in_(uuids))
            q.execute()
    if path:
        query = Invoice.select().where(
            Invoice.rfc_emisor==rfc,
            Invoice.acuse==True,
            Invoice.date_cancel==None)
        for row in query:
            date_cancel = get_date_cancel(path, row.uuid)
            if date_cancel is not None:
                print ('Date cancel', date_cancel)
                row.date_cancel = date_cancel
                row.save()
    return


def get_date_cancel(path, uuid):
    date_cancel = None
    name = '{}.pdf'.format(uuid)
    path_pdf = os.path.join(path, name)
    if not os.path.exists(path_pdf):
        return

    name = '{}.txt'.format(uuid)
    path_txt = os.path.join(path, name)
    cmd = [PDF_TO_TEXT, path_pdf]
    subprocess.call(cmd)
    if not os.path.exists(path_txt):
        return

    with open(path_txt) as f:
        data = f.readlines()
    if data:
        date = data[9].strip()
        uuid2 = data[19].strip()
        if uuid2 == uuid:
            try:
                date_cancel = datetime.strptime(date, TEMPLATE_DATE)
            except:
                pass
    return date_cancel


def save_search(rfc, recibidas, date_start, date_end, count):
    data = {
        'rfc': rfc,
        'recibidas': recibidas,
        'date_start': date_start,
        'date_end': date_end,
    }
    obj, created = Search.get_or_create(**data)
    if created:
        obj.count = count
        obj.save()
    else:
        if count == obj.count:
            q = Search.update(verify=Search.verify + 1).where(Search.id == obj.id)
            q.execute()
        elif count > obj.count:
            q = Search.update(verify=1, count=count).where(Search.id == obj.id)
            q.execute()
    return


def get_companies():
    rows = Company.select().tuples()
    return tuple(rows)


def get_invoices(opt={}):
    filters = []
    if opt:
        uuid = opt.get('uuid', '')
        if uuid:
            filters.append(Invoice.uuid.contains(uuid))
        emisor = opt.get('emisor', '')
        if emisor:
            filters.append(Invoice.emisor.contains(emisor) | Invoice.rfc_emisor.contains(emisor))
        receptor = opt.get('receptor', '')
        if receptor:
            filters.append(Invoice.receptor.contains(receptor) | Invoice.rfc_receptor.contains(receptor))
        type_doc = opt.get('type_doc', '')
        if type_doc:
            filters.append(Invoice.tipo==type_doc)
        status = opt.get('status', '')
        if status:
            filters.append(Invoice.estatus==status)
        year = opt.get('year', 0)
        if year:
            filters.append(database.extract_date('year', Invoice.date_cfdi)==year)
        month = opt.get('month', 0)
        if month:
            filters.append(database.extract_date('month', Invoice.date_cfdi)==month)
        start = opt.get('start', 0)
        if start:
            end = opt['end']
            filters.append(Invoice.date_cfdi.between(start, end))

        rows = Invoice.select(Invoice.id, Invoice.uuid, Invoice.date_cfdi,
            Invoice.emisor, Invoice.rfc_emisor, Invoice.receptor,
            Invoice.rfc_receptor, Invoice.tipo, Invoice.estatus,
            Invoice.date_cancel, Invoice.total).where(*filters).tuples()
    else:
        rows = Invoice.select(Invoice.id, Invoice.uuid, Invoice.date_cfdi,
            Invoice.emisor, Invoice.rfc_emisor, Invoice.receptor,
            Invoice.rfc_receptor, Invoice.tipo, Invoice.estatus,
            Invoice.date_cancel, Invoice.total).tuples()
    return tuple(rows)


def get_emisores():
    rows = Invoice.select(
        Invoice.rfc_emisor).order_by(Invoice.rfc_emisor).distinct().tuples()
    rows = ['Selecciona un RFC'] + [r[0] for r in rows]
    return tuple(rows)


def delete_company(pk):
    query = Company.delete().where(Company.id == pk)
    rows = query.execute()
    return bool(rows)


def delete_invoice(pk):
    query = Invoice.delete().where(Invoice.id == pk)
    rows = query.execute()
    return bool(rows)


def update_status(pk, status):
    q = Invoice.update(estatus=status).where(Invoice.id == pk)
    rows = q.execute()
    return bool(rows)


def save_company(data):
    if Company.select().where(Company.rfc==data['rfc']).exists():
        msg = 'Este RFC ya esta dado de alta'
        return msg
    data['ciec'] = base64.urlsafe_b64encode(
        base64.b64encode(data['ciec'].encode())).decode()
    Company.create(**data)
    return ''


def save_template(name, fields):
    if Template.select().where(Template.name==name).exists():
        msg = 'Este Nombre ya esta dado de alta'
        return msg
    data = {'name': name, 'fields': fields}
    Template.create(**data)
    return ''


def delete_template(name):
    query = Template.delete().where(Template.name == name)
    rows = query.execute()
    return bool(rows)


def get_templates():
    rows = Template.select()
    return {row.name: row.fields for row in rows}


def get_years():
    rows = Invoice.select(fn.date_trunc('year', Invoice.date_cfdi)) \
        .order_by(Invoice.date_cfdi).distinct().tuples()
    rows = ['Todos'] + [r[0] for r in rows]
    return tuple(rows)


def get_months():
    global database
    rows = Invoice.select(database.extract_date('month', Invoice.date_cfdi)) \
        .order_by(Invoice.date_cfdi).distinct().tuples()
    months = ('', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
        'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')
    rows = ['Todos'] + [months[r[0]] for r in rows]
    return tuple(rows)

