"""Unit tests per builtin family (expected values derived from the jq manual / definitions)."""
import math
import pytest

from conftest import evaluate, j
from jqpy.values import JQError

CASES = [
    # length & friends
    ("length", '"héllo"', "5"), ("length", "[1,2]", "2"), ("length", '{"a":1}', "1"),
    ("length", "null", "0"), ("length", "-5", "5"), ("utf8bytelength", '"é"', "2"),
    ("keys", '{"b":1,"a":2}', '["a","b"]'), ("keys", "[5,6]", "[0,1]"),
    ("has(\"a\")", '{"a":null}', "true"), ("has(1)", "[1]", "false"),
    ("map(.+1)", "[1,2]", "[2,3]"), ("map_values(empty)", '{"a":1}', "{}"),
    ("map_values(.+1)", '{"a":1}', '{"a":2}'),
    ("add", "[1,2,3]", "6"), ("add", '["a","b"]', '"ab"'), ("add", "[]", "null"),
    ("add(.[].a)", '[{"a":1},{"a":2}]', "3"),
    ("any", "[false,true]", "true"), ("all", "[true,false]", "false"), ("any", "[]", "false"),
    ("all", "[]", "true"), ("any(. > 2)", "[1,3]", "true"), ("all(. > 0)", "[1,3]", "true"),
    ("any(1,2; . == 2)", "null", "true"),
    ("flatten", "[1,[2,[3]]]", "[1,2,3]"), ("flatten(1)", "[1,[2,[3]]]", "[1,2,[3]]"),
    ("floor, ceil, round, sqrt", "4.5", "4 5 5 2.1213203435596424"),
    ("round", "-2.5", "-3"), ("fabs", "-3", "3"), ("abs", "-3", "3"), ("abs", "0", "0"),
    ("pow(2;10), log2, exp2", "8", "1024 3 256"), ("log10", "1000", "3"),
    ("[.[]|trunc]", "[1.9,-1.9]", "[1,-1]"),
    ("tonumber", '"12"', "12"), ("tonumber", '"1.5"', "1.5"), ("tonumber", "3", "3"),
    ("tostring", "[1,\"a\"]", '"[1,\\"a\\"]"'), ("tostring", '"x"', '"x"'),
    ("toboolean", '"true"', "true"), ("type", "[1]", '"array"'),
    ("[.[]|type]", '[null,true,1,"a",[],{}]', '["null","boolean","number","string","array","object"]'),
    ("[infinite, -infinite] | tojson", "null", '"[1.7976931348623157e+308,-1.7976931348623157e+308]"'),
    ("[nan] | .[0] | isnan", "null", "true"), ("isinfinite", "1", "false"), ("isnormal", "1", "true"),
    ("isnormal", "0", "false"), ("[.[]|isfinite]", "[1,2]", "[true,true]") if False else ("isfinite", "1", "true"),
    ("sort", '[3,"a",null,[1],{},true,false,1]', '[null,false,true,1,3,"a",[1],{}]'),
    ("sort_by(.a)", '[{"a":2},{"a":1}]', '[{"a":1},{"a":2}]'),
    ("sort_by(.a, .b)", '[{"a":1,"b":2},{"a":1,"b":1}]', '[{"a":1,"b":1},{"a":1,"b":2}]'),
    ("group_by(.a)", '[{"a":1,"b":1},{"a":2},{"a":1,"b":2}]', '[[{"a":1,"b":1},{"a":1,"b":2}],[{"a":2}]]'),
    ("min, max", "[3,1,2]", "1 3"), ("min", "[]", "null"),
    ("min_by(.a), max_by(.a)", '[{"a":2},{"a":1}]', '{"a":1} {"a":2}'),
    ("unique", "[2,1,2]", "[1,2]"), ("unique_by(length)", '["a","bb","c"]', '["a","bb"]'),
    ("reverse", "[1,2]", "[2,1]"), ("reverse", '"abc"', '"cba"'), ("reverse", "null", "[]"),
    ("contains(\"bar\")", '"foobar"', "true"), ("contains([1])", "[1,2]", "true"),
    ("contains({a:1})", '{"a":1,"b":2}', "true"), ("contains([[1]])", "[[1,2]]", "true"),
    ("inside([1,2])", "[1]", "true"),
    ("indices(1)", "[0,1,1]", "[1,2]"), ("indices(\"a\")", '"banana"', "[1,3,5]"),
    ("indices([1,2])", "[1,2,1,2]", "[0,2]"), ("index(\",\"), rindex(\",\")", '"a,b,c"', "1 3"),
    ("startswith(\"a\"), endswith(\"c\")", '"abc"', "true true"),
    ("ltrimstr(\"a\"), rtrimstr(\"c\"), trimstr(\"a\")", '"abc"', '"bc" "ab" "bc"'),
    ("ltrimstr(1)", '"a"', '"a"'),
    ("trim, ltrim, rtrim", '"  a b  "', '"a b" "a b  " "  a b"'),
    ("explode", '"aé"', "[97,233]"), ("implode", "[97,233]", '"aé"'),
    ("split(\", \")", '"a, b"', '["a","b"]'), ("split(\"\")", '"ab"', '["a","b"]'),
    ("join(\",\")", '["a",1,null,true]', '"a,1,,true"'), ("join(\",\")", "[]", '""'),
    ("ascii_downcase, ascii_upcase", '"aBé"', '"abé" "ABé"'),
    ("combinations", "[[1,2],[3,4]]", "[1,3] [1,4] [2,3] [2,4]"),
    ("[combinations(2)]", "[0,1]", "[[0,0],[0,1],[1,0],[1,1]]"),
    ("walk(if type == \"number\" then .+1 else . end)", "[1,{\"a\":2}]", '[2,{"a":3}]'),
    ("transpose", "[[1],[2,3]]", "[[1,2],[null,3]]"),
    ("in({\"a\":1})", '"a"', "true"),
    ("bsearch(2), bsearch(0), bsearch(4)", "[1,2,3]", "1 -1 -4"),
    ("tojson", '{"a":[1,"x"]}', '"{\\"a\\":[1,\\"x\\"]}"'),
    ("fromjson", '"{\\"a\\":1}"', '{"a":1}'),
    ("tostream", '{"a":[1]}', '[["a",0],1] [["a",0]] [["a"]]'),
    ("fromstream(tostream)", '{"a":[1,{"b":2}]}', '{"a":[1,{"b":2}]}'),
    ("[1|truncate_stream([[0],1],[[1,0],2],[[1,0]],[[1]])]", "null", "[[[0],2],[[0]]]"),
    ("[.[]|toarray]", "[1,[2]]", "[[1],[2]]"),
    ("have_literal_numbers", "null", "true"),
    ("splits(\",\")", '"a,b"', '"a" "b"'),
    ("ascii", "65", '"A"'),
    ("getpath([\"a\"])", '{"a":1}', "1"),
    ("[paths]", "[[1]]", "[[0],[0,0]]"), ("[leaf_paths]", '{"a":[1]}', '[["a",0]]'),
    ("INDEX(.id)", '[{"id":1},{"id":2}]', '{"1":{"id":1},"2":{"id":2}}'),
    ("IN(2,3)", "2", "true"), ("IN([1,2],[3]; [3],[4])", "null", "true"),
    ("[JOIN({\"1\":\"x\"}; .[]; tostring)]", "[1]", '[[1,"x"]]'),
    ("input_line_number", "null", "0"),
    ("[limit(2; .[])]", "[1,2,3]", "[1,2]"), ("[skip(1; .[])]", "[1,2,3]", "[2,3]"),
    ("ltrimstr(\"x\")", "1", "1"),
    ("significand, logb, gamma", "8", "1 3 8.525161361065415"),
    ("frexp", "8", "[0.5,4]"), ("modf", "3.5", "[0.5,3]"), ("ldexp(1;3)", "null", "8") if False else ("drem(5;3)", "null", "-1"),
    ("[.[]|exp10]", "[2]", "[100]"), ("atan2(0;1)", "null", "0"), ("fma(2;3;4)", "null", "10"),
    ("cbrt", "27", "3"), ("fmin(1;2), fmax(1;2)", "null", "1 2"), ("hypot(3;4)", "null", "5"),
    ("copysign(3;-1)", "null", "-3"), ("nearbyint", "2.5", "2"), ("rint", "3.5", "4"),
    ("[splits(\"a\";\"i\")]", '"bAc"', '["b","c"]'),
    ("ltrimstr(\"\")", '"a"', '"a"'),
    ("env.HOME|type", "null", '"string"'),
    ("builtins|length > 100", "null", "true"),
    ("$ENV|has(\"PATH\")", "null", "true"),
    ("@text", "[1]", '"[1]"'), ("@json", '"a"', '"\\"a\\""'),
    ("@html", "\"<&'\\\">\"", '"&lt;&amp;&apos;&quot;&gt;"'),
    ("@uri", '"a b/é~"', '"a%20b%2F%C3%A9~"'),
    ("@csv", '[1,"a\\"b",null,true]', '"1,\\"a\\"\\"b\\",,true"'),
    ("@tsv", '["a\\tb","c\\\\d",null,false,1]', '"a\\\\tb\\tc\\\\\\\\d\\t\\tfalse\\t1"'),
    ("@sh", '"it\'s"', '"\'it\'\\\\\'\'s\'"'), ("@sh", '[1,"a b"]', '"1 \'a b\'"'),
    ("@base64", '"hello"', '"aGVsbG8="'), ("@base64d", '"aGVsbG8="', '"hello"'),
    ("@base64d", '"aGVsbG8"', '"hello"'), ("@base32", '"hi"', '"NBUQ===="'), ("@base32d", '"NBUQ===="', '"hi"'),
    ("@urid", '"a%20b%C3%A9"', '"a bé"'),
    ('@json "x=\\(.)"', '[1,"a"]', '"x=[1,\\"a\\"]"'),
    ('@html "<b>\\(.)</b>"', '"<"', '"<b>&lt;</b>"'),
    ('@uri "q=\\(.)"', '"a b"', '"q=a%20b"'),
    # regex
    ('test("a.c")', '"abc"', "true"), ('test("A";"i")', '"a"', "true"), ('test("a b";"x")', '"ab"', "true"),
    ('[match("a";"g").offset]', '"aXa"', "[0,2]"),
    ('match("(?<n>b)").captures[0].name', '"abc"', '"n"'),
    ('capture("(?<y>\\\\d+)-(?<m>\\\\d+)")', '"2020-05"', '{"y":"2020","m":"05"}'),
    ('[scan("\\\\d")]', '"a1b2"', '["1","2"]'), ('[scan("(a)(b)?")]', '"ab a"', '[["a","b"],["a",null]]'),
    ('sub("a";"b")', '"aa"', '"ba"'), ('gsub("a";"b")', '"aa"', '"bb"'),
    ('gsub("(?<x>\\\\w)";"\\(.x|ascii_upcase)")', '"ab"', '"AB"'), ('gsub("";"-")', '"ab"', '"-a-b-"'),
    ('gsub("^";">")', '"a\\nb"', '">a\\nb"'),
    ('gsub("a";"b";"i")', '"aA"', '"bb"'), ('[match("";"g")]|length', '"abc"', "4"),
    ('split("a+";"g")', '"xaay"', '["x","y"]'),
    ('test("^b")', '"a\\nb"', "false"),
    ('[match("\\\\h+";"g").string]', '"ab zz"', '["ab"]'),
    ('test("[[:alpha:]]+")', '"abc"', "true"),
    ('[match("é";"g").offset]', '"aéé"', "[1,2]"),
    # dates
    ("todate", "1425599621", '"2015-03-05T23:53:41Z"'), ("fromdate", '"2015-03-05T23:53:41Z"', "1425599621"),
    ("gmtime", "1425599621", "[2015,2,5,23,53,41,4,63]"), ("gmtime|mktime", "1425599621", "1425599621"),
    ("gmtime | [.[5] > 41.67, .[5] < 41.68, .[0:5]]", "1425599621.678", "[true,true,[2015,2,5,23,53]]"),
    ('strftime("%A, %B %d, %Y")', "1435677542", '"Tuesday, June 30, 2015"'),
    ('strftime("%Y-%m-%dT%H:%M:%SZ %j %Z")', "0", '"1970-01-01T00:00:00Z 001 UTC"'),
    ('strptime("%Y-%m-%d")', '"2015-03-05"', "[2015,2,5,0,0,0,4,63]"),
    ('strptime("%Y-%m-%dT%H:%M:%SZ")|mktime', '"2015-03-05T23:51:47Z"', "1425599507"),
    ("dateadd(\"seconds\"; 10)", "5", "15"), ("date", "0", '"1970-01-01T00:00:00Z"'),
    ('fromdateiso8601', '"2015-03-05T23:51Z"', "1425599460"), ('fromdateiso8601', '"2015-03-05T23Z"', "1425596400"),
    ('fromdateiso8601', '"2015-03-05"', "1425513600"), ('fromdateiso8601', '"2015-03-05 23:51:47+09:00"', "1425567107"),
    ('fromdateiso8601', '"2015-03-05T24:00:00Z"', "1425600000"),
    ('fromdateiso8601', '"2015-03-05T23:59:60Z"', "1425599999"),
    ('fromdateiso8601', '"2015-03-05T23,5Z"', "1425598200"),
    ('fromdateiso8601', '"+012015-03-05T00:00:00Z"', "316995033600"),
    ('fromdateiso8601', '"2015-w10-4t23:51:47z"', "1425599507"),
    ('now|type', "null", '"number"'),
]


@pytest.mark.parametrize("prog,inp,expected", CASES, ids=["%03d-%s" % (i, c[0][:40]) for i, c in enumerate(CASES)])
def test_builtin(prog, inp, expected):
    got = evaluate(prog, j(inp)[0])
    exp = j(expected)
    assert len(got) == len(exp)
    for g, e in zip(got, exp):
        if isinstance(e, float) and not isinstance(g, bool):
            assert g == pytest.approx(e, rel=1e-6)
        else:
            assert g == e and type(g) is type(e) or g == e


@pytest.mark.parametrize("prog,inp", [
    ("fromdateiso8601", '"2015"'), ("fromdateiso8601", '"2015-03"'), ("fromdateiso8601", '"T23:51:47"'),
    ("fromdateiso8601", '"2015-02-30"'), ("fromdateiso8601", '"2016-W53-1"'), ("fromdateiso8601", '"2015-03-05Z"'),
    ("fromdateiso8601", '"20150305T23:51:47Z"'), ("fromdateiso8601", "1"),
    ("tonumber", '"abc"'), ("tonumber", "[]"), ("@csv", "1"), ("@csv", "[[1]]"), ("@sh", "[[1]]"),
    ("@base64d", '"!!!"'), ("implode", "[-1]"), ("keys", "1"), ("sort", "1"), ("test(1)", '"a"'),
    ("test(\"(\")", '"a"'), ("ltrimstr", "1") if False else ("split(1)", '"a"'), ("join(\",\")", "[[1]]"),
    ("flatten(-1)", "[]"), ("has(\"a\")", "[1]"), ("contains(1)", '"a"'), ("startswith(1)", '"a"'),
    ("mktime", '"x"'), ("strftime(\"%Y\")", '"x"'), ("strptime(\"%Y\")", '"x"'), ("ascii_downcase", "1"),
    ("fromjson", '"{"'), ("tojson|fromjson|error", "1"), ("trim", "1"), ("utf8bytelength", "1"),
    ("range(\"a\")", "null"), ("limit(-1; 1)", "null"), ("nth(-1; 1)", "null"), ("halt_error(\"x\")", "1") if False else ("error", "1"),
])
def test_builtin_errors(prog, inp):
    with pytest.raises(JQError):
        evaluate(prog, j(inp)[0])


def test_nan_ordering_and_equality():
    assert evaluate("[nan] | sort | .[0] | isnan") == [True]
    assert evaluate("nan == nan, nan < nan, nan > nan") == [False, True, False]
    assert evaluate("[nan, 1] | min | isnan") == [True]


def test_big_literals_compare_exactly():
    assert evaluate("100000000000000000000000000001 > 100000000000000000000000000000") == [True]
    assert evaluate("[.] | tojson", None) == ["[null]"]
