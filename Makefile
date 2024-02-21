TEST_OPTIONS=-m unittest discover --start-directory tests --top-level-directory .
CPU_COUNT=$(shell python -c "from multiprocessing import cpu_count; print(cpu_count())")

help:
	@echo "Please use \`make <target>' where <target> is one of:"
	@echo "  help           to show this message"
	@echo "  test           to run unit tests"
	@echo "  docs-html      to generate HTML documentation"
	@echo "  docs-clean     to remove documentation"
	@echo "  package        to generate installable Python packages"
	@echo "  package-clean  to remove generated Python packages"
	@echo "  publish        to upload dist/* to PyPI"

docs-html:
	@cd docs; $(MAKE) html

docs-clean:
	@cd docs; $(MAKE) clean

test:
	python $(TEST_OPTIONS)

package:
	./setup.py sdist bdist_wheel --universal

package-clean:
	rm -rf build dist nailgun.egg-info

publish: package
	twine upload dist/*

.PHONY: help docs-html docs-clean test package package-clean publish
