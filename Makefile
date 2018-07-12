export PATH := $(PATH):bin

.PHONY: run
run:
	. ./settings.sh ; \
	pipenv run ./snipe.py

.PHONY: test
test:
	pipenv run nosetests
