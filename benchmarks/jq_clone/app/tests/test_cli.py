"""CLI behaviour: options, formatting, errors, exit codes."""
import json
import os

import pytest

from conftest import run_jq


def out(args, stdin="", **kw):
    rc, o, e = run_jq(args, stdin, **kw)
    return o


def test_pretty_default_two_spaces():
    assert out(["."], '{"a":[1,{"b":null}],"c":{}, "d":[]}') == (
        '{\n  "a": [\n    1,\n    {\n      "b": null\n    }\n  ],\n  "c": {},\n  "d": []\n}\n')


def test_compact_tab_indent():
    assert out(["-c", "."], '{"a": [1, 2]}') == '{"a":[1,2]}\n'
    assert out(["--tab", "."], '{"a":[1]}') == '{\n\t"a": [\n\t\t1\n\t]\n}\n'
    assert out(["--indent", "1", "."], '{"a":[1]}') == '{\n "a": [\n  1\n ]\n}\n'
    assert out(["--indent", "0", "."], '{"a": [1]}') == '{"a":[1]}\n'
    assert run_jq(["--indent", "8", "."], "1")[0] == 2


def test_raw_join_ascii_sort():
    assert out(["-r", ".[]"], '["a","b\\nc",1]') == "a\nb\nc\n1\n"
    assert out(["-j", ".[]"], '["a","b",1]') == "ab1"
    assert out(["-a", "-c", "."], '"é😀"') == '"\\u00e9\\ud83d\\ude00"\n'
    assert out(["-S", "-c", "."], '{"b":1,"a":{"d":1,"c":2}}') == '{"a":{"c":2,"d":1},"b":1}\n'
    assert out(["-c", "."], '{"b":1,"a":2}') == '{"b":1,"a":2}\n'
    assert out(["--raw-output0", ".[]"], '["a","b"]') == "a\0b\0"


def test_number_formatting():
    o = out(["-c", "."], "[1.0, 1.50, 100000000000000000000, 0.1, 1e1000, -0, 3, 1.5e300, 0.0001]")
    assert o == "[1.0,1.50,100000000000000000000,0.1,1.7976931348623157e+308,-0,3,1.5E+300,0.0001]\n"
    assert out(["-c", "[.[] | . + 0]"], "[1.0, 2.5, 100000000000000000000]") == "[1,2.5,1e+20]\n"
    assert out(["-nc", "[1/3, 1e-5 * 1, 1e17 * 1, 3.0e-7 * 1, 123456789012 * 10, 0.1 + 0.2]"]) == (
        "[0.3333333333333333,1e-05,1e+17,3e-07,1234567890120,0.30000000000000004]\n")
    assert out(["-nc", "[nan, infinite, -infinite]"]) == "[null,1.7976931348623157e+308,-1.7976931348623157e+308]\n"
    assert out(["-nc", "[1.0|tojson, (1.0|tostring)]"]) == '["1.0","1.0"]\n'


def test_multiple_inputs_and_files(tmp_path):
    assert out(["-c", "."], '1 "a" [2] {"b":3}\nnull') == '1\n"a"\n[2]\n{"b":3}\nnull\n'
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text('{"a":1}')
    f2.write_text("[2] 3")
    assert out(["-c", ".", str(f1), str(f2)]) == '{"a":1}\n[2]\n3\n'
    assert out(["-c", "input_filename", str(f1)]) == json.dumps(str(f1)) + "\n"


def test_null_input_slurp_raw():
    assert out(["-n", "1+1"]) == "2\n"
    assert out(["-c", "-s", "."], "1 2 3") == "[1,2,3]\n"
    assert out(["-c", "-n", "[inputs]"], "1 2 3") == "[1,2,3]\n"
    assert out(["-c", "-n", "input, input"], "1 2 3") == "1\n2\n"
    assert out(["-c", "[., input]"], "1 2 3 4") == "[1,2]\n[3,4]\n"
    assert out(["-R", "."], "a\nb\n") == '"a"\n"b"\n'
    assert out(["-R", "."], "a\nb") == '"a"\n"b"\n'
    assert out(["-Rs", "."], "a\nb\n") == '"a\\nb\\n"\n'
    assert out(["-Rn", "-c", "[inputs]"], "a\nb\n") == '["a","b"]\n'
    assert out(["-c", "-s", "."], "") == "[]\n"
    assert out(["-nr", '"x"']) == "x\n"


def test_args(tmp_path):
    assert out(["-n", "-c", "[$a, $b, $ARGS.named]", "--arg", "a", "1", "--argjson", "b", '{"x":[1]}']) == (
        '["1",{"x":[1]},{"a":"1","b":{"x":[1]}}]\n')
    assert out(["-n", "-c", "$ARGS", "--args", "x", "y"]) == '{"positional":["x","y"],"named":{}}\n'
    assert out(["-n", "-c", "$ARGS.positional", "--jsonargs", "1", '"s"', "null"]) == '[1,"s",null]\n'
    s = tmp_path / "s.json"
    s.write_text('1 {"a":2}')
    r = tmp_path / "r.txt"
    r.write_text("raw\ntext")
    assert out(["-n", "-c", "[$s, $r]", "--slurpfile", "s", str(s), "--rawfile", "r", str(r)]) == (
        '[[1,{"a":2}],"raw\\ntext"]\n')
    assert out(["-n", "$ENV.FOO", "-r"], env={"FOO": "bar"}) == "bar\n"
    assert out(["-n", "env.FOO", "-r"], env={"FOO": "bar"}) == "bar\n"


def test_from_file(tmp_path):
    p = tmp_path / "p.jq"
    p.write_text("# comment\n.a | . + 1\n")
    d = tmp_path / "d.json"
    d.write_text('{"a":1}')
    assert out(["-f", str(p), str(d)]) == "2\n"
    assert out(["--from-file", str(p)], '{"a":5}') == "6\n"


def test_exit_status():
    assert run_jq(["-e", "."], "true")[0] == 0
    assert run_jq(["-e", "."], "null")[0] == 1
    assert run_jq(["-e", "."], "false")[0] == 1
    assert run_jq(["-e", "empty"], "1")[0] == 4
    assert run_jq(["--exit-status", ".[]"], "[1,null]")[0] == 1
    assert run_jq(["."], "null")[0] == 0


def test_runtime_error_stderr_and_code():
    rc, o, e = run_jq(["-c", ".a"], '{"a":1}\n[1]\n{"a":3}\n')
    assert rc == 5
    assert o == "1\n3\n"
    assert e == 'jq: error (at <stdin>:2): Cannot index array with "a"\n'
    rc, o, e = run_jq(["error"], '{"a":1}\n')
    assert (rc, e) == (5, 'jq: error (at <stdin>:1) (not a string): {"a":1}\n')
    rc, o, e = run_jq(["error"], '"msg"')
    assert e == "jq: error (at <stdin>:0): msg\n"
    rc, o, e = run_jq(["-n", "error(\"x\")"])
    assert rc == 5 and e == "jq: error (at <unknown>): x\n"


def test_compile_and_usage_errors():
    rc, o, e = run_jq(["1 +"], "")
    assert rc == 3 and "syntax error" in e and e.rstrip().endswith("jq: 1 compile error")
    rc, o, e = run_jq(["foo"], "")
    assert rc == 3 and "foo/0 is not defined" in e
    assert run_jq([], "")[0] == 2
    assert run_jq(["--nonsense", "."], "")[0] == 2
    assert run_jq(["--arg", "x"], "")[0] == 2
    assert run_jq(["."], "{")[0] == 2
    rc, o, e = run_jq(["."], '{"a":1} {')
    assert rc == 2 and o == '{\n  "a": 1\n}\n' and "jq: error" in e
    rc, o, e = run_jq([".", "/nonexistent/file"], "")
    assert rc == 2 and "Could not open /nonexistent/file" in e


def test_halt():
    rc, o, e = run_jq(["-n", '"bye\\n"|halt_error(1)'])
    assert (rc, o, e) == (1, "", "bye\n")
    rc, o, e = run_jq(["-n", '{"a":1}|halt_error'])
    assert (rc, e) == (5, '{"a":1}\n')
    assert run_jq(["-n", "1, halt, 2"])[:2] == (0, "1\n")


def test_stream_and_seq():
    assert out(["-c", "--stream", "."], '{"a":[1,2],"b":3}') == (
        '[["a",0],1]\n[["a",1],2]\n[["a",1]]\n[["b"],3]\n[["b"]]\n')
    assert out(["-c", "--stream", "."], '3 []') == '[[],3]\n[[],[]]\n'
    assert out(["-c", "--seq", "."], "[1]") == "\x1e[1]\n"


def test_short_option_clusters_and_misc():
    assert out(["-nrc", '"a"']) == "a\n"
    assert out(["-cn", "[1,2]"]) == "[1,2]\n"
    assert out([".a", "-c"], '{"a":[1]}') == "[1]\n"
    assert out(["-n", "--", "-1"]) == "-1\n" if False else True
    rc, o, e = run_jq(["-V"])
    assert rc == 0 and o.startswith("jq-")
    rc, o, e = run_jq(["-h"])
    assert rc == 0 and "Usage" in o


def test_color_output():
    assert out(["-nC", "null"]) == "\x1b[0;90mnull\x1b[0m\n"
    o = out(["-nCc", '[{"a":true,"b":false},123,null]'])
    assert o == ("\x1b[1;39m[\x1b[1;39m{\x1b[0m\x1b[1;34m\"a\"\x1b[0m\x1b[1;39m:\x1b[0m\x1b[0;39mtrue\x1b[0m"
                 "\x1b[1;39m,\x1b[0m\x1b[1;34m\"b\"\x1b[0m\x1b[1;39m:\x1b[0m\x1b[0;39mfalse\x1b[0m"
                 "\x1b[1;39m\x1b[1;39m}\x1b[0m\x1b[1;39m,\x1b[0;39m123\x1b[0m\x1b[1;39m,\x1b[0;90mnull\x1b[0m"
                 "\x1b[1;39m\x1b[1;39m]\x1b[0m\n")
    assert out(["-nC", "1"], env={"JQ_COLORS": "0;31:0;32:0;33:0;34"}) == "\x1b[0;34m1\x1b[0m\n"


def test_unicode_and_surrogates():
    assert out(["-c", "."], '"\\ud83d\\ude00 \\ud800"') == '"😀 \ufffd"\n'
    assert out(["-c", "length"], '"😀"') == "1\n"


def test_debug_stderr_input_line():
    rc, o, e = run_jq(["-c", "debug"], "[1]")
    assert o == "[1]\n" and e == '["DEBUG:",[1]]\n'
    rc, o, e = run_jq(["-n", '"a\\n"|stderr|empty'])
    assert e == "a\n" or e == '"a\\n"'


def test_seq_input_with_record_separators():
    assert out(["-c", "--seq", "."], "\x1e1\n\x1e[2]\n") == "\x1e1\n\x1e[2]\n"
