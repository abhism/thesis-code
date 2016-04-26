#!/bin/bash
cd /home/shivanshu/thesis/spec/installed/
source shrc
runspec --config=mytest.cfg --size=test --noreportable --tune=base --iterations=1 $1
rm -r benchspec/CPU2006/*.$1/run/*
