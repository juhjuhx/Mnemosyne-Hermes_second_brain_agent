"""Tests for video-slice skill."""

from unittest.mock import patch


def test_detect_scenes_uses_adaptive_detector():
    """detect_scenes should use AdaptiveDetector by default."""
    from src.video_slice_server import detect_scenes

    with (
        patch("src.video_slice_server.subprocess"),
        patch("scenedetect.open_video"),
        patch("scenedetect.SceneManager") as mock_sm,
    ):
        mock_sm_inst = mock_sm.return_value
        mock_sm_inst.get_scene_list.return_value = [
            (
                type("FrameTime", (), {"get_seconds": lambda self: 0.0})(),
                type("FrameTime", (), {"get_seconds": lambda self: 8.5})(),
            )
        ]
        result = detect_scenes("/fake/video.mp4", max_segment_sec=10)
        assert len(result) == 1
        assert result[0] == (0.0, 8.5)


def test_detect_scenes_splits_long_scenes():
    """Scenes longer than max_segment_sec should be split."""
    from src.video_slice_server import detect_scenes

    with (
        patch("src.video_slice_server.subprocess"),
        patch("scenedetect.open_video"),
        patch("scenedetect.SceneManager") as mock_sm,
    ):
        mock_sm.return_value.get_scene_list.return_value = [
            (
                type("F", (), {"get_seconds": lambda s: 0.0})(),
                type("F", (), {"get_seconds": lambda s: 25.0})(),
            )
        ]
        result = detect_scenes("/fake.mp4", max_segment_sec=10)
        # 25s scene split into 3 chunks: 0-10, 10-20, 20-25
        assert result == [(0.0, 10.0), (10.0, 20.0), (20.0, 25.0)]


def test_extract_middle_frame_calls_ffmpeg(tmp_path):
    """extract_middle_frame should call ffmpeg with -ss midpoint."""
    from src.video_slice_server import extract_middle_frame

    output = str(tmp_path / "frame.jpg")
    with patch("src.video_slice_server.subprocess.run") as mock_run:
        extract_middle_frame("/fake.mp4", 10.0, 20.0, output)
        args = mock_run.call_args[0][0]
        assert "ffmpeg" in args
        assert "-ss" in args
        assert "15.0" in args  # midpoint of 10 and 20


def test_slice_nonexistent_video():
    """slice with non-existent video should return error, not crash."""
    from src.video_slice_server import VideoSliceMCPServer

    server = VideoSliceMCPServer()
    result = server.slice(video_path="/nonexistent/video.mp4")
    assert "error" in result
