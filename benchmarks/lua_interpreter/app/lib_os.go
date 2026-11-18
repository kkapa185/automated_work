package main

import (
	"errors"
	"fmt"
	"os"
	"strings"
	"syscall"
	"time"
)

var startTime = time.Now()

// osErr converts a Go error to (message, errno) like C's strerror.
func osErr(err error, name string) (string, int64) {
	var en syscall.Errno
	msg := err.Error()
	var code int64
	if errors.As(err, &en) {
		msg = en.Error()
		code = int64(en)
	}
	if msg != "" {
		msg = strings.ToUpper(msg[:1]) + msg[1:]
	}
	if name != "" {
		msg = name + ": " + msg
	}
	return msg, code
}

func failResult(err error, name string) []Value {
	msg, code := osErr(err, name)
	return []Value{nil, msg, code}
}

func getDateField(th *Thread, t *Table, key string, def int64, delta int64) int64 {
	v := t.getStr(key)
	if v == nil {
		if def < 0 {
			th.rtError("field '%s' missing in date table", key)
		}
		return def
	}
	n, ok := toInteger(v)
	if !ok {
		if _, isNum := toNumber(v); isNum {
			th.rtError("field '%s' is not an integer", key)
		}
		th.rtError("field '%s' missing in date table", key)
	}
	return n
}

func setDateFields(t *Table, tm time.Time) {
	t.setStr("year", int64(tm.Year()))
	t.setStr("month", int64(tm.Month()))
	t.setStr("day", int64(tm.Day()))
	t.setStr("hour", int64(tm.Hour()))
	t.setStr("min", int64(tm.Minute()))
	t.setStr("sec", int64(tm.Second()))
	t.setStr("yday", int64(tm.YearDay()))
	t.setStr("wday", int64(tm.Weekday())+1)
	t.setStr("isdst", tm.IsDST())
}

var dayNames = []string{"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"}
var monthNames = []string{"January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"}

func strftime(th *Thread, f string, tm time.Time) string {
	var b strings.Builder
	for i := 0; i < len(f); i++ {
		c := f[i]
		if c != '%' {
			b.WriteByte(c)
			continue
		}
		i++
		if i >= len(f) {
			th.rtError("bad argument #1 to 'date' (invalid conversion specifier '%%')")
		}
		spec := f[i]
		if (spec == 'E' || spec == 'O') && i+1 < len(f) {
			ok := false
			if spec == 'E' {
				ok = strings.IndexByte("cCxXyY", f[i+1]) >= 0
			} else {
				ok = strings.IndexByte("deHImMSuUVwWy", f[i+1]) >= 0
			}
			if !ok {
				th.rtError("bad argument #1 to 'date' (invalid conversion specifier '%%%s')", f[i:i+2])
			}
			i++
			spec = f[i]
		}
		hour12 := tm.Hour() % 12
		if hour12 == 0 {
			hour12 = 12
		}
		switch spec {
		case 'a':
			b.WriteString(dayNames[tm.Weekday()][:3])
		case 'A':
			b.WriteString(dayNames[tm.Weekday()])
		case 'b', 'h':
			b.WriteString(monthNames[tm.Month()-1][:3])
		case 'B':
			b.WriteString(monthNames[tm.Month()-1])
		case 'c':
			b.WriteString(strftime(th, "%a %b %e %H:%M:%S %Y", tm))
		case 'C':
			fmt.Fprintf(&b, "%02d", tm.Year()/100)
		case 'd':
			fmt.Fprintf(&b, "%02d", tm.Day())
		case 'D':
			b.WriteString(strftime(th, "%m/%d/%y", tm))
		case 'e':
			fmt.Fprintf(&b, "%2d", tm.Day())
		case 'F':
			b.WriteString(strftime(th, "%Y-%m-%d", tm))
		case 'g':
			y, _ := tm.ISOWeek()
			fmt.Fprintf(&b, "%02d", y%100)
		case 'G':
			y, _ := tm.ISOWeek()
			fmt.Fprintf(&b, "%d", y)
		case 'H':
			fmt.Fprintf(&b, "%02d", tm.Hour())
		case 'I':
			fmt.Fprintf(&b, "%02d", hour12)
		case 'j':
			fmt.Fprintf(&b, "%03d", tm.YearDay())
		case 'm':
			fmt.Fprintf(&b, "%02d", int(tm.Month()))
		case 'M':
			fmt.Fprintf(&b, "%02d", tm.Minute())
		case 'n':
			b.WriteByte('\n')
		case 'p':
			if tm.Hour() < 12 {
				b.WriteString("AM")
			} else {
				b.WriteString("PM")
			}
		case 'r':
			b.WriteString(strftime(th, "%I:%M:%S %p", tm))
		case 'R':
			b.WriteString(strftime(th, "%H:%M", tm))
		case 'S':
			fmt.Fprintf(&b, "%02d", tm.Second())
		case 't':
			b.WriteByte('\t')
		case 'T', 'X':
			b.WriteString(strftime(th, "%H:%M:%S", tm))
		case 'u':
			wd := int(tm.Weekday())
			if wd == 0 {
				wd = 7
			}
			fmt.Fprintf(&b, "%d", wd)
		case 'U':
			fmt.Fprintf(&b, "%02d", (tm.YearDay()-1+7-int(tm.Weekday()))/7)
		case 'V':
			_, w := tm.ISOWeek()
			fmt.Fprintf(&b, "%02d", w)
		case 'w':
			fmt.Fprintf(&b, "%d", int(tm.Weekday()))
		case 'W':
			fmt.Fprintf(&b, "%02d", (tm.YearDay()-1+7-(int(tm.Weekday())+6)%7)/7)
		case 'x':
			b.WriteString(strftime(th, "%m/%d/%y", tm))
		case 'y':
			fmt.Fprintf(&b, "%02d", tm.Year()%100)
		case 'Y':
			fmt.Fprintf(&b, "%d", tm.Year())
		case 'z':
			b.WriteString(tm.Format("-0700"))
		case 'Z':
			b.WriteString(tm.Format("MST"))
		case '%':
			b.WriteByte('%')
		default:
			th.rtError("bad argument #1 to 'date' (invalid conversion specifier '%%%c')", spec)
		}
	}
	return b.String()
}

func cpuClock() float64 {
	var ru syscall.Rusage
	if err := syscall.Getrusage(syscall.RUSAGE_SELF, &ru); err == nil {
		return float64(ru.Utime.Sec) + float64(ru.Utime.Usec)/1e6 + float64(ru.Stime.Sec) + float64(ru.Stime.Usec)/1e6
	}
	return time.Since(startTime).Seconds()
}

func openOS(th *Thread) {
	o := newTable(0, 16)
	G.setStr("os", o)
	loadedTable.setStr("os", o)
	reg(o, "time", func(th *Thread, args []Value) []Value {
		if len(args) == 0 || args[0] == nil {
			return []Value{time.Now().Unix()}
		}
		t := checkTable(th, args, 0, "time")
		year := getDateField(th, t, "year", -1, 0)
		month := getDateField(th, t, "month", -1, 0)
		day := getDateField(th, t, "day", -1, 0)
		hour := getDateField(th, t, "hour", 12, 0)
		min := getDateField(th, t, "min", 0, 0)
		sec := getDateField(th, t, "sec", 0, 0)
		tm := time.Date(int(year), time.Month(month), int(day), int(hour), int(min), int(sec), 0, time.Local)
		setDateFields(t, tm)
		return []Value{tm.Unix()}
	})
	reg(o, "clock", func(th *Thread, args []Value) []Value { return []Value{cpuClock()} })
	reg(o, "date", func(th *Thread, args []Value) []Value {
		format := optStr(th, args, 0, "date", "%c")
		var secs int64
		if len(args) > 1 && args[1] != nil {
			secs = checkInt(th, args, 1, "date")
		} else {
			secs = time.Now().Unix()
		}
		tm := time.Unix(secs, 0)
		if strings.HasPrefix(format, "!") {
			tm = tm.UTC()
			format = format[1:]
		} else {
			tm = tm.Local()
		}
		if strings.HasPrefix(format, "*t") {
			t := newTable(0, 9)
			setDateFields(t, tm)
			return []Value{t}
		}
		return []Value{strftime(th, format, tm)}
	})
	reg(o, "difftime", func(th *Thread, args []Value) []Value {
		return []Value{checkNum(th, args, 0, "difftime") - checkNum(th, args, 1, "difftime")}
	})
	reg(o, "getenv", func(th *Thread, args []Value) []Value {
		v, ok := os.LookupEnv(checkStr(th, args, 0, "getenv"))
		if !ok {
			return []Value{nil}
		}
		return []Value{v}
	})
	reg(o, "exit", func(th *Thread, args []Value) []Value {
		code := 0
		switch v := argOr(args, 0).(type) {
		case nil, bool:
			if v == false {
				code = 1
			}
		default:
			code = int(checkInt(th, args, 0, "exit"))
		}
		exitWith(code)
		return nil
	})
	reg(o, "remove", func(th *Thread, args []Value) []Value {
		name := checkStr(th, args, 0, "remove")
		if err := os.Remove(name); err != nil {
			return failResult(err, name)
		}
		return []Value{true}
	})
	reg(o, "rename", func(th *Thread, args []Value) []Value {
		a, b := checkStr(th, args, 0, "rename"), checkStr(th, args, 1, "rename")
		if err := os.Rename(a, b); err != nil {
			return failResult(err, a)
		}
		return []Value{true}
	})
	reg(o, "tmpname", func(th *Thread, args []Value) []Value {
		f, err := os.CreateTemp("", "lua_")
		if err != nil {
			th.rtError("unable to generate a unique filename")
		}
		name := f.Name()
		f.Close()
		return []Value{name}
	})
	reg(o, "setlocale", func(th *Thread, args []Value) []Value {
		l := optStr(th, args, 0, "setlocale", "")
		if l == "" || l == "C" || l == "POSIX" {
			return []Value{"C"}
		}
		return []Value{nil}
	})
}
