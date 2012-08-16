#!/usr/bin/env python
"""A simple wrapper around the turnin program."""

import json
import os
import re
import smtplib
import socket
import sys
from email.mime.application import MIMEApplication
from optparse import OptionParser

RE_TURNIN = re.compile('(\w+)@(\w+)')
SMTP_SERVERS = ('localhost', 'letters.cs.ucsb.edu')


def main():
    """Submit the program."""
    usage = 'Usage: %prog [options] assignment@class FILES-AND-DIRECTORIES'
    parser = OptionParser(usage=usage)
    parser.add_option('-a', '--action', help='The action to trigger')
    parser.add_option('-e', '--email', help='The email to send the result to')
    options, args = parser.parse_args()

    if len(args) < 2:
        parser.error('Invalid number of arguments')

    # Get project, and destination user
    match = RE_TURNIN.match(args[0])
    if not match:
        parser.error('Invalid assignment@class: {0}'.format(args[0]))
    project, user = match.groups()

    # Call turnin, afterall this is a wrapper
    ret = os.system('turnin {}'.format(' '.join(args)))
    if ret:  # Exit it turnin failed
        return ret

    from_email = '{0}@cs.ucsb.edu'.format(os.getlogin())
    to_email = '{0}@cs.ucsb.edu'.format(user)
    data = json.dumps({'action': options.action,
                       'base_path': os.getcwd(),
                       'project': project,
                       'user': os.getlogin(),
                       'user_email': options.email})

    # Build message
    msg = MIMEApplication(data)
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = 'auto_grade email'

    # Notify user of turnin
    sys.stdout.write('Sending submission notification...')
    sys.stdout.flush()
    smtp = smtplib.SMTP()

    for hostname in SMTP_SERVERS:
        try:
            smtp.connect(hostname)
            sys.stdout.write(' connected to {0}...'.format(hostname))
            sys.stdout.flush()
            break
        except socket.error:
            pass
    else:
        print 'could not connect, notify TA'
        return 1

    smtp.sendmail(from_email, to_email, msg.as_string())
    smtp.quit()
    print ' turnin complete!'
    return 0

if __name__ == '__main__':
    sys.exit(main())
