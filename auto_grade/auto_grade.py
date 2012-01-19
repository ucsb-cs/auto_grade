#!/usr/bin/env python
import cStringIO
import datetime
import difflib
import email
import glob
import logging
import logging.handlers
import os
import re
import select
import shutil
import signal
import smtplib
import sys
import tempfile
import time
from optparse import OptionParser
from subprocess import Popen, PIPE, STDOUT

RE_USER_NAME = re.compile('([^@]+)@cs.ucsb.edu')
RE_PROJECT = re.compile(r'[^+]+\+([^@/\\]+)@cs.ucsb.edu')


class Turnin(object):
    """Base Turnin class. This will extract and make projects"""

    def __init__(self, project, user, action, verbose):
        self.status = "Failed"
        self.project = project
        self.user = user
        self.log_messages = []
        self.submission = None
        self.verbose = verbose

        self.turnin_dir = os.path.join(os.environ['HOME'], 'TURNIN', project)
        self.work_dir = os.path.join(self.turnin_dir, self.user)
        self.message = 'User: %s\nProject: %s\n' % (user, project)

        if not self.get_latest_turnin() or not self.extract_submission():
            return
        self.status = "Success"

    def get_latest_turnin(self):
        """Returns the name of the user's most recent turnin"""
        self.message += '...Finding most recent submission\n'

        if not os.path.isdir(self.turnin_dir):
            self.log_error('Failure: Turnin directory does not exist')
            return False

        user_submission_re = re.compile('%s(-(\d+))?.tar.Z' % self.user)
        latest = -1
        for elem in os.listdir(self.turnin_dir):
            match = user_submission_re.match(elem)
            if match:
                if match.group(2) and int(match.group(2)) > latest:
                    latest = int(match.group(2))
                    self.submission = elem
                elif 0 > latest:
                    latest = 0
                    self.submission = elem

        if latest == -1:
            self.log_error('Failure: No submissions in turnin directory')
            return False

        self.message += '\tFound submission: %s\n' % self.submission
        return True

    def extract_submission(self):
        self.message += '...Extracting submission\n'
        submission = os.path.join(self.turnin_dir, self.submission)

        if os.path.isdir(self.work_dir):
            os.system('rm -rf %s' % self.work_dir)
        os.mkdir(self.work_dir)
        os.chmod(self.work_dir, 0700)
        p = Popen('tar -xvzf %s -C %s' % (submission, self.work_dir),
                             shell=True, stdout=PIPE, stderr=STDOUT)
        p.wait()
        self.message += ''.join(['\t%s' % x for x in p.stdout.readlines()])
        return p.returncode == 0

    def delete_submission(self):
        """ Should only be used on test stuff """
        if self.submission:
            os.remove(os.path.join(self.turnin_dir, self.submission))
            os.system('rm -rf %s' % os.path.join(self.turnin_dir, self.user))

    def make_submission(self, src_dir='', makefile=None, target='',
                        silent=False):
        if not silent:
            self.message += '...Making submission\n'
        build_dir = os.path.join(self.turnin_dir, self.user, src_dir)
        if not os.path.isdir(build_dir):
            self.log_error('Build directory: %s does not exist' % build_dir)
            return False
        makefile_location = ''
        if makefile:
            if not os.path.isfile(makefile):
                self.log_error('Make file %s does not exist' % makefile)
                return False
            makefile_location = '-f %s' % makefile

        make_cmd = 'make %s -C %s %s' % (makefile_location, build_dir, target)
        p = Popen(make_cmd, shell=True, stdout=PIPE, stderr=STDOUT)
        p.wait()
        if not silent:
            self.message += ''.join(['\t%s' % x for x in p.stdout.readlines()])
        return p.returncode == 0

    def file_checker(self, file_verifiers, exact=False):
        success = True
        self.message += '...Verifying files\n'

        submitted = []
        for path, _, files in os.walk(self.work_dir):
            for filename in files:
                tmp = os.path.join(path[len(self.work_dir) + 1:], filename)
                submitted.append(tmp)

        for file_verifier in file_verifiers:
            success &= file_verifier.verify(self.work_dir)
            if file_verifier.exists:
                submitted.remove(file_verifier.name)
            self.message += file_verifier.message

        if exact and submitted:
            self.message += '\textra files: %s\n' % ', '.join(submitted)
            success = False

        return success

    def patch_checker(self, patch_filename, src_tarball, src_dir):
        self.message += '...Attempting to apply: %s\n' % patch_filename
        null = open('/dev/null', 'w')

        try:
            # extract source
            p = Popen('tar -xvzf %s -C %s' % (src_tarball, self.work_dir),
                      shell=True, stdout=null, stderr=null)
            p.wait()
            if p.returncode != 0:
                self.message += '\tsource extraction failed, contact TA\n'
                return False

            patch_file = open(os.path.join(self.work_dir, patch_filename))
            p = Popen('patch -d %s -p1' % src_dir, shell=True,
                      stdin=patch_file, stdout=PIPE, stderr=STDOUT)
            stdout, _ = p.communicate()
            patch_file.close()
            self.message += '\n'.join(['\t%s' % x for x in stdout.split('\n')
                                       if x != ''])
            self.message += '\n'
            if p.returncode != 0:
                return False
        finally:
            # cleanup
            null.close()
            os.system('rm -rf %s' % src_dir)
        return True

    def score_it(self, binary, prefix='', max_time=5, diff_lines=None,
                 timeout_quit=False, check_status=False):
        self.max_time = max_time
        self.diff_lines = diff_lines
        self.message += '...Scoring\n'
        input_dir = os.path.join(self.project, 'input')
        output_dir = os.path.join(self.project, 'output')

        if not os.path.isdir(input_dir):
            self.log_error('Failure: Scoring Input directory does not exist')
            return None, None
        if not os.path.isdir(output_dir):
            self.log_error('Failure: Scoring Output directory does not exist')
            return None, None
        if not os.path.isfile(binary.split()[0]):
            self.log_error('Binary does not exist')
            return None, None

        passed = 0
        total = 0
        for test in sorted(os.listdir(input_dir)):
            if not test.startswith(prefix):
                continue
            in_file = open(os.path.join(input_dir, test))
            out_file = os.path.join(output_dir, '%s.stdout' % test)
            if not os.path.isfile(out_file):
                self.log_error('Failure: No outfile: %s' % out_file)
                return
            if check_status:
                status_file = os.path.join(output_dir, '%s.status' % test)
                if not os.path.isfile(status_file):
                    self.log_error('Failure: No status file %s' % status_file)
                    return None, None

            true_output = open(out_file).readlines()
            status, output = self.timed_subprocess(binary, in_file, max_time)
            in_file.close()
            if status == None:
                if timeout_quit:
                    self.score_timeout_failure(test)
                    return passed, -1
                diff = None
            else:
                # Only show diff_lines lines excluding first 3
                # <= 0 show None | >0 Show up to that many | None show all
                diff = ''
                for line in difflib.unified_diff(true_output, output):
                    diff += line
                if self.diff_lines:
                    max = 3 + self.diff_lines
                else:
                    max = None
                diff = '\n'.join(diff.split('\n')[3:max])

                if check_status and status != int(open(status_file).read()):
                    diff += '\t\tStatus mismatch: Expected: '
                    diff += '%d, got: %d\n' % (my_status, status)

            t_tot, t_pas = self.score_callback(test, true_output, output, diff)
            total += t_tot
            passed += t_pas

        return passed, total

    def score_callback(self, test_name, true_output, submit_output, diff):
        """Returns the a touple of points. The first value is the number of
        points to add to the possible total. The second is the number of points
        to add to the current score."""
        if diff == None:
            self.score_timeout_failure(test_name)
            return 1, 0
        elif len(diff):
            self.score_failure(test_name, diff)
            return 1, 0
        return 1, 1

    def generic_score_message(self, passed, total, header=None, log=True):
        if not header:
            header = 'Score'
        self.message += '\n%s: %d out of %d\n' % (header, passed, total)
        if log:
            self.log_messages.append('Score: %s %s %d/%d' % (self.user,
                                                             self.project,
                                                             passed, total))

    def score_timeout_failure(self, test):
        self.message += '\t%s - Took longer than %ds\n' % (test, self.max_time)

    def score_failure(self, test, diff, points=1):
        if int(points) == points:
            pt_val = str(points)
        else:
            pt_val = '%.2f' % points

        if points > 1:
            pt_str = 'pts'
        else:
            pt_str = 'pt'

        self.message += '\t%s - Failed (%s %s)\n' % (test, pt_val, pt_str)
        if self.diff_lines > 0:
            self.message += '\t...First %d lines of diff\n\n' % self.diff_lines
            self.message += diff
            self.message += '\n'
        elif self.diff_lines == None:
            self.message += diff
            self.message += '\n'

    def log_error(self, message):
        self.log_messages.append(message)
        self.message += '%s\n' % message

    def timed_subprocess(self, cmd, in_file, time_limit, stderr=None):
        """Returns output_file, returnstatus for ran process.
        Return status of None indicates the process timed out."""

        if stderr == None:
            stderr = open('/dev/null', 'w')
        else:
            stderr = STDOUT

        tmp_dir = tempfile.mkdtemp()
        try:
            p = Popen(cmd.split(), stdin=in_file, stdout=PIPE, stderr=stderr,
                      cwd=tmp_dir)
            poll = select.poll()
            poll.register(p.stdout)
            do_poll = True
            start = time.time()
            output = cStringIO.StringIO()
            while do_poll:
                remaining = start + time_limit - time.time()
                if remaining <= 0:
                    if os.fork():
                        time.sleep(.01)
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    else:
                        os.setpgrp()
                    return None, None
                rlist = poll.poll(remaining)
                for fd, event in rlist:
                    output.write(os.read(fd, 1024))
                    if event == select.POLLHUP:
                        poll.unregister(fd)
                        do_poll = False
            status = p.wait()
            output.seek(0)
        finally:
            shutil.rmtree(tmp_dir)
        return status, output.readlines()


class FileVerifier(object):
    def __init__(self, name, min_lines=0, max_lines=None,
                 min_size=0, max_size=None, diff_file=None, optional=False):
        self.name = name
        self.min_lines = min_lines
        self.max_lines = max_lines
        self.min_size = min_size
        self.max_size = max_size
        self.diff_file = diff_file
        self.optional = optional
        self.verified = False
        self.exists = False

    def verify(self, work_dir):
        filename = os.path.join(work_dir, self.name)
        template = '\t%%s %s%%s\n' % self.name
        try:
            with open(filename) as f:
                self.exists = True
                line_count = size = 0
                for line_count, line in enumerate(f):
                    size += len(line)
            if (self.min_lines and self.min_lines > line_count or
                self.max_lines and self.max_lines < line_count):
                self.message = template % ('failed', ' (invalid line count: '
                                           'count=%d min=%s max=%s)' %
                                           (line_count, self.min_lines,
                                            self.max_lines))
                return False
            elif (self.min_size and self.min_size > size or
                  self.max_size and self.max_size < size):
                self.message = template % ('failed', ' (invalid file size)')
                return False
            elif (self.diff_file and
                  not os.system('diff %s %s 2>&1 >/dev/null' %
                                (filename, self.diff_file))):
                self.message = template % ('failed', ' (file not modified)')
                return False
        except IOError:
            if self.optional:
                self.message = template % ('passed', ' (missing optional)')
                self.verified = True
                return True
            self.message = template % ('failed', ' (file does not exist)')
            return False
        self.message = template % ('passed', '')
        self.verified = True
        return True


class ProcessEmail(object):
    def relay_and_exit(self, message):
        """To be called when this script should not process the message"""
        print message
        sys.exit(0)

    def assert_valid_user(self, from_address):
        """Returns user account if valid CS account otherwise None"""
        real_name, email_addr = email.Utils.parseaddr(from_address)
        match = RE_USER_NAME.match(email_addr)
        if not match:
            self.relay_and_exit(self.input)
        else:
            self.user = match.group(1)

    def assert_valid_project(self, to_address):
        """Returns name of project from cs160+projname or None"""
        real_name, email_addr = email.Utils.parseaddr(to_address)
        match = RE_PROJECT.match(email_addr)
        if not match:
            self.relay_and_exit(self.input)
        else:
            self.project = match.group(1)

    def assert_valid_action(self, subject):
        """Returns action name from subject line or None.
           Should be single word."""
        if not len(subject.split()) == 1:
            self.relay_and_exit(self.input)
        else:
            self.action = subject.strip()

    def __init__(self):
        # Get email message
        self.input = sys.stdin.read()
        message = email.message_from_string(self.input)
        # Verify Message
        self.assert_valid_project(message['to'])
        self.assert_valid_user(message['from'])
        self.assert_valid_action(message['subject'])
        if message.is_multipart() or message.get_payload():
            self.relay_and_exit(self.input)

    def get_triple_string(self):
        return "%s %s %s" % (self.project, self.user, self.action)


def auto_grade(project, user, action, verbose):
    # Setup logging
    homedir = os.path.expanduser('~')
    log_path = os.path.join(homedir, 'logs', '%s.log' % project)
    logger = logging.getLogger('auto_grade')
    try:
        handler = logging.handlers.RotatingFileHandler(log_path,
                                                       maxBytes=1024 * 1024,
                                                       backupCount=1000)
    except IOError:
        sys.stderr.write('Cannot open log file\n')
        sys.exit(1)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    message = 'Submission: %s %s %s' % (user, project, action)
    if verbose > 0:
        print message
    else:
        logger.info(message)

    # Test for project specifc file, and import
    if os.path.isfile(os.path.join(project, '__init__.py')):
        exec 'from %s import ProjectTurnin' % project
        turnin = locals()['ProjectTurnin'](project, user, action, verbose)
    else:
        turnin = Turnin(project, user, action, verbose)

    message = "Status: %s\n%s" % (turnin.status, turnin.message)
    if verbose:
        print message
        sys.exit(1)

    for log_message in turnin.log_messages:
        logger.info(log_message)

    # Send email
    smtp = smtplib.SMTP()
    smtp.connect('letters')
    to = 'To: %s@cs.ucsb.edu' % user
    subject = 'Subject: %s Result' % project
    msg = '%s\n%s\n\n%s' % (to, subject, message)
    smtp.sendmail('%s@cs.ucsb.edu' % os.environ['LOGNAME'],
                  '%s@cs.ucsb.edu' % user, msg)
    smtp.quit()


def display_scores(project):
    log_path = os.path.join(os.path.expanduser('~'), 'logs', project)
    logs = glob.glob('%s.log*' % log_path)
    if not logs:
        sys.stderr.write('No log file for project: %s\n' % project)
        sys.exit(1)

    scores = {}
    for log_file in logs:
        for line in open(log_file).readlines():
            if 'Score' not in line:
                continue
            ddate, ttime, _, _, user, _, score = line[:-1].split()
            ttime = ttime.split(',')[0]
            t = time.strptime('%s %s' % (ddate, ttime), '%Y-%m-%d %H:%M:%S')
            if user not in scores:
                scores[user] = {t: score}
            elif t not in scores[user]:
                scores[user][t] = score

    for user in sorted(scores):
        already_score = []
        for t in sorted(scores[user]):
            score = scores[user][t]
            if score not in already_score:
                print '%s % 7s %s' % (time.strftime('%a %b %d %I:%M %p', t),
                                      scores[user][t], user)
                already_score.append(score)
        print

if __name__ == '__main__':
    # Change dir to directory with this file.
    os.chdir(sys.path[0])

    parser = OptionParser()
    parser.add_option('--process', action='store_true')
    parser.add_option('--scores')
    parser.add_option('-v', '--verbose', action='count')
    options, args = parser.parse_args()

    if options.scores:
        display_scores(options.scores)
        sys.exit(1)
    elif not options.process:
        """This is called from procmailrc on the machine letters.cs which is
           not suitable for a build environment"""
        arg_string = ProcessEmail().get_triple_string()
        os.system('ssh csil %s --process %s' % (sys.argv[0], arg_string))
        sys.exit(0)
    elif len(args) == 2:
        auto_grade(*args, action='DEFAULT', verbose=options.verbose)
    elif len(args) == 3:
        auto_grade(*args, verbose=options.verbose)
    else:
        parser.error('incorrect number of arguments')
