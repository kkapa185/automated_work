package main

import (
	"fmt"
	"math"
	"runtime"
	"strings"
)

type ctl int

const (
	cNone ctl = iota
	cBreak
	cReturn
	cGoto
	cTail
)

const maxDepth = 200000

type Proto struct {
	name      string
	chunk     string // short source
	line      int
	lastLine  int
	nparams   int
	isVararg  bool
	nslots    int
	body      func(*Frame) ctl
	upvals    []UpvalDesc
	paramCapt []bool
	anyCapt   bool
	isMain    bool
}

type Frame struct {
	slots     []Value
	varargs   []Value
	ret       []Value
	fn        *Closure
	parent    *Frame
	th        *Thread
	line      int
	gotoLabel *Label
	tailFn    Value
	tailArgs  []Value
	marker    bool
}

type frame8 struct {
	Frame
	inl [8]Value
}

type Thread struct {
	top   *Frame
	depth int
	co    *Coroutine
}

type Coroutine struct {
	th     *Thread
	fn     Value
	status string
	// fields for the coroutine implementation
	resumeCh chan []Value
	yieldCh  chan coMsg
	started  bool
	parent   *Thread
	err      *LuaError
}

type coMsg struct {
	vals []Value
	err  *LuaError
	done bool
}

// LuaError is the panic payload for Lua errors.
type LuaError struct {
	value     Value
	traceback string
}

func (e *LuaError) Error() string {
	if s, ok := e.value.(string); ok {
		return s
	}
	return fmt.Sprintf("(error object is a %s value)", typeName(e.value))
}

// coKill is the panic payload used to unwind a closed coroutine.
type coKill struct{}

var stringMeta *Table

func (fr *Frame) where() string {
	if fr == nil || fr.marker || fr.fn == nil {
		return ""
	}
	return fmt.Sprintf("%s:%d: ", fr.fn.proto.chunk, fr.line)
}

func (th *Thread) whereLevel(level int) string {
	fr := th.top
	for i := 1; i < level && fr != nil; i++ {
		fr = fr.parent
	}
	return fr.where()
}

// rtError raises a runtime error with position information.
func (th *Thread) rtError(format string, args ...interface{}) {
	msg := fmt.Sprintf(format, args...)
	panic(&LuaError{value: th.whereLevel(1) + msg})
}

func (th *Thread) throw(v Value) { panic(&LuaError{value: v}) }

func newFrame(p *Proto) *Frame {
	if p.nslots <= 8 {
		f := &frame8{}
		f.slots = f.inl[:p.nslots]
		return &f.Frame
	}
	return &Frame{slots: make([]Value, p.nslots)}
}

func (th *Thread) callLua(cl *Closure, args []Value) []Value {
	th.depth++
	if th.depth > maxDepth {
		th.depth--
		th.rtError("stack overflow")
	}
	parent := th.top
	for {
		p := cl.proto
		fr := newFrame(p)
		fr.th = th
		fr.fn = cl
		fr.parent = parent
		th.top = fr
		np := p.nparams
		if p.anyCapt {
			for i := 0; i < np; i++ {
				var v Value
				if i < len(args) {
					v = args[i]
				}
				if p.paramCapt[i] {
					fr.slots[i] = &Cell{v}
				} else {
					fr.slots[i] = v
				}
			}
		} else {
			n := np
			if len(args) < n {
				n = len(args)
			}
			copy(fr.slots, args[:n])
		}
		if p.isVararg && len(args) > np {
			fr.varargs = args[np:]
		}
		c := p.body(fr)
		if c == cTail {
			f := fr.tailFn
			args = fr.tailArgs
			if ncl, ok := f.(*Closure); ok {
				cl = ncl
				continue
			}
			// not reached: non-closure tail calls are executed in place
			th.top = parent
			th.depth--
			return th.callValue(f, args)
		}
		th.top = parent
		th.depth--
		return fr.ret
	}
}

// callValue calls any value without pushing a marker frame.
func (th *Thread) callValue(f Value, args []Value) []Value {
	switch fv := f.(type) {
	case *Closure:
		return th.callLua(fv, args)
	case *GoFunction:
		return fv.fn(th, args)
	}
	return th.callMeta(f, args, "")
}

// call is used by native functions to invoke callbacks (pushes a C marker).
func (th *Thread) call(f Value, args []Value) []Value {
	m := &Frame{marker: true, parent: th.top, th: th}
	th.top = m
	r := th.callValue(f, args)
	th.top = m.parent
	return r
}

func (th *Thread) call1(f Value, args ...Value) Value {
	r := th.call(f, args)
	if len(r) == 0 {
		return nil
	}
	return r[0]
}

func (th *Thread) callMeta(f Value, args []Value, desc string) []Value {
	for i := 0; i < 100; i++ {
		h := th.metaOf(f, "__call")
		if h == nil {
			th.rtError("attempt to call a %s value%s", th.objTypeName(f), desc)
		}
		na := make([]Value, 0, len(args)+1)
		na = append(na, f)
		na = append(na, args...)
		args = na
		f = h
		switch fv := f.(type) {
		case *Closure:
			return th.callLua(fv, args)
		case *GoFunction:
			return fv.fn(th, args)
		}
	}
	th.rtError("'__call' chain too long")
	return nil
}

func (th *Thread) getMeta(v Value) *Table {
	switch t := v.(type) {
	case *Table:
		return t.meta
	case string:
		return stringMeta
	case *Userdata:
		return t.meta
	}
	return nil
}

func (th *Thread) metaOf(v Value, ev string) Value {
	mt := th.getMeta(v)
	if mt == nil {
		return nil
	}
	return mt.getStr(ev)
}

func (th *Thread) objTypeName(v Value) string {
	if mt := th.getMeta(v); mt != nil {
		if _, isT := v.(*Table); isT || isUD(v) {
			if n, ok := mt.getStr("__name").(string); ok {
				return n
			}
		}
	}
	return typeName(v)
}

func isUD(v Value) bool { _, ok := v.(*Userdata); return ok }

func first(r []Value) Value {
	if len(r) == 0 {
		return nil
	}
	return r[0]
}

// ---- indexing ----

func (th *Thread) index(obj, key Value, desc string) Value {
	for loop := 0; loop < 2000; loop++ {
		var h Value
		if t, ok := obj.(*Table); ok {
			v := t.get(key)
			if v != nil {
				return v
			}
			if t.meta == nil {
				return nil
			}
			h = t.meta.getStr("__index")
			if h == nil {
				return nil
			}
		} else {
			h = th.metaOf(obj, "__index")
			if h == nil {
				th.indexError(obj, key, desc)
			}
		}
		switch h.(type) {
		case *Closure, *GoFunction:
			return first(th.callValue(h, []Value{obj, key}))
		}
		obj = h
		desc = ""
	}
	th.rtError("'__index' chain too long; possible loop")
	return nil
}

func (th *Thread) indexError(obj, key Value, desc string) {
	if desc == "" {
		if ks, ok := key.(string); ok {
			desc = fmt.Sprintf(" (field '%s')", ks)
		}
	}
	th.rtError("attempt to index a %s value%s", th.objTypeName(obj), desc)
}

func (th *Thread) checkKey(k Value) {
	if k == nil {
		th.rtError("index is nil")
	}
	if f, ok := k.(float64); ok && math.IsNaN(f) {
		th.rtError("index is NaN")
	}
}

func (th *Thread) setIndex(obj, key, val Value, desc string) {
	for loop := 0; loop < 2000; loop++ {
		var h Value
		if t, ok := obj.(*Table); ok {
			if t.meta == nil {
				th.checkKey(key)
				t.set(key, val)
				return
			}
			if t.get(key) != nil {
				t.set(key, val)
				return
			}
			h = t.meta.getStr("__newindex")
			if h == nil {
				th.checkKey(key)
				t.set(key, val)
				return
			}
		} else {
			h = th.metaOf(obj, "__newindex")
			if h == nil {
				th.indexError(obj, key, desc)
			}
		}
		switch h.(type) {
		case *Closure, *GoFunction:
			th.callValue(h, []Value{obj, key, val})
			return
		}
		obj = h
		desc = ""
	}
	th.rtError("'__newindex' chain too long; possible loop")
}

// ---- tostring ----

func (th *Thread) tostr(v Value) string {
	switch x := v.(type) {
	case string:
		return x
	case int64, float64:
		return numToString(x)
	case nil:
		return "nil"
	case bool:
		if x {
			return "true"
		}
		return "false"
	}
	if h := th.metaOf(v, "__tostring"); h != nil {
		r := th.callValue(h, []Value{v})
		s, ok := first(r).(string)
		if !ok {
			if n, ok2 := first(r).(int64); ok2 {
				return numToString(n)
			}
			if n, ok2 := first(r).(float64); ok2 {
				return numToString(n)
			}
			th.rtError("'__tostring' must return a string")
		}
		return s
	}
	name := typeName(v)
	if mt := th.getMeta(v); mt != nil {
		if n, ok := mt.getStr("__name").(string); ok {
			name = n
		}
	}
	return fmt.Sprintf("%s: %p", name, v)
}

// ---- arithmetic ----

func opEvent(op int) string {
	switch op {
	case opAdd:
		return "__add"
	case opSub:
		return "__sub"
	case opMul:
		return "__mul"
	case opDiv:
		return "__div"
	case opMod:
		return "__mod"
	case opPow:
		return "__pow"
	case opIdiv:
		return "__idiv"
	case opBand:
		return "__band"
	case opBor:
		return "__bor"
	case opBxor:
		return "__bxor"
	case opShl:
		return "__shl"
	case opShr:
		return "__shr"
	case opNeg:
		return "__unm"
	case opBnot:
		return "__bnot"
	case opConcat:
		return "__concat"
	}
	return ""
}

func imod(a, b int64) int64 {
	if b == -1 {
		return 0
	}
	m := a % b
	if m != 0 && (m^b) < 0 {
		m += b
	}
	return m
}

func idiv(a, b int64) int64 {
	if b == -1 {
		return -a
	}
	q := a / b
	if (a%b != 0) && ((a ^ b) < 0) {
		q--
	}
	return q
}

func fmod(a, b float64) float64 {
	if math.IsInf(b, 0) && !math.IsInf(a, 0) && !math.IsNaN(a) {
		if (a >= 0) == (b > 0) || a == 0 {
			return a
		}
		return b
	}
	m := math.Mod(a, b)
	if m != 0 && (m < 0) != (b < 0) {
		m += b
	}
	return m
}

func shiftLeft(a int64, n int64) int64 {
	if n <= -64 || n >= 64 {
		return 0
	}
	if n >= 0 {
		return int64(uint64(a) << uint(n))
	}
	return int64(uint64(a) >> uint(-n))
}

func isBitop(op int) bool {
	switch op {
	case opBand, opBor, opBxor, opShl, opShr, opBnot:
		return true
	}
	return false
}

func (th *Thread) arith(op int, a, b Value, da, db string) Value {
	if isBitop(op) {
		x, ok1 := toIntStrict(a)
		y, ok2 := toIntStrict(b)
		if ok1 && ok2 {
			switch op {
			case opBand:
				return x & y
			case opBor:
				return x | y
			case opBxor:
				return x ^ y
			case opShl:
				return shiftLeft(x, y)
			case opShr:
				return shiftLeft(x, -y)
			case opBnot:
				return ^x
			}
		}
	} else {
		x, ok1 := toNumber(a)
		y, ok2 := toNumber(b)
		if ok1 && ok2 {
			if v, ok := th.arithNum(op, x, y); ok {
				return v
			}
		}
	}
	ev := opEvent(op)
	h := th.metaOf(a, ev)
	if h == nil {
		h = th.metaOf(b, ev)
	}
	if h != nil {
		return first(th.callValue(h, []Value{a, b}))
	}
	// error
	if isBitop(op) {
		_, an := toNumber(a)
		_, bn := toNumber(b)
		if an && bn {
			th.rtError("number has no integer representation")
		}
		bad, d := a, da
		if an {
			bad, d = b, db
		}
		th.rtError("attempt to perform bitwise operation on a %s value%s", th.objTypeName(bad), d)
	}
	bad, d := b, db
	if _, ok := toNumber(a); !ok {
		bad, d = a, da
	}
	th.rtError("attempt to perform arithmetic on a %s value%s", th.objTypeName(bad), d)
	return nil
}

// toIntStrict converts for bitwise ops: ints, integral floats, numeric strings.
func toIntStrict(v Value) (int64, bool) { return toInteger(v) }

func (th *Thread) arithNum(op int, x, y Value) (Value, bool) {
	xi, xIsInt := x.(int64)
	yi, yIsInt := y.(int64)
	if xIsInt && yIsInt {
		switch op {
		case opAdd:
			return xi + yi, true
		case opSub:
			return xi - yi, true
		case opMul:
			return xi * yi, true
		case opIdiv:
			if yi == 0 {
				th.rtError("attempt to perform 'n//0'")
			}
			return idiv(xi, yi), true
		case opMod:
			if yi == 0 {
				th.rtError("attempt to perform 'n%%0'")
			}
			return imod(xi, yi), true
		}
	}
	xf, _ := toFloat(x)
	yf, _ := toFloat(y)
	switch op {
	case opAdd:
		return xf + yf, true
	case opSub:
		return xf - yf, true
	case opMul:
		return xf * yf, true
	case opDiv:
		return xf / yf, true
	case opPow:
		return math.Pow(xf, yf), true
	case opIdiv:
		return math.Floor(xf / yf), true
	case opMod:
		return fmod(xf, yf), true
	}
	return nil, false
}

func (th *Thread) unm(a Value, da string) Value {
	switch x := a.(type) {
	case int64:
		return -x
	case float64:
		return -x
	case string:
		if n, ok := str2number(x); ok {
			return th.unm(n, da)
		}
	}
	if h := th.metaOf(a, "__unm"); h != nil {
		return first(th.callValue(h, []Value{a, a}))
	}
	th.rtError("attempt to perform arithmetic on a %s value%s", th.objTypeName(a), da)
	return nil
}

func (th *Thread) bnot(a Value, da string) Value {
	return th.arith(opBnot, a, a, da, da)
}

func (th *Thread) length(a Value, da string) Value {
	switch x := a.(type) {
	case string:
		return int64(len(x))
	case *Table:
		if x.meta != nil {
			if h := x.meta.getStr("__len"); h != nil {
				return first(th.callValue(h, []Value{a}))
			}
		}
		return x.length()
	}
	if h := th.metaOf(a, "__len"); h != nil {
		return first(th.callValue(h, []Value{a}))
	}
	th.rtError("attempt to get length of a %s value%s", th.objTypeName(a), da)
	return nil
}

// ---- concat ----

func isStrNum(v Value) bool {
	switch v.(type) {
	case string, int64, float64:
		return true
	}
	return false
}

func (th *Thread) concat(vals []Value, descs []string) Value {
	all := true
	n := 0
	for _, v := range vals {
		switch s := v.(type) {
		case string:
			n += len(s)
		case int64, float64:
			n += 8
		default:
			all = false
		}
	}
	if all {
		var sb strings.Builder
		sb.Grow(n)
		for _, v := range vals {
			if s, ok := v.(string); ok {
				sb.WriteString(s)
			} else {
				sb.WriteString(numToString(v))
			}
		}
		return sb.String()
	}
	acc := vals[len(vals)-1]
	accDesc := descs[len(vals)-1]
	for i := len(vals) - 2; i >= 0; i-- {
		acc = th.concat2(vals[i], acc, descs[i], accDesc)
		accDesc = ""
	}
	return acc
}

func (th *Thread) concat2(a, b Value, da, db string) Value {
	if isStrNum(a) && isStrNum(b) {
		return th.tostr(a) + th.tostr(b)
	}
	h := th.metaOf(a, "__concat")
	if h == nil {
		h = th.metaOf(b, "__concat")
	}
	if h != nil {
		return first(th.callValue(h, []Value{a, b}))
	}
	bad, d := a, da
	if isStrNum(a) {
		bad, d = b, db
	}
	th.rtError("attempt to concatenate a %s value%s", th.objTypeName(bad), d)
	return nil
}

// ---- comparison ----

func rawEquals(a, b Value) bool {
	switch x := a.(type) {
	case int64:
		switch y := b.(type) {
		case int64:
			return x == y
		case float64:
			i, ok := floatToInt(y)
			return ok && i == x
		}
		return false
	case float64:
		switch y := b.(type) {
		case float64:
			return x == y
		case int64:
			i, ok := floatToInt(x)
			return ok && i == y
		}
		return false
	case string:
		y, ok := b.(string)
		return ok && x == y
	case bool:
		y, ok := b.(bool)
		return ok && x == y
	case nil:
		return b == nil
	}
	return a == b
}

func (th *Thread) equals(a, b Value) bool {
	if rawEquals(a, b) {
		return true
	}
	var h Value
	switch x := a.(type) {
	case *Table:
		if _, ok := b.(*Table); !ok {
			return false
		}
		if x.meta != nil {
			h = x.meta.getStr("__eq")
		}
		if h == nil {
			h = th.metaOf(b, "__eq")
		}
	case *Userdata:
		if _, ok := b.(*Userdata); !ok {
			return false
		}
		h = th.metaOf(a, "__eq")
		if h == nil {
			h = th.metaOf(b, "__eq")
		}
	default:
		return false
	}
	if h == nil {
		return false
	}
	return truthy(first(th.callValue(h, []Value{a, b})))
}

func ltIntFloat(i int64, f float64) bool {
	if math.IsNaN(f) {
		return false
	}
	if f >= 9223372036854775808.0 {
		return true
	}
	if f <= -9223372036854775808.0 {
		return false
	}
	return i < int64(math.Ceil(f))
}

func leIntFloat(i int64, f float64) bool {
	if math.IsNaN(f) {
		return false
	}
	if f >= 9223372036854775808.0 {
		return true
	}
	if f < -9223372036854775808.0 {
		return false
	}
	return i <= int64(math.Floor(f))
}

func ltFloatInt(f float64, i int64) bool {
	if math.IsNaN(f) {
		return false
	}
	if f >= 9223372036854775808.0 {
		return false
	}
	if f < -9223372036854775808.0 {
		return true
	}
	return int64(math.Floor(f)) < i
}

func leFloatInt(f float64, i int64) bool {
	if math.IsNaN(f) {
		return false
	}
	if f >= 9223372036854775808.0 {
		return false
	}
	if f <= -9223372036854775808.0 {
		return true
	}
	return int64(math.Ceil(f)) <= i
}

func (th *Thread) lessThan(a, b Value) bool {
	switch x := a.(type) {
	case int64:
		switch y := b.(type) {
		case int64:
			return x < y
		case float64:
			return ltIntFloat(x, y)
		}
	case float64:
		switch y := b.(type) {
		case float64:
			return x < y
		case int64:
			return ltFloatInt(x, y)
		}
	case string:
		if y, ok := b.(string); ok {
			return x < y
		}
	}
	return th.cmpMeta(a, b, "__lt")
}

func (th *Thread) lessEq(a, b Value) bool {
	switch x := a.(type) {
	case int64:
		switch y := b.(type) {
		case int64:
			return x <= y
		case float64:
			return leIntFloat(x, y)
		}
	case float64:
		switch y := b.(type) {
		case float64:
			return x <= y
		case int64:
			return leFloatInt(x, y)
		}
	case string:
		if y, ok := b.(string); ok {
			return x <= y
		}
	}
	return th.cmpMeta(a, b, "__le")
}

func (th *Thread) cmpMeta(a, b Value, ev string) bool {
	h := th.metaOf(a, ev)
	if h == nil {
		h = th.metaOf(b, ev)
	}
	if h != nil {
		return truthy(first(th.callValue(h, []Value{a, b})))
	}
	t1, t2 := th.objTypeName(a), th.objTypeName(b)
	if t1 == t2 {
		th.rtError("attempt to compare two %s values", t1)
	}
	th.rtError("attempt to compare %s with %s", t1, t2)
	return false
}

// ---- pcall ----

func toLuaError(r interface{}) *LuaError {
	switch e := r.(type) {
	case *LuaError:
		return e
	case *SyntaxError:
		return &LuaError{value: e.msg}
	case runtime.Error:
		return &LuaError{value: "internal error: " + e.Error()}
	}
	return nil
}

// pcall runs f protected. On error returns (nil, err).
func (th *Thread) pcall(f Value, args []Value, handler Value) (res []Value, err *LuaError) {
	savedTop, savedDepth := th.top, th.depth
	defer func() {
		if r := recover(); r != nil {
			le := toLuaError(r)
			if le == nil {
				panic(r)
			}
			if handler != nil {
				th.depth = savedDepth
				th.depth++
				le = th.runHandler(handler, le)
			}
			th.top, th.depth = savedTop, savedDepth
			res, err = nil, le
		}
	}()
	res = th.call(f, args)
	return res, nil
}

func (th *Thread) runHandler(handler Value, le *LuaError) (out *LuaError) {
	defer func() {
		if r := recover(); r != nil {
			if e2 := toLuaError(r); e2 != nil {
				out = e2
				return
			}
			panic(r)
		}
	}()
	r := th.call(handler, []Value{le.value})
	return &LuaError{value: first(r)}
}

// ---- traceback ----

func (th *Thread) traceback(msg string, from *Frame) string {
	var sb strings.Builder
	if msg != "" {
		sb.WriteString(msg)
		sb.WriteString("\n")
	}
	sb.WriteString("stack traceback:")
	n := 0
	for fr := from; fr != nil; fr = fr.parent {
		n++
		if n > 22 {
			sb.WriteString("\n\t...")
			break
		}
		if fr.marker || fr.fn == nil {
			sb.WriteString("\n\t[C]: in ?")
			continue
		}
		p := fr.fn.proto
		sb.WriteString(fmt.Sprintf("\n\t%s:%d: in ", p.chunk, fr.line))
		if p.isMain {
			sb.WriteString("main chunk")
		} else if p.name != "" {
			sb.WriteString(p.name)
		} else {
			sb.WriteString(fmt.Sprintf("function <%s:%d>", p.chunk, p.line))
		}
	}
	sb.WriteString("\n\t[C]: in ?")
	return sb.String()
}
