"""Мини-DOM на стандартной библиотеке.

Нужен парсерам бирж, отдающих обычный HTML. Внешних зависимостей нет
намеренно: продукт разворачивается на чужом VPS, и чем короче список пакетов,
тем меньше поводов для сбоя при установке.

Возможностей ровно столько, сколько требуется парсерам: найти узлы по тегу и
подстроке класса, взять атрибут и собрать текст. Разметка в реальном мире
кривая, поэтому незакрытые теги не считаются ошибкой — дерево просто
разворачивается до ближайшего совпадающего закрывающего тега.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Теги без закрывающей пары — их нельзя класть на стек.
_VOID_TAGS = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }
)

# Содержимое этих тегов — код, а не текст карточки.
_NON_TEXT_TAGS = frozenset({"script", "style", "noscript"})

_WS_RE = re.compile(r"\s+")


@dataclass
class Node:
    """Узел дерева. ``children`` содержит и узлы, и строки текста."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node | str"] = field(default_factory=list)

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name, default)

    @property
    def classes(self) -> list[str]:
        return self.get("class").split()

    def has_class(self, needle: str) -> bool:
        """Совпадение по ПОДСТРОКЕ класса.

        Верстка бирж любит суффиксы вроде ``want-card--promoted``, поэтому
        точное сравнение ломается на первом же редизайне.
        """
        return any(needle in cls for cls in self.classes)

    def text(self, separator: str = " ") -> str:
        """Схлопнутый текст поддерева (без script/style)."""
        parts: list[str] = []
        self._collect_text(parts)
        return _WS_RE.sub(separator, separator.join(parts)).strip()

    def _collect_text(self, parts: list[str]) -> None:
        if self.tag in _NON_TEXT_TAGS:
            return
        for child in self.children:
            if isinstance(child, str):
                if child.strip():
                    parts.append(child.strip())
            else:
                child._collect_text(parts)

    def walk(self):
        """Обходит поддерево (включая сам узел) в глубину."""
        yield self
        for child in self.children:
            if not isinstance(child, str):
                yield from child.walk()

    def find_all(
        self,
        *,
        tag: str | None = None,
        cls: str | None = None,
        attr: str | None = None,
    ) -> list["Node"]:
        """Узлы, подходящие под все заданные условия."""
        found: list[Node] = []
        for node in self.walk():
            if node is self and tag is None and cls is None and attr is None:
                continue
            if tag is not None and node.tag != tag:
                continue
            if cls is not None and not node.has_class(cls):
                continue
            if attr is not None and attr not in node.attrs:
                continue
            found.append(node)
        return found

    def find(self, **kwargs) -> "Node | None":
        found = self.find_all(**kwargs)
        return found[0] if found else None

    def find_any_class(self, names: tuple[str, ...]) -> "Node | None":
        """Первый узел, чей класс содержит любую из подстрок.

        Порядок ``names`` — порядок приоритета: так список селекторов читается
        как «сначала новая вёрстка, потом старая».
        """
        for name in names:
            node = self.find(cls=name)
            if node is not None:
                return node
        return None


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self._stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._stack[-1].children.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        # Разворачиваем стек до ближайшего совпадения: так незакрытые <div>
        # внутри карточки не ломают всё остальное дерево.
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data.strip():
            self._stack[-1].children.append(data)


def parse_html(markup: str) -> Node:
    """Разбирает HTML в дерево. Битая разметка не исключение, а норма."""
    builder = _TreeBuilder()
    try:
        builder.feed(markup)
        builder.close()
    except Exception:  # noqa: BLE001 — на кривом HTML отдаём то, что успели собрать
        pass
    return builder.root
