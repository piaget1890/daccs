"""SDS011 帧解析单元测试（FR-1.2 / TC-1）。

SRS 6.1：帧 ``[0xAA, 0xC0, PM2.5_L, PM2.5_H, PM10_L, PM10_H, ID, checksum]``，
``checksum = sum(frame[0:6]) & 0xFF``，校验失败帧丢弃并计数。
"""

from __future__ import annotations

import unittest

from daccs.device.sds011 import FRAME_LEN, parse_frame, parse_frames


def make_frame(pm25: int, pm10: int, device_id: int = 1, bad_checksum: bool = False) -> bytes:
    """构造一帧测试数据。

    校验和 = 前 6 字节之和的低 8 位（SRS 6.1：sum of bytes 1..6），
    **不含** ID 字节。
    """
    body = bytes([0xAA, 0xC0, pm25 & 0xFF, (pm25 >> 8) & 0xFF,
                  pm10 & 0xFF, (pm10 >> 8) & 0xFF, device_id])
    checksum = sum(body[0:6]) & 0xFF
    if bad_checksum:
        checksum = (checksum + 1) & 0xFF
    return body + bytes([checksum])


class TestParseFrame(unittest.TestCase):
    def test_valid_frame(self) -> None:
        frame = parse_frame(make_frame(123, 456, device_id=7))
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertAlmostEqual(frame.pm25, 123.0)
        self.assertAlmostEqual(frame.pm10, 456.0)
        self.assertEqual(frame.device_id, 7)
        self.assertEqual(len(frame.raw), FRAME_LEN)

    def test_big_endian_concentration(self) -> None:
        """浓度按大端解析：0x0100 应为 256 μg/m³。"""
        frame = parse_frame(make_frame(256, 1024))
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertAlmostEqual(frame.pm25, 256.0)
        self.assertAlmostEqual(frame.pm10, 1024.0)

    def test_checksum_mismatch_returns_none(self) -> None:
        self.assertIsNone(parse_frame(make_frame(10, 20, bad_checksum=True)))

    def test_short_buffer_returns_none(self) -> None:
        self.assertIsNone(parse_frame(b"\xAA\xC0\x01"))

    def test_wrong_header_returns_none(self) -> None:
        frame = bytearray(make_frame(10, 20))
        frame[0] = 0xAB
        frame[7] = sum(frame[0:6]) & 0xFF
        self.assertIsNone(parse_frame(bytes(frame)))


class TestParseFrames(unittest.TestCase):
    def test_multiple_frames(self) -> None:
        buffer = make_frame(10, 20) + make_frame(30, 40) + make_frame(50, 60)
        frames, consumed, errors = parse_frames(buffer)
        self.assertEqual(len(frames), 3)
        self.assertEqual(consumed, 3 * FRAME_LEN)
        self.assertEqual(errors, 0)
        self.assertAlmostEqual(frames[1].pm25, 30.0)

    def test_bad_checksum_counted_and_skipped(self) -> None:
        """坏帧被丢弃并计数，后续好帧仍能解析（不能整段错位）。"""
        buffer = make_frame(10, 20, bad_checksum=True) + make_frame(30, 40)
        frames, _consumed, errors = parse_frames(buffer)
        self.assertEqual(len(frames), 1)
        self.assertEqual(errors, 1)
        self.assertAlmostEqual(frames[0].pm25, 30.0)

    def test_garbage_prefix_is_skipped(self) -> None:
        buffer = b"\x00\x11\x22\x33" + make_frame(77, 88)
        frames, _consumed, errors = parse_frames(buffer)
        self.assertEqual(len(frames), 1)
        self.assertEqual(errors, 0)
        self.assertAlmostEqual(frames[0].pm25, 77.0)

    def test_incomplete_tail_is_kept(self) -> None:
        """数据不足时保留未消费部分，等待下一批。"""
        buffer = make_frame(10, 20) + b"\xAA\xC0\x01"
        frames, consumed, errors = parse_frames(buffer)
        self.assertEqual(len(frames), 1)
        self.assertEqual(errors, 0)
        self.assertEqual(consumed, FRAME_LEN)


if __name__ == "__main__":
    unittest.main()
