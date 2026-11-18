package mal

// Env is a lexical environment with an optional outer environment.
type Env struct {
	data  map[Symbol]Value
	outer *Env
}

// NewEnv creates an environment. binds/exprs are bound pairwise; a binding
// named & collects the remaining exprs into a list.
func NewEnv(outer *Env, binds []Value, exprs []Value) *Env {
	e := &Env{data: make(map[Symbol]Value, len(binds)), outer: outer}
	for i, b := range binds {
		s, ok := b.(Symbol)
		if !ok {
			Throw("binding name must be a symbol, got %s", PrStr(b, true))
		}
		if s == "&" {
			if i+1 >= len(binds) {
				Throw("missing name after & in parameter list")
			}
			name, ok := binds[i+1].(Symbol)
			if !ok {
				Throw("binding name must be a symbol, got %s", PrStr(binds[i+1], true))
			}
			rest := []Value{}
			if i < len(exprs) {
				rest = append(rest, exprs[i:]...)
			}
			e.data[name] = NewList(rest...)
			return e
		}
		if i < len(exprs) {
			e.data[s] = exprs[i]
		} else {
			e.data[s] = Nil
		}
	}
	return e
}

// Set binds k to v in this environment and returns v.
func (e *Env) Set(k Symbol, v Value) Value {
	e.data[k] = v
	return v
}

// Lookup finds k in this environment or any outer one.
func (e *Env) Lookup(k Symbol) (Value, bool) {
	for c := e; c != nil; c = c.outer {
		if v, ok := c.data[k]; ok {
			return v, true
		}
	}
	return nil, false
}

// Get returns the value of k or throws "'k' not found".
func (e *Env) Get(k Symbol) Value {
	if v, ok := e.Lookup(k); ok {
		return v
	}
	Throw("'%s' not found", string(k))
	return nil
}
