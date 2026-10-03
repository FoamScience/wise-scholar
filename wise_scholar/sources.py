"""Text out of a learner's own files, cut into sections the tutor can search and read one at a time."""
import re
from html.parser import HTMLParser
from pathlib import Path

SECTION_CHARS = 3200  # about 800 tokens
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".py", ".rs", ".js", ".ts", ".tsx", ".c", ".cpp", ".h", ".hs", ".go",
                 ".java", ".kt", ".rb", ".sh", ".toml", ".yaml", ".yml", ".json", ".csv", ".tex"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("h1", "h2", "h3"):
            self.parts.append("\n# ")
        elif tag in ("p", "div", "li", "br", "tr", "h4", "h5", "h6", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    return "".join(parser.parts)


def extract(path: Path) -> list[tuple[str, str]]:
    """(title, text) pages or chapters of a file; the caller cuts them into sections."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pymupdf

        with pymupdf.open(path) as doc:
            return [(f"page {i + 1}", page.get_text()) for i, page in enumerate(doc)]
    if suffix == ".epub":
        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        return [
            (item.get_name(), html_text(item.get_content().decode("utf-8", "ignore")))
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
        ]
    if suffix in (".html", ".htm"):
        return [(path.name, html_text(path.read_text(errors="ignore")))]
    if suffix in TEXT_SUFFIXES:
        return [(path.name, path.read_text(errors="ignore"))]
    raise ValueError(f"unsupported file type {suffix or path.name!r}; use PDF, EPUB, HTML, Markdown, text or source code")


HEADING_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".html", ".htm", ".epub", ".pdf"}


def sections(parts: list[tuple[str, str]], name: str) -> list[tuple[str, str]]:
    """Cut extracted parts at headings (prose files only; '#' is a comment in code), then into windows of about
    800 tokens; each section carries a title."""
    out: list[tuple[str, str]] = []
    prose = Path(name).suffix.lower() in HEADING_SUFFIXES
    for part_title, text in parts:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            continue
        pieces = re.split(r"\n(?=#{1,3} )", text) if prose else [text]
        for piece in pieces:
            first, _, rest = piece.partition("\n")
            title = first.lstrip("# ").strip()[:120] if first.startswith("#") else part_title
            body = rest if first.startswith("#") else piece
            body = body.strip()
            if not body:
                continue
            windows = [body[i : i + SECTION_CHARS] for i in range(0, len(body), SECTION_CHARS)]
            for i, window in enumerate(windows):
                suffix = f" · part {i + 1}" if len(windows) > 1 else ""
                out.append((f"{name} · {title}{suffix}", window))
    return out
