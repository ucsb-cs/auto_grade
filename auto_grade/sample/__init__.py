#!/usr/bin/env python
import os
from subprocess import Popen, PIPE, STDOUT
from auto_grade import Turnin, FileVerifier

class ProjectTurnin(Turnin):
    def __init__(self, project, user, action, verbose):
        # The parent constructor will automatically (1) find their most recent
        # submission, and (2) extract that submission.
        Turnin.__init__(self, project, user, action, verbose)

        # This is the list of files that can be submitted. The optional
        # argument on the README file means that file need not be submitted.
        files = [FileVerifier('char_count.c', min_size=1),
                 FileVerifier('README', min_size=1, optional=True)]

        # The exact argument to file_checker means the student can submit no
        # other files than the ones specified above.
        if not self.file_checker(files, exact=True):
            self.status = 'Failed'
            self.generic_score_message(0, 1, 'Verification')

        # If char_count.c passes verification, then (1) run our makefile on it
        # and (2) run each of the inputs against the binary to produce a score.
        makefile = os.path.join(os.getcwd(), project, 'solution', 'Makefile')
        if files[0].verified:
            # The first argument to make_submission is the folder to change
            # into relative to their submission.
            if self.make_submission('', makefile):
                binary = os.path.join(self.turnin_dir, user, 'char_count')
                # The timeout argument specifies if tests should continue to
                # run after a single test has timed out.
                passed, total = self.score_it(binary, timeout_quit=True)
                self.generic_score_message(passed, total)

    def score_callback(self, test_name, true_output, their_output, diff):
        # This function is called after each input is run through their
        # program. This function returns the number of points this particular
        # test is out of, and the number of points they received.
        #
        # By being able to modify both, you can scale the number of points for
        # various cases, and even implement extra credit tests by returning the
        # first value as zero, and the second value something non-zero.
        #
        # The diff variable normally contains the difference between their
        # ouput, and the true_output. If the value of diff is None then their
        # test timed out, if the value of diff is the empty string, then they
        # passed the test exactly.

        # Establish the number of points for each test. For convenience tests
        # are prefixed with labels indicating if they should result in a
        # success or error.
        if 'error_' in test_name:
            possible = 1
        elif 'success_1kb' == test_name:
            possible = 4
        else:
            possible = 2

        # Handle timed out tests
        if diff == None:
            self.score_timeout_failure(test_name)
            return possible, 0

        if 'error_' in test_name:
            # For this sample project we don't require error messages to be
            # identical, however, error messages can only span a single line
            # and all error messages must be prefixed with "ERROR:".
            if len(their_output) == 1 and their_output[0].startswith('ERROR:'):
                return possible, possible
            self.score_failure(test_name, diff, possible)
            return possible, 0

        if len(diff):
            self.score_failure(test_name, diff, possible)
            return possible, 0

        return possible, possible
