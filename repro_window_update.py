"""
Pure-stdlib reproduction/verification script for the WINDOW_UPDATE
zero-increment validation fix.

Before the fix, the construction path (``WindowUpdateFrame(stream_id,
window_increment=0)``) silently accepted invalid increments while the
parsing path (``parse_body``) rejected them, and a failed parse left the
frame object half-modified. This script verifies that both paths now share
a single validation rule (increment must be an integer in 1..2**31-1) and
that failed parses never corrupt the frame.

Run with: python repro_window_update.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from hyperframe.exceptions import InvalidDataError, InvalidFrameError
from hyperframe.frame import Frame, WindowUpdateFrame

HEADER = b"\x00\x00\x04\x08\x00\x00\x00\x00\x00"


def parse(payload):
    frame, length = Frame.parse_frame_header(memoryview(HEADER))
    assert length == 4
    frame.parse_body(memoryview(payload))
    return frame


def expect_raises(exc_type, fn, label):
    try:
        fn()
    except exc_type:
        print(f"ok: {label} raised {exc_type.__name__}")
    else:
        raise AssertionError(f"{label} did not raise {exc_type.__name__}")


def main():
    # 1. Zero increment: constructor and parser reject identically.
    expect_raises(InvalidDataError,
                  lambda: WindowUpdateFrame(0, window_increment=0),
                  "constructor increment=0")
    expect_raises(InvalidDataError,
                  lambda: parse(b"\x00\x00\x00\x00"),
                  "parse increment=0")
    expect_raises(InvalidDataError,
                  lambda: parse(b"\x80\x00\x00\x00"),
                  "parse reserved-bit-set increment=0")

    # 2. Negative and overflowing increments are rejected at construction
    #    and on serialize after mutation.
    for bad in (-1, -512, 2**31, 2**32):
        expect_raises(InvalidDataError,
                      lambda bad=bad: WindowUpdateFrame(0, window_increment=bad),
                      f"constructor increment={bad}")
        frame = WindowUpdateFrame(0, window_increment=1)
        frame.window_increment = bad
        expect_raises(InvalidDataError, frame.serialize,
                      f"serialize mutated increment={bad}")

    # 3. Boundary values: 1 and 2**31-1 are valid on both paths.
    for good in (1, 2**31 - 1):
        frame = WindowUpdateFrame(0, window_increment=good)
        assert frame.serialize()[9:] == good.to_bytes(4, "big")
        assert parse(good.to_bytes(4, "big")).window_increment == good
        print(f"ok: increment={good} accepted by constructor, parse, serialize")

    # 4. Malformed payloads: empty, truncated, and trailing bytes all raise
    #    InvalidFrameError.
    for payload in (b"", b"\x00", b"\x00\x00\x02", b"\x00\x00\x02\x00\xff"):
        expect_raises(InvalidFrameError, lambda p=payload: parse(p),
                      f"parse payload={payload!r}")

    # 5. A failed parse leaves the frame untouched and reusable.
    frame = WindowUpdateFrame(1, window_increment=512)
    before = frame.serialize()
    expect_raises(InvalidDataError, lambda: frame.parse_body(memoryview(b"\x00" * 4)),
                  "failed parse on live frame")
    assert frame.window_increment == 512
    assert frame.serialize() == before
    frame.parse_body(memoryview(b"\x00\x00\x04\x00"))
    assert frame.window_increment == 1024
    print("ok: failed parse left no half-populated state; frame reusable")

    # 6. Parse/serialize roundtrip preserves the exact bytes of legal frames.
    raw = b"\x00\x00\x04\x08\x00\x00\x00\x00\x01\x7f\xff\xff\xff"
    parsed, length = Frame.parse_frame_header(memoryview(raw[:9]))
    parsed.parse_body(memoryview(raw[9:9 + length]))
    assert parsed.serialize() == raw
    print("ok: legal frame roundtrips byte-identically")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
