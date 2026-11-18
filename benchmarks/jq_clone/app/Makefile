.PHONY: test setup smoke
setup:
	python3 -m pip install -r requirements.txt
test:
	python3 -m pytest tests -q
smoke:
	echo '{"a":[1,2,3]}' | ./jq -c '.a | map(. * 2)'
