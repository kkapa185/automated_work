.PHONY: test build rope clean
test:
	python3 -m unittest discover -s tests
build:
	python3 -m compileall -q agclib agcasm
rope:
	./agcasm assemble agc_source/Comanche055/MAIN.agc -o out/Comanche055.binsource --symbols out/Comanche055.symbols.json --listing out/Comanche055.lst
	./agcasm assemble agc_source/Luminary099/MAIN.agc -o out/Luminary099.binsource --symbols out/Luminary099.symbols.json --listing out/Luminary099.lst
clean:
	rm -rf out build __pycache__ agclib/__pycache__ tests/__pycache__
