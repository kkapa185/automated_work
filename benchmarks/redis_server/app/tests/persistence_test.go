package tests

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestSnapshotSurvivesRestart(t *testing.T) {
	dir := t.TempDir()
	s := startServer(t, dir)
	c := s.Client(t)
	c.Do("SET", "plain", "value")
	c.Do("SET", "ttl", "v", "EX", 1000)
	c.Do("SET", "short", "v", "PX", 100)
	c.Do("SELECT", 5)
	c.Do("SET", "other", "db5")
	before := c.Do("LASTSAVE").(int64)
	expect(t, c, OK, "SAVE")
	if after := c.Do("LASTSAVE").(int64); after < before {
		t.Fatal("LASTSAVE went backwards")
	}
	if _, err := os.Stat(filepath.Join(dir, "dump.kvdb")); err != nil {
		t.Fatal("snapshot not written:", err)
	}
	s.Kill()
	time.Sleep(200 * time.Millisecond) // "short" expires while down

	s2 := startServer(t, dir)
	c2 := s2.Client(t)
	expect(t, c2, "value", "GET", "plain")
	expect(t, c2, Nil, "GET", "short")
	if v := c2.Do("TTL", "ttl").(int64); v < 990 || v > 1000 {
		t.Fatalf("remaining TTL not preserved: %d", v)
	}
	expect(t, c2, 2, "DBSIZE")
	c2.Do("SELECT", 5)
	expect(t, c2, "db5", "GET", "other")
}

func TestBgSaveAndCorruptSnapshot(t *testing.T) {
	dir := t.TempDir()
	s := startServer(t, dir)
	c := s.Client(t)
	c.Do("SET", "k", "v")
	expect(t, c, Simple("Background saving started"), "BGSAVE")
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(filepath.Join(dir, "dump.kvdb")); err == nil {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	s.Kill()
	s2 := startServer(t, dir)
	expect(t, s2.Client(t), "v", "GET", "k")
	s2.Kill()
	// corrupt file: server must still start, empty
	os.WriteFile(filepath.Join(dir, "dump.kvdb"), []byte("KVDBgarbage"), 0o644)
	s3 := startServer(t, dir)
	expect(t, s3.Client(t), 0, "DBSIZE")
}

func TestCollectionsSurviveRestart(t *testing.T) {
	dir := t.TempDir()
	s := startServer(t, dir)
	c := s.Client(t)
	c.Do("RPUSH", "l", "a", "b", "c")
	c.Do("HSET", "h", "f1", "v1", "f2", "v2")
	c.Do("SADD", "s", 1, 2, 3)
	c.Do("RPUSH", "lt", "x")
	c.Do("EXPIRE", "lt", 500)
	expect(t, c, OK, "SAVE")
	s.Kill()
	c2 := startServer(t, dir).Client(t)
	expect(t, c2, arr("a", "b", "c"), "LRANGE", "l", 0, -1)
	expect(t, c2, arr("f1", "v1", "f2", "v2"), "HGETALL", "h")
	expect(t, c2, arr("1", "2", "3"), "SMEMBERS", "s")
	expect(t, c2, "intset", "OBJECT", "ENCODING", "s")
	if v := c2.Do("TTL", "lt").(int64); v < 490 {
		t.Fatal(v)
	}
}

func restart(t *testing.T, s *Srv) (*Srv, *C) {
	t.Helper()
	s.Kill()
	s2 := startServer(t, s.Dir)
	return s2, s2.Client(t)
}

func TestSigtermSavesWhenDirGiven(t *testing.T) {
	dir := t.TempDir()
	s := startServer(t, dir)
	c := s.Client(t)
	c.Do("SET", "k", "v")
	c.Do("SET", "t", "v", "EX", 1000)
	s.Term() // no explicit SAVE
	s2 := startServer(t, dir)
	c2 := s2.Client(t)
	expect(t, c2, "v", "GET", "k")
	if v := c2.Do("TTL", "t").(int64); v < 990 {
		t.Fatal(v)
	}
}

func TestNoDirMeansCwdAndNoSaveOnSigterm(t *testing.T) {
	cwd := t.TempDir()
	s := startServerCwd(t, cwd)
	c := s.Client(t)
	c.Do("SET", "k", "v")
	s.Term()
	if _, err := os.Stat(filepath.Join(cwd, "dump.kvdb")); err == nil {
		t.Fatal("SIGTERM must not write a snapshot when --dir was not given")
	}
	s = startServerCwd(t, cwd)
	c = s.Client(t)
	expect(t, c, Nil, "GET", "k")
	c.Do("SET", "k", "v")
	expect(t, c, OK, "SAVE") // explicit SAVE writes into the working directory
	if _, err := os.Stat(filepath.Join(cwd, "dump.kvdb")); err != nil {
		t.Fatal("SAVE should use cwd by default:", err)
	}
	s.Kill()
	s = startServerCwd(t, cwd)
	expect(t, s.Client(t), "v", "GET", "k")
}

func TestAllTypesAllDatabasesSurviveRestart(t *testing.T) {
	s := startServer(t, "")
	c := s.Client(t)
	for _, db := range []int{0, 7, 15} {
		c.Do("SELECT", db)
		c.Do("SET", "s", "string\x00bin\r\n")
		c.Do("RPUSH", "l", "a", "b", "c")
		c.Do("HSET", "h", "f1", "v1", "f2", "v2")
		c.Do("SADD", "set", "x", "y")
		c.Do("ZADD", "z", 1.25, "a", "-inf", "b", "inf", "c")
		c.Do("SET", "bin\x00key", "v")
	}
	expect(t, c, OK, "SAVE")
	s2, c2 := restart(t, s)
	for _, db := range []int{0, 7, 15} {
		c2.Do("SELECT", db)
		expect(t, c2, 6, "DBSIZE")
		expect(t, c2, "string\x00bin\r\n", "GET", "s")
		expect(t, c2, arr("a", "b", "c"), "LRANGE", "l", 0, -1)
		expect(t, c2, arr("f1", "v1", "f2", "v2"), "HGETALL", "h")
		sameSet(t, c2.Do("SMEMBERS", "set"), "x", "y")
		expect(t, c2, arr("b", "-inf", "a", "1.25", "c", "inf"), "ZRANGE", "z", 0, -1, "WITHSCORES")
		expect(t, c2, "v", "GET", "bin\x00key")
	}
	c2.Do("SELECT", 1)
	expect(t, c2, 0, "DBSIZE")
	// a second generation: save again from the restored state
	c2.Do("SELECT", 0)
	expect(t, c2, OK, "SAVE")
	_, c3 := restart(t, s2)
	expect(t, c3, 6, "DBSIZE")
}

func TestRemainingTTLSurvivesRestartAndStillExpires(t *testing.T) {
	s := startServer(t, "")
	c := s.Client(t)
	c.Do("SET", "k", "v", "PX", 2500)
	c.Do("SET", "gone", "v", "PX", 300)
	c.Do("SET", "p", "v")
	expect(t, c, OK, "SAVE")
	s.Kill()
	time.Sleep(500 * time.Millisecond) // downtime counts against the TTL
	s2 := startServer(t, s.Dir)
	c2 := s2.Client(t)
	expect(t, c2, Nil, "GET", "gone")
	pttl := c2.Do("PTTL", "k").(int64)
	if pttl <= 0 || pttl > 2000 {
		t.Fatalf("PTTL after restart = %d, want within (0, 2000]", pttl)
	}
	expect(t, c2, -1, "TTL", "p")
	time.Sleep(time.Duration(pttl+100) * time.Millisecond)
	expect(t, c2, Nil, "GET", "k")
}

func TestSaveCommandsMisc(t *testing.T) {
	s := startServer(t, "")
	c := s.Client(t)
	c.Do("SET", "k", "v")
	before := time.Now().Unix()
	expect(t, c, OK, "SAVE")
	if ls := c.Do("LASTSAVE").(int64); ls < before {
		t.Fatalf("LASTSAVE %d < %d", ls, before)
	}
	leftovers, _ := filepath.Glob(filepath.Join(s.Dir, "*tmp*"))
	if len(leftovers) != 0 {
		t.Fatalf("temp files left behind: %v", leftovers)
	}
	for i := 0; i < 5; i++ { // BGSAVE storms never break the server
		r := c.Do("BGSAVE")
		if r != Simple("Background saving started") && r != Err("ERR Background save already in progress") {
			t.Fatalf("BGSAVE: %#v", r)
		}
	}
	expect(t, c, Err("ERR syntax error"), "BGSAVE", "NOW")
	expect(t, c, Simple("PONG"), "PING")
	// failure to write is an error reply, not a crash
	os.RemoveAll(s.Dir)
	if r, ok := c.Do("SAVE").(Err); !ok || !strings.HasPrefix(string(r), "ERR") {
		t.Fatalf("SAVE into missing dir: %#v", r)
	}
	expect(t, c, "v", "GET", "k")
}

// A snapshot is a point-in-time image: pairs written atomically by
// transactions must never be torn in the file, even while writers hammer the
// server during SAVE/BGSAVE.
func TestSnapshotConsistentUnderConcurrentWrites(t *testing.T) {
	s := startServer(t, "")
	stop := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 4; i++ {
		w := s.Client(t)
		wg.Add(1)
		go func() {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
				}
				w.Send("MULTI")
				w.Send("INCR", "x")
				w.Send("INCR", "y")
				w.Send("EXEC")
				for j := 0; j < 4; j++ {
					if _, err := w.TryRead(5 * time.Second); err != nil {
						return
					}
				}
			}
		}()
	}
	c := s.Client(t)
	time.Sleep(100 * time.Millisecond)
	for i := 0; i < 5; i++ {
		if i%2 == 0 {
			expect(t, c, OK, "SAVE")
		} else {
			c.Do("BGSAVE")
			time.Sleep(100 * time.Millisecond)
		}
		time.Sleep(50 * time.Millisecond)
	}
	close(stop)
	wg.Wait()
	time.Sleep(200 * time.Millisecond) // let a BGSAVE finish
	_, c2 := restart(t, s)
	x, y := c2.Do("GET", "x"), c2.Do("GET", "y")
	if x == nil || x != y {
		t.Fatalf("torn snapshot: x=%v y=%v", x, y)
	}
}

func TestLargeSnapshotSaveAndLoad(t *testing.T) {
	s := startServer(t, "")
	c := s.Client(t)
	const n = 200000
	for i := 0; i < n; i += 2000 {
		for j := i; j < i+2000; j++ {
			c.Send("SET", "key:"+itoa(j), "value-"+itoa(j))
		}
		for j := i; j < i+2000; j++ {
			c.Read()
		}
	}
	st := time.Now()
	expect(t, c, OK, "SAVE")
	saveT := time.Since(st)
	s.Kill()
	st = time.Now()
	s2 := startServer(t, s.Dir)
	c2 := s2.Client(t)
	expect(t, c2, n, "DBSIZE")
	loadT := time.Since(st)
	t.Logf("%d keys: save %v, restart+load %v", n, saveT, loadT)
	if saveT > 5*time.Second || loadT > 10*time.Second {
		t.Fatalf("snapshot too slow: save %v load %v", saveT, loadT)
	}
	expect(t, c2, "value-123456", "GET", "key:123456")
}
