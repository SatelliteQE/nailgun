help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo "  help        to show this message"
	@echo "  docs-html   to generate HTML documentation"
	@echo "  docs-clean  to remove documentation"
	@echo "  lint        to run flake8 and pylint"
	@echo "  test        to run unit tests"

docs-html:
	@cd docs; $(MAKE) html

docs-clean:
	@cd docs; $(MAKE) clean

lint:
	flake8 .
	pylint --reports=n --disable=I nailgun tests setup.py docs/conf.py

test:
	python -m unittest discover --start-directory tests --top-level-directory .

.PHONY: help lint test
