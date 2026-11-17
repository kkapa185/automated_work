package main

import (
	"bytes"
	"errors"
	"strings"
	"testing"
	"time"
)

func ms(n int) time.Duration { return time.Duration(n) * time.Millisecond }

func fixture() []Result {
	var rs []Result
	for i := 1; i <= 10; i++ {
		rs = append(rs, Result{
			StatusCode: 200, Duration: ms(100 * i), ContentLength: 100,
			ConnDuration: ms(10), DnsDuration: ms(1), ReqDuration: ms(2),
			DelayDuration: ms(30), ResDuration: ms(5), Offset: ms(50 * i),
		})
	}
	return rs
}

// R13-R18: hand-computed known answer (latencies 0.1..1.0s, total 2s).
func TestSummaryKnownAnswer(t *testing.T) {
	var b bytes.Buffer
	WriteSummary(&b, fixture(), 2*time.Second)
	bar := strings.Repeat("■", 40)
	want := "Summary:\n" +
		"  Total:\t2.0000 secs\n" +
		"  Slowest:\t1.0000 secs\n" +
		"  Fastest:\t0.1000 secs\n" +
		"  Average:\t0.5500 secs\n" +
		"  Requests/sec:\t5.0000\n" +
		"  \n" +
		"  Total data:\t1000 bytes\n" +
		"  Size/request:\t100 bytes\n" +
		"\nResponse time histogram:\n" +
		"  0.100 [1]\t|" + bar + "\n" +
		"  0.190 [0]\t|\n" +
		"  0.280 [1]\t|" + bar + "\n" +
		"  0.370 [1]\t|" + bar + "\n" +
		"  0.460 [1]\t|" + bar + "\n" +
		"  0.550 [1]\t|" + bar + "\n" +
		"  0.640 [1]\t|" + bar + "\n" +
		"  0.730 [1]\t|" + bar + "\n" +
		"  0.820 [1]\t|" + bar + "\n" +
		"  0.910 [1]\t|" + bar + "\n" +
		"  1.000 [1]\t|" + bar + "\n" +
		"\nLatency distribution:\n" +
		"  10% in 0.1000 secs\n  25% in 0.2000 secs\n  50% in 0.5000 secs\n  75% in 0.7000 secs\n" +
		"  90% in 0.9000 secs\n  95% in 0.9000 secs\n  99% in 0.9000 secs\n" +
		"\nDetails (average, fastest, slowest):\n" +
		"  DNS+dialup:\t0.0100 secs, 0.0100 secs, 0.0100 secs\n" +
		"  DNS-lookup:\t0.0010 secs, 0.0010 secs, 0.0010 secs\n" +
		"  req write:\t0.0020 secs, 0.0020 secs, 0.0020 secs\n" +
		"  resp wait:\t0.0300 secs, 0.0300 secs, 0.0300 secs\n" +
		"  resp read:\t0.0050 secs, 0.0050 secs, 0.0050 secs\n" +
		"\nStatus code distribution:\n  [200]\t10 responses\n"
	if b.String() != want {
		t.Fatalf("got:\n%q\nwant:\n%q", b.String(), want)
	}
}

// R15: bar scaling with integer division by max bucket.
func TestHistogramBarScaling(t *testing.T) {
	// 4 samples at fastest, 1 at slowest -> counts [4,...,1]
	lats := []float64{1, 1, 1, 1, 2}
	bounds, counts := histogram(lats)
	if len(bounds) != 11 || counts[0] != 4 || counts[10] != 1 || bounds[10] != 2 {
		t.Fatalf("%v %v", bounds, counts)
	}
	var b bytes.Buffer
	writeHistogram(&b, lats)
	lines := strings.Split(strings.TrimRight(b.String(), "\n"), "\n")
	if strings.Count(lines[0], "■") != 40 || strings.Count(lines[10], "■") != 10 {
		t.Fatalf("bad bars:\n%s", b.String())
	}
}

func TestHistogramAllEqual(t *testing.T) {
	_, counts := histogram([]float64{0.5, 0.5, 0.5})
	if counts[0] != 3 {
		t.Fatal(counts)
	}
}

// R16
func TestPercentile(t *testing.T) {
	d := []float64{1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
	if percentile(d, 50) != 5 || percentile(d, 10) != 1 || percentile(d, 99) != 9 {
		t.Fatal("percentile mismatch")
	}
	if percentile([]float64{7}, 99) != 7 {
		t.Fatal("single")
	}
}

// R14, R18: failed requests excluded; error distribution sorted by count desc.
func TestSummaryErrors(t *testing.T) {
	rs := fixture()[:2]
	rs = append(rs, Result{Err: errors.New("boom")}, Result{Err: errors.New("boom")}, Result{Err: errors.New("alpha")})
	rs[1].StatusCode = 404
	var b bytes.Buffer
	WriteSummary(&b, rs, time.Second)
	s := b.String()
	for _, w := range []string{"Total data:\t200 bytes", "Size/request:\t100 bytes",
		"  [200]\t1 responses\n  [404]\t1 responses\n", "Error distribution:\n  [2]\tboom\n  [1]\talpha\n"} {
		if !strings.Contains(s, w) {
			t.Errorf("missing %q in\n%s", w, s)
		}
	}
}

func TestSummaryAllFailed(t *testing.T) {
	var b bytes.Buffer
	WriteSummary(&b, []Result{{Err: errors.New("x")}}, time.Second)
	s := b.String()
	if strings.Contains(s, "histogram") || strings.Contains(s, "Size/request") || !strings.Contains(s, "[1]\tx") {
		t.Fatal(s)
	}
}

// R19
func TestCSV(t *testing.T) {
	rs := []Result{fixture()[0], {Err: errors.New("e")}}
	var b bytes.Buffer
	WriteCSV(&b, rs)
	want := "response-time,DNS+dialup,DNS,Request-write,Response-delay,Response-read,status-code,offset\n" +
		"0.1000,0.0100,0.0010,0.0020,0.0300,0.0050,200,0.0500\n"
	if b.String() != want {
		t.Fatalf("%q", b.String())
	}
}
