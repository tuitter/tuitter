"""
ASCII Video Player Widget for Textual
Plays ASCII art frames as an animation
"""
from textual.widgets import Static
from textual.widget import Widget
from textual.reactive import reactive
from textual.app import RenderResult, ComposeResult
from textual import events
from pathlib import Path
from typing import List
from PIL import Image
import math



class ASCIIVideoPlayer(Widget):
    """Widget that plays ASCII video by cycling through frames."""
    
    DEFAULT_CSS = """
    ASCIIVideoPlayer {
        height: auto;
        layout: vertical;
    }
    """
    
    current_frame = reactive(0)
    is_playing = reactive(False)
    
    def __init__(self, frames_dir: str, fps: int = 1, **kwargs):
        super().__init__(**kwargs)
        self.frames_dir = Path(frames_dir)
        self.fps = fps
        self.frame_paths: List[Path] = []
        self.total_frames = 0
        self.viewer = None  # Static containing text frames
        self._load_frames()
    
    def _load_frames(self):
        """Load all ASCII frame paths (txt files)."""
        if not self.frames_dir.exists():
            return
        
        # Load TXT frame paths
        self.frame_paths = sorted(self.frames_dir.glob("frame_*.txt"))
        self.total_frames = len(self.frame_paths)
        
        # Load metadata if exists
        metadata_file = self.frames_dir / "metadata.txt"
        if metadata_file.exists():
            metadata = {}
            for line in metadata_file.read_text().split('\n'):
                if '=' in line:
                    key, value = line.split('=')
                    metadata[key] = value
            
            if 'fps' in metadata:
                self.fps = int(metadata['fps'])
    
    def compose(self) -> ComposeResult:
        """Compose with image viewer and controls."""
        # Text container for ASCII frames
        initial_text = self.frame_paths[0].read_text() if self.frame_paths else "No ASCII frames found"
        self.viewer = Static(initial_text, id="video-frame")
        yield self.viewer
        
        yield Static("⏸ Frame 1/40 | Click to play", id="video-controls", classes="video-controls")
    
    def watch_current_frame(self, frame_num: int) -> None:
        """Update frame when current_frame changes."""
        if not self.frame_paths or frame_num >= len(self.frame_paths):
            return
        
        try:
            # Load new image and update viewer
            # Read ASCII text and update
            frame_text = self.frame_paths[frame_num].read_text()
            if self.viewer is not None:
                self.viewer.update(frame_text)
                self.refresh()
            self.refresh()
            
            # Update controls
            status = "▶" if self.is_playing else "⏸"
            self.query_one("#video-controls", Static).update(
                f"{status} Frame {frame_num + 1}/{self.total_frames} | Click to pause/play"
            )
        except Exception as e:
            print(f"Error updating frame: {e}")
    
    def on_mount(self) -> None:
        """Start playing when mounted."""
        print(f"Video mounted with {len(self.frame_paths)} frames")
        if self.total_frames > 0:
            self.play()
            print(f"Started playing at {self.fps} fps")
    
    def play(self) -> None:
        """Start playing the video."""
        self.is_playing = True
        interval = 1.0 / self.fps
        print(f"Setting interval: {interval}s between frames")
        self.update_timer = self.set_interval(interval, self.next_frame)
    
    def pause(self) -> None:
        """Pause the video."""
        self.is_playing = False
        if hasattr(self, 'update_timer'):
            self.update_timer.pause()
    
    def next_frame(self) -> None:
        """Advance to next frame."""
        self.current_frame = (self.current_frame + 1) % self.total_frames
    
    def reset(self) -> None:
        """Reset to first frame."""
        self.current_frame = 0
    
    def on_click(self) -> None:
        """Toggle play/pause on click."""
        if self.is_playing:
            self.pause()
        else:
            self.play()

