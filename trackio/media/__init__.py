"""
Media module for Trackio.

This module contains all media-related functionality including:
- TrackioImage, TrackioVideo, TrackioAudio classes
- Video writing utilities
- Audio conversion utilities
"""

try:
    from trackio.media.audio_writer import write_audio
    from trackio.media.file_storage import FileStorage
    from trackio.media.media import (
        TrackioAudio,
        TrackioImage,
        TrackioMedia,
        TrackioVideo,
    )
    from trackio.media.video_writer import write_video
except ImportError:
    from media.audio_writer import write_audio
    from media.file_storage import FileStorage
    from media.media import TrackioAudio, TrackioImage, TrackioMedia, TrackioVideo
    from media.video_writer import write_video

__all__ = [
    "TrackioMedia",
    "TrackioImage",
    "TrackioVideo",
    "TrackioAudio",
    "FileStorage",
    "write_video",
    "write_audio",
]
