## Installation

All the files within this directory, except for this README of course
need to be moved into the root directory of the class account. For
completeness those files are:

    .procmailrc
    auto_grade/
    TURNIN/
    turnin_wrapper.py

The turnin_wrapper.py file is to be used by students on turn in. It
simply wraps the turnin command, with the addition of sending a
specially formatted email to the class account.

The `.procmailrc` file passes any of these specially formatted emails
to the script `auto_grade/auto_grade.py`. Because this script is run
from the mailsever the first pass through auto_grade actually connects
to the csil server to perform all the work. This worker machine can be
changed to any other machine in CSIL.  !!!IMPORTANT!!!  In order for
this to work, you must have passwordless SSH enabled such that the
account can SSH into itself on another machine. This can be
accomplished by simply running:

    ssh-keygen
    cat ~/.ssh/id_rsa.pub >> ~/.ssh/authorized_keys

The `auto_grade` directory contains `auto_grade.py`, and a directory,
`sample`, that contains the configuration for the sample project.

The `TURNIN` directory also contains a directory, `sample`, which is
where submissions for the sample project will go. It also contains a
solution to the project which scores 9/10 on auto_grade.


## Testing

Auto_grade comes with a sample project titled `sample`. The sample
project is a simple program that counts the number of alphanumeric and
whitespace characters in the input stream. There are two error cases
in this sample project both of which must output an error message on a
single line prefixed with `ERROR:` and then exit. The first error case
is that no input is entered, and the second is a non-alphanumeric nor
non-whitespace character is seen on the input. The successful output
should be exactly: `Alphanumeric: <NUM>\nWhitespace: <NUM>\n` Where
<NUM> is replaced by the appropriate count for that type.

Once the auto_grade files have been copied in the correct location, you will
need to perform the following to test it using the sample application.

1. Generate output files for the sample project. From any directory,
   execute the following:
   
        cp ~/auto_grade/sample/Makefile ~/auto_grade/sample/solution/
        make -C ~/auto_grade/sample/solution/
        ~/auto_grade/auto_grade.py --generate-expected sample

2. Test user bboe's solution to the sample project. From your home
   directory, execute:

        ~/auto_grade/auto_grade.py -v --process sample bboe

   The -v argument means to print the output to the screen. Without
   that argument the output will be emailed to the student.

3. Submit your own version of the sample project to test the end to
   end workings of auto_grade. In your home account (not class
   account) create a file called char_count.c and fill it in as you
   desire. When ready run the following, of course, replacing
   `<CLASS_ACCOUNT>` with the class account you are setting auto_grade
   up on:

        ~<CLASS_ACCOUNT>/turnin_wrapper.py sample@<CLASS_ACCOUNT> char_count.c

   If everything is setup correctly, you should receive the normal
   turnin prompt ensuring you want to submit. Following successful
   submission, you should nearly immediately receive an email to your
   `<USER>@cs.ucsb.edu` email address containing your submission's
   score.

4. View all the scores students have received sorted and grouped by
   student:

        ./auto_grade/auto_grade.py --scores sample


## Adapting to your project

It should be relatively simple to adapt auto_grade for your needs. The
best reference is the file `auto_grade/sample/__init__.py` which
documents what is done in the grading of that particular project.

Additionally check out the extra functions provided by auto_grade in
`auto_grade/auto_grade.py`. If you have any questions please send them
to Bryce Boe (account bboe).


## Known Issues / Potential Problems

* Students' code can do something mallicious such as executing `rm -rf
  ~` thus deleting all the files in the class's home directory. Along
  these lines, students could also retrieve all other student's
  submissions. I trust the students wont do this as doing so would be
  grounds for expulsion from the University. The solution to this
  would be to run their code in a chroot jail however that requires
  special permissions.

* Students' code can retrieve the contents of the input files by
  simply echoing the input. The contents will then appear in their
  diff. The quantity of diff output can be modified to prevent this,
  however, without output students cannot see what they are doing
  wrong.
