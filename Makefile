TEST_OPTIONS=-m unittest discover --start-directory tests --top-level-directory .

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
	pylint --reports=n --disable=I --ignore-imports=y \
		nailgun tests setup.py docs/conf.py
	pylint --reports=n --disable=I --ignore-imports=y --disable=similarities \
		docs/create_organization_nailgun.py docs/create_organization_plain.py \
		docs/create_user_nailgun.py docs/create_user_plain.py

test:
	python $(TEST_OPTIONS)

test-coverage:
	coverage run --source nailgun $(TEST_OPTIONS)

package:
	./setup.py sdist bdist_wheel --universal

package-clean:
	rm -rf build dist nailgun.egg-info

.PHONY: help lint test docs-html docs-clean package package-clean
