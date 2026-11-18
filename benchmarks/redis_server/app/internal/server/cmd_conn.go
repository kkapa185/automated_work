package server

import (
	"fmt"
	"os"
	"runtime"
	"strconv"
	"strings"
	"time"
)

func registerAll(s *Server) {
	// connection / server
	s.register("ping", -1, false, cmdPing)
	s.register("echo", 2, false, func(c *Client, a [][]byte) { c.addBulk(a[1]) })
	s.register("select", 2, false, cmdSelect)
	s.register("dbsize", 1, false, func(c *Client, a [][]byte) { c.addInt(int64(len(c.db.data))) })
	s.register("flushdb", -1, true, cmdFlushDB)
	s.register("flushall", -1, true, cmdFlushAll)
	s.register("info", -1, false, cmdInfo)
	s.register("time", 1, false, cmdTime)
	s.register("quit", -1, false, func(c *Client, a [][]byte) { c.addSimple("OK"); c.quit = true })
	s.register("command", -1, false, cmdCommand)
	s.register("config", -2, false, cmdConfig)
	s.register("client", -2, false, cmdClient)
	s.register("hello", -1, false, cmdHello)
	s.register("save", 1, false, cmdSave)
	s.register("bgsave", -1, false, cmdBgSave)
	s.register("lastsave", 1, false, func(c *Client, a [][]byte) { c.addInt(c.srv.lastSave) })
	s.register("shutdown", -1, false, cmdShutdown)
	registerKeys(s)
	registerStrings(s)
	registerLists(s)
	registerHashes(s)
	registerSets(s)
	registerZSets(s)
	registerTx(s)
	registerPubSub(s)
}

func cmdPing(c *Client, a [][]byte) {
	if c.subCount() > 0 { // subscribed connections get a push-style pong
		c.addArrayLen(2)
		c.addBulkStr("pong")
		if len(a) == 2 {
			c.addBulk(a[1])
		} else {
			c.addBulkStr("")
		}
		return
	}
	switch len(a) {
	case 1:
		c.addSimple("PONG")
	case 2:
		c.addBulk(a[1])
	default:
		c.addErr("ERR wrong number of arguments for 'ping' command")
	}
}

func cmdSelect(c *Client, a [][]byte) {
	n, ok := parseInt64(a[1])
	if !ok {
		c.addErr("ERR invalid DB index")
		return
	}
	if n < 0 || n >= numDBs {
		c.addErr("ERR DB index is out of range")
		return
	}
	c.db = c.srv.dbs[n]
	c.addSimple("OK")
}

func checkFlushMode(c *Client, a [][]byte) bool {
	if len(a) > 2 {
		c.addErr(errSyntax)
		return false
	}
	if len(a) == 2 {
		m := strings.ToUpper(string(a[1]))
		if m != "ASYNC" && m != "SYNC" {
			c.addErr(errSyntax)
			return false
		}
	}
	return true
}

func cmdFlushDB(c *Client, a [][]byte) {
	if !checkFlushMode(c, a) {
		return
	}
	c.db.flush()
	c.addSimple("OK")
}

func cmdFlushAll(c *Client, a [][]byte) {
	if !checkFlushMode(c, a) {
		return
	}
	for _, d := range c.srv.dbs {
		d.flush()
	}
	c.addSimple("OK")
}

func cmdTime(c *Client, a [][]byte) {
	now := time.Now()
	c.addArrayLen(2)
	c.addBulkStr(strconv.FormatInt(now.Unix(), 10))
	c.addBulkStr(strconv.FormatInt(int64(now.Nanosecond()/1000), 10))
}

func cmdInfo(c *Client, a [][]byte) {
	s := c.srv
	want := map[string]bool{}
	all := len(a) == 1
	for _, x := range a[1:] {
		n := strings.ToLower(string(x))
		if n == "all" || n == "default" || n == "everything" {
			all = true
		}
		want[n] = true
	}
	var sb strings.Builder
	section := func(name string, lines ...string) {
		if !all && !want[name] {
			return
		}
		if sb.Len() > 0 {
			sb.WriteString("\r\n")
		}
		sb.WriteString("# " + strings.ToUpper(name[:1]) + name[1:] + "\r\n")
		for _, l := range lines {
			sb.WriteString(l + "\r\n")
		}
	}
	up := time.Since(s.started)
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	section("server",
		"redis_version:7.0.0-kv", "redis_mode:standalone", "os:"+runtime.GOOS,
		"arch_bits:64", "process_id:"+strconv.Itoa(os.Getpid()),
		"tcp_port:"+s.cfg["port"], "uptime_in_seconds:"+strconv.Itoa(int(up.Seconds())),
		"uptime_in_days:"+strconv.Itoa(int(up.Hours()/24)), "hz:10", "config_file:")
	section("clients", "connected_clients:"+strconv.Itoa(len(s.clients)), "blocked_clients:"+strconv.Itoa(s.blockedCount()))
	section("memory", "used_memory:"+strconv.FormatUint(ms.HeapAlloc, 10),
		"used_memory_human:"+strconv.FormatUint(ms.HeapAlloc/1024, 10)+"K", "maxmemory:0")
	section("persistence", "loading:0", "rdb_bgsave_in_progress:"+b2s(s.bgSaving),
		"rdb_last_save_time:"+strconv.FormatInt(s.lastSave, 10), "aof_enabled:0")
	section("stats", "total_connections_received:"+strconv.FormatInt(s.stats.connections, 10),
		"total_commands_processed:"+strconv.FormatInt(s.stats.commands, 10),
		"expired_keys:"+strconv.FormatInt(s.stats.expired, 10),
		"keyspace_hits:"+strconv.FormatInt(s.stats.hits, 10),
		"keyspace_misses:"+strconv.FormatInt(s.stats.misses, 10))
	section("replication", "role:master", "connected_slaves:0")
	section("cpu", "used_cpu_sys:0.0", "used_cpu_user:0.0")
	var ks []string
	for _, d := range s.dbs {
		if len(d.data) > 0 {
			ks = append(ks, fmt.Sprintf("db%d:keys=%d,expires=%d,avg_ttl=0", d.id, len(d.data), len(d.ttl)))
		}
	}
	section("keyspace", ks...)
	c.addBulkStr(sb.String())
}

func b2s(b bool) string {
	if b {
		return "1"
	}
	return "0"
}

func cmdSave(c *Client, a [][]byte) {
	if err := c.srv.saveLocked(); err != nil {
		c.addErr("ERR " + err.Error())
		return
	}
	c.addSimple("OK")
}

func cmdBgSave(c *Client, a [][]byte) {
	if len(a) > 2 || (len(a) == 2 && strings.ToUpper(string(a[1])) != "SCHEDULE") {
		c.addErr(errSyntax)
		return
	}
	if c.srv.bgSaving {
		c.addErr("ERR Background save already in progress")
		return
	}
	c.srv.bgSaveLocked()
	c.addSimple("Background saving started")
}

func cmdShutdown(c *Client, a [][]byte) {
	save := true
	for _, x := range a[1:] {
		switch strings.ToUpper(string(x)) {
		case "NOSAVE":
			save = false
		case "SAVE", "NOW", "FORCE":
		default:
			c.addErr(errSyntax)
			return
		}
	}
	if save {
		if err := c.srv.saveLocked(); err != nil {
			c.addErr("ERR Errors trying to SHUTDOWN. Check logs.")
			return
		}
	}
	os.Exit(0)
}

func cmdCommand(c *Client, a [][]byte) {
	s := c.srv
	if len(a) == 1 {
		names := s.commandNames()
		c.addArrayLen(len(names))
		for _, n := range names {
			addCommandInfo(c, s.cmds[n])
		}
		return
	}
	switch strings.ToUpper(string(a[1])) {
	case "COUNT":
		c.addInt(int64(len(s.cmds)))
	case "INFO":
		c.addArrayLen(len(a) - 2)
		for _, n := range a[2:] {
			if cmd := s.cmds[strings.ToLower(string(n))]; cmd != nil {
				addCommandInfo(c, cmd)
			} else {
				c.addNilArray()
			}
		}
	case "DOCS":
		c.addEmptyArray()
	case "LIST":
		names := s.commandNames()
		c.addArrayLen(len(names))
		for _, n := range names {
			c.addBulkStr(n)
		}
	default:
		c.addErr(fmt.Sprintf("ERR unknown subcommand '%s'. Try COMMAND HELP.", a[1]))
	}
}

func addCommandInfo(c *Client, cmd *Cmd) {
	c.addArrayLen(6)
	c.addBulkStr(cmd.name)
	c.addInt(int64(cmd.arity))
	if cmd.write {
		c.addArrayLen(1)
		c.addSimple("write")
	} else {
		c.addArrayLen(1)
		c.addSimple("readonly")
	}
	c.addInt(0)
	c.addInt(0)
	c.addInt(0)
}

func cmdConfig(c *Client, a [][]byte) {
	s := c.srv
	sub := strings.ToUpper(string(a[1]))
	switch sub {
	case "GET":
		if len(a) < 3 {
			c.addErr("ERR wrong number of arguments for 'config|get' command")
			return
		}
		var out []string
		seen := map[string]bool{}
		for _, p := range a[2:] {
			pat := []byte(strings.ToLower(string(p)))
			for _, k := range sortedKeys(s.cfg) {
				if !seen[k] && globMatch(pat, []byte(k)) {
					seen[k] = true
					out = append(out, k, s.cfg[k])
				}
			}
		}
		c.addArrayLen(len(out))
		for _, x := range out {
			c.addBulkStr(x)
		}
	case "SET":
		if len(a) < 4 || len(a)%2 != 0 {
			c.addErr("ERR wrong number of arguments for 'config|set' command")
			return
		}
		for i := 2; i < len(a); i += 2 {
			s.cfg[strings.ToLower(string(a[i]))] = string(a[i+1])
		}
		s.refreshLimits()
		c.addSimple("OK")
	case "RESETSTAT":
		s.stats = stats{}
		c.addSimple("OK")
	case "REWRITE":
		c.addSimple("OK")
	default:
		c.addErr(fmt.Sprintf("ERR unknown subcommand '%s'. Try CONFIG HELP.", a[1]))
	}
}

func cmdClient(c *Client, a [][]byte) {
	sub := strings.ToUpper(string(a[1]))
	switch sub {
	case "ID":
		c.addInt(c.id)
	case "SETNAME":
		if len(a) != 3 {
			c.addErr("ERR wrong number of arguments for 'client|setname' command")
			return
		}
		c.name = string(a[2])
		c.addSimple("OK")
	case "GETNAME":
		if c.name == "" {
			c.addNil()
		} else {
			c.addBulkStr(c.name)
		}
	case "SETINFO":
		c.addSimple("OK")
	case "INFO", "LIST":
		c.addBulkStr(fmt.Sprintf("id=%d addr=%s name=%s db=%d\n", c.id, c.conn.RemoteAddr(), c.name, c.db.id))
	default:
		c.addErr(fmt.Sprintf("ERR unknown subcommand '%s'. Try CLIENT HELP.", a[1]))
	}
}

func cmdHello(c *Client, a [][]byte) {
	if len(a) > 1 {
		v, ok := parseInt64(a[1])
		if !ok {
			c.addErr("ERR Protocol version is not an integer or out of range")
			return
		}
		if v != 2 {
			c.addErr("NOPROTO sorry, this protocol version is not supported")
			return
		}
	}
	c.addArrayLen(14)
	for _, kv := range [][2]string{{"server", "redis"}, {"version", "7.0.0-kv"}} {
		c.addBulkStr(kv[0])
		c.addBulkStr(kv[1])
	}
	c.addBulkStr("proto")
	c.addInt(2)
	c.addBulkStr("id")
	c.addInt(c.id)
	c.addBulkStr("mode")
	c.addBulkStr("standalone")
	c.addBulkStr("role")
	c.addBulkStr("master")
	c.addBulkStr("modules")
	c.addEmptyArray()
}

func sortedKeys(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sortStrings(out)
	return out
}
