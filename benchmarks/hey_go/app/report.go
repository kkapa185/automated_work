package main

import (
	"fmt"
	"io"
	"sort"
	"strings"
	"time"
)

const barChar = "■"

func secs(d time.Duration) float64 { return d.Seconds() }

// WriteCSV dumps per-request metrics.
func WriteCSV(w io.Writer, results []Result) {
	fmt.Fprintln(w, "response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset")
	for _, r := range results {
		if r.Err != nil {
			continue
		}
		fmt.Fprintf(w, "%4.4f,%4.4f,%4.4f,%4.4f,%4.4f,%4.4f,%d,%4.4f\n",
			secs(r.Duration), secs(r.ConnDuration), secs(r.DnsDuration), secs(r.ReqDuration),
			secs(r.DelayDuration), secs(r.ResDuration), r.StatusCode, secs(r.Offset))
	}
}

// WriteSummary prints the human-readable report.
func WriteSummary(w io.Writer, results []Result, total time.Duration) {
	var ok []Result
	errs := map[string]int{}
	for _, r := range results {
		if r.Err != nil {
			errs[r.Err.Error()]++
		} else {
			ok = append(ok, r)
		}
	}
	lats := make([]float64, len(ok))
	var sum float64
	var totalData int64
	for i, r := range ok {
		lats[i] = secs(r.Duration)
		sum += lats[i]
		totalData += r.ContentLength
	}
	sort.Float64s(lats)
	var avg, rps, fastest, slowest float64
	if len(ok) > 0 {
		avg = sum / float64(len(ok))
		fastest, slowest = lats[0], lats[len(lats)-1]
		if total > 0 {
			rps = float64(len(ok)) / secs(total)
		}
	}
	fmt.Fprintf(w, "Summary:\n")
	fmt.Fprintf(w, "  Total:\t%4.4f secs\n", secs(total))
	fmt.Fprintf(w, "  Slowest:\t%4.4f secs\n", slowest)
	fmt.Fprintf(w, "  Fastest:\t%4.4f secs\n", fastest)
	fmt.Fprintf(w, "  Average:\t%4.4f secs\n", avg)
	fmt.Fprintf(w, "  Requests/sec:\t%4.4f\n", rps)
	fmt.Fprintf(w, "  \n")
	fmt.Fprintf(w, "  Total data:\t%d bytes\n", totalData)
	if len(ok) > 0 {
		fmt.Fprintf(w, "  Size/request:\t%d bytes\n", totalData/int64(len(ok)))
	}
	if len(ok) > 0 {
		fmt.Fprintf(w, "\nResponse time histogram:\n")
		writeHistogram(w, lats)
		fmt.Fprintf(w, "\nLatency distribution:\n")
		for _, p := range []int{10, 25, 50, 75, 90, 95, 99} {
			fmt.Fprintf(w, "  %d%% in %4.4f secs\n", p, percentile(lats, p))
		}
		fmt.Fprintf(w, "\nDetails (average, fastest, slowest):\n")
		detail := func(name string, f func(Result) time.Duration) {
			var s, mn, mx float64
			for i, r := range ok {
				v := secs(f(r))
				s += v
				if i == 0 || v < mn {
					mn = v
				}
				if i == 0 || v > mx {
					mx = v
				}
			}
			fmt.Fprintf(w, "  %s\t%4.4f secs, %4.4f secs, %4.4f secs\n", name, s/float64(len(ok)), mn, mx)
		}
		detail("DNS+dialup:", func(r Result) time.Duration { return r.ConnDuration })
		detail("DNS-lookup:", func(r Result) time.Duration { return r.DnsDuration })
		detail("req write:", func(r Result) time.Duration { return r.ReqDuration })
		detail("resp wait:", func(r Result) time.Duration { return r.DelayDuration })
		detail("resp read:", func(r Result) time.Duration { return r.ResDuration })
	}
	codes := map[int]int{}
	for _, r := range ok {
		codes[r.StatusCode]++
	}
	var keys []int
	for k := range codes {
		keys = append(keys, k)
	}
	sort.Ints(keys)
	fmt.Fprintf(w, "\nStatus code distribution:\n")
	for _, k := range keys {
		fmt.Fprintf(w, "  [%d]\t%d responses\n", k, codes[k])
	}
	if len(errs) > 0 {
		type ec struct {
			msg string
			n   int
		}
		var l []ec
		for m, n := range errs {
			l = append(l, ec{m, n})
		}
		sort.Slice(l, func(i, j int) bool {
			if l[i].n != l[j].n {
				return l[i].n > l[j].n
			}
			return l[i].msg < l[j].msg
		})
		fmt.Fprintf(w, "\nError distribution:\n")
		for _, e := range l {
			fmt.Fprintf(w, "  [%d]\t%s\n", e.n, e.msg)
		}
	}
}

// percentile of sorted data: index int(p*len/100)-1, floored at 0.
func percentile(sorted []float64, p int) float64 {
	i := len(sorted)*p/100 - 1
	if i < 0 {
		i = 0
	}
	return sorted[i]
}

// histogram returns bucket upper bounds and counts (11 buckets).
func histogram(sorted []float64) ([]float64, []int) {
	min, max := sorted[0], sorted[len(sorted)-1]
	const nb = 10
	bounds := make([]float64, nb+1)
	width := (max - min) / nb
	for i := 0; i < nb; i++ {
		bounds[i] = min + width*float64(i)
	}
	bounds[nb] = max
	counts := make([]int, nb+1)
	for _, v := range sorted {
		for i, b := range bounds {
			if v <= b || i == nb {
				counts[i]++
				break
			}
		}
	}
	return bounds, counts
}

func writeHistogram(w io.Writer, sorted []float64) {
	bounds, counts := histogram(sorted)
	maxc := 0
	for _, c := range counts {
		if c > maxc {
			maxc = c
		}
	}
	for i, c := range counts {
		bar := strings.Repeat(barChar, c*40/maxc)
		fmt.Fprintf(w, "  %4.3f [%v]\t|%s\n", bounds[i], c, bar)
	}
}
