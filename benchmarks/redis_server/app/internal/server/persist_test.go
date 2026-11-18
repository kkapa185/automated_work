package server

import (
	"testing"
)

func sampleServer() *Server {
	s := New(Options{Port: 0, Dir: ""})
	d0, d3 := s.dbs[0], s.dbs[3]
	d0.add("str", []byte("v\x00\xff"))
	e := d0.add("ttl", []byte("x"))
	d0.setExp(e, nowMs()+100000)
	l := &List{}
	l.pushBack([]byte("a"))
	l.pushBack([]byte("b"))
	d0.add("list", l)
	h := newHash()
	h.set("f", []byte("v"), &s.lim)
	d3.add("hash", h)
	st := newSet()
	st.add("1", &s.lim)
	st.add("2", &s.lim)
	d3.add("set", st)
	z := newZSet()
	z.put("m", 1.5, &s.lim)
	z.put("n", -2, &s.lim)
	d3.add("zset", z)
	return s
}

func TestSnapshotRoundTrip(t *testing.T) {
	s := sampleServer()
	data := s.encodeSnapshot()
	r := New(Options{})
	if err := r.loadSnapshot(data); err != nil {
		t.Fatal(err)
	}
	if len(r.dbs[0].data) != 3 || len(r.dbs[3].data) != 3 {
		t.Fatalf("keys: %d %d", len(r.dbs[0].data), len(r.dbs[3].data))
	}
	if string(r.dbs[0].data["str"].val.([]byte)) != "v\x00\xff" {
		t.Fatal("string")
	}
	if e := r.dbs[0].data["ttl"]; e.exp != s.dbs[0].data["ttl"].exp {
		t.Fatal("absolute expiry must be preserved")
	}
	if r.dbs[0].data["list"].val.(*List).Len() != 2 {
		t.Fatal("list")
	}
	if sc, _ := r.dbs[3].data["zset"].val.(*ZSet).score("n"); sc != -2 {
		t.Fatal("zset")
	}
	if r.dbs[3].data["set"].val.(*Set).enc != setIntset {
		t.Fatal("set encoding recomputed on load")
	}
}

func TestSnapshotSkipsExpiredKeys(t *testing.T) {
	s := New(Options{})
	e := s.dbs[0].add("gone", []byte("x"))
	s.dbs[0].setExp(e, nowMs()-1)
	s.dbs[0].add("here", []byte("y"))
	r := New(Options{})
	if err := r.loadSnapshot(s.encodeSnapshot()); err != nil {
		t.Fatal(err)
	}
	if len(r.dbs[0].data) != 1 || r.dbs[0].data["here"] == nil {
		t.Fatal("expired key must not be saved")
	}
}

func TestEmptySnapshotLoads(t *testing.T) {
	r := New(Options{})
	r.dbs[0].add("old", []byte("x"))
	if err := r.loadSnapshot(New(Options{}).encodeSnapshot()); err != nil {
		t.Fatal(err)
	}
	if len(r.dbs[0].data) != 0 {
		t.Fatal("load replaces the keyspace")
	}
}

// Every truncation and every single-byte corruption must be rejected without
// panicking and must leave the live dataset untouched.
func TestCorruptSnapshotsRejected(t *testing.T) {
	data := sampleServer().encodeSnapshot()
	r := New(Options{})
	r.dbs[0].add("live", []byte("keep"))
	for n := 0; n < len(data); n++ {
		if err := r.loadSnapshot(data[:n]); err == nil {
			t.Fatalf("truncated to %d bytes accepted", n)
		}
	}
	for i := range data {
		bad := append([]byte(nil), data...)
		bad[i] ^= 0x5a
		if err := r.loadSnapshot(bad); err == nil {
			t.Fatalf("corruption at byte %d accepted", i)
		}
	}
	if r.dbs[0].data["live"] == nil {
		t.Fatal("failed load must not clobber the dataset")
	}
}

// Structurally invalid bodies with a *valid* checksum (hostile or buggy
// writer) must also fail cleanly.
func TestMalformedBodyWithValidChecksum(t *testing.T) {
	good := sampleServer().encodeSnapshot()
	body := good[:len(good)-5] // strip 0xFF + crc
	for cut := 5; cut < len(body); cut++ {
		b := append(append([]byte(nil), body[:cut]...), 0xFF)
		b = appendCRC(b)
		New(Options{}).loadSnapshot(b) // must not panic; error or success both acceptable
	}
	huge := append([]byte(snapMagic), snapVersion, 0xFE, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F) // key count 2^32
	huge = appendCRC(huge)
	if err := New(Options{}).loadSnapshot(huge); err == nil {
		t.Fatal("bogus key count accepted")
	}
}
