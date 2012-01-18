#!/usr/bin/env python
import os
import shutil
import subprocess
import sys
import tempfile

if __name__ == '__main__':
    def usage():
        sys.stderr.write('Usage: %s program input_dir output_dir\n' %
                         os.path.basename(sys.argv[0]))
        sys.exit(1)

    if len(sys.argv) < 4:
        usage()

    if not (os.path.isdir(sys.argv[2]) and os.path.isdir(sys.argv[3])):
        sys.stderr.write('input_dir or output_dir is not a directory\n')
        sys.exit(1)

    null = open('/dev/null', 'w')
    binary = [os.path.join(os.getcwd(), sys.argv[1])]
    binary.extend(sys.argv[4:])

    for test in sorted(os.listdir(sys.argv[2])):
        in_file = open(os.path.join(os.getcwd(), sys.argv[2], test))
        out_file = open(os.path.join(os.getcwd(), sys.argv[3],
                                     '%s.stdout' % test), 'w')

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
            print test
