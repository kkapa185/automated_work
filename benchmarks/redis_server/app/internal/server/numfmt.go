package server

import (
	"math"
	"math/big"
	"strconv"
	"strings"
)

// parseInt64 parses a strictly formatted base-10 signed 64-bit integer, like
// Redis: no whitespace, no '+', no leading zeros, no "-0".
func parseInt64(b []byte) (int64, bool) {
	n := len(b)
	if n == 0 || n > 20 {
		return 0, false
	}
	i := 0
	if b[0] == '-' {
		i = 1
		if n == 1 {
			return 0, false
		}
	}
	if b[i] < '0' || b[i] > '9' {
		return 0, false
	}
	if b[i] == '0' && n > i+1 {
		return 0, false
	}
	if b[i] == '0' && i == 1 {
		return 0, false
	}
	for _, c := range b[i:] {
		if c < '0' || c > '9' {
			return 0, false
		}
	}
	v, err := strconv.ParseInt(string(b), 10, 64)
	if err != nil {
		return 0, false
	}
	return v, true
}

// parseFloat parses a double like strtod with Redis' extra restrictions:
// no surrounding whitespace, no NaN, no overflow.
func parseFloat(b []byte) (float64, bool) {
	if len(b) == 0 || isSpace(b[0]) || isSpace(b[len(b)-1]) {
		return 0, false
	}
	s := string(b)
	f, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsNaN(f) {
		return 0, false
	}
	return f, true
}

// formatDouble renders a score/double: shortest round-trip form, "inf"/"-inf".
func formatDouble(f float64) string {
	switch {
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	case f == 0:
		if math.Signbit(f) {
			return "-0"
		}
		return "0"
	}
	a := math.Abs(f)
	if a >= 1e-6 && a < 1e21 {
		return strconv.FormatFloat(f, 'f', -1, 64)
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}

// parseLongDouble parses a decimal into a 64-bit-mantissa float (x87 long
// double precision), rejecting NaN, whitespace and overflow.
func parseLongDouble(b []byte) (*big.Float, bool) {
	if len(b) == 0 || isSpace(b[0]) || isSpace(b[len(b)-1]) {
		return nil, false
	}
	f, _, err := big.ParseFloat(string(b), 10, 64, big.ToNearestEven)
	if err != nil {
		return nil, false
	}
	if !f.IsInf() && f.Sign() != 0 && f.MantExp(nil) > 16384 {
		return nil, false
	}
	return f, true
}

// formatLongDouble prints like "%.17Lf" with trailing zeros trimmed.
func formatLongDouble(f *big.Float) string {
	s := f.Text('f', 17)
	if strings.Contains(s, ".") {
		s = strings.TrimRight(s, "0")
		s = strings.TrimSuffix(s, ".")
	}
	if s == "-0" {
		s = "0"
	}
	return s
}

// addLongDouble computes a+b in long-double precision. ok=false when the
// result would be NaN or infinite.
func addLongDouble(a, b *big.Float) (*big.Float, bool) {
	if a.IsInf() && b.IsInf() && a.Signbit() != b.Signbit() {
		return nil, false
	}
	r := new(big.Float).SetPrec(64).SetMode(big.ToNearestEven).Add(a, b)
	if r.IsInf() || (r.Sign() != 0 && r.MantExp(nil) > 16384) {
		return nil, false
	}
	return r, true
}
