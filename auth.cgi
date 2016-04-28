#! /usr/bin/python
# -*- mode: Python; -*-

# jpiitula@ling.helsinki.fi for making Korp authentication work in
# FIN-CLARIN; HTTP Basic Authentication for development version, and
# Martin's Shibboleth session for production use (trusting
# REMOTE_USER, which korp.cgi passes as remote_user).

# This server script is meant to receive HTTP Basic Authentication
# credentials (username and password in plain) from Korp backend
# (korp.cgi) and then return the list of authorized korpora in JSON (I
# think).

# This script may be written to log some info in a file -- set
# level=logging.INFO for that, or perhaps that code should now be
# removed.

from __future__ import print_function

import cgi
import json
import MySQLdb

import logging
import os

import sys

import korp_config as config

sys.stderr = sys.stdout

LOG_FILE = "/v/korp/log/korp-auth.log"
LOG_LEVEL = logging.INFO    # in non-logging version, WARNING


def main():
    print_header()

    form_raw = cgi.FieldStorage(keep_blank_values=True)
    form = dict((field, form_raw.getvalue(field))
                for field in form_raw.keys())
    logging.info('raw form: %s', form)

    conn = MySQLdb.connect(use_unicode=True,
                           charset="utf8",
                           **config.AUTH_DBCONNECT)
    cursor = conn.cursor()

    authenticated, academic = False, False
    entitlement = ''

    if 'remote_user' in form:
        username = form['remote_user']
        authenticated = True
        # entitlement contains LBR REMS IDs (URNs) as a semicolon separated list. 
        entitlement = form['entitlement']
        # convert entitle ment to a SQL friendly form
        if entitlement:
            entitlement = tuple(filter(None,(entitlement+';').split(';')))
        else:
            entitlement = tuple('')

        # academic is TRUE if 'faculty' is part of affiliation.
        academic = 'faculty' in form.get('affiliation', '').lower()
    else:
        username = form.get('username', '')
        password = form.get('password', '')
        # Faking the ACA bit - not for production use:
        if username.endswith('+ACA'):
            username, _ = username.rsplit('+')
            academic = True
        cursor.execute('''
        select secret from auth_secret
        where person = %s''', [username])
        secret = cursor.fetchone()
        if secret is not None and secret[0] == password:
            authenticated = True

    logging.debug('DEBUG entitlement %s',entitlement)


    # We can grant ACA status to people locally:
    if  authenticated and not academic:
        cursor.execute('''
        select 1 from auth_academic
        where person = %s''', [username])
        if cursor.fetchone():
            academic = True

    if authenticated:

        # entitlement is a tuple of URNs that need mapping to Korp corpus IDs
       
        # create as many parameters as entitlement has entries. The empty list is "''"
        # eg 2 parameters yield "'%s', '%s'"
        in_parameters=', '.join(map(lambda x: "'%s'", entitlement))
        if not in_parameters:
            in_parameters = "''"

        # The query with parameters filled in. This is easier to debug.
        sql='''
        select corpus from auth_license
        where license = 'ACA' and %s = True
        union distinct
        select corpus from auth_allow
        where person = '%s'
        union distinct
        select corpus from auth_lbr_map
        where lbr_id IN (%s); ''' % (academic, username, in_parameters)

        # finally fill in entitlement values
        sql = sql % entitlement

        logging.debug('DEBUG sql: %s',sql)

        cursor.execute(sql)

        corpora = [ corpus for corpus, in cursor ]
        logging.debug('DEBUG corpora: %s',corpora)

        result = dict(authenticated=True,
                      permitted_resources=dict(username=username,
                                               corpora=corpora))
    else:
        result = dict(authenticated=False)

    result = json.dumps(result)
    logging.info('result: %s', result)
    print(result)
    conn.close()

def print_header():
    '''Copied from korp.cgi - may not be quite right here'''
    print("Content-Type: application/json")
    print("Access-Control-Allow-Origin: *")
    print("Access-Control-Allow-Methods: GET, POST")
    print("Access-Control-Allow-Headers: Authorization")
    print()

if __name__ == '__main__':
    logging.basicConfig(filename=LOG_FILE,
                        format=('[auth ' + str(os.getpid()) +
                                ' @ %(asctime)s] %(message)s'),
                        level=LOG_LEVEL)

    logging.info('entering auth.cgi')
    main()
    logging.info('exiting auth.cgi')
