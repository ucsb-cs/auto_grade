#!/usr/bin/env python
"""A simple program that filters lines starting with ERROR:"""

import sys


def main():
    """Run the filter."""
    for line in sys.stdin:
        if line.startswith('ERROR: '):
            print 'ERROR: <FILTERED>'
        else:
            sys.stdout.write(line)

if __name__ == '__main__':
    sys.exit(main())
