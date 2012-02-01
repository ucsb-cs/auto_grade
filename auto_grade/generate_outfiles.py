#!/usr/bin/env python
import os
import shutil
import subprocess
import sys
import tempfile
from optparse import OptionParser


def main():
    parser = OptionParser(usage='Usage: %prog [options] program [args...]')
    parser.add_option('-i', '--input', default='input',
                      help='Folder containing input files [default: %default]')
    parser.add_option('-o', '--output', default='output',
                      help='Folder to store output files [default: %default]')
    parser.add_option('-p', '--prefix', default='',
                      help='Only consider input files with this prefix')
    options, args = parser.parse_args()

    if len(args) == 0:
        parser.error('Must provide a binary')
    elif not os.path.isfile(args[0]):
        parser.error('"%s" does not exist' % args[0])
    elif not os.path.isdir(options.input):
        parser.error('input dir "%s" is not a directory' % options.input)
    elif not os.path.isdir(options.output):
        parser.error('output dir "%s" is not a directory' % options.output)

    null = open('/dev/null', 'w')
    binary = [os.path.join(os.getcwd(), args[0])] + args[1:]

    for test in sorted(os.listdir(options.input)):
        if not test.startswith(options.prefix):
            continue
        in_file = open(os.path.join(os.getcwd(), options.input, test))
        out_file_name = os.path.join(os.getcwd(), options.output,
                                     '%s.stdout' % test)
        if os.path.isfile(out_file_name):
            raise Exception('Output file %s already exists' % out_file_name)
        out_file = open(out_file_name, 'w')
        tmp_dir = tempfile.mkdtemp()
        try:
            p = subprocess.Popen(binary, stdin=in_file, cwd=tmp_dir,
                                 stdout=out_file, stderr=null)
            p.wait()
        except:
            raise
        finally:
            shutil.rmtree(tmp_dir)
        if p.returncode != 0:
            print 'Error on test "%s"' % test


if __name__ == '__main__':
    sys.exit(main())
