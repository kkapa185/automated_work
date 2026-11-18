package main

import "fmt"

type blockScope struct {
	parent  *blockScope
	nactive int
	labels  map[string]*Label
	nclose  int
	isLoop  bool
}

type pendingGoto struct {
	node    *SGoto
	scope   *blockScope
	nactive int
}

type funcState struct {
	parent  *funcState
	fb      *FuncBody
	actives []*VarInfo
	scope   *blockScope
	nclose  int
	gotos   []pendingGoto
	loops   int
}

type Parser struct {
	lx    *Lexer
	tok   Token
	ahead Token
	hasAh bool
	fs    *funcState
	chunk string
}

func parseChunk(src, chunk string) (fb *FuncBody, err error) {
	defer func() {
		if r := recover(); r != nil {
			if se, ok := r.(*SyntaxError); ok {
				fb, err = nil, fmt.Errorf("%s", se.msg)
				return
			}
			panic(r)
		}
	}()
	p := &Parser{lx: newLexer(src, chunk), chunk: chunk}
	p.advance()
	fb = &FuncBody{isVararg: true, isMain: true, name: "main chunk"}
	fb.upvals = []UpvalDesc{{name: "_ENV"}}
	fs := &funcState{fb: fb}
	p.fs = fs
	p.openScope(false)
	blk := p.block()
	if p.tok.kind != tkEOF {
		p.errExpected("<eof>")
	}
	p.closeScope()
	p.finishGotos(fs)
	fb.body = blk
	fb.lastLine = p.tok.line
	return fb, nil
}

func (p *Parser) advance() {
	if p.hasAh {
		p.tok = p.ahead
		p.hasAh = false
	} else {
		p.tok = p.lx.next()
	}
}

func (p *Parser) peek() Token {
	if !p.hasAh {
		p.ahead = p.lx.next()
		p.hasAh = true
	}
	return p.ahead
}

func tokText(t Token) string {
	switch t.kind {
	case tkName, tkString, tkNumber:
		return "'" + t.raw + "'"
	case tkEOF:
		return "<eof>"
	}
	if n, ok := symNames[t.kind]; ok {
		return "'" + n + "'"
	}
	if t.kind >= tkAnd && t.kind <= tkWhile {
		return "'" + t.s + "'"
	}
	return "'" + string(rune(t.kind)) + "'"
}

func (p *Parser) errNear(msg string) {
	p.lx.errorAt(msg, tokText(p.tok), p.tok.line)
}

func (p *Parser) errExpected(what string) {
	if what[0] == '<' {
		p.errNear(what + " expected")
	}
	p.errNear(fmt.Sprintf("'%s' expected", what))
}

func tokName(kind int) string {
	switch kind {
	case tkName:
		return "<name>"
	case tkString:
		return "<string>"
	case tkNumber:
		return "<number>"
	}
	if n, ok := symNames[kind]; ok {
		return n
	}
	for k, v := range keywords {
		if v == kind {
			return k
		}
	}
	return string(rune(kind))
}

func (p *Parser) check(kind int) {
	if p.tok.kind != kind {
		p.errExpected(tokName(kind))
	}
}

func (p *Parser) expect(kind int) {
	p.check(kind)
	p.advance()
}

func (p *Parser) accept(kind int) bool {
	if p.tok.kind == kind {
		p.advance()
		return true
	}
	return false
}

func (p *Parser) expectMatch(what, who int, line int) {
	if p.tok.kind != what {
		if line == p.tok.line {
			p.errExpected(tokName(what))
		}
		p.errNear(fmt.Sprintf("'%s' expected (to close '%s' at line %d)", tokName(what), tokName(who), line))
	}
	p.advance()
}

func (p *Parser) name() string {
	p.check(tkName)
	s := p.tok.s
	p.advance()
	return s
}

// ---- scopes ----

func (p *Parser) openScope(loop bool) {
	fs := p.fs
	fs.scope = &blockScope{parent: fs.scope, nactive: len(fs.actives), isLoop: loop}
}

func (p *Parser) closeScope() {
	fs := p.fs
	sc := fs.scope
	fs.actives = fs.actives[:sc.nactive]
	fs.nclose -= sc.nclose
	fs.scope = sc.parent
}

func (p *Parser) declare(name string, attrib int) *VarInfo {
	fs := p.fs
	v := &VarInfo{name: name, slot: len(fs.actives), attrib: attrib}
	fs.actives = append(fs.actives, v)
	if len(fs.actives) > fs.fb.nslots {
		fs.fb.nslots = len(fs.actives)
	}
	return v
}

func (fs *funcState) findLocal(name string) *VarInfo {
	for i := len(fs.actives) - 1; i >= 0; i-- {
		if fs.actives[i].name == name {
			return fs.actives[i]
		}
	}
	return nil
}

func (fs *funcState) upvalIndex(name string) int {
	for i, u := range fs.fb.upvals {
		if u.name == name {
			return i
		}
	}
	if fs.parent == nil {
		return -1
	}
	if v := fs.parent.findLocal(name); v != nil {
		v.captured = true
		fs.fb.upvals = append(fs.fb.upvals, UpvalDesc{name: name, fromLocal: true, slot: v.slot, info: v})
		return len(fs.fb.upvals) - 1
	}
	if idx := fs.parent.upvalIndex(name); idx >= 0 {
		fs.fb.upvals = append(fs.fb.upvals, UpvalDesc{name: name, idx: idx, info: fs.parent.fb.upvals[idx].info})
		return len(fs.fb.upvals) - 1
	}
	return -1
}

func (p *Parser) resolveVar(name string, line int) Expr {
	fs := p.fs
	if v := fs.findLocal(name); v != nil {
		return &ELocal{info: v, line: line}
	}
	if idx := fs.upvalIndex(name); idx >= 0 {
		return &EUpval{idx: idx, info: fs.fb.upvals[idx].info, name: name, line: line}
	}
	env := p.resolveVar("_ENV", line)
	return &EIndex{obj: env, key: &EStr{name}, line: line, global: true}
}

// ---- gotos ----

func (p *Parser) finishGotos(fs *funcState) {
	for _, g := range fs.gotos {
		var prev *blockScope
		for sc := g.scope; sc != nil; prev, sc = sc, sc.parent {
			if l, ok := sc.labels[g.node.name]; ok {
				g.node.label = l
				at := g.nactive
				if prev != nil {
					at = prev.nactive
				}
				if l.nactive > at && !l.atEnd {
					p.lx.errorAt(fmt.Sprintf("<goto %s> at line %d jumps into the scope of local '%s'", g.node.name, g.node.line, l.names[at]), "", l.line)
				}
				break
			}
		}
		if g.node.label == nil {
			p.lx.errorAt(fmt.Sprintf("no visible label '%s' for goto at line %d", g.node.name, g.node.line), "", g.node.line)
		}
	}
}

// ---- statements ----

func blockEnd(k int) bool {
	switch k {
	case tkEOF, tkEnd, tkElse, tkElseif, tkUntil:
		return true
	}
	return false
}

func (p *Parser) block() *Block {
	b := &Block{}
	for !blockEnd(p.tok.kind) {
		if p.tok.kind == tkReturn {
			b.stmts = append(b.stmts, p.retStat())
			break
		}
		if s := p.statement(); s != nil {
			b.stmts = append(b.stmts, s)
			if lb, ok := s.(*SLabel); ok {
				for p.tok.kind == ';' {
					p.advance()
				}
				if blockEnd(p.tok.kind) {
					lb.label.atEnd = true
				}
			}
		}
	}
	return b
}

// scopedBlock parses a block in its own scope.
func (p *Parser) scopedBlock(loop bool) *Block {
	p.openScope(loop)
	b := p.block()
	p.closeScope()
	return b
}

func (p *Parser) retStat() Stmt {
	line := p.tok.line
	p.advance()
	var exprs []Expr
	if !blockEnd(p.tok.kind) && p.tok.kind != ';' {
		exprs = p.exprList()
	}
	p.accept(';')
	if !blockEnd(p.tok.kind) {
		p.errExpected("<eof>")
	}
	tail := false
	if len(exprs) == 1 && p.fs.nclose == 0 {
		switch exprs[0].(type) {
		case *ECall, *EMethod:
			tail = true
		}
	}
	return &SReturn{exprs: exprs, tail: tail, line: line}
}

func (p *Parser) statement() Stmt {
	line := p.tok.line
	switch p.tok.kind {
	case ';':
		p.advance()
		return nil
	case tkIf:
		return p.ifStat(line)
	case tkWhile:
		p.advance()
		cond := p.expr()
		p.expect(tkDo)
		body := p.scopedBlock(true)
		p.expectMatch(tkEnd, tkWhile, line)
		return &SWhile{cond: cond, body: body}
	case tkDo:
		p.advance()
		body := p.scopedBlock(false)
		p.expectMatch(tkEnd, tkDo, line)
		return &SDo{body}
	case tkFor:
		return p.forStat(line)
	case tkRepeat:
		p.advance()
		p.openScope(true)
		body := p.block()
		p.expectMatch(tkUntil, tkRepeat, line)
		cond := p.expr()
		p.closeScope()
		return &SRepeat{body: body, cond: cond}
	case tkFunction:
		return p.funcStat(line)
	case tkLocal:
		p.advance()
		if p.accept(tkFunction) {
			name := p.name()
			v := p.declare(name, attrNone)
			fn := p.funcBody(false, line, "local '"+name+"'")
			return &SLocalFunc{v: v, fn: fn}
		}
		return p.localStat(line)
	case tkDbColon:
		p.advance()
		name := p.name()
		p.expect(tkDbColon)
		for sc := p.fs.scope; sc != nil; sc = sc.parent {
			if l, ok := sc.labels[name]; ok {
				p.lx.errorAt(fmt.Sprintf("label '%s' already defined on line %d", name, l.line), "", line)
			}
		}
		l := &Label{name: name, line: line, nactive: len(p.fs.actives)}
		for _, v := range p.fs.actives {
			l.names = append(l.names, v.name)
		}
		sc := p.fs.scope
		if sc.labels == nil {
			sc.labels = map[string]*Label{}
		}
		sc.labels[name] = l
		return &SLabel{l}
	case tkReturn:
		return p.retStat()
	case tkBreak:
		p.advance()
		hasLoop := false
		for sc := p.fs.scope; sc != nil; sc = sc.parent {
			if sc.isLoop {
				hasLoop = true
			}
		}
		if !hasLoop {
			p.lx.errorAt("break outside a loop at line "+fmt.Sprint(line), "", line)
		}
		return &SBreak{}
	case tkGoto:
		p.advance()
		name := p.name()
		g := &SGoto{name: name, line: line}
		p.fs.gotos = append(p.fs.gotos, pendingGoto{g, p.fs.scope, len(p.fs.actives)})
		return g
	}
	return p.exprStat(line)
}

func (p *Parser) ifStat(line int) Stmt {
	s := &SIf{}
	for {
		p.advance() // if / elseif
		cond := p.expr()
		p.expect(tkThen)
		blk := p.scopedBlock(false)
		s.conds = append(s.conds, cond)
		s.blocks = append(s.blocks, blk)
		if p.tok.kind != tkElseif {
			break
		}
	}
	if p.accept(tkElse) {
		s.els = p.scopedBlock(false)
	}
	p.expectMatch(tkEnd, tkIf, line)
	return s
}

func (p *Parser) forStat(line int) Stmt {
	p.advance()
	n1 := p.name()
	switch p.tok.kind {
	case '=':
		p.advance()
		start := p.expr()
		p.expect(',')
		limit := p.expr()
		var step Expr
		if p.accept(',') {
			step = p.expr()
		}
		p.expect(tkDo)
		p.openScope(true)
		v := p.declare(n1, attrNone)
		body := p.scopedBlock(false)
		p.closeScope()
		p.expectMatch(tkEnd, tkFor, line)
		return &SNumFor{v: v, start: start, limit: limit, step: step, body: body, line: line}
	case ',', tkIn:
		names := []string{n1}
		for p.accept(',') {
			names = append(names, p.name())
		}
		p.expect(tkIn)
		exprs := p.exprList()
		p.expect(tkDo)
		p.openScope(true)
		var vars []*VarInfo
		for _, n := range names {
			vars = append(vars, p.declare(n, attrNone))
		}
		body := p.scopedBlock(false)
		p.closeScope()
		p.expectMatch(tkEnd, tkFor, line)
		return &SGenFor{vars: vars, exprs: exprs, body: body, line: line}
	}
	p.errNear("'=' or 'in' expected")
	return nil
}

func (p *Parser) funcStat(line int) Stmt {
	p.advance()
	nline := p.tok.line
	n := p.name()
	target := p.resolveVar(n, nline)
	fullname := n
	isMethod := false
	for p.tok.kind == '.' || p.tok.kind == ':' {
		colon := p.tok.kind == ':'
		p.advance()
		k := p.name()
		target = &EIndex{obj: target, key: &EStr{k}, line: nline}
		if colon {
			fullname += ":" + k
			isMethod = true
			break
		}
		fullname += "." + k
	}
	hint := "function '" + fullname + "'"
	if isMethod {
		hint = "method '" + p.lastNameOf(fullname) + "'"
	}
	fn := p.funcBody(isMethod, line, hint)
	p.checkAssignable(target)
	return &SAssign{targets: []Expr{target}, exprs: []Expr{fn}, line: line}
}

func (p *Parser) lastNameOf(full string) string {
	for i := len(full) - 1; i >= 0; i-- {
		if full[i] == ':' {
			return full[i+1:]
		}
	}
	return full
}

func (p *Parser) localStat(line int) Stmt {
	type nv struct {
		name string
		attr int
	}
	var names []nv
	nclose := 0
	for {
		n := p.name()
		attr := attrNone
		if p.accept('<') {
			a := p.name()
			switch a {
			case "const":
				attr = attrConst
			case "close":
				attr = attrClose
				nclose++
				if nclose > 1 {
					p.lx.errorAt("multiple to-be-closed variables in local list", "", p.tok.line)
				}
			default:
				p.lx.errorAt(fmt.Sprintf("unknown attribute '%s'", a), "", p.tok.line)
			}
			p.expect('>')
		}
		names = append(names, nv{n, attr})
		if !p.accept(',') {
			break
		}
	}
	var exprs []Expr
	if p.accept('=') {
		exprs = p.exprList()
	}
	s := &SLocal{exprs: exprs, line: line}
	for _, n := range names {
		v := p.declare(n.name, n.attr)
		s.vars = append(s.vars, v)
		if n.attr == attrClose {
			p.fs.nclose++
			p.fs.scope.nclose++
		}
	}
	return s
}

func (p *Parser) checkAssignable(e Expr) {
	switch t := e.(type) {
	case *ELocal:
		if t.info.attrib != attrNone {
			p.lx.errorAt(fmt.Sprintf("attempt to assign to const variable '%s'", t.info.name), "", p.tok.line)
		}
	case *EUpval:
		if t.info != nil && t.info.attrib != attrNone {
			p.lx.errorAt(fmt.Sprintf("attempt to assign to const variable '%s'", t.name), "", p.tok.line)
		}
	case *EIndex:
	default:
		p.errNear("syntax error")
	}
}

func (p *Parser) exprStat(line int) Stmt {
	e := p.suffixedExpr()
	if p.tok.kind == '=' || p.tok.kind == ',' {
		targets := []Expr{e}
		for p.accept(',') {
			targets = append(targets, p.suffixedExpr())
		}
		for _, t := range targets {
			p.checkAssignable(t)
		}
		p.expect('=')
		exprs := p.exprList()
		return &SAssign{targets: targets, exprs: exprs, line: line}
	}
	switch e.(type) {
	case *ECall, *EMethod:
		return &SCall{call: e, line: line}
	}
	p.errNear("syntax error")
	return nil
}

// ---- functions ----

func (p *Parser) funcBody(isMethod bool, line int, hint string) *EFunc {
	fb := &FuncBody{line: line, name: hint}
	fs := &funcState{parent: p.fs, fb: fb}
	p.fs = fs
	p.openScope(false)
	if isMethod {
		fb.params = append(fb.params, p.declare("self", attrNone))
	}
	p.expect('(')
	if p.tok.kind != ')' {
		for {
			if p.tok.kind == tkDots {
				p.advance()
				fb.isVararg = true
				break
			}
			fb.params = append(fb.params, p.declare(p.name(), attrNone))
			if !p.accept(',') {
				break
			}
		}
	}
	p.expect(')')
	fb.body = p.block()
	fb.lastLine = p.tok.line
	p.expectMatch(tkEnd, tkFunction, line)
	p.closeScope()
	p.finishGotos(fs)
	p.fs = fs.parent
	return &EFunc{fb}
}

// ---- expressions ----

func (p *Parser) exprList() []Expr {
	list := []Expr{p.expr()}
	for p.accept(',') {
		list = append(list, p.expr())
	}
	return list
}

func (p *Parser) primaryExpr() Expr {
	line := p.tok.line
	switch p.tok.kind {
	case tkName:
		n := p.tok.s
		p.advance()
		return p.resolveVar(n, line)
	case '(':
		p.advance()
		e := p.expr()
		p.expectMatch(')', '(', line)
		switch e.(type) {
		case *ECall, *EMethod, *EVararg:
			return &EParen{e}
		}
		return &EParen{e}
	}
	p.errNear("unexpected symbol")
	return nil
}

func (p *Parser) suffixedExpr() Expr {
	e := p.primaryExpr()
	for {
		line := p.tok.line
		switch p.tok.kind {
		case '.':
			p.advance()
			k := p.name()
			e = &EIndex{obj: e, key: &EStr{k}, line: line}
		case '[':
			p.advance()
			k := p.expr()
			p.expect(']')
			e = &EIndex{obj: e, key: k, line: line}
		case ':':
			p.advance()
			n := p.name()
			args := p.callArgs()
			e = &EMethod{obj: e, name: n, args: args, line: line}
		case '(', tkString, '{':
			args := p.callArgs()
			e = &ECall{fn: e, args: args, line: line}
		default:
			return e
		}
	}
}

func (p *Parser) callArgs() []Expr {
	switch p.tok.kind {
	case tkString:
		s := p.tok.s
		p.advance()
		return []Expr{&EStr{s}}
	case '{':
		return []Expr{p.tableCons()}
	case '(':
		line := p.tok.line
		p.advance()
		if p.accept(')') {
			return nil
		}
		args := p.exprList()
		p.expectMatch(')', '(', line)
		return args
	}
	p.errNear("function arguments expected")
	return nil
}

func (p *Parser) tableCons() Expr {
	line := p.tok.line
	p.expect('{')
	t := &ETable{line: line}
	for p.tok.kind != '}' {
		switch {
		case p.tok.kind == tkName && p.peek().kind == '=':
			k := p.tok.s
			p.advance()
			p.advance()
			t.items = append(t.items, TItem{&EStr{k}, p.expr()})
		case p.tok.kind == '[':
			p.advance()
			k := p.expr()
			p.expect(']')
			p.expect('=')
			t.items = append(t.items, TItem{k, p.expr()})
		default:
			t.items = append(t.items, TItem{nil, p.expr()})
		}
		if !p.accept(',') && !p.accept(';') {
			break
		}
	}
	p.expectMatch('}', '{', line)
	return t
}

func (p *Parser) simpleExpr() Expr {
	line := p.tok.line
	switch p.tok.kind {
	case tkNumber:
		v := p.tok.n
		p.advance()
		return &ENum{v}
	case tkString:
		s := p.tok.s
		p.advance()
		return &EStr{s}
	case tkNil:
		p.advance()
		return &ENil{}
	case tkTrue:
		p.advance()
		return &ETrue{}
	case tkFalse:
		p.advance()
		return &EFalse{}
	case tkDots:
		if !p.fs.fb.isVararg {
			p.errNear("cannot use '...' outside a vararg function")
		}
		p.advance()
		return &EVararg{line}
	case '{':
		return p.tableCons()
	case tkFunction:
		p.advance()
		return p.funcBody(false, line, "")
	}
	return p.suffixedExpr()
}

type prio struct{ l, r int }

var binPrio = map[int]prio{
	'+': {10, 10}, '-': {10, 10}, '*': {11, 11}, '%': {11, 11}, '^': {14, 13},
	'/': {11, 11}, tkIdiv: {11, 11}, '&': {6, 6}, '|': {4, 4}, '~': {5, 5},
	tkShl: {7, 7}, tkShr: {7, 7}, tkConcat: {9, 8},
	tkEq: {3, 3}, '<': {3, 3}, tkLe: {3, 3}, tkNe: {3, 3}, '>': {3, 3}, tkGe: {3, 3},
	tkAnd: {2, 2}, tkOr: {1, 1},
}

var binOps = map[int]int{
	'+': opAdd, '-': opSub, '*': opMul, '%': opMod, '^': opPow, '/': opDiv, tkIdiv: opIdiv,
	'&': opBand, '|': opBor, '~': opBxor, tkShl: opShl, tkShr: opShr, tkConcat: opConcat,
	tkEq: opEq, '<': opLt, tkLe: opLe, tkNe: opNe, '>': opGt, tkGe: opGe, tkAnd: opAnd, tkOr: opOr,
}

const unaryPrio = 12

func (p *Parser) expr() Expr { return p.subExpr(0) }

func (p *Parser) subExpr(limit int) Expr {
	var e Expr
	line := p.tok.line
	switch p.tok.kind {
	case tkNot, '-', '#', '~':
		k := p.tok.kind
		p.advance()
		operand := p.subExpr(unaryPrio)
		op := map[int]int{tkNot: opNot, '-': opNeg, '#': opLen, '~': opBnot}[k]
		e = foldUnary(op, operand, line)
	default:
		e = p.simpleExpr()
	}
	for {
		k := p.tok.kind
		pr, ok := binPrio[k]
		if !ok || pr.l <= limit {
			return e
		}
		line := p.tok.line
		p.advance()
		r := p.subExpr(pr.r)
		e = &EBin{op: binOps[k], l: e, r: r, line: line}
	}
}

func foldUnary(op int, e Expr, line int) Expr {
	if op == opNeg {
		if n, ok := e.(*ENum); ok {
			switch v := n.v.(type) {
			case int64:
				return &ENum{-v}
			case float64:
				return &ENum{-v}
			}
		}
	}
	return &EUn{op: op, e: e, line: line}
}
