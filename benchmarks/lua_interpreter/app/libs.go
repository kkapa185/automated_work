package main

// openLibs registers the standard libraries other than the base library.
func openLibs(th *Thread) {
	openString(th)
	openTable(th)
	openMath(th)
	openUTF8(th)
	openCoroutine(th)
	openOS(th)
	openIO(th)
	openDebug(th)
}
