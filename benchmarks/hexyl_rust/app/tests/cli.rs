//! Integration tests. Expected outputs are derived by hand from the written spec.

use std::io::Write;
use std::process::{Command, Stdio};

struct Out {
    stdout: String,
    stderr: String,
    code: i32,
}

fn run_env(args: &[&str], input: &[u8], env: &[(&str, &str)]) -> Out {
    let mut cmd = Command::new(env!("CARGO_BIN_EXE_hexyl"));
    cmd.args(args)
        .env_remove("NO_COLOR")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (k, v) in env {
        cmd.env(k, v);
    }
    let mut child = cmd.spawn().unwrap();
    let mut stdin = child.stdin.take().unwrap();
    let data = input.to_vec();
    let t = std::thread::spawn(move || {
        let _ = stdin.write_all(&data);
    });
    let o = child.wait_with_output().unwrap();
    t.join().unwrap();
    Out {
        stdout: String::from_utf8(o.stdout).unwrap(),
        stderr: String::from_utf8_lossy(&o.stderr).into_owned(),
        code: o.status.code().unwrap_or(-1),
    }
}

fn run(args: &[&str], input: &[u8]) -> String {
    let o = run_env(args, input, &[]);
    assert_eq!(o.code, 0, "stderr: {}", o.stderr);
    o.stdout
}

const SAMPLE: &[u8] = b"Hello, World!\0\x01\x02\xff\x80 tab\there\n";

const TOP: &str = "┌────────┬─────────────────────────┬─────────────────────────┬────────┬────────┐\n";
const BOT: &str = "└────────┴─────────────────────────┴─────────────────────────┴────────┴────────┘\n";

// ---- R1 -------------------------------------------------------------------
#[test]
fn r1_default_layout_example() {
    let expected = format!(
        "{TOP}\
│00000000│ 48 65 6c 6c 6f 2c 20 57 ┊ 6f 72 6c 64 21 00 01 02 │Hello, W┊orld!⋄••│\n\
│00000010│ ff 80 20 74 61 62 09 68 ┊ 65 72 65 0a             │×× tab_h┊ere_    │\n\
{BOT}"
    );
    assert_eq!(run(&["--color=never"], SAMPLE), expected);
}

// ---- R2/R3 ----------------------------------------------------------------
#[test]
fn r3_colour_sequences_example() {
    let l1 = "│\x1b[90m00000000\x1b[39m│ \x1b[36m48 65 6c 6c 6f 2c \x1b[32m20 \x1b[36m57\x1b[39m ┊ \
\x1b[36m6f 72 6c 64 21 \x1b[90m00 \x1b[32m01 02\x1b[39m │\
\x1b[36mHello,\x1b[32m \x1b[36mW\x1b[39m┊\x1b[36morld!\x1b[90m⋄\x1b[32m••\x1b[39m│\n";
    let l2 = "│\x1b[90m00000010\x1b[39m│ \x1b[33mff 80 \x1b[32m20 \x1b[36m74 61 62 \x1b[32m09 \x1b[36m68\x1b[39m ┊ \
\x1b[36m65 72 65 \x1b[32m0a            \x1b[39m │\
\x1b[33m××\x1b[32m \x1b[36mtab\x1b[32m_\x1b[36mh\x1b[39m┊\x1b[36mere\x1b[32m_    \x1b[39m│\n";
    let expected = format!("{TOP}{l1}{l2}{BOT}");
    assert_eq!(run(&[], SAMPLE), expected);
    assert_eq!(run(&["--color=always"], SAMPLE), expected);
}

#[test]
fn r2_categories_single_panel() {
    // NULL, printable, space, tab, control, DEL, non-ascii, newline
    let o = run(&["--color=never", "--panels", "1"], b"\0A \t\x01\x7f\x80\n");
    let expected = "┌────────┬─────────────────────────┬────────┐\n\
│00000000│ 00 41 20 09 01 7f 80 0a │⋄A _••×_│\n\
└────────┴─────────────────────────┴────────┘\n";
    assert_eq!(o, expected);
}

#[test]
fn r2_colour_categories() {
    let o = run(&["--panels", "1", "-P"], b"\0A \t\x01\x7f\x80\n");
    // hex: null, print, space(ws) then tab (ws, same category), control, control, non-ascii, ws
    let hex = "\x1b[90m00 \x1b[36m41 \x1b[32m20 09 \x1b[32m01 7f \x1b[33m80 \x1b[32m0a\x1b[39m";
    assert!(o.contains(&format!("│ {hex} │")), "{o:?}");
    assert!(o.contains("\x1b[90m⋄\x1b[36mA\x1b[32m _\x1b[32m••\x1b[33m×\x1b[32m_\x1b[39m│"), "{o:?}");
}

// ---- R4 -------------------------------------------------------------------
#[test]
fn r4_squeeze_hidden_position_ascii_border() {
    let o = run(&["--color=never", "-C", "-P", "--border", "ascii"], &[0u8; 64]);
    let lines: Vec<&str> = o.lines().collect();
    assert_eq!(lines[2], "|*                        |                         |        |        |");
    assert_eq!(lines[1], "| 00 00 00 00 00 00 00 00 | 00 00 00 00 00 00 00 00 |⋄⋄⋄⋄⋄⋄⋄⋄|⋄⋄⋄⋄⋄⋄⋄⋄|");
    assert_eq!(lines[0], "+-------------------------+-------------------------+--------+--------+");
}

#[test]
fn r4_squeeze_with_position_and_total_length() {
    let o = run(&["--color=never"], &[0u8; 64]);
    let expected = format!(
        "{TOP}\
│00000000│ 00 00 00 00 00 00 00 00 ┊ 00 00 00 00 00 00 00 00 │⋄⋄⋄⋄⋄⋄⋄⋄┊⋄⋄⋄⋄⋄⋄⋄⋄│\n\
│*       │                         ┊                         │        ┊        │\n\
│00000040│                         ┊                         │        ┊        │\n\
{BOT}"
    );
    assert_eq!(o, expected);
}

#[test]
fn r4_squeeze_then_partial_line() {
    let mut data = vec![0u8; 48];
    data.push(b'x');
    let o = run(&["--color=never"], &data);
    let lines: Vec<&str> = o.lines().collect();
    assert_eq!(lines.len(), 5);
    assert!(lines[2].starts_with("│*       │"));
    let pad = " ".repeat(22);
    let expected = format!("│00000030│ 78{pad}┊{}│x       ┊        │", " ".repeat(25));
    assert_eq!(lines[3], expected);
}

#[test]
fn r4_no_squeezing() {
    let o = run(&["--color=never", "-v"], &[0u8; 48]);
    assert_eq!(o.lines().count(), 5);
    assert!(!o.contains('*'));
    let o = run(&["--color=never", "--no-squeezing"], &[0u8; 48]);
    assert!(!o.contains('*'));
}

#[test]
fn r4_two_identical_lines() {
    let o = run(&["--color=never"], &[7u8; 32]);
    let lines: Vec<&str> = o.lines().collect();
    assert_eq!(lines.len(), 5);
    assert!(lines[2].starts_with("│*       │"));
    assert!(lines[3].starts_with("│00000020│"));
}

// ---- R5 -------------------------------------------------------------------
fn seq(n: usize) -> Vec<u8> {
    (0..n).map(|i| i as u8).collect()
}

#[test]
fn r5_length_aliases() {
    let want = run(&["--color=never", "-n", "4"], &seq(32));
    assert!(want.contains("│00000000│ 00 01 02 03"));
    assert!(!want.contains("04 05"));
    for a in [["-c", "4"], ["-l", "4"], ["--bytes", "4"], ["--length", "4"]] {
        assert_eq!(run(&["--color=never", a[0], a[1]], &seq(32)), want);
    }
}

#[test]
fn r5_number_formats() {
    let data = vec![1u8; 4000];
    let count = |arg: &str| -> usize {
        let o = run(&["--color=never", "-v", "--panels", "8", "-n", arg], &data);
        // data lines only (3 border lines excluded)
        o.matches(" 01").count()
    };
    assert_eq!(count("0x10"), 16);
    assert_eq!(count("1kB"), 1000);
    assert_eq!(count("1KiB"), 1024);
    assert_eq!(count("2block"), 1024);
}

#[test]
fn r5_block_size() {
    let data = vec![1u8; 100];
    let o = run(&["--color=never", "-v", "--block-size", "8", "-n", "3block"], &data);
    assert_eq!(o.matches(" 01").count(), 24);
}

#[test]
fn r5_skip_positive_and_offset() {
    let o = run(&["--color=never", "-s", "0x10", "-n", "2"], &seq(64));
    assert!(o.contains("│00000010│ 10 11 "), "{o}");
}

#[test]
fn r5_skip_negative() {
    let o = run(&["--color=never", "-s", "-4"], &seq(64));
    assert!(o.contains("│0000003c│ 3c 3d 3e 3f "), "{o}");
    let o = run(&["--color=never", "-s", "-2", "-n", "1"], &seq(64));
    assert!(o.contains("│0000003e│ 3e "));
}

#[test]
fn r5_skip_negative_file_and_too_far() {
    let dir = std::env::temp_dir().join(format!("hexyl_t_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let f = dir.join("a.bin");
    std::fs::write(&f, seq(40)).unwrap();
    let p = f.to_str().unwrap();
    let o = run(&["--color=never", "-s", "-8", p], b"");
    assert!(o.contains("│00000020│ 20 21 22 23 24 25 26 27 "), "{o}");
    let e = run_env(&["-s", "-100", p], b"", &[]);
    assert_ne!(e.code, 0);
    let _ = std::fs::remove_dir_all(dir);
}

// ---- R6 -------------------------------------------------------------------
#[test]
fn r6_color_modes() {
    let never = run(&["--color=never"], b"A");
    assert!(!never.contains('\x1b'));
    assert!(run(&["--color=always"], b"A").contains("\x1b[36m"));
    assert!(run(&[], b"A").contains("\x1b[36m"));
    // not a tty here
    assert!(!run(&["--color=auto"], b"A").contains('\x1b'));
    let no = run_env(&["--color=always"], b"A", &[("NO_COLOR", "1")]);
    assert!(!no.stdout.contains('\x1b'));
    let no = run_env(&["--color=force"], b"A", &[("NO_COLOR", "1")]);
    assert!(no.stdout.contains("\x1b[36m"));
    let no = run_env(&["--color=force"], b"A", &[]);
    assert!(no.stdout.contains("\x1b[36m"));
}

// ---- R7 -------------------------------------------------------------------
#[test]
fn r7_ascii_border() {
    let o = run(&["--color=never", "--border", "ascii", "--panels", "1"], b"AB");
    let expected = "+--------+-------------------------+--------+\n\
|00000000| 41 42                   |AB      |\n\
+--------+-------------------------+--------+\n";
    assert_eq!(o, expected);
    let two = run(&["--color=never", "--border=ascii"], b"AB");
    assert!(two.lines().nth(1).unwrap().contains(" 41 42                   |                         |AB      |        |"));
}

#[test]
fn r7_no_border() {
    let o = run(&["--color=never", "--border", "none", "--panels", "1"], b"ABCDEFGH");
    assert_eq!(o, " 00000000  41 42 43 44 45 46 47 48  ABCDEFGH \n");
}

// ---- R8 -------------------------------------------------------------------
#[test]
fn r8_plain() {
    let o = run(&["-p"], b"ABCDEFGHIJKLMNOP");
    assert_eq!(o, "  41 42 43 44 45 46 47 48   49 4a 4b 4c 4d 4e 4f 50  \n");
    let o = run(&["--plain"], b"A");
    assert!(!o.contains('\x1b') && !o.contains("A\n") && !o.contains("00000000"));
}

#[test]
fn r8_no_characters_and_no_position() {
    let o = run(&["--color=never", "--no-characters", "--panels", "1"], b"AB");
    assert_eq!(
        o,
        "┌────────┬─────────────────────────┐\n│00000000│ 41 42                   │\n└────────┴─────────────────────────┘\n"
    );
    let o = run(&["--color=never", "-P", "--panels", "1"], b"AB");
    assert_eq!(
        o,
        "┌─────────────────────────┬────────┐\n│ 41 42                   │AB      │\n└─────────────────────────┴────────┘\n"
    );
    // -C overrides -p's no-characters
    let o = run(&["-p", "-C"], b"AB");
    assert!(o.contains("AB"));
}

// ---- R9 -------------------------------------------------------------------
#[test]
fn r9_character_tables() {
    let data = b"A\0\x01\xff \n";
    let o = run(&["--color=never", "--panels", "1", "--character-table", "ascii"], data);
    assert!(o.contains("│A... .  │"), "{o}");
    let o = run(&["--color=never", "--panels", "1", "--character-table=braille"], data);
    assert!(o.contains("│A⠀⠁⣿ ⠊  │"), "{o}");
    let o = run(&["--color=never", "--panels", "1", "--character-table=default"], data);
    assert!(o.contains("│A⋄•× _  │"), "{o}");
}

// ---- R10 ------------------------------------------------------------------
#[test]
fn r10_display_offset() {
    let o = run(&["--color=never", "-o", "0x100", "--panels", "1"], b"A");
    assert!(o.contains("│00000100│ 41"));
    let o = run(&["--color=never", "--display-offset", "16", "-s", "1"], b"AB");
    assert!(o.contains("│00000011│ 42"));
}

#[test]
fn r10_panels() {
    let o = run(&["--color=never", "--panels", "3"], &seq(24));
    let l = o.lines().nth(1).unwrap();
    assert!(l.contains("┊"));
    assert_eq!(l.chars().count(), 1 + 8 + 1 + 3 * 25 + 2 + 1 + 3 * 8 + 2 + 1);
    let o = run(&["--color=never", "--panels", "1"], &seq(24));
    assert_eq!(o.lines().count(), 5);
}

#[test]
fn r10_panels_auto() {
    let width = |w: &str| {
        let o = run(&["--color=never", "--panels", "auto", "--terminal-width", w], &seq(200));
        o.lines().next().unwrap().chars().count()
    };
    assert_eq!(width("80"), 80);
    assert_eq!(width("79"), 45); // one panel
    assert_eq!(width("115"), 115); // three panels
    assert_eq!(width("1"), 45); // never fewer than one panel
}

// ---- R11 ------------------------------------------------------------------
fn group_hex(args: &[&str]) -> String {
    let mut a = vec!["--color=never", "--panels", "1", "--no-characters", "-P", "--border", "none"];
    a.extend_from_slice(args);
    run(&a, b"ABCDEFGH")
}

#[test]
fn r11_group_size_and_endianness() {
    assert_eq!(group_hex(&["-g", "1"]), "  41 42 43 44 45 46 47 48  \n");
    assert_eq!(group_hex(&["-g", "2"]), "  4142 4344 4546 4748  \n");
    assert_eq!(group_hex(&["--group-size", "4"]), "  41424344 45464748  \n");
    assert_eq!(group_hex(&["-g", "8"]), "  4142434445464748  \n");
    assert_eq!(group_hex(&["-g", "2", "--endianness", "little"]), "  4241 4443 4645 4847  \n");
    assert_eq!(group_hex(&["-g", "4", "--endianness", "little"]), "  44434241 48474645  \n");
    assert_eq!(group_hex(&["-g", "4", "--endianness", "big"]), "  41424344 45464748  \n");
    assert_eq!(group_hex(&["-g", "8", "--endianness=little"]), "  4847464544434241  \n");
}

#[test]
fn r11_group_header_width() {
    let o = run(&["--color=never", "--panels", "1", "-g", "4"], b"ABCDEFGH");
    assert_eq!(o.lines().next().unwrap(), format!("┌────────┬{}┬────────┐", "─".repeat(19)));
}

#[test]
fn r11_invalid_group_size() {
    assert_ne!(run_env(&["-g", "3"], b"", &[]).code, 0);
}

// ---- R12 ------------------------------------------------------------------
#[test]
fn r12_bases() {
    let f = |b: &str| group_hex(&["-b", b]);
    assert_eq!(f("16"), "  41 42 43 44 45 46 47 48  \n");
    assert_eq!(f("8"), "  101 102 103 104 105 106 107 110  \n");
    assert_eq!(f("10"), "  065 066 067 068 069 070 071 072  \n");
    assert_eq!(
        f("2"),
        "  01000001 01000010 01000011 01000100 01000101 01000110 01000111 01001000  \n"
    );
    assert_eq!(f("octal"), f("8"));
    assert_eq!(f("decimal"), f("10"));
    assert_eq!(f("binary"), f("2"));
    assert_eq!(f("hexadecimal"), f("16"));
}

#[test]
fn r12_binary_header_width() {
    let o = run(&["--color=never", "--panels", "1", "--base", "2"], b"A");
    assert_eq!(o.lines().next().unwrap(), format!("┌────────┬{}┬────────┐", "─".repeat(73)));
    let o = run(&["--color=never", "--panels", "1", "--base", "10"], b"\xff");
    assert!(o.contains("│00000000│ 255 "));
}

#[test]
fn r12_invalid_base() {
    assert_ne!(run_env(&["-b", "7"], b"", &[]).code, 0);
}

// ---- R13 ------------------------------------------------------------------
#[test]
fn r13_errors() {
    let e = run_env(&["/nonexistent/file/xyz"], b"", &[]);
    assert_ne!(e.code, 0);
    assert!(e.stdout.is_empty());
    assert!(!e.stderr.is_empty());
    let e = run_env(&["--bogus"], b"", &[]);
    assert_ne!(e.code, 0);
    assert!(!e.stderr.is_empty());
    for bad in [["-n", "abc"], ["-s", "1x"], ["--panels", "0"], ["--panels", "x"], ["--block-size", "0"]] {
        let e = run_env(&bad, b"", &[]);
        assert_ne!(e.code, 0, "{bad:?}");
        assert!(e.stdout.is_empty());
    }
    assert_ne!(run_env(&["--color", "purple"], b"", &[]).code, 0);
}

#[test]
fn r13_help_and_version() {
    let h = run(&["-h"], b"");
    assert!(h.contains("--length") && h.contains("--panels"));
    let v = run(&["-V"], b"");
    assert!(v.starts_with("hexyl "));
}

#[test]
fn r13_empty_input() {
    let o = run(&["--color=never"], b"");
    assert_eq!(
        o,
        format!(
            "{TOP}│        │                         ┊                         │        ┊        │\n{BOT}"
        )
    );
}

// ---- R14 ------------------------------------------------------------------
#[test]
fn r14_file_and_stdin_agree() {
    let dir = std::env::temp_dir().join(format!("hexyl_f_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let f = dir.join("in.bin");
    std::fs::write(&f, SAMPLE).unwrap();
    let from_file = run(&["--color=never", f.to_str().unwrap()], b"");
    assert_eq!(from_file, run(&["--color=never"], SAMPLE));
    assert_eq!(from_file, run(&["--color=never", "-"], SAMPLE));
    let _ = std::fs::remove_dir_all(dir);
}

#[test]
fn r13_directory_input_is_an_error() {
    let e = run_env(&["."], b"", &[]);
    assert_ne!(e.code, 0);
    assert!(e.stdout.is_empty(), "{}", e.stdout);
    assert!(e.stderr.contains("directory"));
}
