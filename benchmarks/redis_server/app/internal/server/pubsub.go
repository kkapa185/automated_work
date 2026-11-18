package server

import (
	"fmt"
	"sort"
	"strings"
)

func registerPubSub(s *Server) {
	s.register("subscribe", -2, false, func(c *Client, a [][]byte) { subscribeCmd(c, a, false) })
	s.register("psubscribe", -2, false, func(c *Client, a [][]byte) { subscribeCmd(c, a, true) })
	s.register("unsubscribe", -1, false, func(c *Client, a [][]byte) { unsubscribeCmd(c, a, false) })
	s.register("punsubscribe", -1, false, func(c *Client, a [][]byte) { unsubscribeCmd(c, a, true) })
	s.register("publish", 3, false, cmdPublish)
	s.register("pubsub", -2, false, cmdPubSub)
}

// commands a subscribed (RESP2) connection may run
var subscribedOK = map[string]bool{
	"subscribe": true, "unsubscribe": true, "psubscribe": true, "punsubscribe": true,
	"ping": true, "quit": true, "reset": true,
}

func (c *Client) subCount() int { return len(c.subs) + len(c.psubs) }

func (c *Client) addSubReply(kind, name string, nameNil bool) {
	c.addArrayLen(3)
	c.addBulkStr(kind)
	if nameNil {
		c.addNil()
	} else {
		c.addBulkStr(name)
	}
	c.addInt(int64(c.subCount()))
}

func subscribeCmd(c *Client, a [][]byte, pattern bool) {
	s := c.srv
	for _, x := range a[1:] {
		name := string(x)
		reg, mine, kind := s.channels, &c.subs, "subscribe"
		if pattern {
			reg, mine, kind = s.patterns, &c.psubs, "psubscribe"
		}
		if *mine == nil {
			*mine = map[string]struct{}{}
		}
		if _, dup := (*mine)[name]; !dup {
			(*mine)[name] = struct{}{}
			if reg[name] == nil {
				reg[name] = map[*Client]struct{}{}
			}
			reg[name][c] = struct{}{}
		}
		c.addSubReply(kind, name, false)
	}
	// Publish the confirmation before releasing the lock so no message can
	// overtake it on the wire.
	c.flush()
}

func unsubscribeCmd(c *Client, a [][]byte, pattern bool) {
	s := c.srv
	reg, mine, kind := s.channels, c.subs, "unsubscribe"
	if pattern {
		reg, mine, kind = s.patterns, c.psubs, "punsubscribe"
	}
	var names []string
	if len(a) == 1 {
		for n := range mine {
			names = append(names, n)
		}
		sort.Strings(names)
		if len(names) == 0 {
			c.addSubReply(kind, "", true)
			c.flush()
			return
		}
	} else {
		for _, x := range a[1:] {
			names = append(names, string(x))
		}
	}
	for _, n := range names {
		if _, ok := mine[n]; ok {
			delete(mine, n)
			delete(reg[n], c)
			if len(reg[n]) == 0 {
				delete(reg, n)
			}
		}
		c.addSubReply(kind, n, false)
	}
	c.flush()
}

// unsubscribeAll drops every subscription without replying (disconnect, RESET).
func (s *Server) unsubscribeAll(c *Client) {
	for n := range c.subs {
		delete(s.channels[n], c)
		if len(s.channels[n]) == 0 {
			delete(s.channels, n)
		}
	}
	for n := range c.psubs {
		delete(s.patterns[n], c)
		if len(s.patterns[n]) == 0 {
			delete(s.patterns, n)
		}
	}
	c.subs, c.psubs = nil, nil
}

func cmdPublish(c *Client, a [][]byte) {
	s := c.srv
	channel, msg := a[1], a[2]
	n := int64(0)
	if subs := s.channels[string(channel)]; len(subs) > 0 {
		var m Client
		m.addArrayLen(3)
		m.addBulkStr("message")
		m.addBulk(channel)
		m.addBulk(msg)
		for t := range subs {
			t.push(m.buf)
			n++
		}
	}
	for pat, subs := range s.patterns {
		if !globMatch([]byte(pat), channel) {
			continue
		}
		var m Client
		m.addArrayLen(4)
		m.addBulkStr("pmessage")
		m.addBulkStr(pat)
		m.addBulk(channel)
		m.addBulk(msg)
		for t := range subs {
			t.push(m.buf)
			n++
		}
	}
	c.addInt(n)
}

func cmdPubSub(c *Client, a [][]byte) {
	s := c.srv
	sub := strings.ToUpper(string(a[1]))
	switch sub {
	case "CHANNELS":
		if len(a) > 3 {
			c.addErr("ERR wrong number of arguments for 'pubsub|channels' command")
			return
		}
		var out []string
		for ch := range s.channels {
			if len(a) == 2 || globMatch(a[2], []byte(ch)) {
				out = append(out, ch)
			}
		}
		sort.Strings(out)
		c.addArrayLen(len(out))
		for _, ch := range out {
			c.addBulkStr(ch)
		}
	case "NUMSUB":
		c.addArrayLen(2 * (len(a) - 2))
		for _, ch := range a[2:] {
			c.addBulk(ch)
			c.addInt(int64(len(s.channels[string(ch)])))
		}
	case "NUMPAT":
		if len(a) != 2 {
			c.addErr("ERR wrong number of arguments for 'pubsub|numpat' command")
			return
		}
		c.addInt(int64(len(s.patterns)))
	default:
		c.addErr(fmt.Sprintf("ERR unknown subcommand '%s'. Try PUBSUB HELP.", a[1]))
	}
}
