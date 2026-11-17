//! Table rendering: borders, rows, colours and squeezing.

use std::io::{self, Read, Write};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Border {
    Unicode,
    Ascii,
    None,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Table {
    Default,
    Ascii,
    Braille,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Base {
    Binary,
    Octal,
    Decimal,
    Hex,
}

impl Base {
    pub fn width(self) -> usize {
        match self {
            Base::Binary => 8,
            Base::Octal | Base::Decimal => 3,
            Base::Hex => 2,
        }
    }
    fn fmt(self, b: u8) -> String {
        match self {
            Base::Binary => format!("{b:08b}"),
            Base::Octal => format!("{b:03o}"),
            Base::Decimal => format!("{b:03}"),
            Base::Hex => format!("{b:02x}"),
        }
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub panels: usize,
    pub group: usize,
    pub little_endian: bool,
    pub base: Base,
    pub border: Border,
    pub color: bool,
    pub show_position: bool,
    pub show_chars: bool,
    pub table: Table,
    pub squeeze: bool,
    pub display_offset: u64,
}

pub const PANEL_BYTES: usize = 8;

impl Config {
    pub fn hex_panel_width(&self) -> usize {
        2 + PANEL_BYTES * self.base.width() + (PANEL_BYTES / self.group - 1)
    }

    /// Total width of a line with `panels` panels.
    pub fn line_width(&self, panels: usize) -> usize {
        let mut w = 1 + if self.show_position { 9 } else { 0 };
        w += panels * self.hex_panel_width() + (panels - 1) + 1;
        if self.show_chars {
            w += panels * PANEL_BYTES + (panels - 1) + 1;
        }
        w
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Cat {
    Null,
    Print,
    Space,
    Control,
    NonAscii,
}

fn category(b: u8) -> Cat {
    match b {
        0 => Cat::Null,
        b' ' | b'\t' | b'\n' | 0x0c | b'\r' => Cat::Space,
        0x21..=0x7e => Cat::Print,
        0x80..=0xff => Cat::NonAscii,
        _ => Cat::Control,
    }
}

fn sgr(c: Cat) -> &'static str {
    match c {
        Cat::Null => "90",
        Cat::Print => "36",
        Cat::Space | Cat::Control => "32",
        Cat::NonAscii => "33",
    }
}

fn glyph(b: u8, cat: Cat, table: Table) -> char {
    match table {
        Table::Default => match cat {
            Cat::Null => '⋄',
            Cat::Print => b as char,
            Cat::Space => {
                if b == b' ' {
                    ' '
                } else {
                    '_'
                }
            }
            Cat::Control => '•',
            Cat::NonAscii => '×',
        },
        Table::Ascii => match b {
            0x20..=0x7e => b as char,
            _ => '.',
        },
        Table::Braille => match b {
            0x20..=0x7e => b as char,
            _ => char::from_u32(0x2800 + b as u32).unwrap(),
        },
    }
}

enum Pos {
    Offset(u64),
    Blank,
    Star,
}

pub struct Renderer<W: Write> {
    cfg: Config,
    out: W,
    cur: Option<Cat>,
}

impl<W: Write> Renderer<W> {
    pub fn new(cfg: Config, out: W) -> Self {
        Renderer { cfg, out, cur: None }
    }

    fn v(&self) -> &'static str {
        match self.cfg.border {
            Border::Unicode => "│",
            Border::Ascii => "|",
            Border::None => " ",
        }
    }
    fn dv(&self) -> &'static str {
        match self.cfg.border {
            Border::Unicode => "┊",
            Border::Ascii => "|",
            Border::None => " ",
        }
    }

    fn paint(&mut self, c: Cat) -> io::Result<()> {
        if self.cfg.color && self.cur != Some(c) {
            write!(self.out, "\x1b[{}m", sgr(c))?;
            self.cur = Some(c);
        }
        Ok(())
    }

    fn reset(&mut self) -> io::Result<()> {
        if self.cur.take().is_some() {
            self.out.write_all(b"\x1b[39m")?;
        }
        Ok(())
    }

    fn spaces(&mut self, n: usize) -> io::Result<()> {
        write!(self.out, "{:n$}", "")
    }

    fn rule(&mut self, l: &str, j: &str, r: &str) -> io::Result<()> {
        let h = match self.cfg.border {
            Border::Unicode => "─",
            _ => "-",
        };
        let mut segs: Vec<String> = Vec::new();
        if self.cfg.show_position {
            segs.push(h.repeat(8));
        }
        for _ in 0..self.cfg.panels {
            segs.push(h.repeat(self.cfg.hex_panel_width()));
        }
        if self.cfg.show_chars {
            for _ in 0..self.cfg.panels {
                segs.push(h.repeat(PANEL_BYTES));
            }
        }
        writeln!(self.out, "{l}{}{r}", segs.join(j))
    }

    pub fn header(&mut self) -> io::Result<()> {
        match self.cfg.border {
            Border::Unicode => self.rule("┌", "┬", "┐"),
            Border::Ascii => self.rule("+", "+", "+"),
            Border::None => Ok(()),
        }
    }

    pub fn footer(&mut self) -> io::Result<()> {
        match self.cfg.border {
            Border::Unicode => self.rule("└", "┴", "┘"),
            Border::Ascii => self.rule("+", "+", "+"),
            Border::None => Ok(()),
        }
    }

    fn row(&mut self, pos: Pos, bytes: &[u8]) -> io::Result<()> {
        let star_in_hex = matches!(pos, Pos::Star) && !self.cfg.show_position;
        let (panels, g, w) = (self.cfg.panels, self.cfg.group, self.cfg.base.width());
        let hexw = self.cfg.hex_panel_width();
        let (v, dv) = (self.v(), self.dv());
        self.out.write_all(v.as_bytes())?;
        if self.cfg.show_position {
            match pos {
                Pos::Offset(o) => {
                    let text = format!("{o:08x}");
                    if self.cfg.color {
                        write!(self.out, "\x1b[90m{text}\x1b[39m")?;
                    } else {
                        self.out.write_all(text.as_bytes())?;
                    }
                }
                Pos::Star => write!(self.out, "{:<8}", "*")?,
                Pos::Blank => self.spaces(8)?,
            }
            self.out.write_all(v.as_bytes())?;
        }
        for p in 0..panels {
            if star_in_hex && p == 0 {
                self.out.write_all(b"*")?;
                self.spaces(hexw - 1)?;
            } else if matches!(pos, Pos::Star | Pos::Blank) && bytes.is_empty() {
                self.spaces(hexw)?;
            } else {
                self.out.write_all(b" ")?;
                for k in 0..PANEL_BYTES {
                    let j = k % g;
                    let src = p * PANEL_BYTES
                        + (k / g) * g
                        + if self.cfg.little_endian { g - 1 - j } else { j };
                    if let Some(&b) = bytes.get(src) {
                        self.paint(category(b))?;
                        let s = self.cfg.base.fmt(b);
                        self.out.write_all(s.as_bytes())?;
                    } else {
                        self.spaces(w)?;
                    }
                    if k + 1 < PANEL_BYTES && (k + 1) % g == 0 {
                        self.out.write_all(b" ")?;
                    }
                }
                self.reset()?;
                self.out.write_all(b" ")?;
            }
            if p + 1 < panels {
                self.out.write_all(dv.as_bytes())?;
            } else {
                self.out.write_all(v.as_bytes())?;
            }
        }
        if self.cfg.show_chars {
            for p in 0..panels {
                for k in 0..PANEL_BYTES {
                    match bytes.get(p * PANEL_BYTES + k) {
                        Some(&b) => {
                            let c = category(b);
                            self.paint(c)?;
                            let mut buf = [0u8; 4];
                            let s = glyph(b, c, self.cfg.table).encode_utf8(&mut buf);
                            self.out.write_all(s.as_bytes())?;
                        }
                        None => self.out.write_all(b" ")?,
                    }
                }
                self.reset()?;
                self.out
                    .write_all(if p + 1 < panels { dv } else { v }.as_bytes())?;
            }
        }
        self.out.write_all(b"\n")
    }

    /// Dump everything readable from `input`.
    pub fn dump<R: Read>(&mut self, mut input: R) -> io::Result<()> {
        let line_len = self.cfg.panels * PANEL_BYTES;
        let mut buf = vec![0u8; line_len];
        let mut prev: Option<Vec<u8>> = None;
        let mut squeezing = false;
        let mut offset = self.cfg.display_offset;
        let mut any = false;
        self.header()?;
        loop {
            let n = fill(&mut input, &mut buf)?;
            if n == 0 {
                break;
            }
            any = true;
            let line = &buf[..n];
            let full = n == line_len;
            if full && self.cfg.squeeze && prev.as_deref() == Some(line) {
                if !squeezing {
                    self.row(Pos::Star, &[])?;
                    squeezing = true;
                }
            } else {
                squeezing = false;
                self.row(Pos::Offset(offset), line)?;
            }
            offset += n as u64;
            prev = if full { Some(line.to_vec()) } else { None };
            if !full {
                break;
            }
        }
        if !any {
            self.row(Pos::Blank, &[])?;
        } else if squeezing {
            self.row(Pos::Offset(offset), &[])?;
        }
        self.footer()?;
        self.out.flush()
    }
}

fn fill<R: Read>(r: &mut R, buf: &mut [u8]) -> io::Result<usize> {
    let mut n = 0;
    while n < buf.len() {
        match r.read(&mut buf[n..]) {
            Ok(0) => break,
            Ok(k) => n += k,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
            Err(e) => return Err(e),
        }
    }
    Ok(n)
}
