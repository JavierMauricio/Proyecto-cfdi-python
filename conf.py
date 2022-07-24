
#~ En tipo (TYPE) puedes usar sqlite, postgres o mysql
#~ IMPORTANTE: Si usas postgres o mysql, asegurate de instalar los drivers
#~ requeridos por cada motor de base de datos.
#~ Mira aquí para más detalles:
#~ http://docs.peewee-orm.com/en/latest/peewee/database.html#vendor-specific-parameters

#~ Asegurate de probar la conexión y crear las tablas primero
#~ ./cfdi-descarga.py -db

DEBUG = False

DB = {
    'TYPE': 'sqlite',
    'HOST': '',
    'PORT': '',
    'NAME': 'invoices.sqlite',
    'USER': '',
    'PWD': '',
}

