#!/usr/bin/env python
import os, re, smtplib, sys

RE_TURNIN = re.compile('(\w+)@(\w+)')

if __name__ == '__main__':
    def usage():
        sys.stderr.write(' '.join(['Usage: %s assignment@class',
                                   'FILES-AND-DIRECTORIES... [-t TARGET]\n'])
                         % os.path.basename(sys.argv[0]))
        sys.exit(1)

    if len(sys.argv) < 3:
        usage()

    # Get project, to_user, and target
    match = RE_TURNIN.match(sys.argv[1])
    if not match:
        sys.stderr.write("Invalid assignment@class: %s\n" % sys.argv[1])
        usage()
    project, user = match.groups()

    if sys.argv[-2] == '-t':
        target = sys.argv[-1]
        turnin_args = ' '.join(sys.argv[1:-2])
    else:
        target = 'DEFAULT'
        turnin_args = ' '.join(sys.argv[1:])

    # Call turnin, afterall this is a wrapper
    ret = os.system('turnin %s' % turnin_args)
    if ret:
        sys.exit(ret)

    # Notify user of turnin
    smtp = smtplib.SMTP()
    smtp.connect('letters')
    from_addr = '%s@cs.ucsb.edu' % os.getlogin()
    to_addr = '%s+%s@cs.ucsb.edu' % (user, project)
    message = 'To: %s\nSubject: %s\n' % (to_addr, target)
    smtp.sendmail(from_addr, to_addr, message)

    smtp.quit()
