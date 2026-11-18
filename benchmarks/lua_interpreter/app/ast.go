package main

type Expr interface{}
type Stmt interface{}

const (
	opAdd = iota
	opSub
	opMul
	opDiv
	opIdiv
	opMod
	opPow
	opBand
	opBor
	opBxor
	opShl
	opShr
	opConcat
	opEq
	opNe
	opLt
	opLe
	opGt
	opGe
	opAnd
	opOr
	// unary
	opNeg
	opNot
	opLen
	opBnot
)

const (
	attrNone = iota
	attrConst
	attrClose
)

type VarInfo struct {
	name     string
	slot     int
	captured bool
	attrib   int
}

type UpvalDesc struct {
	name      string
	fromLocal bool
	slot      int // parent's local slot
	idx       int // parent's upvalue index
	info      *VarInfo
}

type FuncBody struct {
	params   []*VarInfo
	isVararg bool
	body     *Block
	nslots   int
	upvals   []UpvalDesc
	name     string
	line     int
	lastLine int
	isMain   bool
}

type Block struct {
	stmts []Stmt
}

type Label struct {
	name    string
	line    int
	nactive int
	names   []string
	atEnd   bool
}

type (
	ENil    struct{}
	ETrue   struct{}
	EFalse  struct{}
	EVararg struct{ line int }
	ENum    struct{ v Value }
	EStr    struct{ s string }
	ELocal  struct {
		info *VarInfo
		line int
	}
	EUpval struct {
		idx  int
		info *VarInfo
		name string
		line int
	}
	EIndex struct {
		obj, key Expr
		line     int
		global   bool
	}
	ECall struct {
		fn   Expr
		args []Expr
		line int
	}
	EMethod struct {
		obj  Expr
		name string
		args []Expr
		line int
	}
	EBin struct {
		op   int
		l, r Expr
		line int
	}
	EUn struct {
		op   int
		e    Expr
		line int
	}
	EParen struct{ e Expr }
	EFunc  struct{ fb *FuncBody }
	TItem  struct{ key, val Expr }
	ETable struct {
		items []TItem
		line  int
	}
)

type (
	SLocal struct {
		vars  []*VarInfo
		exprs []Expr
		line  int
	}
	SAssign struct {
		targets []Expr
		exprs   []Expr
		line    int
	}
	SCall struct {
		call Expr
		line int
	}
	SDo    struct{ body *Block }
	SWhile struct {
		cond Expr
		body *Block
	}
	SRepeat struct {
		body *Block
		cond Expr
	}
	SIf struct {
		conds  []Expr
		blocks []*Block
		els    *Block
	}
	SNumFor struct {
		v                  *VarInfo
		start, limit, step Expr
		body               *Block
		line               int
	}
	SGenFor struct {
		vars  []*VarInfo
		exprs []Expr
		body  *Block
		line  int
	}
	SLocalFunc struct {
		v  *VarInfo
		fn *EFunc
	}
	SReturn struct {
		exprs []Expr
		tail  bool
		line  int
	}
	SBreak struct{}
	SGoto  struct {
		name  string
		label *Label
		line  int
	}
	SLabel struct{ label *Label }
)
