#!/usr/bin/env python
import ConfigParser
import cStringIO
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
from os.path import isdir, join
from optparse import OptionParser
from subprocess import Popen, PIPE, STDOUT


class Project(object):
    """Base class for defining a project."""
    def __init__(self, project):
        self.project = project
        self.input_dir = None
        self.build_dir = None

        self.test_config = ConfigParser.SafeConfigParser()
        files = ('tests.cfg', join(project, 'tests.cfg'))
        if not self.test_config.read(files):
            raise Exception('Could not find any tests.cfg')

    @staticmethod
    def point_string(points, with_pt=True):
        if int(points) == points:
            pt_val = '%d' % points
        else:
            pt_val = '%.2f' % points
        if not with_pt:
            return pt_val
        if points > 1:
            return pt_val + ' pts'
        else:
            return pt_val + ' pt'

    @staticmethod
    def timed_subprocess(cmd, test_input, time_limit, files, stderr,
                         output_filter):
        """Returns output_file, returnstatus for ran process.
        Return status of None indicates the process timed out.

        input can either be a file object, None, or a string.
        """
        if not stderr:
            stderr = open('/dev/null', 'w')
        else:
            stderr = STDOUT

        if not test_input:
            in_file = None
        elif isinstance(test_input, str):
            in_file = PIPE
        else:
            in_file = test_input

        tmp_dir = tempfile.mkdtemp()
        if files:
            for src in files:
                shutil.copy(src, tmp_dir)
        try:
            poll = select.epoll()
            main_pipe = Popen(cmd.split(), stdin=in_file, stdout=PIPE,
                              stderr=stderr, cwd=tmp_dir)
            if in_file == PIPE:
                main_pipe.stdin.write(test_input)
            if output_filter:
                filter_pipe = Popen(output_filter.split(), cwd=tmp_dir,
                                    stdin=main_pipe.stdout, stdout=PIPE)
                main_pipe.stdout.close()
                poll.register(filter_pipe.stdout,
                              select.EPOLLIN | select.EPOLLHUP)
            else:
                poll.register(main_pipe.stdout,
                              select.EPOLLIN | select.EPOLLHUP)
            do_poll = True
            start = time.time()
            output = cStringIO.StringIO()
            while do_poll:
                remaining = start + time_limit - time.time()
                if remaining <= 0:
                    os.kill(main_pipe.pid, signal.SIGKILL)
                    #if os.fork():
                    #    time.sleep(.01)
                    #    os.killpg(os.getpgid(main_pipe.pid), signal.SIGKILL)
                    #else:
                    #    os.setpgrp()
                    return None, None
                rlist = poll.poll(remaining)
                for file_descriptor, event in rlist:
                    output.write(os.read(file_descriptor, 8192))
                    if event == select.POLLHUP:
                        poll.unregister(file_descriptor)
                        do_poll = False
            if output_filter:
                filter_pipe.wait()
            main_status = main_pipe.wait()
            output.seek(0)
            output = output.readlines()
        finally:
            shutil.rmtree(tmp_dir)
        return main_status, output

    def fetch_tests(self):
        self.input_dir = join(self.project, 'input')
        #if not isdir(self.input_dir):
        #    raise Exception('Scoring input directory does not exist')

        config = self.test_config
        test_files_dir = join(self.project, 'test_files')
        if isdir(test_files_dir):
            test_files = dict((x, join(test_files_dir, x)) for x in
                              os.listdir(test_files_dir))
        else:
            test_files = {}

        test_inputs = sorted(os.listdir(self.input_dir))
        for section in sorted(config.sections(), key=len, reverse=True):
            count = 1
            settings = TestSettings(self.test_config, section, self.project,
                                    self.build_dir, test_files)
            remaining = []
            for input_file in test_inputs:
                if input_file.startswith(section):
                    yield input_file, settings, count
                    count += 1
                else:
                    remaining.append(input_file)
            test_inputs = remaining

            if count == 1:  # No provided input files, use the input argument
                yield None, settings, None

        if not test_inputs:
            return
        settings = TestSettings(self.test_config, 'DEFAULT', self.project,
                                self.build_dir, test_files)
        for i, test in enumerate(tests):
            yield test, settings, i + 1

    def generate_output(self):
        self.build_dir = join(os.getcwd(), self.project, 'solution')
        if not isdir(self.build_dir):
            raise Exception('Solution dir %r does not exist.' % self.build_dir)
        output_dir = join(self.project, 'output')
        if not isdir(output_dir):
            os.mkdir(output_dir)
        for test, settings, _ in self.fetch_tests():
            if test:
                print 'Running %r' % test
                with open(join(self.input_dir, test)) as test_file:
                    status, output = self.timed_subprocess(
                        settings.args, test_file, settings.time_limit,
                        settings.files, settings.check_stderr,
                        settings.output_filter)
            else:
                test = settings._section
                print 'Running %r' % test
                status, output = self.timed_subprocess(
                    settings.args, settings.input, settings.time_limit,
                    settings.files, settings.check_stderr,
                    settings.output_filter)

            if status is None:
                raise Exception('Oops, you timed out')

            with open(join(output_dir, '%s.stdout' % test), 'w') as file_obj:
                file_obj.write(''.join(output))
            # Always write status regardless of check_status setting
            with open(join(output_dir, '%s.status' % test), 'w') as file_obj:
                file_obj.write('%d\n' % status)


class Submission(Project):
    """Class for representing student submissions of a certain project."""
    def __init__(self, project, user, action, verbose):
        super(Submission, self).__init__(project)
        self.user = user
        self.log_messages = []
        self.submission = None
        self.verbose = verbose
        self.turnin_dir = join(os.environ['HOME'], 'TURNIN', project)
        self.work_dir = join(self.turnin_dir, user)
        self.message = 'User: %s\nProject: %s\n' % (user, project)

        if self.get_latest_submission() and self.extract_submission():
            self.status = "Success"
        else:
            self.status = "Failure"

    def get_latest_submission(self):
        """Returns the name of the user's most recent submission"""
        self.message += '...Finding most recent submission\n'

        if not isdir(self.turnin_dir):
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
        submission = join(self.turnin_dir, self.submission)

        if isdir(self.work_dir):
            shutil.rmtree(self.work_dir)
        os.mkdir(self.work_dir)
        os.chmod(self.work_dir, 0700)
        pipe = Popen('tar -xvzf %s -C %s' % (submission, self.work_dir),
                     shell=True, stdout=PIPE, stderr=STDOUT)
        pipe.wait()
        self.message += ''.join(['\t%s' % x for x in pipe.stdout.readlines()])
        return pipe.returncode == 0

    def delete_submission(self):
        """ Should only be used on test stuff """
        if self.submission:
            os.remove(join(self.turnin_dir, self.submission))
            shutil.rmtree(join(self.turnin_dir, self.user))

    def copy_build_files(self):
        build_files_path = join(self.project, 'build_files')
        if not isdir(build_files_path):
            return
        for filename in os.listdir(build_files_path):
            if os.path.isfile(join(self.build_dir, filename)):
                continue
            shutil.copy(join(build_files_path, filename), self.build_dir)

    def make_submission(self, src_dir='', target='', silent=False):
        self.build_dir = join(self.turnin_dir, self.user, src_dir)
        if not isdir(self.build_dir):
            self.log_error('Build directory %r does not exist' %
                           self.build_dir)
            return False

        self.copy_build_files()

        if not silent:
            self.message += '...Making submission\n'

        makefile = join(os.getcwd(), self.project, 'Makefile')
        if not os.path.isfile(makefile):
            self.log_error('Make file %s does not exist' % makefile)
            return False
        makefile_location = '-f %s' % makefile

        make_cmd = 'make %s -C %s %s' % (makefile_location, self.build_dir,
                                         target)
        pipe = Popen(make_cmd, shell=True, stdout=PIPE, stderr=STDOUT)
        pipe.wait()
        if not silent:
            self.message += ''.join(['\t%s' % x for x in
                                     pipe.stdout.readlines()])
        return pipe.returncode == 0

    def file_checker(self, file_verifiers, exact=False):
        success = True
        self.message += '...Verifying files\n'

        original_files_dir = join(self.project, 'original_files')
        if isdir(original_files_dir):
            original_files = dict((x, join(original_files_dir, x)) for
                                  x in os.listdir(original_files_dir))
        else:
            original_files = {}

        submitted = []
        for path, _, files in os.walk(self.work_dir):
            for filename in files:
                submitted.append(join(path, filename))
        for file_verifier in file_verifiers:
            original_file = original_files.get(file_verifier.name)
            success &= file_verifier.verify(self.work_dir, original_file)
            if file_verifier.exists:
                if file_verifier.name in submitted:
                    submitted.remove(file_verifier.name)
                else:
                    submitted.remove(join(self.work_dir, file_verifier.name))
            self.message += file_verifier.message(self.work_dir)

        if exact and submitted:
            submitted = [x[len(self.work_dir) + 1:] for x in submitted]
            self.message += '\textra files: %s\n' % ', '.join(submitted)
            success = False

        return success

    def patch_checker(self, patch_filename, src_tarball, src_dir):
        self.message += '...Attempting to apply: %s\n' % patch_filename
        null = open('/dev/null', 'w')

        try:
            # extract source
            pipe = Popen('tar -xvzf %s -C %s' % (src_tarball, self.work_dir),
                         shell=True, stdout=null, stderr=null)
            pipe.wait()
            if pipe.returncode != 0:
                self.message += '\tsource extraction failed, contact TA\n'
                return False

            patch_file = open(join(self.work_dir, patch_filename))
            pipe = Popen('patch -d %s -p1' % src_dir, shell=True,
                      stdin=patch_file, stdout=PIPE, stderr=STDOUT)
            stdout, _ = pipe.communicate()[:2]
            patch_file.close()
            self.message += '\n'.join(['\t%s' % x for x in stdout.split('\n')
                                       if x != ''])
            self.message += '\n'
            if pipe.returncode != 0:
                return False
        finally:
            # cleanup
            null.close()
            shutil.rmtree(src_dir)
        return True

    def score_it(self, score_msg='Tentative Score'):
        output_dir = join(self.project, 'output')
        if not isdir(output_dir):
            raise Exception('Scoring output directory does not exist')

        self.message += '...Scoring\n'
        passed = total = 0
        for test, settings, count in self.fetch_tests():
            if test:
                name = '%s (%d)' % (settings.name if settings.name else test,
                                    count)
            else:
                test = settings._section
                name = settings.name if settings.name else test

            total += settings.points_possible

            if settings.description:
                name += ' [desc: %s]' % settings.description
            if settings.always_fail:
                self.score_failure(name, settings.points_possible, None)
                continue

            out_file = join(output_dir, '%s.stdout' % test)
            if not os.path.isfile(out_file):
                raise Exception('No outfile: %s' % out_file)
            status_file = join(output_dir, '%s.status' % test)
            if not os.path.isfile(status_file):
                raise Exception('No status file %s' % status_file)

            expected = open(out_file).readlines()
            if count:  # Test from input file
                with open(join(self.input_dir, test)) as test_in:
                    status, output = self.timed_subprocess(
                        settings.args, test_in, settings.time_limit,
                        settings.files, settings.check_stderr,
                        settings.output_filter)
            else:
                status, output = self.timed_subprocess(
                    settings.args, settings.input, settings.time_limit,
                    settings.files, settings.check_stderr,
                    settings.output_filter)
            if status == None:
                self.score_timeout_failure(name, settings.points_possible,
                                           settings.time_limit)

                if settings.timeout_quit:
                    return passed, -1
                continue

            # Only show diff_lines lines excluding first 3
            diff = []
            for line in difflib.unified_diff(expected, output):
                if len(line) > settings.diff_max_line_width:
                    diff.append(line[:settings.diff_max_line_width] + '...\n')
                else:
                    diff.append(line)
            if settings.diff_lines < 0:
                max_lines = None
            else:
                max_lines = 3 + settings.diff_lines
            diff_lines = len(diff)
            diff = ''.join(diff[3:max_lines])
            if max_lines and max_lines < diff_lines:
                diff += '...remaining diff truncated...\n'

            if settings.check_status:
                expected = int(open(status_file).read())
                if status != expected:
                    diff += ('\t\tStatus mismatch: Expected: '
                             '%d, got: %d\n' % (expected, status))

            if len(diff):
                self.score_failure(name, settings.points_possible, diff)
            else:
                passed += settings.points
        self.generic_score_message(passed, total, score_msg)

    def generic_score_message(self, passed, total, header=None, log=True):
        if not header:
            header = 'Score'

        passed = self.point_string(passed, False)
        total = self.point_string(total, False)

        self.message += '\n%s: %s out of %s\n' % (header, passed, total)
        if log:
            self.log_messages.append('Score: %s %s/%s' % (self.user,
                                                          passed, total))

    def score_timeout_failure(self, name, points, time_limit):
        self.message += '\t%s - Took longer than %d seconds (%s)\n' % (
            name, time_limit, self.point_string(points))

    def score_failure(self, name, points, diff):
        self.message += '\t%s - Failed (%s)\n' % (name,
                                                  self.point_string(points))
        if diff:
            self.message += '<BEGIN DIFF>\n'
            self.message += diff
            self.message += ('</END DIFF>\n\n')

    def log_error(self, message):
        self.log_messages.append(message)
        self.message += '%s\n' % message


class TestSettings(object):
    def __init__(self, config, section, project_dir, build_dir, test_files):
        self._config = config
        self._section = section
        self._items = dict(config.items(section))

        self.args = join(build_dir, self._items['args'])
        self.binary = self.args.split()[0]
        if not os.path.isfile(self.binary) and not self.always_fail:
            raise Exception('Binary %r does not exist for section %r' %
                            (self.binary, section))
        self.files = [test_files[x.strip()] for x in
                      self._items['files'].split(',') if x.strip()]
        if self._items['input']:
            self.input = self._items['input'] + '\n'
        else:
            self.input = None
        if self._items['output_filter']:
            self.output_filter = join(os.getcwd(), project_dir,
                                      self._items['output_filter'])
            output_binary = self.output_filter.split()[0]
            if not os.path.isfile(output_binary):
                raise Exception('Output filter %r does not exist' %
                                output_binary)
        else:
            self.output_filter = None

    def __getattr__(self, attribute):
        if attribute in ('timeout_quit', 'check_status', 'check_stderr',
                         'always_fail'):
            return self._config.getboolean(self._section, attribute)
        if attribute in ('points', 'points_possible', 'time_limit'):
            return float(self._items[attribute])
        if attribute in ('diff_lines', 'diff_max_line_width'):
            return int(self._items[attribute])
        return self._items[attribute]


class FileVerifier(object):
    def __init__(self, name, min_lines=0, max_lines=None,
                 min_size=0, max_size=None, diff_file=None, optional=False,
                 case_sensitive=True, bad_re=None, bad_re_msg=None):
        self.name = name
        self.min_lines = min_lines
        self.max_lines = max_lines
        self.min_size = min_size
        self.max_size = max_size
        self.optional = optional
        self.case_sensitive = case_sensitive
        self.bad_re = bad_re
        self.bad_re_msg = bad_re_msg
        self.verified = False
        self.exists = False
        self.message_args = None

    def verify(self, work_dir, diff_file=None):
        if not self.case_sensitive:
            basename = os.path.basename(self.name)
            work_dir = join(work_dir, os.path.dirname(self.name))
            mapping = dict((x.lower(), x) for x in os.listdir(work_dir))
            if basename in mapping:
                if basename == self.name:
                    self.name = mapping[self.name]
                else:
                    self.name = join(work_dir, mapping[basename])
        filename = join(work_dir, self.name)
        invalid_lines = []
        try:
            with open(filename) as file_obj:
                self.exists = True
                line_count = size = 0
                for line_count, line in enumerate(file_obj):
                    if self.bad_re:
                        match = self.bad_re.search(line)
                        if match:
                            invalid_lines.append(
                                'Forbidden content on line %d: %s' % (
                                    line_count + 1, match.group(0)))
                            invalid_lines.append(self.bad_re_msg)
                    size += len(line)
            line_count += 1
            if (self.min_lines and self.min_lines > line_count or
                self.max_lines and self.max_lines < line_count):
                self.message_args = ('failed', ' (invalid line count: '
                                     'count=%d min=%s max=%s)' %
                                     (line_count, self.min_lines,
                                      self.max_lines))
                return False
            elif (self.min_size and self.min_size > size or
                  self.max_size and self.max_size < size):
                self.message_args = ('failed', ' (invalid file size)')
                return False
            elif (diff_file and not os.system('diff %s %s 2>&1 >/dev/null' %
                                              (filename, diff_file))):
                self.message_args = ('failed', ' (file not modified)')
                return False
        except IOError:
            if self.optional:
                self.message_args = ('passed', ' (missing optional)')
                self.verified = True
                return True
            self.message_args = ('failed', ' (file does not exist)')
            return False
        if invalid_lines:
            errors = '\n'.join(['\t\t%s' % x for x in invalid_lines])
            self.message_args = ('failed', ' invalid lines\n%s' % errors)
            return False
        self.message_args = ('passed', '')
        self.verified = True
        return True

    def message(self, work_dir=''):
        if self.name.startswith('/'):
            name = self.name[len(work_dir) + 1:]
        else:
            name = self.name
        template = '\t%%s %s%%s\n' % name
        return template % self.message_args


class ProcessEmail(object):
    RE_USER_NAME = re.compile('([^@]+)@cs.ucsb.edu')
    RE_PROJECT = re.compile(r'[^+]+\+([^@/\\]+)@cs.ucsb.edu')

    @staticmethod
    def relay_and_exit(message):
        """To be called when this script should not process the message"""
        print message
        sys.exit(0)

    def __init__(self):
        self.project = None
        self.user = None
        self.action = None
        # Get email message
        self.input = sys.stdin.read()
        message = email.message_from_string(self.input)
        # Verify Message
        self.assert_valid_project(message['to'])
        self.assert_valid_user(message['from'])
        self.assert_valid_action(message['subject'])
        if message.is_multipart() or message.get_payload():
            self.relay_and_exit(self.input)

    def assert_valid_user(self, from_address):
        """Returns user account if valid CS account otherwise None"""
        _, email_addr = email.utils.parseaddr(from_address)
        match = self.RE_USER_NAME.match(email_addr)
        if not match:
            self.relay_and_exit(self.input)
        else:
            self.user = match.group(1)

    def assert_valid_project(self, to_address):
        """Returns name of project from cs160+projname or None"""
        _, email_addr = email.utils.parseaddr(to_address)
        match = self.RE_PROJECT.match(email_addr)
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

    def get_triple_string(self):
        return "%s %s %s" % (self.project, self.user, self.action)


def auto_grade(project, user, action, verbose):
    if not verbose:
        # Setup logging
        log_dir = join(os.path.expanduser('~'), 'logs')
        try:
            os.mkdir(log_dir)
            os.chmod(log_dir, 0700)
        except OSError:
            pass
        log_path = join(log_dir, '%s.log' % project)
        logger = logging.getLogger('auto_grade')
        try:
            handler = logging.handlers.RotatingFileHandler(log_path,
                                                           maxBytes=1048576,
                                                           backupCount=1000)
        except IOError:
            sys.stderr.write('Cannot open log file\n')
            sys.exit(1)
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    message = 'Submission: %s' % user
    if verbose > 0:
        print message
    else:
        logger.info(message)

    # Test for project specifc file, and import
    if os.path.isfile(join(project, '__init__.py')):
        # pylint: disable-msg=W0122
        exec 'from %s import ProjectSubmission' % project
        sub_class = locals()['ProjectSubmission']
    else:
        sub_class = Submission
    submission = sub_class(project, user, action, verbose)
    message = "Status: %s\n%s" % (submission.status, submission.message)
    if verbose:
        print message
        sys.exit(0)

    for log_message in submission.log_messages:
        logger.info(log_message)

    # Send email
    smtp = smtplib.SMTP()
    smtp.connect('letters')
    to_addr = 'To: %s@cs.ucsb.edu' % user
    subject = 'Subject: %s Result' % project
    msg = '%s\n%s\n\n%s' % (to_addr, subject, message)
    smtp.sendmail('%s@cs.ucsb.edu' % os.environ['LOGNAME'],
                  '%s@cs.ucsb.edu' % user, msg)
    smtp.quit()


def display_scores(project):
    log_path = join(os.path.expanduser('~'), 'logs', project)
    logs = glob.glob('%s.log*' % log_path)
    if not logs:
        sys.stderr.write('No log file for project: %s\n' % project)
        sys.exit(1)

    scores = {}
    user_max = {}
    for log_file in logs:
        for line in open(log_file).readlines():
            if 'Score' not in line:
                continue
            the_date, the_time, _, _, user, score = line[:-1].split()
            the_time = the_time.split(',')[0]
            timestamp = time.strptime('%s %s' % (the_date, the_time),
                                      '%Y-%m-%d %H:%M:%S')
            if user not in scores:
                scores[user] = {timestamp: score}
            elif timestamp not in scores[user]:
                scores[user][timestamp] = score
            else:
                scores[user][timestamp] = max(score, scores[user][timestamp])
            int_score = int(score.split('/')[0])
            user_max[user] = max(user_max.setdefault(user, 0), int_score)

    for user in sorted(scores):
        already_score = []
        for timestamp in sorted(scores[user]):
            score = scores[user][timestamp]
            if score not in already_score:
                if int(score.split('/')[0]) == user_max[user]:
                    best = '*'
                else:
                    best = ' '
                print '%s % 7s%s %s' % (time.strftime('%a %b %d %I:%M %p',
                                                      timestamp),
                                        scores[user][timestamp], best, user)
                already_score.append(score)
        print


class UserDiffs(object):
    def __init__(self, project, user):
        self.project = project
        self.user = user
        self.submissions = None
        self.turnin_dir = join(os.environ['HOME'], 'TURNIN', project)
        self.get_submissions()
        self.build_diffs()

    @staticmethod
    def extract_submission(submission):
        tmp_dir = tempfile.mkdtemp()
        pipe = Popen('tar -xvzf %s -C %s' % (submission, tmp_dir),
                     shell=True, stdout=PIPE, stderr=STDOUT)
        pipe.wait()
        if pipe.returncode != 0:
            shutil.rmtree(tmp_dir)
            raise Exception('Extraction failed')
        return tmp_dir

    def get_submissions(self):
        if not isdir(self.turnin_dir):
            print 'Failure: Turnin directory does not exist'
            return

        user_submission_re = re.compile('%s(-(\d+))?.tar.Z' % self.user)
        submissions = {}
        for elem in os.listdir(self.turnin_dir):
            match = user_submission_re.match(elem)
            if not match:
                continue

            if match.group(2):
                submissions[int(match.group(2))] = elem
            else:
                submissions[0] = elem
        self.submissions = [x[1] for x in sorted(submissions.items())]

    def build_diffs(self):
        base = new = None
        for submission in self.submissions:
            new = self.extract_submission(join(self.turnin_dir,
                                               submission))
            if base and new:
                print '---\n---Changed in %s---\n---' % submission
                pipe = Popen('git diff -p --stat --color %s %s' % (base, new),
                             shell=True, stdout=PIPE, stderr=STDOUT)
                stdout, _ = pipe.communicate()
                print stdout
                shutil.rmtree(base)
            base = new
        shutil.rmtree(base)


def main():
    # Change dir to directory with this file.
    os.chdir(sys.path[0])

    parser = OptionParser()
    parser.add_option('--diffs')
    parser.add_option('--generate-expected')
    parser.add_option('--process', action='store_true')
    parser.add_option('--scores')
    parser.add_option('-v', '--verbose', action='count')
    options, args = parser.parse_args()

    if options.diffs:
        if len(args) != 1:
            parser.error('Incorrect number of arguments for --diffs')
        UserDiffs(options.diffs, args[0])
    elif options.generate_expected:
        project = Project(options.generate_expected)
        project.generate_output()
    elif options.process:
        # pylint: disable-msg=W0142
        if len(args) == 2:
            auto_grade(*args, action='DEFAULT', verbose=options.verbose)
        elif len(args) == 3:
            auto_grade(*args, verbose=options.verbose)
        else:
            parser.error('incorrect number of arguments for --process')
    elif options.scores:
        display_scores(options.scores)
    else:
        # This is called from procmailrc on the machine letters.cs which is not
        # suitable for a build environment
        arg_string = ProcessEmail().get_triple_string()
        os.system('ssh csil %s --process %s' % (sys.argv[0], arg_string))

if __name__ == '__main__':
    sys.exit(main())
