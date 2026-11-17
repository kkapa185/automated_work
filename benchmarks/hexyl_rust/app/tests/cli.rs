use hexyl::parse_size;
use std::io::Write;
use std::process::{Command, Stdio};

const SAMPLE: &[u8] = b"Hello, World!\0\x01\x02\xff\x80 tab\there\n";

fn run(args: &[&str], input: &[u8]) -> (String, String, i32) {
    let mut c = Command::new(env!("CARGO_BIN_EXE_hexyl"))
        .args(args)
        .env_remove("NO_COLOR")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let _ = c.stdin.take().unwrap().write_all(input);
    let o = c.wait_with_output().unwrap();
    (
        String::from_utf8_lossy(&o.stdout).into_owned(),
        String::from_utf8_lossy(&o.stderr).into_owned(),
        o.status.code().unwrap_or(-1),
    )
}

fn out(args: &[&str], input: &[u8]) -> String {
    let (o, e, c) = run(args, input);
    assert_eq!(c, 0, "stderr: {e}");
    o
}

const DEFAULT_SAMPLE: &str = "┌────────┬─────────────────────────┬─────────────────────────┬────────┬────────┐
│00000000│ 48 65 6c 6c 6f 2c 20 57 ┊ 6f 72 6c 64 21 00 01 02 │Hello, W┊orld!⋄••│
│00000010│ ff 80 20 74 61 62 09 68 ┊ 65 72 65 0a             │×× tab_h┊ere_    │
└────────┴─────────────────────────┴─────────────────────────┴────────┴────────┘
";

#[test]
fn r1_r2_r4_default_layout_no_color() {
    assert_eq!(out(&["--color=never"], SAMPLE), DEFAULT_SAMPLE);
}

#[test]
fn r3_color_sequences() {
    let o = out(&[], SAMPLE);
    let l = o.lines().nth(1).unwrap();
    assert!(l.starts_with("│\x1b[90m00000000\x1b[39m│ \x1b[36m48 65 6c 6c 6f 2c \x1b[32m20 \x1b[36m57\x1b[39m ┊ "), "{l:?}");
    assert!(l.contains("\x1b[36mHello,\x1b[32m \x1b[36mW\x1b[39m┊"));
}

#[test]
fn r7_no_color_env_and_force() {
    let run_env = |args: &[&str], v: &str| {
        let mut c = Command::new(env!("CARGO_BIN_EXE_hexyl"))
            .args(args).env("NO_COLOR", v)
            .stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
        c.stdin.take().unwrap().write_all(b"a").unwrap();
        String::from_utf8(c.wait_with_output().unwrap().stdout).unwrap()
    };
    assert!(!run_env(&[], "1").contains('\x1b'));
    assert!(run_env(&["--color=force"], "1").contains('\x1b'));
    // auto with piped stdout: no colour
    assert!(!out(&["--color=auto"], b"a").contains('\x1b'));
    assert!(out(&["--color=always"], b"a").contains('\x1b'));
}

#[test]
fn r5_squeezing() {
    let o = out(&["--color=never"], &[0u8; 64]);
    let lines: Vec<&str> = o.lines().collect();
    assert_eq!(lines.len(), 5);
    assert_eq!(lines[2], "│*       │                         ┊                         │        ┊        │");
    assert!(lines[3].starts_with("│00000040│  "));
    let o = out(&["--color=never", "-v"], &[0u8; 64]);
    assert_eq!(o.lines().count(), 6);
    assert!(o.contains("│00000030│"));
    assert!(!o.contains('*'));
    // squeeze followed by different data: no trailing length line
    let mut d = vec![1u8; 48];
    d.extend_from_slice(b"xyz");
    let o = out(&["--color=never"], &d);
    assert!(o.contains("│*       │") && o.contains("│00000030│ 78 79 7a"));
}

#[test]
fn r16_empty_input() {
    let o = out(&["--color=never"], b"");
    assert_eq!(o.lines().count(), 3);
    assert!(o.lines().nth(1).unwrap().starts_with("│        │"));
}

#[test]
fn r6_length_skip_and_units() {
    let o = out(&["--color=never", "-n", "5", "-s", "7"], SAMPLE);
    assert!(o.contains("│00000007│ 57 6f 72 6c 64 "));
    let o = out(&["--color=never", "-s", "-4"], SAMPLE);
    assert!(o.contains("│0000001c│ 68 65 72 65") || o.contains("65 72 65 0a"));
    let o = out(&["--color=never", "--bytes", "0x2"], SAMPLE);
    assert!(o.contains("48 65  ") && !o.contains("6c"));
    let o = out(&["--color=never", "-c", "1"], SAMPLE);
    assert!(o.contains("│H "));
    let o = out(&["--color=never", "--block-size", "4", "-s", "1block", "-n", "2block"], SAMPLE);
    assert!(o.contains("│00000004│ 6f 2c 20 57 6f 72 6c 64"));
    // file argument
    let dir = std::env::temp_dir().join(format!("hexyl_t_{}", std::process::id()));
    std::fs::write(&dir, SAMPLE).unwrap();
    let o = out(&["--color=never", "-s", "-1", dir.to_str().unwrap()], b"");
    assert!(o.contains("│0000001b│ 0a"), "{o}");
    let _ = std::fs::remove_file(&dir);
}

#[test]
fn r6_parse_size() {
    assert_eq!(parse_size("42", 512).unwrap(), 42);
    assert_eq!(parse_size("0x1f", 512).unwrap(), 31);
    assert_eq!(parse_size("0x1B", 512).unwrap(), 27);
    assert_eq!(parse_size("2kB", 512).unwrap(), 2000);
    assert_eq!(parse_size("1KiB", 512).unwrap(), 1024);
    assert_eq!(parse_size("3MiB", 512).unwrap(), 3 << 20);
    assert_eq!(parse_size("1GB", 512).unwrap(), 1_000_000_000);
    assert_eq!(parse_size("2block", 100).unwrap(), 200);
    assert_eq!(parse_size("0x10kB", 1).unwrap(), 16000);
    assert!(parse_size("abc", 512).is_err());
    assert!(parse_size("5xx", 512).is_err());
}

#[test]
fn r8_border_styles() {
    let o = out(&["--color=never", "--border=ascii"], SAMPLE);
    assert!(o.starts_with("+--------+-------------------------+-------------------------+--------+--------+\n"));
    assert!(o.contains("|00000000| 48 65 6c 6c 6f 2c 20 57 | 6f 72 6c 64 21 00 01 02 |Hello, W|orld!⋄••|"));
    let o = out(&["--color=never", "--border=none"], SAMPLE);
    assert_eq!(o.lines().count(), 2);
    assert!(o.starts_with(" 00000000  48 65"));
}

#[test]
fn r9_plain() {
    let o = out(&["-p"], SAMPLE);
    assert!(!o.contains('\x1b') && !o.contains('│') && !o.contains("Hello"));
    assert_eq!(o.lines().count(), 2);
    assert!(o.starts_with("  48 65 6c 6c 6f 2c 20 57   6f 72"));
}

#[test]
fn r10_characters_and_tables() {
    let o = out(&["--color=never", "--no-characters"], SAMPLE);
    assert!(!o.contains("Hello") && o.lines().next().unwrap() == "┌────────┬─────────────────────────┬─────────────────────────┐");
    assert!(o.contains("01 02 │\n"));
    let o = out(&["--color=never", "--no-characters", "-C"], SAMPLE);
    assert!(o.contains("Hello"));
    let o = out(&["--color=never", "--character-table=ascii"], SAMPLE);
    assert!(o.contains("│Hello, W┊orld!...│") && o.contains("│.. tab.h┊ere.    │"));
    let o = out(&["--color=never", "--character-table=braille"], SAMPLE);
    assert!(o.contains("orld!⠀⠁⠂│") && o.contains("⣿"));
}

#[test]
fn r11_position_and_offset() {
    let o = out(&["--color=never", "-P"], SAMPLE);
    assert!(o.starts_with("┌─────────────────────────┬─────────────────────────┬────────┬────────┐\n│ 48 65"));
    let o = out(&["--color=never", "-o", "0x100", "-s", "4"], SAMPLE);
    assert!(o.contains("│00000104│ 6f 2c"));
}

#[test]
fn r12_panels() {
    let o = out(&["--color=never", "--panels", "1"], SAMPLE);
    assert!(o.lines().nth(1).unwrap().starts_with("│00000000│ 48 65 6c 6c 6f 2c 20 57 │Hello, W│"));
    assert_eq!(o.lines().count(), 6);
    let o = out(&["--color=never", "--panels", "auto", "--terminal-width", "115"], SAMPLE);
    assert_eq!(o.lines().next().unwrap().chars().count(), 115);
    assert!(o.lines().nth(1).unwrap().contains("┊ ff 80"));
    let o = out(&["--color=never", "--panels", "auto", "--terminal-width", "114"], SAMPLE);
    assert_eq!(o.lines().next().unwrap().chars().count(), 80);
    let o = out(&["--color=never", "--panels", "auto", "--terminal-width", "10"], SAMPLE);
    assert_eq!(o.lines().next().unwrap().chars().count(), 45);
}

#[test]
fn r13_groups_and_endianness() {
    let o = out(&["--color=never", "-g", "2"], SAMPLE);
    assert!(o.contains("│ 4865 6c6c 6f2c 2057 ┊ 6f72"), "{o}");
    let o = out(&["--color=never", "-g", "4", "--endianness", "little"], SAMPLE);
    assert!(o.contains("│ 6c6c6548 57202c6f ┊ 646c726f 02010021 │"), "{o}");
    let o = out(&["--color=never", "-g", "8", "--endianness=big"], SAMPLE);
    assert!(o.contains("│ 48656c6c6f2c2057 ┊ 6f726c6421000102 │"));
    // header width follows the panel width
    assert!(o.starts_with("┌────────┬──────────────────┬──────────────────┬────────┬────────┐"));
    assert!(run(&["-g", "3"], b"a").2 != 0);
}

#[test]
fn r14_bases() {
    let b = b"\x05A";
    assert!(out(&["--color=never", "-b", "2"], b).contains("│ 00000101 01000001 "));
    assert!(out(&["--color=never", "--base=octal"], b).contains("│ 005 101 "));
    assert!(out(&["--color=never", "-b", "10"], b).contains("│ 005 065 "));
    assert!(out(&["--color=never", "-b", "hexadecimal"], b).contains("│ 05 41 "));
    assert!(run(&["-b", "7"], b).2 != 0);
}

#[test]
fn r15_errors() {
    let (o, e, c) = run(&["/nonexistent/file"], b"");
    assert!(o.is_empty() && !e.is_empty() && c != 0);
    assert!(run(&["--bogus"], b"").2 != 0);
    assert!(run(&["-n", "zz"], b"").2 != 0);
    assert!(run(&["--color=purple"], b"").2 != 0);
    assert!(run(&["-s", "-100"], b"abc").2 != 0);
    assert!(run(&["--panels", "0"], b"abc").2 != 0);
    let (o, _, c) = run(&["-V"], b"");
    assert_eq!(c, 0);
    assert!(o.starts_with("hexyl "));
    let (o, _, c) = run(&["-h"], b"");
    assert_eq!(c, 0);
    assert!(o.contains("--panels"));
}

#[test]
fn r17_stdin_dash() {
    assert_eq!(out(&["--color=never", "-"], SAMPLE), DEFAULT_SAMPLE);
}

#[test]
fn r6_stdin_skip_positive_negative_and_zero_length() {
    let data: Vec<u8> = (b'a'..=b'z').collect();
    let o = out(&["--color=never", "-s", "5"], &data);
    assert!(o.contains("│00000005│ 66 67 68 69 6a 6b 6c 6d ┊ 6e"));
    let o = out(&["--color=never", "-s", "-5"], &data);
    assert!(o.contains("│00000015│ 76 77 78 79 7a "));
    let o = out(&["--color=never", "-n", "0"], &data);
    assert_eq!(o.lines().count(), 3);
    let o = out(&["--color=never", "-s", "1KiB"], &data);
    assert_eq!(o.lines().count(), 3);
}
