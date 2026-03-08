"""
Data models for the social.vim application.
These models define the structure of data used throughout the app.
"""
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime


@dataclass
class User:
    """Represents a user in the system."""
    id: int
    username: str
    display_name: str
    bio: str
    followers: int
    following: int
    posts_count: int
    ascii_pic: str = ""
    pic_url: str = ""


@dataclass
class Post:
    """Represents a social media post."""
    id: str
    author: str
    content: str
    timestamp: datetime
    likes: int
    reposts: int
    comments: int
    liked_by_user: bool = False
    reposted_by_user: bool = False


@dataclass
class Message:
    """Represents a chat message."""
    id: int
    sender: str
    sender_handle: str  # Denormalized from user table per PostgreSQL schema
    content: str
    created_at: datetime
    is_read: bool = False


@dataclass
class Conversation:
    """Represents a conversation thread."""
    id: int
    participant_handles: List[str]
    last_message_preview: str
    last_message_at: datetime
    unread: bool = False
    messages: List[Message] = None


@dataclass
class Notification:
    """Represents a notification."""
    id: str
    type: str  # 'mention', 'like', 'repost', 'follow', 'comment'
    actor: str
    username: str  # Added to match backend
    content: str
    timestamp: datetime
    read: bool = False
    related_post: Optional[str] = None


@dataclass
class UserSettings:
    """Represents user settings."""
    user_id: int
    email_notifications: bool = True
    show_online_status: bool = True
    private_account: bool = False
    github_connected: bool = False
    gitlab_connected: bool = False
    google_connected: bool = False
    discord_connected: bool = False
    ascii_pic: str = ""
    pic_url: str = ""
    updated_at: Optional[datetime] = None
