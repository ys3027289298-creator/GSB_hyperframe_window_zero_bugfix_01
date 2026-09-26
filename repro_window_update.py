"""
Pure-stdlib reproduction/verification script for the WINDOW_UPDATE
zero-increment validation fix.

Before the fix, constructing ``WindowUpdateFrame(stream_id, window_increment=0)``
produced a usable object serializing to an increment of 0, while parsing the
same 4-byte payload raised ``InvalidDataError`` (after mutating the frame).
After the fix, construction, attribute assignment, and parsing all validate
the increment through a single shared check.

Run with: python repro_window_update.py
Exits 0 on success, 1 on failure. Requires no third-party packages.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from hyperframe.exceptions import InvalidDataError, InvalidFrameError
from hyperframe.frame import Frame, WindowUpdateFrame

FAILURES = []


def check(name, fn):
    try:
        fn()
    except AssertionError as exc:
        FAILURES.append(f"{name}: {exc}")
        print(f"FAIL {name}: {exc}")
    else:
        print(f"ok   {name}")


def expect_raises(exc_types, fn):
    try:
        fn()
    except exc_types as err:
        return err
    raise AssertionError(f"expected {exc_types}, nothing raised")


def decode(data):
    frame, length = Frame.parse_frame_header(memoryview(data[:9]))
    frame.parse_body(memoryview(data[9:9 + length]))
    return frame


def test_construct_zero():
    err = expect_raises(InvalidDataError, lambda: WindowUpdateFrame(0, window_increment=0))
    assert "2^31-1" in str(err), f"unclear message: {err}"


def test_parse_zero():
    err = expect_raises(InvalidDataError, lambda: decode(b"\x00\x00\x04\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"))
    assert "2^31-1" in str(err), f"unclear message: {err}"


def test_construct_and_parse_zero_match():
    construct_err = expect_raises(InvalidDataError, lambda: WindowUpdateFrame(1, window_increment=0))
    parse_err = expect_raises(InvalidDataError, lambda: decode(b"\x00\x00\x04\x08\x00\x00\x00\x00\x01\x00\x00\x00\x00"))
    assert type(construct_err) is type(parse_err), "exception types differ"
    assert str(construct_err) == str(parse_err), "exception messages differ"


def test_negative_and_overflow():
    expect_raises(InvalidDataError, lambda: WindowUpdateFrame(0, window_increment=-1))
    expect_raises(InvalidDataError, lambda: WindowUpdateFrame(0, window_increment=2**31))


def test_max_increment_roundtrip():
    frame = WindowUpdateFrame(0, window_increment=2**31 - 1)
    assert frame.serialize() == b"\x00\x00\x04\x08\x00\x00\x00\x00\x00\x7f\xff\xff\xff"
    assert decode(frame.serialize()).window_increment == 2**31 - 1


def test_bad_payload_lengths():
    expect_raises(InvalidFrameError, lambda: decode(b"\x00\x00\x00\x08\x00\x00\x00\x00\x00"))  # empty
    expect_raises(InvalidFrameError, lambda: decode(b"\x00\x00\x04\x08\x00\x00\x00\x00\x00\x00\x00\x02"))  # short
    expect_raises(InvalidFrameError, lambda: decode(b"\x00\x00\x05\x08\x00\x00\x00\x00\x00\x00\x00\x02\x00\xff"))  # trailing


def test_reserved_bit_masked_to_zero_rejected():
    expect_raises(InvalidDataError, lambda: decode(b"\x00\x00\x04\x08\x00\x00\x00\x00\x00\x80\x00\x00\x00"))


def test_failed_parse_leaves_frame_untouched():
    frame, _ = Frame.parse_frame_header(memoryview(b"\x00\x00\x04\x08\x00\x00\x00\x00\x00"))
    frame.window_increment = 512
    expect_raises(InvalidDataError, lambda: frame.parse_body(memoryview(b"\x00\x00\x00\x00")))
    assert frame.window_increment == 512, "failed parse modified the frame"
    assert frame.serialize() == b"\x00\x00\x04\x08\x00\x00\x00\x00\x00\x00\x00\x02\x00"


def test_assignment_validates():
    frame = WindowUpdateFrame(0, window_increment=1)
    frame.window_increment = 100
    assert frame.window_increment == 100
    expect_raises(InvalidDataError, lambda: setattr(frame, "window_increment", 0))
    assert frame.window_increment == 100, "failed assignment modified the frame"


def test_legal_frames_unchanged():
    for stream_id, increment in ((0, 1), (1, 512), (2**31 - 1, 2**31 - 1)):
        frame = WindowUpdateFrame(stream_id, window_increment=increment)
        parsed = decode(frame.serialize())
        assert parsed.stream_id == stream_id
        assert parsed.window_increment == increment
        assert parsed.serialize() == frame.serialize()


if __name__ == "__main__":
    for name, fn in sorted(
        ((name, fn) for name, fn in globals().items() if name.startswith("test_")),
    ):
        check(name, fn)
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("\nall checks passed")
