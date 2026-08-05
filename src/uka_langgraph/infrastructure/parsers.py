from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from html.parser import HTMLParser
from typing import Any

from uka_langgraph.domain.models import ParsedFragment

MAX_FRAGMENTS = 256
MAX_FRAGMENT_CHARS = 8_000


class FragmentLimitExceeded(ValueError):
    """Raised instead of silently discarding source fragments."""


def sniff_media_type(content: bytes) -> str:
    if not content or b"\x00" in content[:4096]:
        return "application/octet-stream"
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "application/octet-stream"
    stripped = text.lstrip()
    lowered = stripped[:256].lower()
    if lowered.startswith("<!doctype html") or re.match(r"^<html(?:\s|>)", lowered):
        return "text/html"
    if stripped.startswith(("{", "[")):
        try:
            json.loads(text)
        except (json.JSONDecodeError, ValueError):
            pass
        else:
            return "application/json"
    lines = text.splitlines()
    if lines and any(re.match(r"^\s{0,3}#{1,6}\s+", line) for line in lines[:40]):
        return "text/markdown"
    if len(lines) >= 2:
        try:
            dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t|")
            if dialect.delimiter in lines[0]:
                return "text/csv"
        except csv.Error:
            pass
    return "text/plain; charset=utf-8"


class ParserRegistry:
    revision = "parser-registry-v1"

    def __init__(self) -> None:
        self.parsers = (
            JsonParser(),
            HtmlParser(),
            CsvParser(),
            MarkdownParser(),
            PlainTextParser(),
        )

    def detect(self, content: bytes) -> str:
        return sniff_media_type(content)

    def parse(self, media_type: str, content: bytes) -> list[ParsedFragment]:
        for parser in self.parsers:
            if parser.supports(media_type, content):
                fragments = parser.parse(content)
                if not fragments:
                    raise ValueError(f"parser produced no fragments: {parser.revision}")
                if len(fragments) > MAX_FRAGMENTS:
                    raise FragmentLimitExceeded(
                        f"fragment limit exceeded: {len(fragments)} > {MAX_FRAGMENTS}"
                    )
                return fragments
        raise ValueError(f"unsupported media type: {media_type}")


class PlainTextParser:
    revision = "plain-text-v1"

    def supports(self, media_type: str, content: bytes) -> bool:
        return media_type.startswith("text/plain")

    def parse(self, content: bytes) -> list[ParsedFragment]:
        text = content.decode("utf-8-sig")
        return _nonempty_lines(text, locator_type="lines")


class MarkdownParser:
    revision = "markdown-v1"

    def supports(self, media_type: str, content: bytes) -> bool:
        return media_type == "text/markdown"

    def parse(self, content: bytes) -> list[ParsedFragment]:
        text = content.decode("utf-8-sig")
        lines = text.splitlines()
        fragments: list[ParsedFragment] = []
        section = "root"
        block: list[str] = []
        start_line = 1

        def flush(end_line: int) -> None:
            nonlocal block
            value = "\n".join(block).strip()
            if value:
                fragments.extend(
                    _chunk_fragment(
                        value,
                        "markdown_lines",
                        {"start_line": start_line, "end_line": end_line, "section": section},
                    )
                )
            block = []

        for number, line in enumerate(lines, start=1):
            heading = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
            if heading:
                flush(number - 1)
                section = heading.group(1).strip()
                start_line = number + 1
            elif not line.strip():
                if block:
                    flush(number - 1)
                start_line = number + 1
            else:
                if not block:
                    start_line = number
                block.append(line)
        flush(len(lines))
        return fragments


class JsonParser:
    revision = "json-v1"

    def supports(self, media_type: str, content: bytes) -> bool:
        return media_type == "application/json"

    def parse(self, content: bytes) -> list[ParsedFragment]:
        value = json.loads(content.decode("utf-8-sig"))
        fragments: list[ParsedFragment] = []

        def walk(item: Any, path: str) -> None:
            if isinstance(item, dict):
                for key in sorted(item, key=str):
                    escaped = str(key).replace("~", "~0").replace("/", "~1")
                    walk(item[key], f"{path}/{escaped}")
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    walk(child, f"{path}/{index}")
            else:
                rendered = json.dumps(item, ensure_ascii=False, sort_keys=True)
                text = f"{path or '/'} = {rendered}"
                fragments.extend(
                    _chunk_fragment(text, "json_pointer", {"pointer": path or "/"})
                )
                if len(fragments) > MAX_FRAGMENTS:
                    raise FragmentLimitExceeded(
                        f"fragment limit exceeded: > {MAX_FRAGMENTS}"
                    )

        walk(value, "")
        if not fragments and isinstance(value, (dict, list)):
            fragments.append(
                ParsedFragment(
                    text=json.dumps(value, ensure_ascii=False, sort_keys=True),
                    locator_type="json_pointer",
                    position={"pointer": "/"},
                    media_type="application/json-fragment",
                )
            )
        return fragments


class CsvParser:
    revision = "csv-v1"

    def supports(self, media_type: str, content: bytes) -> bool:
        return media_type == "text/csv"

    def parse(self, content: bytes) -> list[ParsedFragment]:
        text = content.decode("utf-8-sig")
        sample = text[:8192]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
        fragments: list[ParsedFragment] = []
        for row_number, row in enumerate(reader, start=2):
            normalized = {str(key): value for key, value in row.items() if key is not None}
            rendered = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
            fragments.extend(
                _chunk_fragment(rendered, "csv_row", {"row": row_number})
            )
            if len(fragments) > MAX_FRAGMENTS:
                raise FragmentLimitExceeded(
                    f"fragment limit exceeded: > {MAX_FRAGMENTS}"
                )
        return fragments


class _TextExtractor(HTMLParser):
    blocked = {"script", "style", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.fragments: list[ParsedFragment] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack.append(tag.lower())

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index] == lowered:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if any(tag in self.blocked for tag in self.stack):
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        line, column = self.getpos()
        self.fragments.extend(
            _chunk_fragment(
                text,
                "html_text",
                {"line": line, "column": column, "element_path": "/".join(self.stack)},
            )
        )


class HtmlParser:
    revision = "html-v1"

    def supports(self, media_type: str, content: bytes) -> bool:
        return media_type == "text/html"

    def parse(self, content: bytes) -> list[ParsedFragment]:
        parser = _TextExtractor()
        parser.feed(content.decode("utf-8-sig"))
        parser.close()
        return parser.fragments


def _line_blocks(text: str, locator_type: str) -> list[ParsedFragment]:
    fragments: list[ParsedFragment] = []
    lines = text.splitlines()
    block: list[str] = []
    start = 1
    for number, line in enumerate(lines, start=1):
        if not line.strip() and block:
            value = "\n".join(block).strip()
            fragments.extend(
                _chunk_fragment(
                    value, locator_type, {"start_line": start, "end_line": number - 1}
                )
            )
            block = []
            start = number + 1
        else:
            if not block:
                start = number
            block.append(line)
    if block:
        fragments.extend(
            _chunk_fragment(
                "\n".join(block).strip(),
                locator_type,
                {"start_line": start, "end_line": len(lines)},
            )
        )
    return fragments


def _nonempty_lines(text: str, locator_type: str) -> list[ParsedFragment]:
    fragments: list[ParsedFragment] = []
    for number, line in enumerate(text.splitlines(), start=1):
        value = line.strip()
        if not value:
            continue
        fragments.extend(
            _chunk_fragment(
                value,
                locator_type,
                {"start_line": number, "end_line": number},
            )
        )
    return fragments


def _chunk_fragment(
    text: str, locator_type: str, position: dict[str, Any]
) -> list[ParsedFragment]:
    if len(text) <= MAX_FRAGMENT_CHARS:
        return [ParsedFragment(text=text, locator_type=locator_type, position=position)]
    chunks: list[ParsedFragment] = []
    for index, start in enumerate(range(0, len(text), MAX_FRAGMENT_CHARS)):
        chunk = text[start : start + MAX_FRAGMENT_CHARS]
        chunk_position = {**position, "chunk_index": index, "char_start": start}
        chunks.append(
            ParsedFragment(text=chunk, locator_type=locator_type, position=chunk_position)
        )
    return chunks


def fragment_hash(fragment: ParsedFragment) -> str:
    return hashlib.sha256(fragment.text.encode("utf-8")).hexdigest()
