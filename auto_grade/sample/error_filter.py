#!/usr/bin/env python
import sys


def main():
    for line in sys.stdin:
        if line.startswith('ERROR: '):
            print 'ERROR: <FILTERED>'
        else:
            sys.stdout.write(line)

if __name__ == '__main__':
    sys.exit(main())
