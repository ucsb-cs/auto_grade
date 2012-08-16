#!/usr/bin/env python
"""An example project configuration."""

from auto_grade import FileVerifier, Submission


class ProjectSubmission(Submission):
    """The project configuration"""
    # pylint: disable-msg=E0101
    def __init__(self, project, user, action, verbose):
        # The parent constructor will automatically (1) find their most recent
        # submission, and (2) extract that submission.
        super(ProjectSubmission, self).__init__(project, user, action, verbose)

        # This is the list of files that can be submitted. The optional
        # argument on the README file means that file need not be submitted.
        files = [FileVerifier('char_count.c', min_size=1),
                 FileVerifier('README', min_size=1, optional=True)]

        self.status = 'Failed'

        # The exact argument to file_checker means the student can submit no
        # other files than the ones specified above.
        if not self.file_checker(files, exact=True):
            return self.generic_score_message(0, 2, 'Verification', log=False)

        # If the submission passes file verification, then run our Makefile.
        if not self.make_submission():
            return self.generic_score_message(1, 2, 'Verification', log=False)

        # Add a successful verification message to the output
        self.status = 'Success'
        self.generic_score_message(2, 2, 'Verification', log=False)

        # Run their submission against our test cases
        self.score_it()
