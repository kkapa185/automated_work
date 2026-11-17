//! Core of the hexyl clone: number parsing and the dump printer.
use anyhow::{anyhow, bail, Result};
use std::io::{Read, Write};

/// Parse a number with optional `0x` prefix and unit suffix.
/// Units: kB MB GB TB (1000), KiB MiB GiB TiB (1024), `block`/`blocks` (block_size).
pub fn parse_size(input: &str, block_size: u64) -> Result<u64> {
    let s = input.trim();
    if s.is_empty() {
        bail!("empty number");
    }
    let (digits_end, radix) = if s.len() > 2 && (s.starts_with("0x") || s.starts_with("0X")) {
        // hex digits: stop at first non-hex char; careful, units like "B" are hex digits,
        // so for hex only accept an optional unit that starts after the digit run when
        // the remainder is a known unit.
        let body = &s[2..];
        let mut end = body.len();
        for (i, _) in body.char_indices() {
            if body[..i].chars().all(|c| c.is_ascii_hexdigit()) && !body[..i].is_empty() {
                if unit_multiplier(&body[i..], block_size).is_some() {
                    end = i;
                    break;
                }
            }
        }
        (end + 2, 16)
    } else {
        let end = s.find(|c: char| !c.is_ascii_digit()).unwrap_or(s.len());
        (end, 10)
    };
    let (num_part, unit) = s.split_at(digits_end);
    let num_part = if radix == 16 { &num_part[2..] } else { num_part };
    if num_part.is_empty() {
        bail!("invalid number '{}'", input);
    }
    let n = u64::from_str_radix(num_part, radix).map_err(|_| anyhow!("invalid number '{}'", input))?;
    let mult = unit_multiplier(unit, block_size).ok_or_else(|| anyhow!("invalid unit in '{}'", input))?;
    n.checked_mul(mult).ok_or_else(|| anyhow!("number '{}' is too large", input))
}

fn unit_multiplier(unit: &str, block_size: u64) -> Option<u64> {
    let u = unit.trim();
    if u.is_empty() {
        return Some(1);
    }
    let lower = u.to_ascii_lowercase();
    Some(match lower.as_str() {
        "kb" => 1000,
        "mb" => 1000_u64.pow(2),
        "gb" => 1000_u64.pow(3),
        "tb" => 1000_u64.pow(4),
        "kib" => 1024,
        "mib" => 1024_u64.pow(2),
        "gib" => 1024_u64.pow(3),
        "tib" => 1024_u64.pow(4),
        "block" | "blocks" => block_size,
        _ => return None,
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BorderStyle {
    Unicode,
    Ascii,
    None,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CharacterTable {
    Default,
    Ascii,
    Braille,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Endianness {
    Little,
    Big,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Base {
    Binary,
    Octal,
    Decimal,
    Hexadecimal,
}

impl Base {
    fn digits(self) -> usize {
        match self {
            Base::Binary => 8,
            Base::Octal | Base::Decimal => 3,
            Base::Hexadecimal => 2,
        }
    }
    fn format(self, b: u8) -> String {
        match self {
            Base::Binary => format!("{:08b}", b),
            Base::Octal => format!("{:03o}", b),
            Base::Decimal => format!("{:03}", b),
            Base::Hexadecimal => format!("{:02x}", b),
        }
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub show_color: bool,
    pub show_char_panel: bool,
    pub show_position: bool,
    pub border: BorderStyle,
    pub character_table: CharacterTable,
    pub squeeze: bool,
    pub panels: usize,
    pub group_size: usize,
    pub endianness: Endianness,
    pub base: Base,
    pub display_offset: u64,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            show_color: true,
            show_char_panel: true,
            show_position: true,
            border: BorderStyle::Unicode,
            character_table: CharacterTable::Default,
            squeeze: true,
            panels: 2,
            group_size: 1,
            endianness: Endianness::Big,
            base: Base::Hexadecimal,
            display_offset: 0,
        }
    }
}

struct Style {
    left: char,
    right: char,
    mid: char,
    psep: char,
    h: char,
    tl: char,
    tr: char,
    bl: char,
    br: char,
    tj: char,
    bj: char,
}

impl Style {
    fn of(b: BorderStyle) -> Style {
        match b {
            BorderStyle::Unicode => Style {
                left: '│', right: '│', mid: '│', psep: '┊', h: '─',
                tl: '┌', tr: '┐', bl: '└', br: '┘', tj: '┬', bj: '┴',
            },
            BorderStyle::Ascii => Style {
                left: '|', right: '|', mid: '|', psep: '|', h: '-',
                tl: '+', tr: '+', bl: '+', br: '+', tj: '+', bj: '+',
            },
            BorderStyle::None => Style {
                left: ' ', right: ' ', mid: ' ', psep: ' ', h: ' ',
                tl: ' ', tr: ' ', bl: ' ', br: ' ', tj: ' ', bj: ' ',
            },
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Category {
    Null,
    Printable,
    Whitespace,
    Control,
    NonAscii,
}

fn category(b: u8) -> Category {
    if b == 0 {
        Category::Null
    } else if b.is_ascii_graphic() {
        Category::Printable
    } else if b.is_ascii_whitespace() || b == b' ' {
        Category::Whitespace
    } else if b.is_ascii() {
        Category::Control
    } else {
        Category::NonAscii
    }
}

fn color_code(c: Category) -> u8 {
    match c {
        Category::Null => 90,
        Category::Printable => 36,
        Category::Whitespace | Category::Control => 32,
        Category::NonAscii => 33,
    }
}

fn glyph(b: u8, table: CharacterTable) -> char {
    let cat = category(b);
    match table {
        CharacterTable::Default => match cat {
            Category::Null => '⋄',
            Category::Printable => b as char,
            Category::Whitespace => if b == b' ' { ' ' } else { '_' },
            Category::Control => '•',
            Category::NonAscii => '×',
        },
        CharacterTable::Ascii => match cat {
            Category::Printable => b as char,
            Category::Whitespace if b == b' ' => ' ',
            _ => '.',
        },
        CharacterTable::Braille => match cat {
            Category::Printable => b as char,
            Category::Whitespace if b == b' ' => ' ',
            _ => char::from_u32(0x2800 + b as u32).unwrap(),
        },
    }
}

struct Painter {
    enabled: bool,
    cur: Option<u8>,
}

impl Painter {
    fn set(&mut self, out: &mut String, code: u8) {
        if self.enabled && self.cur != Some(code) {
            out.push_str(&format!("\x1b[{}m", code));
            self.cur = Some(code);
        }
    }
    fn reset(&mut self, out: &mut String) {
        if self.cur.is_some() {
            out.push_str("\x1b[39m");
            self.cur = None;
        }
    }
}

/// Number of bytes shown on a line for the given configuration.
pub fn bytes_per_line(cfg: &Config) -> usize {
    8 * cfg.panels
}

fn hex_panel_width(cfg: &Config) -> usize {
    let d = cfg.base.digits();
    let groups = 8 / cfg.group_size;
    8 * d + (groups - 1) + 2
}

/// Total width of a rendered line for `panels` panels.
pub fn line_width(cfg: &Config, panels: usize) -> usize {
    let w = hex_panel_width(cfg);
    let mut total = 1 + panels * w + (panels - 1) + 1;
    if cfg.show_position {
        total += 9;
    }
    if cfg.show_char_panel {
        total += panels * 8 + (panels - 1) + 1;
    }
    total
}

/// Largest panel count that fits into `width` columns (at least 1).
pub fn auto_panels(cfg: &Config, width: usize) -> usize {
    let mut n = 1;
    while line_width(cfg, n + 1) <= width {
        n += 1;
    }
    n
}

pub struct Printer<W: Write> {
    out: W,
    cfg: Config,
    style: Style,
}

impl<W: Write> Printer<W> {
    pub fn new(out: W, cfg: Config) -> Self {
        let style = Style::of(cfg.border);
        Printer { out, cfg, style }
    }

    fn rule(&self, left: char, junction: char, right: char) -> String {
        let s = &self.style;
        let mut o = String::new();
        o.push(left);
        if self.cfg.show_position {
            o.extend(std::iter::repeat(s.h).take(8));
            o.push(junction);
        }
        let w = hex_panel_width(&self.cfg);
        for p in 0..self.cfg.panels {
            if p > 0 {
                o.push(junction);
            }
            o.extend(std::iter::repeat(s.h).take(w));
        }
        if self.cfg.show_char_panel {
            for _ in 0..self.cfg.panels {
                o.push(junction);
                o.extend(std::iter::repeat(s.h).take(8));
            }
        }
        o.push(right);
        o
    }

    pub fn header(&mut self) -> Result<()> {
        if self.cfg.border != BorderStyle::None {
            let l = self.rule(self.style.tl, self.style.tj, self.style.tr);
            writeln!(self.out, "{}", l)?;
        }
        Ok(())
    }

    pub fn footer(&mut self) -> Result<()> {
        if self.cfg.border != BorderStyle::None {
            let l = self.rule(self.style.bl, self.style.bj, self.style.br);
            writeln!(self.out, "{}", l)?;
        }
        Ok(())
    }

    fn render_line(&mut self, pos: Option<(String, bool)>, slots: &[Option<u8>]) -> Result<()> {
        let cfg = self.cfg.clone();
        let s = &self.style;
        let mut o = String::new();
        let mut p = Painter { enabled: cfg.show_color, cur: None };
        o.push(s.left);
        if cfg.show_position {
            let (text, colored) = pos.unwrap_or_else(|| ("        ".into(), false));
            if colored && cfg.show_color {
                o.push_str(&format!("\x1b[90m{}\x1b[39m", text));
            } else {
                o.push_str(&text);
            }
            o.push(s.mid);
        }
        let d = cfg.base.digits();
        let g = cfg.group_size;
        for panel in 0..cfg.panels {
            o.push(' ');
            let base = panel * 8;
            for gi in 0..(8 / g) {
                let mut order: Vec<usize> = (0..g).map(|k| base + gi * g + k).collect();
                if cfg.endianness == Endianness::Little {
                    order.reverse();
                }
                let mut pending_sep = gi > 0;
                for idx in order {
                    let slot = slots.get(idx).copied().flatten();
                    if slot.is_none() {
                        p.reset(&mut o);
                    }
                    if pending_sep {
                        o.push(' ');
                        pending_sep = false;
                    }
                    match slot {
                        Some(b) => {
                            p.set(&mut o, color_code(category(b)));
                            o.push_str(&cfg.base.format(b));
                        }
                        None => o.extend(std::iter::repeat(' ').take(d)),
                    }
                }
            }
            p.reset(&mut o);
            o.push(' ');
            if panel + 1 < cfg.panels {
                o.push(s.psep);
            } else if cfg.show_char_panel {
                o.push(s.mid);
            } else {
                o.push(s.right);
            }
        }
        if cfg.show_char_panel {
            for panel in 0..cfg.panels {
                for k in 0..8 {
                    match slots.get(panel * 8 + k).copied().flatten() {
                        Some(b) => {
                            p.set(&mut o, color_code(category(b)));
                            o.push(glyph(b, cfg.character_table));
                        }
                        None => {
                            p.reset(&mut o);
                            o.push(' ');
                        }
                    }
                }
                p.reset(&mut o);
                o.push(if panel + 1 < cfg.panels { s.psep } else { s.right });
            }
        }
        o.push('\n');
        self.out.write_all(o.as_bytes())?;
        Ok(())
    }

    /// Dump all bytes from `reader`. `start` is the offset of the first byte (added to display offset).
    pub fn print_all<R: Read>(&mut self, mut reader: R, start: u64) -> Result<()> {
        let line_len = bytes_per_line(&self.cfg);
        let base = self.cfg.display_offset.wrapping_add(start);
        let mut offset: u64 = 0;
        let mut prev: Option<Vec<u8>> = None;
        let mut squeezing = false;
        let mut buf = vec![0u8; line_len];
        self.header()?;
        loop {
            let mut n = 0;
            while n < line_len {
                let r = reader.read(&mut buf[n..]);
                match r {
                    Ok(0) => break,
                    Ok(k) => n += k,
                    Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
                    Err(e) => return Err(e.into()),
                }
            }
            if n == 0 {
                break;
            }
            let full = n == line_len;
            if full && self.cfg.squeeze && prev.as_deref() == Some(&buf[..]) {
                if !squeezing {
                    squeezing = true;
                    self.render_line(Some((format!("{:<8}", "*"), false)), &vec![None; line_len])?;
                }
            } else {
                squeezing = false;
                let slots: Vec<Option<u8>> = buf[..n].iter().map(|&b| Some(b)).collect();
                let pos = format!("{:08x}", base.wrapping_add(offset));
                self.render_line(Some((pos, true)), &slots)?;
            }
            prev = if full { Some(buf.clone()) } else { None };
            offset += n as u64;
            if !full {
                break;
            }
        }
        if offset == 0 {
            self.render_line(None, &vec![None; line_len])?;
        } else if squeezing {
            let pos = format!("{:08x}", base.wrapping_add(offset));
            self.render_line(Some((pos, true)), &vec![None; line_len])?;
        }
        self.footer()?;
        self.out.flush()?;
        Ok(())
    }
}
