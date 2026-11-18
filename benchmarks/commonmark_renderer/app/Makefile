.PHONY: test test-spec test-perf
test:
	python3 -m unittest discover -s tests -t . -v 2>&1 | tail -n 15
test-spec:
	python3 -m unittest tests.test_spec
test-perf:
	python3 -m unittest tests.test_perf
