#!/bin/bash

echo "--- message 1 -- to deliver"

/usr/sbin/sendmail -bF system.filter <2pass.eml

echo "--- message 2 -- supposed to fail delivery"

/usr/sbin/sendmail -bF system.filter <2fail.eml
