.PHONY: help
# target: help - Display callable targets.
help:
	@egrep "^# target:" [Mm]akefile | sed 's/^# target: //g'

.PHONY: test
# target: test - Run module tests.
test:
	python setup.py test
