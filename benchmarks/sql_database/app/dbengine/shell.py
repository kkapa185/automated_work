"""The `sqlite3`-compatible command-line shell: reads SQL and dot-commands from stdin."""
import sys
from .errors import SqlError
from .tokenizer import tokenize
from .parser import Parser
from .executor import Engine
from . import values as V
from .functions import like_regex


def statement_complete(text):
    """True if text ends with a complete SQL statement (terminated by ';')."""
    if ';' not in text:
        return False
    toks = tokenize(text)
    toks = toks[:-1]
    if not toks or toks[-1].kind == 'bad':
        return False
    if not (toks[-1].kind == 'op' and toks[-1].val == ';'):
        return False
    if len(toks) >= 2 and toks[0].kind == 'id' and toks[0].up == 'CREATE':
        j = 1
        if toks[j].kind == 'id' and toks[j].up in ('TEMP', 'TEMPORARY'):
            j += 1
        if j < len(toks) and toks[j].kind == 'id' and toks[j].up == 'TRIGGER':
            depth = 0
            last_end = False
            for k, t in enumerate(toks):
                if t.kind == 'id':
                    if t.up == 'CASE':
                        depth += 1
                    elif t.up == 'END':
                        if depth > 0:
                            depth -= 1
                            last_end = False
                        else:
                            last_end = True
                        continue
                if k == len(toks) - 1:
                    break
                last_end = False
            return len(toks) >= 2 and toks[-2].kind == 'id' and toks[-2].up == 'END' and depth == 0
    return True


class Shell:
    def __init__(self, engine, out=None, err=None):
        self.engine = engine
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.headers = False
        self.mode = 'list'
        self.sep = '|'
        self.rowsep = '\n'
        self.nullvalue = ''
        self.widths = []
        self.errors = 0
        self.bail = False
        self.echo = False
        self.quit = False
        self.timer = False
        self.table_name = 'table'
        self.colsep_set = False

    # ------------------------------------------------------------ output helpers
    def write(self, s):
        self.out.write(s)

    def error(self, msg):
        self.out.flush()
        self.err.write(msg + '\n')
        self.err.flush()

    def fmt(self, v):
        if v is None:
            return self.nullvalue
        t = type(v)
        if t is str:
            return v
        if t is int:
            return str(v)
        if t is float:
            return V.format_real(v)
        return v.decode('utf-8', 'surrogateescape')

    def csv_field(self, v):
        s = self.fmt(v)
        if v is None:
            return s
        if type(v) is str or type(v) is bytes:
            if any(c in s for c in (self.sep, '"', '\r', '\n')) or s == '':
                if s == '' and False:
                    return s
                if s != '':
                    return '"' + s.replace('"', '""') + '"'
        return s

    def quote_val(self, v):
        if v is None:
            return 'NULL'
        t = type(v)
        if t is str:
            return "'" + v.replace("'", "''") + "'"
        if t is bytes:
            return "X'" + v.hex() + "'"
        if t is float:
            return V.format_real(v)
        return str(v)

    def print_result(self, cols, rows):
        mode = self.mode
        w = self.write
        if not rows:
            return      # like sqlite3, headers are only emitted together with the first row
        if mode == 'list' or mode == 'tabs' or mode == 'ascii':
            sep = '\t' if mode == 'tabs' else self.sep
            rs = self.rowsep
            if self.headers and cols:
                w(sep.join(cols) + rs)
            for r in rows:
                w(sep.join([self.fmt(v) for v in r]) + rs)
        elif mode == 'csv':
            rs = '\r\n'
            if self.headers and cols:
                w(self.sep.join([self.csv_field(c) if False else self._csvhdr(c) for c in cols]) + rs)
            for r in rows:
                w(self.sep.join([self.csv_field(v) for v in r]) + rs)
        elif mode == 'line':
            if not cols:
                return
            width = max(len(c) for c in cols)
            first = True
            for r in rows:
                if not first:
                    w('\n')
                first = False
                for c, v in zip(cols, r):
                    w('%s = %s\n' % (c.rjust(width), self.fmt(v)))
        elif mode == 'column':
            self.print_column(cols, rows)
        elif mode in ('table', 'box', 'markdown'):
            self.print_grid(cols, rows, mode)
        elif mode == 'quote':
            if self.headers and cols:
                w(','.join(["'" + c.replace("'", "''") + "'" for c in cols]) + '\n')
            for r in rows:
                w(','.join([self.quote_val(v) for v in r]) + '\n')
        elif mode == 'insert':
            for r in rows:
                cl = ''
                if self.headers:
                    cl = '(' + ','.join(cols) + ')'
                w('INSERT INTO %s%s VALUES(%s);\n' % (self.table_name, cl, ','.join([self.quote_val(v) for v in r])))
        elif mode == 'json':
            if not rows:
                return
            parts = []
            for r in rows:
                items = []
                for c, v in zip(cols, r):
                    items.append(self.json_str(c) + ':' + self.json_val(v))
                parts.append('{' + ','.join(items) + '}')
            w('[' + ',\n'.join(parts) + ']\n')
        elif mode == 'html':
            if self.headers and cols:
                w('<TR>' + ''.join('<TH>%s</TH>' % c for c in cols) + '\n</TR>\n')
            for r in rows:
                w('<TR>' + ''.join('<TD>%s</TD>' % self.fmt(v).replace('&', '&amp;').replace('<', '&lt;')
                                   .replace('>', '&gt;') for v in r) + '\n</TR>\n')

    def _csvhdr(self, c):
        if any(ch in c for ch in (self.sep, '"', '\r', '\n')):
            return '"' + c.replace('"', '""') + '"'
        return c

    @staticmethod
    def json_str(s):
        out = ['"']
        for ch in s:
            if ch == '"':
                out.append('\\"')
            elif ch == '\\':
                out.append('\\\\')
            elif ch == '\n':
                out.append('\\n')
            elif ch == '\r':
                out.append('\\r')
            elif ch == '\t':
                out.append('\\t')
            elif ord(ch) < 32:
                out.append('\\u%04x' % ord(ch))
            else:
                out.append(ch)
        out.append('"')
        return ''.join(out)

    def json_val(self, v):
        if v is None:
            return 'null'
        t = type(v)
        if t is int:
            return str(v)
        if t is float:
            return V.format_real(v) if v == v and abs(v) != float('inf') else 'null'
        if t is bytes:
            return self.json_str(v.decode('utf-8', 'replace'))
        return self.json_str(v)

    def print_column(self, cols, rows):
        if not cols:
            return
        texts = [[self.fmt(v).replace('\n', ' ') if True else '' for v in r] for r in rows]
        widths = []
        for i, c in enumerate(cols):
            if i < len(self.widths) and self.widths[i] != 0:
                widths.append(abs(self.widths[i]))
                continue
            wd = len(c) if self.headers else 1
            for t in texts:
                wd = max(wd, len(t[i]))
            widths.append(max(wd, 1))
        w = self.write
        if self.headers:
            w('  '.join(c.ljust(widths[i]) for i, c in enumerate(cols)) + '\n')
            w('  '.join('-' * widths[i] for i in range(len(cols))) + '\n')
        for t, r in zip(texts, rows):
            cells = []
            for i, s in enumerate(t):
                cells.append(s.ljust(widths[i]) if len(s) <= widths[i] else s[:widths[i]])
            w('  '.join(cells) + '\n')

    def print_grid(self, cols, rows, mode):
        if not cols:
            return
        texts = [[self.fmt(v).replace('\n', ' ') for v in r] for r in rows]
        widths = [len(c) for c in cols]
        for t in texts:
            for i, s in enumerate(t):
                widths[i] = max(widths[i], len(s))
        num = [[type(v) in (int, float) for v in r] for r in rows]
        w = self.write

        def cell(s, i, isnum):
            return s.rjust(widths[i]) if isnum else s.ljust(widths[i])
        if mode == 'markdown':
            w('| ' + ' | '.join(c.ljust(widths[i]) for i, c in enumerate(cols)) + ' |\n')
            w('|' + '|'.join('-' * (widths[i] + 2) for i in range(len(cols))) + '|\n')
            for t, nm in zip(texts, num):
                w('| ' + ' | '.join(cell(s, i, nm[i]) for i, s in enumerate(t)) + ' |\n')
            return
        if mode == 'table':
            line = '+' + '+'.join('-' * (x + 2) for x in widths) + '+\n'
            w(line)
            w('| ' + ' | '.join(c.ljust(widths[i]) for i, c in enumerate(cols)) + ' |\n')
            w(line)
            for t, nm in zip(texts, num):
                w('| ' + ' | '.join(cell(s, i, nm[i]) for i, s in enumerate(t)) + ' |\n')
            if texts:
                w(line)
            return
        top = '┌' + '┬'.join('─' * (x + 2) for x in widths) + '┐\n'
        mid = '├' + '┼'.join('─' * (x + 2) for x in widths) + '┤\n'
        bot = '└' + '┴'.join('─' * (x + 2) for x in widths) + '┘\n'
        w(top)
        w('│ ' + ' │ '.join(c.ljust(widths[i]) for i, c in enumerate(cols)) + ' │\n')
        w(mid)
        for t, nm in zip(texts, num):
            w('│ ' + ' │ '.join(cell(s, i, nm[i]) for i, s in enumerate(t)) + ' │\n')
        w(bot)

    # ------------------------------------------------------------ SQL execution
    def run_sql(self, src, startline):
        """Execute every statement of src. A failing statement is reported and skipped; execution continues
        with the next statement. Returns True if any error occurred."""
        parser = Parser(src)
        failed = False

        def report(e):
            nonlocal failed
            kind = 'Parse error' if e.kind == 'parse' else 'Error'
            self.error('%s near line %d: %s' % (kind, startline, e.msg))
            self.errors += 1
            failed = True
        while True:
            try:
                stmt = parser.parse_statement()
            except SqlError as e:
                report(e)
                # resynchronise after the next ';'
                while parser.tok.kind != 'eof' and not (parser.tok.kind == 'op' and parser.tok.val == ';'):
                    if parser.tok.kind == 'bad':
                        return True
                    parser.next()
                continue
            if stmt is None:
                return failed
            try:
                res = self.engine.execute(stmt)
            except SqlError as e:
                report(e)
                continue
            except (OverflowError, ValueError, ZeroDivisionError, MemoryError, TypeError, KeyError, IndexError,
                    AttributeError) as e:
                report(SqlError(str(e)))
                continue
            except RecursionError:
                report(SqlError('expression tree is too large (maximum depth 1000)'))
                continue
            if res.columns:
                self.print_result(res.columns, res.rows)

    # ------------------------------------------------------------ dot commands
    def dot_command(self, line, lineno):
        import shlex
        text = line.strip()
        try:
            parts = shlex.split(text, posix=True)
        except ValueError:
            parts = text.split()
        cmd = parts[0][1:].lower() if parts else ''
        args = parts[1:]
        eng = self.engine
        db = eng.db
        if cmd in ('quit', 'exit'):
            self.quit = True
        elif cmd in ('headers', 'header'):
            if len(args) != 1 or args[0].lower() not in ('on', 'off', '1', '0', 'yes', 'no', 'true', 'false'):
                self.error('Usage: .headers on|off')
                self.errors += 1
                return
            self.headers = args[0].lower() in ('on', '1', 'yes', 'true')
        elif cmd == 'mode':
            if not args:
                self.write('current output mode: %s\n' % self.mode)
                return
            m = args[0].lower()
            if m not in ('list', 'csv', 'line', 'column', 'tabs', 'table', 'box', 'markdown', 'json', 'insert',
                         'quote', 'html', 'ascii'):
                self.error('Error: mode should be one of: ascii box column csv html insert json line list '
                           'markdown quote table tabs tcl')
                self.errors += 1
                return
            self.mode = m
            if m == 'list':
                self.sep = '|'
            elif m == 'csv':
                self.sep = ','
            elif m == 'tabs':
                self.sep = '\t'
            if m == 'insert' and len(args) > 1:
                self.table_name = args[1]
            elif m == 'insert':
                self.table_name = 'table'
            if m == 'column' or m == 'line':
                pass
        elif cmd == 'separator':
            if not args:
                self.error('Usage: .separator COL ?ROW?')
                self.errors += 1
                return
            self.sep = self._unescape(args[0])
            if len(args) > 1:
                self.rowsep = self._unescape(args[1])
        elif cmd == 'nullvalue':
            if not args:
                self.error('Usage: .nullvalue STRING')
                self.errors += 1
                return
            self.nullvalue = self._unescape(args[0])
        elif cmd == 'tables':
            self.dot_tables(args)
        elif cmd == 'schema':
            self.dot_schema(args)
        elif cmd == 'indexes':
            pat = args[0].lower() if args else None
            names = []
            for t in db.tables.values():
                if pat and t.name.lower() != pat:
                    continue
                for ix in t.indexes:
                    names.append(ix.name)
            if names:
                self.write('\n'.join(sorted(names)) + '\n')
        elif cmd == 'bail':
            self.bail = bool(args) and args[0].lower() in ('on', '1', 'yes', 'true')
        elif cmd == 'echo':
            self.echo = bool(args) and args[0].lower() in ('on', '1', 'yes', 'true')
        elif cmd == 'timer':
            self.timer = bool(args) and args[0].lower() in ('on', '1', 'yes', 'true')
        elif cmd == 'width':
            self.widths = []
            for a in args:
                try:
                    self.widths.append(int(a))
                except ValueError:
                    self.widths.append(0)
        elif cmd == 'print':
            self.write(' '.join(args) + '\n')
        elif cmd == 'read':
            if not args:
                self.error('Usage: .read FILE')
                self.errors += 1
                return
            try:
                with open(args[0], encoding='utf-8', errors='surrogateescape') as f:
                    data = f.read()
            except OSError:
                self.error('Error: cannot open "%s"' % args[0])
                self.errors += 1
                return
            self.process(data.split('\n'))
        elif cmd == 'show':
            self.write('     echo: %s\n  headers: %s\n     mode: %s\nnullvalue: "%s"\n   output: stdout\n'
                       'separator: "%s"\n' % ('on' if self.echo else 'off', 'on' if self.headers else 'off',
                                             self.mode, self.nullvalue, self.sep))
        elif cmd == 'dump':
            self.dot_dump()
        elif cmd in ('help',):
            self.write('.headers on|off   Turn display of headers on or off\n'
                       '.mode MODE        Set output mode\n.quit             Exit this program\n')
        elif cmd in ('open', 'output', 'once', 'databases', 'changes', 'stats', 'eqp', 'explain', 'binary',
                     'prompt', 'log', 'trace', 'wal_checkpoint'):
            pass
        else:
            self.error('Error: unknown command or invalid arguments:  "%s". Enter ".help" for help' % cmd)
            self.errors += 1

    @staticmethod
    def _unescape(s):
        return s.replace('\\t', '\t').replace('\\n', '\n').replace('\\r', '\r').replace('\\\\', '\\')

    def dot_tables(self, args):
        db = self.engine.db
        names = [t.name for t in db.tables.values()] + [v.name for v in db.views.values()]
        names = [n for n in names if not n.lower().startswith('sqlite_')]
        if args:
            rx = like_regex(args[0], None)
            names = [n for n in names if rx.match(n.lower())]
        names.sort()
        if not names:
            return
        maxlen = max(len(n) for n in names)
        ncol = max(80 // (maxlen + 2), 1)
        nrow = (len(names) + ncol - 1) // ncol
        for i in range(nrow):
            line = []
            for j in range(i, len(names), nrow):
                sp = '' if j < nrow else '  '
                line.append(sp + names[j].ljust(maxlen))
            self.write(''.join(line) + '\n')

    def dot_schema(self, args):
        db = self.engine.db
        pat = args[0] if args else None
        rx = like_regex(pat.lower(), None) if pat else None
        for o in db.objects:
            if o.sql is None:
                continue
            if rx and not (rx.match(o.tbl_name.lower())):
                continue
            self.write(o.sql + ';\n')

    def dot_dump(self):
        db = self.engine.db
        self.write('PRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;\n')
        for o in db.objects:
            if o.type == 'table':
                self.write(o.sql + ';\n')
                for rid, row in o.scan().items():
                    vals = ','.join(self.quote_val(v) for v in row[:len(o.columns)])
                    self.write('INSERT INTO %s VALUES(%s);\n' % (o.name, vals))
            elif o.sql:
                self.write(o.sql + ';\n')
        self.write('COMMIT;\n')

    # ------------------------------------------------------------ main loop
    def process(self, lines):
        buf = []
        startline = 0
        lineno = 0
        for line in lines:
            lineno += 1
            if self.quit:
                return
            if not buf:
                stripped = line.lstrip()
                if stripped == '':
                    continue
                if stripped[0] == '.':
                    if self.echo:
                        self.write(line + '\n')
                    self.dot_command(stripped, lineno)
                    if self.bail and self.errors:
                        self.quit = True
                    continue
                startline = lineno
            buf.append(line)
            text = '\n'.join(buf)
            if statement_complete(text):
                if self.echo:
                    self.write(text + '\n')
                self.run_sql(text, startline)
                buf = []
                if self.bail and self.errors:
                    self.quit = True
                    return
        if buf and not self.quit:
            text = '\n'.join(buf)
            if text.strip():
                if self.echo:
                    self.write(text + '\n')
                self.run_sql(text, startline)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    path = None
    for a in argv:
        if a.startswith('-') and a != '-':
            continue
        path = a
        break
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='surrogateescape', newline='\n')
        sys.stdin.reconfigure(encoding='utf-8', errors='surrogateescape')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.setrecursionlimit(20000)
    try:
        engine = Engine(path)
    except SqlError as e:
        sys.stderr.write('Error: %s\n' % e.msg)
        return 1
    shell = Shell(engine)
    data = sys.stdin.read()
    try:
        shell.process(data.split('\n') if data else [])
    except BrokenPipeError:
        return 1
    finally:
        try:
            engine.close()
        except Exception as e:  # pragma: no cover
            sys.stderr.write('Error: %s\n' % e)
            shell.errors += 1
        try:
            sys.stdout.flush()
        except Exception:
            pass
    return 1 if shell.errors else 0
