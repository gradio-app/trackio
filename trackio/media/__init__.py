"""
Media module for Trackio.

This module contains all media-related functionality including:
- TrackioImage, TrackioVideo, TrackioAudio classes
- Video writing utilities
- Audio conversion utilities
"""

try:
    from trackio.media.audio import TrackioAudio
    from trackio.media.image import TrackioImage
    from trackio.media.media import TrackioMedia
    from trackio.media.utils import get_project_media_path
    from trackio.media.video import TrackioVideo
except ImportError:
    from media.audio import TrackioAudio
    from media.image import TrackioImage
    from media.media import TrackioMedia
    from media.utils import get_project_media_path
    from media.video import TrackioVideo

write_audio = TrackioAudio.write_audio
write_video = TrackioVideo.write_video

__all__ = [
    "TrackioMedia",
    "TrackioImage",
    "TrackioVideo",
    "TrackioAudio",
    "get_project_media_path",
    "write_video",
    "write_audio",
]
