"""A from-scratch CommonMark 0.31.2 parser and HTML renderer."""
from .blocks import parse
from .render import render_html

__all__ = ["parse", "render_html", "markdown_to_html"]


def markdown_to_html(text, unsafe=False, hardbreaks=False, nobreaks=False,
                     smart=False, sourcepos=False):
    """Convert Markdown (str) to HTML (str)."""
    doc = parse(text, smart=smart)
    return render_html(doc, unsafe=unsafe, hardbreaks=hardbreaks,
                       nobreaks=nobreaks, sourcepos=sourcepos)
