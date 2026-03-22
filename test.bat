@echo off
:: Run all .hpprgm tests from ANY folder — add 0-App to PATH to use this globally
:: Usage: test
:: Usage: test -v
py "%~dp0test_all.py" %*
