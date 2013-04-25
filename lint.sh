#!/bin/bash

dir=$(dirname $0)

# flake 8
flake8 $dir
if [ $? -ne 0 ]; then
    echo "Exiting due to flake8 errors. Fix and re-run to finish tests."
    exit 1
fi

# pylint
output=$(find $dir -name [A-Za-z_]\*.py -exec pylint --rcfile=$dir/.pylintrc {} \; 2>/dev/null)
if [ -n "$output" ]; then
    echo "--pylint--"
    echo -e "$output"
    exit 1
fi

exit 0
