"""Transcript exports: SRT/VTT/TXT timestamp formatting."""

from types import SimpleNamespace

from app.services.transcript_format import _clock, render, to_srt, to_txt, to_vtt

SEGS = [
    SimpleNamespace(start_sec=0.0, end_sec=2.5, text="Hello class."),
    SimpleNamespace(start_sec=3661.5, end_sec=3663.0, text="One hour in."),
]


def test_clock_formats_and_rounding():
    assert _clock(0, ",") == "00:00:00,000"
    assert _clock(3661.5, ",") == "01:01:01,500"
    assert _clock(3661.5, ".") == "01:01:01.500"
    assert _clock(59.9996, ",") == "00:01:00,000"  # rounds up across the second boundary
    assert _clock(-1, ",") == "00:00:00,000"


def test_srt_blocks_are_numbered_from_one():
    assert to_srt(SEGS) == (
        "1\n00:00:00,000 --> 00:00:02,500\nHello class.\n"
        "\n"
        "2\n01:01:01,500 --> 01:01:03,000\nOne hour in.\n"
    )


def test_vtt_has_header_and_dot_millis():
    out = to_vtt(SEGS)
    assert out.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nHello class.\n")
    assert "01:01:01.500 --> 01:01:03.000" in out


def test_txt_and_render_dispatch():
    assert to_txt(SEGS) == "[00:00] Hello class.\n[1:01:01] One hour in.\n"
    assert render(SEGS, "srt") == to_srt(SEGS)
    assert render([], "vtt") == "WEBVTT\n\n"
