#!/bin/sh

# This script is experimental and incomplete. You should not consider the generated data.

# How to execute, ex:
#   docker exec -it netapi_app ./fast_coverage_test.sh .
#   docker exec -it netapi_app ./fast_coverage_test.sh networkapi
#   docker exec -it netapi_app ./fast_coverage_test.sh networkapi/plugins/Juniper/JUNOS
# How to check results:
#   From command output e GloboNetworkAPI/coverage-out folder (html)

if [ $# -eq 0 ]
  then
    echo "No arguments supplied"
    exit
fi

echo "exporting NETWORKAPI_DEBUG"
export NETWORKAPI_LOG_QUEUE=0

echo "exporting DJANGO_SETTINGS_MODULE"
export DJANGO_SETTINGS_MODULE='networkapi.settings_ci'

# Updates the SDN controller ip address
export REMOTE_CTRL_IP=$(nslookup netapi_odl | grep Address | tail -1 | awk '{print $2}')
echo "Found SDN controller at $REMOTE_CTRL_IP"

echo "Starting tests at: $@"

# This not work properly ...
coverage erase
coverage run -m nose -v -w "$@"
coverage report
coverage html -d coverage-out