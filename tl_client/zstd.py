"""Reading zstd-compressed session files, with nothing to install.

Some agents keep each session file compressed with zstd, appending a small
frame every time they write. The client must read them on whatever Python the
computer has, so a complete decoder (RFC 8878, without dictionaries) is built
in here. When this Python has a faster one (compression.zstd from 3.14, or the
zstandard package), that is used instead; the results are the same.

Frames are independent of each other, so reading can carry on from the frame
where it stopped instead of decompressing the whole file again.
"""

from __future__ import annotations

from typing import Callable

MAGIC = 0xFD2FB528
SKIPPABLE_LOW, SKIPPABLE_HIGH = 0x184D2A50, 0x184D2A5F
MAX_BLOCK = 128 * 1024


class ZstdError(ValueError):
    """The data is not zstd this decoder can read (damaged, or uses a dictionary)."""


# ---- finding frames without decompressing them -------------------------------------


def frame_end(data: bytes, start: int) -> int | None:
    """Where the frame starting at `start` ends, or None when it is not all there yet."""
    if len(data) - start < 4:
        return None
    magic = int.from_bytes(data[start : start + 4], "little")
    if SKIPPABLE_LOW <= magic <= SKIPPABLE_HIGH:
        if len(data) - start < 8:
            return None
        end = start + 8 + int.from_bytes(data[start + 4 : start + 8], "little")
        return end if end <= len(data) else None
    if magic != MAGIC:
        raise ZstdError("not a zstd frame")
    position, checksum = _frame_header(data, start + 4)[:2]
    if position is None:
        return None
    while True:
        if position + 3 > len(data):
            return None
        header = int.from_bytes(data[position : position + 3], "little")
        last, kind, size = header & 1, (header >> 1) & 3, header >> 3
        if kind == 3:
            raise ZstdError("reserved block type")
        position += 3 + (1 if kind == 1 else size)
        if position > len(data):
            return None
        if last:
            position += 4 if checksum else 0
            return position if position <= len(data) else None


def _frame_header(data: bytes, position: int) -> tuple[int | None, bool, int]:
    """(where the first block starts, has a checksum, dictionary id); position None when cut short."""
    if position >= len(data):
        return None, False, 0
    descriptor = data[position]
    size_flag, single_segment = descriptor >> 6, (descriptor >> 5) & 1
    checksum, dictionary_flag = bool((descriptor >> 2) & 1), descriptor & 3
    if (descriptor >> 3) & 1:
        raise ZstdError("reserved bit set")
    dictionary_bytes = (0, 1, 2, 4)[dictionary_flag]
    content_bytes = (1 if single_segment else 0, 2, 4, 8)[size_flag]
    window_bytes = 0 if single_segment else 1
    start = position + 1 + window_bytes
    if start + dictionary_bytes + content_bytes > len(data):
        return None, checksum, 0
    dictionary = int.from_bytes(data[start : start + dictionary_bytes], "little")
    return start + dictionary_bytes + content_bytes, checksum, dictionary


# ---- bit readers ---------------------------------------------------------------------------


class _Backward:
    """A bitstream read from its end towards its start, as zstd writes them."""

    __slots__ = ("data", "pos")

    def __init__(self, data: bytes) -> None:
        if not data or data[-1] == 0:
            raise ZstdError("bitstream without its end marker")
        self.data = data
        self.pos = (len(data) - 1) * 8 + data[-1].bit_length() - 1

    def read(self, count: int) -> int:
        if not count:
            return 0
        self.pos -= count
        return self._bits(self.pos, count)

    def peek(self, count: int) -> int:
        return self._bits(self.pos - count, count)

    def _bits(self, low: int, count: int) -> int:
        if low >= 0:
            chunk = int.from_bytes(self.data[low >> 3 : (low + count + 7) >> 3], "little")
            return (chunk >> (low & 7)) & ((1 << count) - 1)
        top = low + count
        chunk = int.from_bytes(self.data[: (top + 7) >> 3], "little") if top > 0 else 0
        return (chunk << -low) & ((1 << count) - 1)  # before the start: zeros


# ---- FSE tables ------------------------------------------------------------------------------

Table = list  # [(symbol, bits to read, base of the next state)], plus its accuracy log


def _read_counts(data: bytes, start: int, max_symbol: int, max_log: int) -> tuple[list[int], int, int]:
    """A table description: (normalized counts, accuracy log, bytes used)."""
    value = int.from_bytes(data[start : start + 1024], "little")
    log = (value & 0xF) + 5
    if log > max_log:
        raise ZstdError("table accuracy too high")
    bit = 4
    remaining, threshold, bits = (1 << log) + 1, 1 << log, log + 1
    counts: list[int] = []
    previous_zero = False
    while remaining > 1 and len(counts) <= max_symbol:
        if previous_zero:
            zeros = 0
            while (value >> bit) & 3 == 3:
                zeros += 3
                bit += 2
            zeros += (value >> bit) & 3
            bit += 2
            counts.extend([0] * zeros)
            if len(counts) > max_symbol:
                raise ZstdError("table has too many symbols")
        biggest = 2 * threshold - 1 - remaining
        low = (value >> bit) & (threshold - 1)
        if low < biggest:
            count = low
            bit += bits - 1
        else:
            count = (value >> bit) & (2 * threshold - 1)
            if count >= threshold:
                count -= biggest
            bit += bits
        count -= 1
        remaining -= -count if count < 0 else count
        counts.append(count)
        previous_zero = count == 0
        while remaining < threshold:
            bits -= 1
            threshold >>= 1
    if remaining != 1:
        raise ZstdError("table description does not add up")
    return counts, log, (bit + 7) >> 3


def _build(counts: list[int], log: int) -> tuple[Table, int]:
    size = 1 << log
    symbols = [0] * size
    high = size - 1
    following = [0] * len(counts)
    for symbol, count in enumerate(counts):
        if count == -1:
            symbols[high] = symbol
            high -= 1
            following[symbol] = 1
        else:
            following[symbol] = count
    step, mask, position = (size >> 1) + (size >> 3) + 3, size - 1, 0
    for symbol, count in enumerate(counts):
        for _ in range(count if count > 0 else 0):
            symbols[position] = symbol
            position = (position + step) & mask
            while position > high:
                position = (position + step) & mask
    table = []
    for state in range(size):
        symbol = symbols[state]
        following_state = following[symbol]
        following[symbol] += 1
        bits = log - (following_state.bit_length() - 1)
        table.append((symbol, bits, (following_state << bits) - size))
    return table, log


LL_DEFAULT = _build([4, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 2, 1, 1, 1, 1, 1,
                     -1, -1, -1, -1], 6)
ML_DEFAULT = _build([1, 4, 3, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
                     1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1], 6)
OF_DEFAULT = _build([1, 1, 1, 1, 1, 1, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1], 5)

LL_BASE = list(range(16)) + [16, 18, 20, 22, 24, 28, 32, 40, 48, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384,
                             32768, 65536]
LL_BITS = [0] * 16 + [1, 1, 1, 1, 2, 2, 3, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
ML_BASE = [n + 3 for n in range(32)] + [35, 37, 39, 41, 43, 47, 51, 59, 67, 83, 99, 131, 259, 515, 1027, 2051, 4099,
                                        8195, 16387, 32771, 65539]
ML_BITS = [0] * 32 + [1, 1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]


# ---- literals ----------------------------------------------------------------------------------


def _huffman_table(data: bytes, start: int) -> tuple[tuple[list[int], list[int], int], int]:
    """(decoding table: symbols, bit counts, its log; bytes used) from a tree description."""
    header = data[start]
    if header >= 128:
        count = header - 127
        used = 1 + (count + 1) // 2
        weights = []
        for index in range(count):
            byte = data[start + 1 + index // 2]
            weights.append(byte >> 4 if index % 2 == 0 else byte & 0xF)
    else:
        used = 1 + header
        counts, log, size = _read_counts(data, start + 1, 255, 6)
        table, _ = _build(counts, log)
        stream = _Backward(data[start + 1 + size : start + used])
        first, second = stream.read(log), stream.read(log)
        weights = []
        while True:
            if len(weights) > 255:
                raise ZstdError("too many Huffman weights")
            symbol, bits, base = table[first]
            weights.append(symbol)
            first = base + stream.read(bits)
            if stream.pos < 0:
                weights.append(table[second][0])
                break
            symbol, bits, base = table[second]
            weights.append(symbol)
            second = base + stream.read(bits)
            if stream.pos < 0:
                weights.append(table[first][0])
                break
    total = sum(1 << (weight - 1) for weight in weights if weight)
    if not total:
        raise ZstdError("empty Huffman tree")
    log = total.bit_length()
    if log > 11:
        raise ZstdError("Huffman tree too deep")
    rest = (1 << log) - total
    if rest & (rest - 1):
        raise ZstdError("Huffman weights do not add up")
    weights.append(rest.bit_length())
    ranks = [0] * (log + 2)
    for weight in weights:
        ranks[weight] += 1
    starts, position = [0] * (log + 2), 0
    for weight in range(1, log + 1):
        starts[weight] = position
        position += ranks[weight] << (weight - 1)
    symbols, lengths = [0] * (1 << log), [0] * (1 << log)
    for symbol, weight in enumerate(weights):
        if not weight:
            continue
        length = (1 << weight) >> 1
        first = starts[weight]
        symbols[first : first + length] = [symbol] * length
        lengths[first : first + length] = [log + 1 - weight] * length
        starts[weight] += length
    return (symbols, lengths, log), used


def _huffman_stream(data: bytes, count: int, table: tuple[list[int], list[int], int]) -> bytes:
    symbols, lengths, log = table
    stream = _Backward(data)
    raw, pos = stream.data, stream.pos
    out = bytearray(count)
    mask = (1 << log) - 1
    for index in range(count):
        low = pos - log
        if low >= 0:
            key = (int.from_bytes(raw[low >> 3 : (pos + 7) >> 3], "little") >> (low & 7)) & mask
        else:
            key = (int.from_bytes(raw[: (pos + 7) >> 3], "little") << -low) & mask if pos > 0 else 0
        out[index] = symbols[key]
        pos -= lengths[key]
    return bytes(out)


def _literals(block: bytes, state: dict) -> tuple[bytes, int]:
    """(the literals, where the sequences section starts)."""
    first = block[0]
    kind, size_format = first & 3, (first >> 2) & 3
    if kind in (0, 1):
        if size_format in (0, 2):
            regenerated, start = first >> 3, 1
        elif size_format == 1:
            regenerated, start = (first >> 4) + (block[1] << 4), 2
        else:
            regenerated, start = (first >> 4) + (block[1] << 4) + (block[2] << 12), 3
        if kind == 0:
            return block[start : start + regenerated], start + regenerated
        return bytes([block[start]]) * regenerated, start + 1
    header_bytes, size_bits = {0: (3, 10), 1: (3, 10), 2: (4, 14), 3: (5, 18)}[size_format]
    header = int.from_bytes(block[:header_bytes], "little")
    regenerated = (header >> 4) & ((1 << size_bits) - 1)
    compressed = (header >> (4 + size_bits)) & ((1 << size_bits) - 1)
    position, end = header_bytes, header_bytes + compressed
    if kind == 2:
        state["huffman"], used = _huffman_table(block, position)
        position += used
    elif state.get("huffman") is None:
        raise ZstdError("literals reuse a Huffman table that was never given")
    table = state["huffman"]
    if size_format == 0:
        return _huffman_stream(block[position:end], regenerated, table), end
    sizes = [int.from_bytes(block[position + 2 * n : position + 2 * n + 2], "little") for n in range(3)]
    position += 6
    each = (regenerated + 3) // 4
    parts = []
    for n in range(4):
        size = sizes[n] if n < 3 else end - position
        parts.append(_huffman_stream(block[position : position + size], each if n < 3 else regenerated - 3 * each, table))
        position += size
    return b"".join(parts), end


# ---- sequences ----------------------------------------------------------------------------------


def _sequence_table(block: bytes, position: int, mode: int, default, max_symbol: int, max_log: int,
                    state: dict, name: str):
    if mode == 0:
        table = default
    elif mode == 1:
        table = ([(block[position], 0, 0)], 0)
        position += 1
    elif mode == 2:
        counts, log, used = _read_counts(block, position, max_symbol, max_log)
        table = _build(counts, log)
        position += used
    else:
        table = state.get(name)
        if table is None:
            raise ZstdError("sequences reuse a table that was never given")
    state[name] = table
    return table, position


def _block(block: bytes, out: bytearray, state: dict) -> None:
    literals, position = _literals(block, state)
    count = block[position]
    if count == 0:
        out += literals
        return
    if count < 128:
        position += 1
    elif count < 255:
        count = ((count - 128) << 8) + block[position + 1]
        position += 2
    else:
        count = block[position + 1] + (block[position + 2] << 8) + 0x7F00
        position += 3
    modes = block[position]
    position += 1
    (ll_table, ll_log), position = _sequence_table(block, position, modes >> 6, LL_DEFAULT, 35, 9, state, "ll")
    (of_table, of_log), position = _sequence_table(block, position, (modes >> 4) & 3, OF_DEFAULT, 31, 8, state, "of")
    (ml_table, ml_log), position = _sequence_table(block, position, (modes >> 2) & 3, ML_DEFAULT, 52, 9, state, "ml")
    stream = _Backward(block[position:])
    read = stream.read
    ll_state, of_state, ml_state = read(ll_log), read(of_log), read(ml_log)
    reps = state["reps"]
    used = 0
    for index in range(count):
        ll_code, ll_bits, ll_next = ll_table[ll_state]
        of_code, of_bits, of_next = of_table[of_state]
        ml_code, ml_bits, ml_next = ml_table[ml_state]
        if of_code > 31:
            raise ZstdError("offset code out of range")
        offset = (1 << of_code) + read(of_code)
        match = ML_BASE[ml_code] + read(ML_BITS[ml_code])
        literal = LL_BASE[ll_code] + read(LL_BITS[ll_code])
        if offset > 3:
            offset -= 3
            reps[2], reps[1], reps[0] = reps[1], reps[0], offset
        else:
            if literal == 0:
                offset += 1
            if offset == 1:
                offset = reps[0]
            elif offset == 2:
                offset = reps[1]
                reps[1], reps[0] = reps[0], offset
            else:
                offset = reps[2] if offset == 3 else reps[0] - 1
                reps[2], reps[1], reps[0] = reps[1], reps[0], offset
        if index != count - 1:
            ll_state = ll_next + read(ll_bits)
            ml_state = ml_next + read(ml_bits)
            of_state = of_next + read(of_bits)
        if literal:
            out += literals[used : used + literal]
            used += literal
        start = len(out) - offset
        if offset <= 0 or start < 0:
            raise ZstdError("match reaches before the start of the frame")
        if match <= offset:
            out += out[start : start + match]
        else:
            out += (bytes(out[start:]) * (match // offset + 1))[:match]
    out += literals[used:]


def decode_frame(frame: bytes) -> bytes:
    """One whole frame, decoded here (no dictionaries)."""
    magic = int.from_bytes(frame[:4], "little")
    if SKIPPABLE_LOW <= magic <= SKIPPABLE_HIGH:
        return b""
    if magic != MAGIC:
        raise ZstdError("not a zstd frame")
    position, _checksum, dictionary = _frame_header(frame, 4)
    if position is None:
        raise ZstdError("frame cut short")
    if dictionary:
        raise ZstdError("frame needs a dictionary")
    out = bytearray()
    state: dict = {"reps": [1, 4, 8]}
    while True:
        if len(frame) < position + 3:
            raise ZstdError("frame cut short")
        header = int.from_bytes(frame[position : position + 3], "little")
        last, kind, size = header & 1, (header >> 1) & 3, header >> 3
        position += 3
        if kind == 0:
            out += frame[position : position + size]
            position += size
        elif kind == 1:
            out += frame[position : position + 1] * size
            position += 1
        elif kind == 2:
            if size > MAX_BLOCK:
                raise ZstdError("block too large")
            _block(frame[position : position + size], out, state)
            position += size
        else:
            raise ZstdError("reserved block type")
        if last:
            return bytes(out)


# ---- the fastest decoder this Python has ------------------------------------------------------


def _choose() -> tuple[str, Callable[[bytes], bytes]]:
    try:
        from compression import zstd as standard  # Python 3.14+

        return "compression.zstd", standard.decompress
    except ImportError:
        pass
    try:
        import zstandard

        decompressor = zstandard.ZstdDecompressor()
        return "zstandard", lambda frame: decompressor.decompressobj().decompress(frame)
    except ImportError:
        pass
    return "built-in", decode_frame


BACKEND, _decompress = _choose()


def decompress_frame(frame: bytes) -> bytes:
    try:
        return _decompress(frame)
    except ZstdError:
        raise
    except Exception as error:  # the faster decoders raise their own kinds
        raise ZstdError(str(error)) from None
