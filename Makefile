help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo "  help  to show this message"
	@echo "  lint  to run flake8 and pylint"
	@echo "  test  to run unit tests"

lint:
	flake8 .
	pylint --reports=n --disable=I nailgun tests setup.py

test:
	python -m unittest discover --start-directory tests --top-level-directory .

.PHONY: help lint test
