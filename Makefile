help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo "  help           to show this message"
	@echo "  lint           to run flake8 and pylint"
	@echo "  test           to run unit tests"
	@echo "  docs-html      to generate HTML documentation"
	@echo "  docs-clean     to remove documentation"
	@echo "  package        to generate installable Python packages"
	@echo "  package-clean  to remove generated Python packages"

docs-html:
	@cd docs; $(MAKE) html

docs-clean:
	@cd docs; $(MAKE) clean

lint:
	flake8 .
	pylint --reports=n --disable=I --ignore-imports=y nailgun tests setup.py docs/conf.py

test:
	python -m unittest discover --start-directory tests --top-level-directory .

package:
	./setup.py sdist bdist_wheel --universal

package-clean:
	rm -rf build dist nailgun.egg-info

.PHONY: help lint test docs-html docs-clean package package-clean
