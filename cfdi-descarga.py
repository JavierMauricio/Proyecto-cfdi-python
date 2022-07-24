
import getpass
import click

from sat.util import validate_rfc, sat_download, join, validate_folder, today, \
    get_home_user, validate_date
from sat import util
from sat.db import create_tables
from settings import log


def read_credencials(ctx, param, value):
    if 'base_datos' in ctx.params:
        return 'h'
    if 'directorio_fiel' in ctx.params:
        return ''

    try:
        with open(value) as f:
            fields = f.readline().strip().split()
        if not len(fields) == 2:
            msg = 'Se requieren dos campos: RFC y CIEC'
            raise click.ClickException(msg)
    except FileNotFoundError:
        msg = 'No se encontró el archivo de credenciales'
        log.debug(msg)
        return ''

    rfc, ciec = fields
    rfc = rfc.upper()
    msg = validate_rfc(rfc)
    if msg:
        raise click.ClickException(msg)
    ctx.params['rfc'] = rfc
    ctx.params['ciec'] = ciec
    return value


def check_rfc(ctx, param, value):
    if 'base_datos' in ctx.params:
        return ''
    if 'directorio_fiel' in ctx.params:
        return ''

    if 'rfc' in ctx.params:
        return ctx.params['rfc']

    if value is None:
        msg = 'Si no proporcionas archivo de credenciales. El RFC es requerido'
        raise click.ClickException(msg)

    rfc = value.upper()
    msg = validate_rfc(rfc)

    if msg:
        raise click.ClickException(msg)
    return rfc


def check_ciec(ctx, param, value):
    if 'base_datos' in ctx.params:
        return ''
    if 'directorio_fiel' in ctx.params:
        return ''

    if 'ciec' in ctx.params:
        return ctx.params['ciec']

    if value:
        return value.strip()

    ciec = getpass.getpass('Introduce tu clave CIEC: ')
    if not ciec.strip():
        msg = 'La clave CIEC es requerida'
        raise click.ClickException(msg)
    return ciec.strip()


def dir_download(ctx, param, value):
    DEFAULT = 'cfdi-descarga'
    if value == DEFAULT:
        path = join(get_home_user(), DEFAULT)
    else:
        path = value
    msg = validate_folder(path)
    if msg:
        raise click.ClickException(msg)
    return path


def dir_fiel(ctx, param, value):
    if not value:
        return value

    msg = util.validate_folder_fiel(value)
    if msg:
        raise click.ClickException(msg)
    return value


def check_date(opt):
    result = validate_date(opt['año'], opt['mes'], opt['dia'])
    if isinstance(result, str):
        raise click.ClickException(result)
    return result


def check_date_str(ctx, param, value):
    if value is None:
        return
    if param.human_readable_name == 'fecha_final':
        if not 'fecha_inicial' in ctx.params:
            msg = 'La fecha inicial es requerida'
            raise click.ClickException(msg)
    result = validate_date(date_str=value)
    if isinstance(result, str):
        raise click.ClickException(result)
    return result


def check_rfc_arg(ctx, param, value):
    if value is None:
        return
    rfc = value.upper()
    msg = validate_rfc(rfc)
    if msg:
        raise click.ClickException(msg)
    return rfc


help_credenciales = 'Archivo con credenciales para el SAT. Valor predeterminado: ' \
    'credenciales.conf en el directorio actual. Esta opción tiene precedencia ' \
    'sobre los parámetros RFC y CIEC'
help_directorio = 'Directorio local para guardar los CFDIs descargados, el ' \
    'predeterminado es cfdi-descarga en la carpeta del usuario'
help_uuid = 'Folio Fiscal a buscar. Si se usa, se omite el resto de las opciones.'
help_rfc = 'RFC del emisor para identificarse en el SAT. Si no se proporciona ' \
    'archivo de credenciales, este valor es obligatorio.'
help_rfc_emisor = 'RFC del emisor a filtrar. Solo usalo con CFDI recibidos.'
help_rfc_receptor = 'RFC del receptor a filtrar. Solo usalo con CFDI emitidos'
help_ciec = 'CIEC del emisor para identificarse en el SAT. Si no se proporciona ' \
    'archivo de credenciales, se solicitará el valor al usuario.'
help_year = 'El valor por omisión es el año en curso. Valores entre 2011 y el ' \
    'año actual {}'.format(today('y'))
help_month = 'El valor por omisión es el mes en curso. Valores entre 1 y 12'
help_day = 'Por omisión no se usa en la búsqueda. Valores entre 1 y 31. ' \
        'Si se usa, se valida que sea una fecha válida'
help_iday = 'Intervalo de días a partir de la fecha actual y hacia a atras, ' \
    'valores entre 1 y 31.'
help_start = 'Fecha inicial de búsqueda. Formatos aceptados:\n\tD/M/AAAA, ' \
        'D/M/AA, D-M-AAAA y D-M-AA'
help_end = 'Fecha final de búsqueda. Mismos formatos de fecha inicial. Estas ' \
        'opciones reemplazan cualquier otro argumento de búsqueda.'
help_tipo = 'El tipo de descarga: t=todas, e=emitidas, r=recibidas'
help_tipo_cfdi = 'El tipo de complemento a descargar, las opciones son:\n' \
    '-1 = Todos, 8 = Estandar\n1048576 = Nomina 1.1\n137438953472 = N 1.2'
help_sd = 'Solo descarga la lista de CFDI existentes en el SAT, sin descargar el XML'
help_db = 'Verifica la configuración de la base de datos y crea las tablas necesarias'
help_ss = 'Evita crear los subdirectorios RFC, Año, mes'

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

type_cfdi = ['-1', '8', '1048576', '137438953472']

@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-c', '--credenciales', help=help_credenciales,
    callback=read_credencials, default='credenciales.conf')
@click.option('-rfc', help=help_rfc, callback=check_rfc)
@click.option('-ciec', help=help_ciec, callback=check_ciec)
@click.option('-f', '--folder', help=help_directorio,
    callback=dir_download, default='cfdi-descarga')
@click.option('-u', '--uuid', type=click.UUID, help=help_uuid)
@click.option('-a', '--año', type=click.IntRange(2011, today('y')),
    help=help_year, default=today('y'))
@click.option('-m', '--mes', type=click.IntRange(1, 12),
    help=help_month, default=today('m'))
@click.option('-d', '--dia', type=click.IntRange(0, 31),
    help=help_day, default=0)
@click.option('-id', '--intervalo-dias', type=click.IntRange(1, 30),
    help=help_iday)
@click.option('-fi', '--fecha-inicial', callback=check_date_str,
    help=help_start)
@click.option('-ff', '--fecha-final', callback=check_date_str,
    help=help_end)
@click.option('-t', '--tipo', type=click.Choice(['t', 'e', 'r']), default='t',
    help=help_tipo)
@click.option('-tc', '--tipo-complemento', type=click.Choice(type_cfdi), default='-1',
    help=help_tipo_cfdi)
@click.option('-re', '--rfc-emisor', help=help_rfc_emisor, callback=check_rfc_arg)
@click.option('-rr', '--rfc-receptor', help=help_rfc_receptor, callback=check_rfc_arg)
@click.option('-s', '--sin-descargar', is_flag=True, default=False, help=help_sd)
@click.option('-bd', '--base-datos', is_flag=True, default=False, help=help_db)
@click.option('-ss', '--sin-subdirectorios', is_flag=True, default=False, help=help_ss)
@click.option('-df', '--directorio-fiel', default='', callback=dir_fiel)
def main(credenciales, rfc, ciec, folder, uuid, año, mes, dia, intervalo_dias,
    fecha_inicial, fecha_final, tipo, tipo_complemento, rfc_emisor,
    rfc_receptor, sin_descargar, base_datos, sin_subdirectorios,
    directorio_fiel):

    """Descarga documentos del SAT automáticamente"""

    opt = locals()
    del opt['credenciales']

    if opt['base_datos']:
        create_tables()
        return

    if opt['dia']:
        opt['day'] = check_date(opt)
    if opt['fecha_inicial'] and opt['fecha_final'] is None:
        opt['fecha_final'] = today()
    elif opt['fecha_inicial']:
        if opt['fecha_final'] < opt['fecha_inicial']:
            opt['fecha_inicial'], opt['fecha_final'] = opt['fecha_final'], opt['fecha_inicial']

    sat_download(**opt)

    return


if __name__ == '__main__':
    main()

