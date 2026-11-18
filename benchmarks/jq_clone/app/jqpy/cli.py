"""Command line interface for the jq clone."""
import os
import sys
import threading

from . import VERSION
from .values import (JQError, tojson, dumps, iter_values, ParseError, parse_json, truthy,
                     DEFAULT_COLORS)
from .lexer import JQSyntaxError
from .parser import parse
from .interp import Compiler, Scope, Env, HaltEx, BreakEx, dump_trunc
from .builtins import BUILTINS, STATE

USAGE = """Usage:\tjq [OPTIONS] FILTER [FILES...]
\tjq [OPTIONS] --args FILTER [STRINGS...]
\tjq [OPTIONS] --jsonargs FILTER [JSON_TEXTS...]

jq is a tool for processing JSON inputs, applying the given filter to
its JSON text inputs and producing the filter's results as JSON on
standard output.

The simplest filter is ., which copies jq's input to its output
unmodified except for formatting. For more advanced filters see
the jq(1) manpage ("man jq") and/or https://jqlang.github.io/jq/.

Example:

\t$ echo '{"foo": 0}' | jq .
\t{
\t  "foo": 0
\t}

Command options:
  -n, --null-input          use `null` as the single input value;
  -R, --raw-input           read each line as string instead of JSON;
  -s, --slurp               read all inputs into an array and use it as
                            the single input value;
  -c, --compact-output      compact instead of pretty-printed output;
  -r, --raw-output          output strings without escapes and quotes;
      --raw-output0         implies -r and output NUL after each output;
  -j, --join-output         implies -r and output without newline after
                            each output;
  -a, --ascii-output        output strings by only ASCII characters
                            using escape sequences;
  -S, --sort-keys           sort keys of each object on output;
  -C, --color-output        colorize JSON output;
  -M, --monochrome-output   disable colored output;
      --tab                 use tabs for indentation;
      --indent n            use n spaces for indentation (max 7 spaces);
      --unbuffered          flush output stream after each output;
      --stream              parse the input value in streaming fashion;
      --stream-errors       implies --stream and report parse error as
                            an array;
      --seq                 parse input/output with application/json-seq
                            MIME type;
  -f, --from-file file      load filter from the file;
  -L directory              search modules from the directory;
      --arg name value      set $name to the string value;
      --argjson name value  set $name to the JSON value;
      --slurpfile name file set $name to an array of JSON values read
                            from the file;
      --rawfile name file   set $name to string contents of file;
      --args                consume remaining arguments as positional
                            string values;
      --jsonargs            consume remaining arguments as positional
                            JSON values;
  -e, --exit-status         set exit status code based on the output;
  -V, --version             show the version;
  --build-configuration     show jq's build configuration;
  -h, --help                show the help;
  --                        terminates argument processing;

Named arguments are also available as $ARGS.named[], while
positional arguments are available as $ARGS.positional[].
"""


class Usage(Exception):
    def __init__(self, msg, code=2):
        Exception.__init__(self, msg)
        self.msg = msg
        self.code = code


class Options(object):
    def __init__(self):
        self.null_input = False
        self.raw_input = False
        self.slurp = False
        self.compact = False
        self.raw_output = False
        self.raw0 = False
        self.join = False
        self.ascii = False
        self.sort_keys = False
        self.color = False
        self.tab = False
        self.indent = 2
        self.stream = False
        self.stream_errors = False
        self.seq = False
        self.exit_status = False
        self.from_file = False
        self.program = None
        self.files = []
        self.named = {}
        self.positional = []
        self.lib_dirs = []


def parse_args(argv):
    o = Options()
    positional_mode = None   # None, "args", "jsonargs"
    rest = []
    i = 0
    only_pos = False
    n = len(argv)

    def take(k):
        nonlocal i
        if i + k >= n + 0 and i + k > n - 1 + 0:
            pass
        if i + k > n - 1:
            raise Usage("jq: error: %s takes %d parameter%s (e.g. %s)" % (
                argv[i], k, "s" if k > 1 else "", argv[i] + " " + " ".join(["value"] * k)))
        vals = argv[i + 1:i + 1 + k]
        i += k
        return vals

    while i < n:
        a = argv[i]
        if only_pos or not a.startswith("-") or a == "-":
            if o.program is None and not (o.from_file and o.program is not None):
                o.program = a
            elif positional_mode == "args":
                o.positional.append(a)
            elif positional_mode == "jsonargs":
                try:
                    o.positional.append(parse_json(a))
                except ParseError:
                    raise Usage("jq: Invalid JSON text passed to --jsonargs")
            else:
                o.files.append(a)
            i += 1
            continue
        if a == "--":
            only_pos = True
            i += 1
            continue
        if a.startswith("--"):
            name = a[2:]
            if name == "null-input":
                o.null_input = True
            elif name == "raw-input":
                o.raw_input = True
            elif name == "slurp":
                o.slurp = True
            elif name == "compact-output":
                o.compact = True
            elif name == "raw-output":
                o.raw_output = True
            elif name == "raw-output0":
                o.raw_output = True
                o.raw0 = True
            elif name == "join-output":
                o.raw_output = True
                o.join = True
            elif name == "ascii-output":
                o.ascii = True
            elif name == "sort-keys":
                o.sort_keys = True
            elif name == "color-output":
                o.color = True
            elif name == "monochrome-output":
                o.color = False
            elif name == "tab":
                o.tab = True
            elif name == "indent":
                (v,) = take(1)
                try:
                    k = int(v)
                except ValueError:
                    raise Usage("jq: Cannot indent that many characters" if False else "jq: --indent takes a number")
                if k < -1:
                    raise Usage("jq: Cannot indent less than -1 characters")
                if k > 7:
                    raise Usage("jq: Cannot indent more than 7 characters")
                o.indent = k
                o.tab = False
            elif name in ("unbuffered", "binary"):
                pass
            elif name == "stream":
                o.stream = True
            elif name == "stream-errors":
                o.stream = True
                o.stream_errors = True
            elif name == "seq":
                o.seq = True
            elif name == "from-file":
                o.from_file = True
            elif name == "exit-status":
                o.exit_status = True
            elif name == "library-path":
                o.lib_dirs.append(take(1)[0])
            elif name == "arg":
                k, v = take(2)
                o.named[k] = v
            elif name == "argjson":
                k, v = take(2)
                try:
                    o.named[k] = parse_json(v)
                except ParseError:
                    raise Usage("jq: Invalid JSON text passed to --argjson")
            elif name in ("slurpfile", "rawfile"):
                k, fn = take(2)
                try:
                    with open(fn, "rb") as fh:
                        text = fh.read().decode("utf-8", "replace")
                except OSError as e:
                    raise Usage("jq: Bad JSON in --%s %s %s: Could not open %s: %s" % (
                        name, k, fn, fn, e.strerror))
                if name == "rawfile":
                    o.named[k] = text
                else:
                    try:
                        o.named[k] = [v for v, _ in iter_values(text)]
                    except ParseError as e:
                        raise Usage("jq: Bad JSON in --slurpfile %s %s: %s" % (k, fn, e))
            elif name == "args":
                positional_mode = "args"
            elif name == "jsonargs":
                positional_mode = "jsonargs"
            elif name == "help":
                sys.stdout.write(USAGE)
                raise Usage(None, 0)
            elif name == "version":
                sys.stdout.write(VERSION + "\n")
                raise Usage(None, 0)
            elif name == "build-configuration":
                sys.stdout.write("python\n")
                raise Usage(None, 0)
            else:
                raise Usage("jq: Unknown option: %s\n%s" % (a, USAGE.split("\n\n")[0]))
            i += 1
            continue
        # short options cluster
        flags = a[1:]
        j = 0
        while j < len(flags):
            c = flags[j]
            if c == "n":
                o.null_input = True
            elif c == "R":
                o.raw_input = True
            elif c == "s":
                o.slurp = True
            elif c == "c":
                o.compact = True
            elif c == "r":
                o.raw_output = True
            elif c == "j":
                o.raw_output = True
                o.join = True
            elif c == "a":
                o.ascii = True
            elif c == "S":
                o.sort_keys = True
            elif c == "C":
                o.color = True
            elif c == "M":
                o.color = False
            elif c == "e":
                o.exit_status = True
            elif c == "b":
                pass
            elif c == "f":
                o.from_file = True
            elif c == "L":
                rest_ = flags[j + 1:]
                if rest_:
                    o.lib_dirs.append(rest_)
                else:
                    o.lib_dirs.append(take(1)[0])
                break
            elif c == "h":
                sys.stdout.write(USAGE)
                raise Usage(None, 0)
            elif c == "V":
                sys.stdout.write(VERSION + "\n")
                raise Usage(None, 0)
            else:
                raise Usage("jq: Unknown option: %s\n%s" % (a, USAGE.split("\n\n")[0]))
            j += 1
        i += 1
    return o


def stream_events(v, path=(), top=True):
    """Convert a value to jq's streaming form."""
    if isinstance(v, list) and v:
        for i, x in enumerate(v):
            yield from stream_events(x, path + (i,), False)
        yield [list(path) + [len(v) - 1]]
    elif isinstance(v, dict) and v:
        last = None
        for k, x in v.items():
            yield from stream_events(x, path + (k,), False)
            last = k
        yield [list(path) + [last]]
    else:
        yield [list(path), v]


class InputReader(object):
    """Iterates over all input values, tracking the current filename and line."""

    def __init__(self, opts):
        self.opts = opts
        self.files = opts.files
        self.status = 0
        self.cur_name = None
        self.cur_text = ""
        self.cur_end = 0
        self.gen = self._values()
        self.started = False
        self.parse_error = None

    def _rs(self, text):
        # --seq: ASCII RS separates texts; treat it as whitespace
        return text.replace("\x1e", " ") if self.opts.seq else text

    def _texts(self):
        if not self.files:
            data = sys.stdin.buffer.read()
            yield "<stdin>", self._rs(data.decode("utf-8", "replace"))
            return
        for fn in self.files:
            try:
                with open(fn, "rb") as fh:
                    data = fh.read()
            except OSError as e:
                sys.stderr.write("jq: error: Could not open %s: %s\n" % (fn, e.strerror))
                self.status = 2
                continue
            yield fn, self._rs(data.decode("utf-8", "replace"))

    def _values(self):
        o = self.opts
        if o.raw_input:
            if o.slurp:
                parts = []
                for name, text in self._texts():
                    self.cur_name = name
                    parts.append(text)
                self.cur_text = "".join(parts)
                self.cur_end = len(self.cur_text)
                yield "".join(parts)
                return
            carry = ""
            for name, text in self._texts():
                self.cur_name = name
                self.cur_text = text
                lines = (carry + text).split("\n")
                carry = lines.pop()
                pos = 0
                for ln in lines:
                    pos += len(ln) + 1
                    self.cur_end = pos
                    yield ln
            if carry:
                yield carry
            return
        if o.slurp:
            acc = []
            for name, text in self._texts():
                self.cur_name = name
                self.cur_text = text
                try:
                    for v, end in iter_values(text):
                        self.cur_end = end
                        if o.stream:
                            acc.extend(stream_events(v))
                        else:
                            acc.append(v)
                except ParseError as e:
                    self.parse_error = str(e)
                    self.status = 2
                    return
            yield acc
            return
        for name, text in self._texts():
            self.cur_name = name
            self.cur_text = text
            try:
                for v, end in iter_values(text):
                    self.cur_end = end
                    if o.stream:
                        yield from stream_events(v)
                    else:
                        yield v
            except ParseError as e:
                self.parse_error = str(e)
                self.status = 2
                return

    def next(self):
        self.started = True
        v = next(self.gen)
        STATE.filename = None if self.cur_name == "<stdin>" else self.cur_name
        return v

    def location(self):
        if not self.started or self.cur_name is None:
            return "<unknown>"
        t = self.cur_text
        end = self.cur_end
        nl = t.find("\n", max(end - 1, 0))
        upto = nl + 1 if nl >= 0 else len(t)
        line = t.count("\n", 0, upto)
        return "%s:%d" % (self.cur_name, line)


def make_colors():
    cols = list(DEFAULT_COLORS)
    env = os.environ.get("JQ_COLORS")
    if env:
        parts = env.split(":")
        for i, p in enumerate(parts[:8]):
            if all(ch.isdigit() or ch == ";" for ch in p):
                cols[i] = p
    return ["\x1b[" + c + "m" for c in cols]


def run(argv):
    try:
        opts = parse_args(argv)
    except Usage as u:
        if u.msg:
            sys.stderr.write(u.msg + "\n")
            if u.code == 2 and "Unknown option" not in u.msg:
                pass
        return u.code
    if opts.program is None:
        sys.stderr.write(USAGE.split("\n\n")[0] + "\n")
        sys.stderr.write("Use jq --help for help with command-line options,\nor see the jq manpage, or online docs  at https://jqlang.github.io/jq\n")
        return 2
    if opts.from_file:
        try:
            with open(opts.program, "rb") as fh:
                prog_text = fh.read().decode("utf-8", "replace")
        except OSError as e:
            sys.stderr.write("jq: error: Could not open %s: %s\n" % (opts.program, e.strerror))
            return 2
    else:
        prog_text = opts.program

    env_vars = dict(os.environ)
    gvars = {"ENV": env_vars, "ARGS": {"positional": opts.positional, "named": dict(opts.named)},
             "JQ_BUILD_CONFIGURATION": "python"}
    for k, v in opts.named.items():
        gvars[k] = v
    # compile
    comp = Compiler(BUILTINS)
    sc = None
    root = None
    for k, v in gvars.items():
        sc = Scope("v", k, 0, sc)
        root = Env(root, "$" + k, v)
    STATE.lib_dirs = opts.lib_dirs
    try:
        mod, directives, body = parse(prog_text)
        if directives:
            from .modules import load_directives
            body = load_directives(directives, body, opts, comp)
        prog = comp.compile(body, sc)
    except JQSyntaxError as e:
        sys.stderr.write("jq: error: %s at <top-level>, line 1:\n%s\njq: 1 compile error\n" % (e.msg, prog_text))
        return 3
    except JQError as e:
        sys.stderr.write("jq: error: %s\njq: 1 compile error\n" % e.message())
        return 3

    reader = InputReader(opts)
    STATE.next_input = reader.next
    STATE.stderr = sys.stderr
    out = sys.stdout.buffer
    indent = None if opts.compact else ("\t" if opts.tab else (" " * opts.indent if opts.indent > 0 else None))
    colors = make_colors() if opts.color else None
    buf = []
    buflen = 0
    status = 0
    last_output = [None, False]

    def flush():
        nonlocal buf, buflen
        if buf:
            data = "".join(buf)
            try:
                out.write(data.encode("utf-8"))
            except UnicodeEncodeError:
                out.write(data.encode("utf-8", "replace"))
            buf = []
            buflen = 0
        out.flush()

    def emit(v):
        nonlocal buflen
        if opts.seq:
            buf.append("\x1e")
        if opts.raw_output and isinstance(v, str):
            s = v
            if opts.raw0 and "\0" in s:
                raise JQError("jq: error (at %s): Cannot dump a string containing NUL with --raw-output0 option" % reader.location())
            if opts.ascii:
                s = dumps(v, None, False, True)[1:-1] if any(ord(c) > 127 for c in v) else s
            buf.append(s)
        else:
            buf.append(dumps(v, indent, opts.sort_keys, opts.ascii, colors))
        if opts.raw0:
            buf.append("\0")
        elif not opts.join:
            buf.append("\n")
        buflen += 1
        if buflen > 512:
            flush()

    def report(e):
        if e.value is not None and isinstance(e.value, str):
            msg = "jq: error (at %s): %s\n" % (reader.location(), e.value)
        else:
            msg = "jq: error (at %s) (not a string): %s\n" % (reader.location(), tojson(e.value))
        flush()
        sys.stderr.write(msg)
        sys.stderr.flush()

    def process(v):
        nonlocal status
        try:
            for _, x in prog(root, None, v):
                emit(x)
                last_output[0] = x
                last_output[1] = True
        except JQError as e:
            report(e)
            status = 5
        except BreakEx:
            flush()
            sys.stderr.write("jq: error (at %s): break\n" % reader.location())
            status = 5
        except RecursionError:
            flush()
            sys.stderr.write("jq: error (at %s): stack overflow\n" % reader.location())
            status = 5

    try:
        if opts.null_input:
            process(None)
        else:
            while True:
                try:
                    v = reader.next()
                except StopIteration:
                    break
                process(v)
        if reader.parse_error:
            flush()
            sys.stderr.write("jq: error (at %s): %s\n" % (reader.location(), reader.parse_error))
            status = 2
    except HaltEx as h:
        flush()
        if h.msg is not None:
            m = h.msg
            if isinstance(m, str):
                sys.stderr.write(m)
            else:
                sys.stderr.write(tojson(m) + "\n")
            sys.stderr.flush()
        return h.code
    except BrokenPipeError:
        return 0
    flush()
    if reader.status and status == 0:
        status = reader.status
    if status:
        return status
    if opts.exit_status:
        if not last_output[1]:
            return 4
        return 0 if truthy(last_output[0]) else 1
    return 0


def main():
    sys.setrecursionlimit(1000000)
    threading.stack_size(512 * 1024 * 1024)
    result = []

    def target():
        try:
            result.append(run(sys.argv[1:]))
        except BrokenPipeError:
            result.append(0)
        except KeyboardInterrupt:
            result.append(130)

    t = threading.Thread(target=target)
    t.start()
    t.join()
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        pass
    code = result[0] if result else 1
    sys.stdout = None if False else sys.stdout
    os._exit(code) if False else sys.exit(code)
