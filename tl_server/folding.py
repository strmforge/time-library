"""Restatements: the same memory distilled again from another conversation.

People say the same thing in many conversations, so a later conversation often
yields a memory that an earlier one already holds, in slightly different words.
Such a restatement is folded into the earlier memory: the earlier memory gains
the new evidence, and the restatement stays on file (status 'folded') so the
fold can be looked at and undone. Nothing is thrown away.

Two statements count as the same when nothing marks them as different (each
naming a number or name the other does not, v17 and v18; or one of them saying
"not" where the other does not) and either
  - most of their words are shared (Jaccard over the recall tokens, at least
    RESTATED_OVERLAP), or
  - they rest on the very same words, a quote of at least SAME_WORDS_MIN_CHARS
    characters that both cite, and still share a fair part of their words
    (SAME_WORDS_OVERLAP): the rule that already joins memories citing the same
    message, carried over to the same words said in another conversation.

Calibrated 2026-11-22 on 80,046 real memories: at these bars 15,401 and then
another 19,022 folds; samples of 20 and 18 pairs were all the same thing.
"""

from __future__ import annotations

import math
import re
import threading
from typing import Iterable

from .recall import tokens

RESTATED_OVERLAP = 0.6
SAME_WORDS_OVERLAP = 0.3
SAME_WORDS_MIN_CHARS = 12
_EPSILON = 1e-9
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\\-]*")
NEGATION = re.compile(r"不|没|别|勿|禁止|无需|无须|非")


class Statement:
    __slots__ = ("words", "names", "negated")

    def __init__(self, text: str) -> None:
        self.words = frozenset(tokens(text))
        self.names = frozenset(
            name.lower().strip("._:/\\-") for name in IDENTIFIER.findall(text) if len(name) >= 2 or name.isdigit()
        )
        self.negated = bool(NEGATION.search(text))


def overlap(left: Statement, right: Statement) -> float:
    union = left.words | right.words
    return len(left.words & right.words) / len(union) if union else 0.0


def different(left: Statement, right: Statement) -> bool:
    """Signs that two similar statements say different things."""
    if left.negated != right.negated:
        return True
    # One naming only more than the other is a fuller account; each naming
    # something the other does not (v17 / v18) is a different fact.
    return not (left.names <= right.names or right.names <= left.names)


class StatementIndex:
    """The active memories' statements, for finding the one a new statement restates.

    Search is exact for the overlap bar: a statement at or above it must share
    at least one of the new statement's first p words for p = |x| - ceil(t|x|) + 1,
    so only memories holding one of those words are compared, and the words
    picked are the rarest ones, which keeps that set small.
    """

    def __init__(self, bar: float = RESTATED_OVERLAP) -> None:
        self.bar = bar
        self._lock = threading.RLock()
        self._items: dict[int, Statement] = {}
        self._postings: dict[str, list[int]] = {}
        self._counts: dict[str, int] = {}
        self._quoted: dict[str, list[int]] = {}  # quote -> memories citing it (stale ids are skipped)

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, memory_id: int) -> bool:
        return memory_id in self._items

    def add(self, memory_id: int, text: str, quotes: Iterable[str] = ()) -> None:
        with self._lock:
            if memory_id in self._items:
                self.add_quotes(memory_id, quotes)
                return
            statement = Statement(text)
            self._items[memory_id] = statement
            for word in statement.words:
                self._postings.setdefault(word, []).append(memory_id)
                self._counts[word] = self._counts.get(word, 0) + 1
            self.add_quotes(memory_id, quotes)

    def add_quotes(self, memory_id: int, quotes: Iterable[str]) -> None:
        with self._lock:
            for quote in _usable(quotes):
                holders = self._quoted.setdefault(quote, [])
                if memory_id not in holders:
                    holders.append(memory_id)

    def remove(self, memory_id: int) -> None:
        with self._lock:
            statement = self._items.pop(memory_id, None)
            if statement is None:
                return
            for word in statement.words:
                self._counts[word] -= 1
                if not self._counts[word]:
                    del self._counts[word], self._postings[word]
                # Postings keep the id until the word empties; lookups skip it.

    def _candidates(self, statement: Statement, quotes: Iterable[str]) -> tuple[set[int], set[int]]:
        size = len(statement.words)
        prefix = size - math.ceil(self.bar * size - _EPSILON) + 1
        rarest = sorted(statement.words, key=lambda word: (self._counts.get(word, 0), word))[:prefix]
        candidates = {memory_id for word in rarest for memory_id in self._postings.get(word, ())}
        same_words = {memory_id for quote in _usable(quotes) for memory_id in self._quoted.get(quote, ())}
        return candidates, same_words

    def near_but_different(self, text: str, quotes: Iterable[str] = (), limit: int = 3) -> list[tuple[int, float]]:
        """Memories this statement nearly restates, but with a sign it says something else.

        These are the pairs where one may have replaced the other (v17 then v18);
        a model is asked to judge them, since words alone cannot tell.
        """
        statement = Statement(text)
        if not statement.words:
            return []
        with self._lock:
            candidates, same_words = self._candidates(statement, quotes)
            found = []
            for memory_id in candidates | same_words:
                other = self._items.get(memory_id)
                if other is None:
                    continue
                similarity = overlap(statement, other)
                bar = SAME_WORDS_OVERLAP if memory_id in same_words else self.bar
                if similarity + _EPSILON >= bar and different(statement, other):
                    found.append((memory_id, similarity))
        found.sort(key=lambda item: (-item[1], item[0]))
        return found[:limit]

    def find(self, text: str, quotes: Iterable[str] = (), exclude: Iterable[int] = ()) -> tuple[int, float] | None:
        """The memory this statement restates, with how much they overlap; None if none."""
        statement = Statement(text)
        size = len(statement.words)
        if not size:
            return None
        skip = set(exclude)
        with self._lock:
            candidates, same_words = self._candidates(statement, quotes)
            best: tuple[int, float] | None = None
            for memory_id in candidates | same_words:
                other = self._items.get(memory_id)
                if other is None or memory_id in skip:
                    continue
                similarity = overlap(statement, other)
                bar = SAME_WORDS_OVERLAP if memory_id in same_words else self.bar
                if similarity + _EPSILON < bar or different(statement, other):
                    continue
                if best is None or similarity > best[1] or (similarity == best[1] and memory_id < best[0]):
                    best = (memory_id, similarity)
        return best


def _usable(quotes: Iterable[str]) -> list[str]:
    """Quotes long enough to mean the same words, not a stock reply like "可以"."""
    return [quote.strip() for quote in quotes if len(quote.strip()) >= SAME_WORDS_MIN_CHARS]
