"""Extra regex / format / date checks (expected values derived from the manual's definitions)."""
import pytest
from conftest import evaluate, j


@pytest.mark.parametrize("prog,inp,expected", [
    ('[match("(?<x>[a-z])[-_]";"g")|.captures[0].string]', '"a-b_c"', '["a","b"]'),
    ('[splits("x";"i")]', '"aXbxc"', '["a","b","c"]'),
    ('sub("(?<l>[a-z])";"\\(.l)!";"g")', '"ab"', '"a!b!"'),
    ('[match("(?=b)";"g").offset]', '"abc"', "[1]"),
    ('test("B";"ix")', '"abc"', "true"),
    ('test("\\\\p{Alpha}"), test("\\\\p{Digit}")', '"x"', "true false"),
    ('[("test","TEst","teST","TEST")|test("(?i)te(?-i)st")]', "null", "[true,true,false,false]"),
    ('capture("(?<a>\\\\w+) (?<b>\\\\w+)")', '"foo bar"', '{"a":"foo","b":"bar"}'),
    ('[.[]|@sh]', '["a b","c\'d"]', '["\'a b\'","\'c\'\\\\\'\'d\'"]'),
    ('@csv', '["a b","c\'d"]', '"\\"a b\\",\\"c\'d\\""'),
    ('[.[]|tojson]', '[1,[2],"x"]', '["1","[2]","\\"x\\""]'),
    ('strftime("%Y-%m-%dT%H:%M:%SZ")', "[2015,2,5,23,51,47,4,63]", '"2015-03-05T23:51:47Z"'),
    ('mktime', "[2015,2,5,23,51,47,4,63]", "1425599507"),
    ('todate', "1425599507.9", '"2015-03-05T23:51:47Z"'),
    ('fromdateiso8601', '"2015-03-06T08:51:47.25+09:00"', "1425599507.25"),
    ('map(fromdateiso8601)', '["20150305T235147Z","2015-064T23:51:47Z","2015-W10-4T23:51:47Z"]',
     "[1425599507,1425599507,1425599507]"),
])
def test_extra(prog, inp, expected):
    assert evaluate(prog, j(inp)[0]) == j(expected)
