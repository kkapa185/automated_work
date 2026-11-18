package server

import (
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"log"
	"math"
	"os"
	"path/filepath"
	"time"
)

// Snapshot format (little-endian where fixed width):
//
//	"KVDB" version(1)
//	repeated: 0xFE uvarint(dbIndex) uvarint(nKeys)
//	          nKeys x { type(1) int64(expireAtUnixMs, 0=none) uvarint(len) key value }
//	0xFF crc32(IEEE of every preceding byte)
//
// Values: string = uvarint(len) bytes. Collection encodings live in
// encodeValue / decodeValue.
const (
	snapMagic   = "KVDB"
	snapVersion = 1

	tString = 0
	tList   = 1
	tHash   = 2
	tSet    = 3
	tZSet   = 4
)

func (s *Server) snapshotPath() string {
	name := s.cfg["dbfilename"]
	if name == "" {
		name = "dump.kvdb"
	}
	return filepath.Join(s.cfg["dir"], name)
}

func putBytes(b []byte, p []byte) []byte {
	b = binary.AppendUvarint(b, uint64(len(p)))
	return append(b, p...)
}

// encodeSnapshot serialises every database. Caller holds s.mu, so the result
// is a consistent point-in-time image.
func (s *Server) encodeSnapshot() []byte {
	b := append([]byte(snapMagic), snapVersion)
	now := nowMs()
	for _, d := range s.dbs {
		if len(d.keys) == 0 {
			continue
		}
		b = append(b, 0xFE)
		b = binary.AppendUvarint(b, uint64(d.id))
		cnt := 0
		for _, e := range d.keys {
			if e.exp == 0 || e.exp > now {
				cnt++
			}
		}
		b = binary.AppendUvarint(b, uint64(cnt))
		for _, e := range d.keys {
			if e.exp != 0 && e.exp <= now {
				continue
			}
			t, enc := encodeValue(e.val)
			b = append(b, t)
			b = binary.LittleEndian.AppendUint64(b, uint64(e.exp))
			b = putBytes(b, []byte(e.key))
			b = append(b, enc...)
		}
	}
	b = append(b, 0xFF)
	return appendCRC(b)
}

func appendCRC(b []byte) []byte {
	return binary.LittleEndian.AppendUint32(b, crc32.ChecksumIEEE(b))
}

func encodeValue(v any) (byte, []byte) {
	switch x := v.(type) {
	case []byte:
		return tString, putBytes(nil, x)
	case *List:
		b := binary.AppendUvarint(nil, uint64(x.Len()))
		for _, it := range x.items() {
			b = putBytes(b, it)
		}
		return tList, b
	case *Hash:
		b := binary.AppendUvarint(nil, uint64(x.Len()))
		x.each(func(f string, v []byte) {
			b = putBytes(b, []byte(f))
			b = putBytes(b, v)
		})
		return tHash, b
	case *Set:
		b := binary.AppendUvarint(nil, uint64(x.Len()))
		for _, m := range x.items {
			b = putBytes(b, []byte(m))
		}
		return tSet, b
	case *ZSet:
		b := binary.AppendUvarint(nil, uint64(x.Len()))
		for n := x.sl.first(); n != nil; n = n.lvl[0].fwd {
			b = putBytes(b, []byte(n.member))
			b = binary.LittleEndian.AppendUint64(b, math.Float64bits(n.score))
		}
		return tZSet, b
	}
	panic(fmt.Sprintf("unsupported value type %T", v))
}

type decoder struct {
	b   []byte
	err error
}

func (d *decoder) fail() { d.err = errors.New("truncated or corrupt snapshot") }

func (d *decoder) byte() byte {
	if len(d.b) < 1 {
		d.fail()
		return 0
	}
	c := d.b[0]
	d.b = d.b[1:]
	return c
}

func (d *decoder) uvarint() uint64 {
	v, n := binary.Uvarint(d.b)
	if n <= 0 {
		d.fail()
		return 0
	}
	d.b = d.b[n:]
	return v
}

func (d *decoder) u64() uint64 {
	if len(d.b) < 8 {
		d.fail()
		return 0
	}
	v := binary.LittleEndian.Uint64(d.b)
	d.b = d.b[8:]
	return v
}

func (d *decoder) bytes() []byte {
	n := d.uvarint()
	if d.err != nil || n > uint64(len(d.b)) {
		d.fail()
		return nil
	}
	p := append([]byte(nil), d.b[:n]...)
	d.b = d.b[n:]
	return p
}

func decodeValue(t byte, d *decoder, lim *limits) any {
	switch t {
	case tString:
		return d.bytes()
	case tList:
		n := d.uvarint()
		l := &List{}
		for i := uint64(0); i < n && d.err == nil; i++ {
			l.pushBack(d.bytes())
		}
		return l
	case tHash:
		n := d.uvarint()
		h := newHash()
		for i := uint64(0); i < n && d.err == nil; i++ {
			f := d.bytes()
			v := d.bytes()
			h.set(string(f), v, lim)
		}
		return h
	case tSet:
		n := d.uvarint()
		st := newSet()
		for i := uint64(0); i < n && d.err == nil; i++ {
			st.add(string(d.bytes()), lim)
		}
		return st
	case tZSet:
		n := d.uvarint()
		z := newZSet()
		for i := uint64(0); i < n && d.err == nil; i++ {
			m := d.bytes()
			sc := math.Float64frombits(d.u64())
			if math.IsNaN(sc) {
				d.fail()
				break
			}
			z.put(string(m), sc, lim)
		}
		return z
	}
	d.fail()
	return nil
}

// loadSnapshot replaces the keyspace with the snapshot contents.
func (s *Server) loadSnapshot(data []byte) error {
	if len(data) < len(snapMagic)+1+1+4 || string(data[:4]) != snapMagic {
		return errors.New("not a snapshot file")
	}
	body, sum := data[:len(data)-4], binary.LittleEndian.Uint32(data[len(data)-4:])
	if crc32.ChecksumIEEE(body) != sum {
		return errors.New("snapshot checksum mismatch")
	}
	if body[4] != snapVersion {
		return errors.New("unsupported snapshot version")
	}
	d := &decoder{b: body[5:]}
	var fresh [numDBs]*DB
	for i := range fresh {
		fresh[i] = newDB(i, s)
	}
	now := nowMs()
	for {
		marker := d.byte()
		if d.err != nil {
			return d.err
		}
		if marker == 0xFF {
			break
		}
		if marker != 0xFE {
			return errors.New("bad snapshot marker")
		}
		id := d.uvarint()
		n := d.uvarint()
		if d.err != nil || id >= numDBs {
			return errors.New("bad database index in snapshot")
		}
		db := fresh[id]
		for i := uint64(0); i < n; i++ {
			t := d.byte()
			exp := int64(d.u64())
			key := d.bytes()
			val := decodeValue(t, d, &s.lim)
			if d.err != nil {
				return d.err
			}
			if exp != 0 && exp <= now {
				continue
			}
			e := db.add(string(key), val)
			db.setExp(e, exp)
		}
	}
	s.dbs = fresh
	return nil
}

// Load reads the snapshot from the data directory, if one exists.
func (s *Server) Load() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	data, err := os.ReadFile(s.snapshotPath())
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if err := s.loadSnapshot(data); err != nil {
		return err
	}
	if st, err := os.Stat(s.snapshotPath()); err == nil {
		s.lastSave = st.ModTime().Unix()
	}
	log.Printf("loaded snapshot %s", s.snapshotPath())
	return nil
}

func writeFileAtomic(path string, data []byte) error {
	tmp := fmt.Sprintf("%s.tmp-%d", path, os.Getpid())
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err := f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, path)
}

// saveLocked writes a snapshot synchronously. Caller holds s.mu.
func (s *Server) saveLocked() error {
	data := s.encodeSnapshot()
	path := s.snapshotPath()
	s.saveMu.Lock()
	defer s.saveMu.Unlock()
	if err := writeFileAtomic(path, data); err != nil {
		return err
	}
	s.lastSave = time.Now().Unix()
	return nil
}

// Save snapshots the dataset (used on shutdown).
func (s *Server) Save() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.saveLocked()
}

// bgSaveLocked serialises under the lock, then writes the file in the
// background. Caller holds s.mu.
func (s *Server) bgSaveLocked() {
	data := s.encodeSnapshot()
	path := s.snapshotPath()
	s.bgSaving = true
	go func() {
		s.saveMu.Lock()
		err := writeFileAtomic(path, data)
		s.saveMu.Unlock()
		s.mu.Lock()
		s.bgSaving = false
		if err == nil {
			s.lastSave = time.Now().Unix()
		} else {
			log.Printf("background save failed: %v", err)
		}
		s.mu.Unlock()
	}()
}
