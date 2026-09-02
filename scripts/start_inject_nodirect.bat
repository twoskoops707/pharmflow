@echo off
set CPHARM_MANTIS_BILLING_DIRECT=0
set CPHARM_MANTIS_INJECT_PROXY=1
set CPHARM_MANTIS_INJECT_MITM=1
set CPHARM_SKIP_MANTIS_PATCH=0
set CPHARM_DABFLOW_MANTIS_PATCH=1
set CPHARM_EMULATOR_AD_MODE=1
start /min "" "C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" -u "C:\Users\jsmil\FamFlow\scripts\run_mantis_inject_proxies.py" --phones 12
