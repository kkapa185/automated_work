package server

// globMatch implements Redis-style glob matching: * ? [set] [^set] [a-z] and
// backslash escapes. It is binary safe and runs in O(len(p)*len(s)) worst
// case: on a mismatch it only backtracks to the most recent '*', which is
// sufficient because a star can absorb any run of characters.
func globMatch(p, s []byte) bool {
	pi, si := 0, 0
	starP, starS := -1, 0
	for si < len(s) {
		if pi < len(p) && p[pi] == '*' {
			for pi < len(p) && p[pi] == '*' {
				pi++
			}
			if pi == len(p) {
				return true
			}
			starP, starS = pi, si
			continue
		}
		if pi < len(p) {
			if n, ok := matchToken(p[pi:], s[si]); ok {
				pi += n
				si++
				continue
			}
		}
		if starP < 0 {
			return false
		}
		starS++
		si, pi = starS, starP
	}
	for pi < len(p) && p[pi] == '*' {
		pi++
	}
	return pi == len(p)
}

// matchToken matches one non-star pattern token at the start of p against
// byte c and returns how many pattern bytes the token spans.
func matchToken(p []byte, c byte) (int, bool) {
	switch p[0] {
	case '?':
		return 1, true
	case '\\':
		if len(p) >= 2 {
			return 2, p[1] == c
		}
		return 1, c == '\\'
	case '[':
		i := 1
		not := false
		if i < len(p) && p[i] == '^' {
			not = true
			i++
		}
		match := false
		for i < len(p) && p[i] != ']' {
			switch {
			case p[i] == '\\' && i+1 < len(p):
				if p[i+1] == c {
					match = true
				}
				i += 2
			case i+2 < len(p) && p[i+1] == '-' && p[i+2] != ']':
				lo, hi := p[i], p[i+2]
				if lo > hi {
					lo, hi = hi, lo
				}
				if c >= lo && c <= hi {
					match = true
				}
				i += 3
			default:
				if p[i] == c {
					match = true
				}
				i++
			}
		}
		if i < len(p) { // skip the closing ']'
			i++
		}
		return i, match != not
	}
	return 1, p[0] == c
}
