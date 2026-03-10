# Tuitter - Terminal-Based Social Network

## Inspiration

Twitter + LazyGit = Tuitter

We love the efficiency of terminal user interfaces like LazyGit and the social connectivity of Twitter. We asked ourselves: what if we could bring the best of both worlds together? What if you could engage with your social network using vim keybindings, without ever leaving your terminal? That's how Tuitter was born - a vim-style social network that makes social media feel like home for developers.

## What it does

Tuitter is a fully-functional terminal user interface (TUI) social network that brings the familiar social media experience into your terminal with vim-style navigation. Built with Python and Textual, it offers:

- **Timeline** - View posts from people you follow with real-time updates
- **Discover** - Explore trending posts with live search filtering by content, author, or tags
- **Messages** - Direct messaging with conversation threads and chat bubbles
- **Notifications** - Activity feed showing likes, reposts, mentions, and new followers
- **Settings** - Profile management with ASCII art profile pictures, OAuth connections, and preferences
- **Vim-style navigation** - Navigate entirely with keyboard shortcuts (1-5 for screens, i for insert mode, Esc for normal mode)
- **Web-serveable** - Can run in terminal OR be served as a web application using Textual Web

Key features:

- 🚀 Real-time search filtering in Discover feed
- 💬 Multi-conversation messaging system
- 🎨 ASCII art profile pictures generated from images using our integrated asciifer tool
- ⚡ Reactive UI that updates instantly
- 🔌 Backend-ready architecture with clean API abstraction layer
- 🌐 Deployable to web with a single command

## How we built it

**Technology Stack:**

- **Frontend**: Textual (Python framework for TUIs)
- **Backend**: AWS Lambda + API Gateway (serverless architecture)
- **Storage**: AWS S3 for media and profile pictures
- **Language**: Python 3.12+
- **Web Serving**: Textual Web for browser access
- **File Handling**: tkinter for image uploads
- **Image Processing**: asciifer (submodule) for ASCII art conversion

**Architecture:**

We built Tuitter with a modern, scalable serverless architecture:

1. **Frontend/TUI Layer** (`main.py`)
   - Custom widgets for each component (PostItem, ChatMessage, NotificationItem, etc.)
   - Screen-based architecture (Timeline, Discover, Notifications, Messages, Settings)
   - Reactive components that update in real-time
   - Event handlers for user interactions

2. **Data Layer** (`data_models.py`)
   - Dataclasses for User, Post, Message, Conversation, Notification, and UserSettings
   - Type-safe data structures that mirror real social network entities

3. **API Interface** (`api_interface.py`)
   - Abstract base class `APIInterface` defining all backend operations
   - `FakeAPI` implementation with realistic mock data for development
   - Designed to connect to AWS API Gateway endpoints
   - Easy to swap mock data with real serverless API calls

4. **Backend (AWS Serverless)**
   - **AWS Lambda** - Serverless functions for all API endpoints (timeline, messages, notifications)
   - **API Gateway** - RESTful API with JWT authentication
   - **AWS S3** - Storage for uploaded images, ASCII art, and media files
   - **DynamoDB** (planned) - NoSQL database for posts, messages, and user data
   - **CloudFront** (planned) - CDN for fast media delivery

5. **Styling** (`main.tcss`)
   - Textual CSS for theming and layout
   - Vim-inspired dark theme
   - Responsive layouts with proper spacing and visual hierarchy

**Key Technical Decisions:**

- **Serverless Architecture**: Chose AWS Lambda for infinite scalability and zero server management
- **S3 for Storage**: Leveraged S3 for cost-effective, durable storage of ASCII art and images
- **API Gateway**: RESTful API design with proper HTTP methods and status codes
- **Reactive Programming**: Used Textual's reactive attributes and watchers for live updates (e.g., search filtering)
- **Component Reusability**: Created generic widgets (NavigationItem, PostItem) used across screens
- **Lazy Loading**: Posts and messages load on-demand when screens mount
- **State Management**: Centralized state in the main App class with screen switching logic
- **Error Handling**: Comprehensive try-except blocks with user-friendly notifications

## Challenges we ran into

1. **Screen Switching Without Async**
   - Initially faced `DuplicateIds` errors when switching between screens
   - Solved by using `call_after_refresh()` to ensure old widgets are removed before mounting new ones

2. **Live Search Filtering**
   - First attempt using `recompose()` caused the input to lose focus on every keystroke
   - Fixed by implementing a `watch_query_text()` method that only updates the posts container, not the entire feed

3. **Font File Handling**
   - asciifer required specific font paths that didn't exist on all systems
   - Solved by pointing to system fonts (`/System/Library/Fonts/Monaco.ttf`) that exist on every macOS installation

4. **Chat Message Alignment**
   - Getting sent/received messages to properly align left/right while maintaining responsive width
   - Fixed using Textual CSS's `align` property and careful margin/padding tuning

5. **Data Persistence with S3**
   - Ensuring uploaded ASCII profile pictures persist when switching screens
   - Implemented S3 upload pipeline for storing profile pictures
   - Integrated AWS SDK for seamless serverless backend communication

6. **Serverless Cold Starts**
   - Lambda functions can have cold start latency
   - Mitigated with proper loading states and optimized function packaging

## Accomplishments that we're proud of

- ✨ **Beautiful, Functional UI** - Created a polished TUI that rivals modern web apps in user experience
- 🎮 **Vim Keybindings** - Natural navigation for vim users with consistent keyboard shortcuts
- 🔍 **Real-time Search** - Implemented live filtering that updates as you type without losing focus
- 🎨 **ASCII Art Integration** - Seamlessly integrated image-to-ASCII conversion for profile pictures
- 🏗️ **Production-Ready Architecture** - Built with a clean separation that makes backend integration trivial
- 📱 **Responsive Design** - Adapts to different terminal sizes with proper scrolling
- ⚡ **Performance** - Instant screen switching and smooth interactions despite complex layouts

## What we learned

- **Textual Framework Mastery**: Deep dive into reactive programming, event handling, and custom widget creation
- **TUI Design Patterns**: How to translate web UI/UX patterns into terminal interfaces effectively
- **State Management in TUIs**: Managing complex application state across multiple screens without traditional routing
- **Async Considerations**: When to use async vs sync in Textual, and how to handle blocking operations
- **CSS-like Styling for Terminals**: Translating traditional CSS concepts to Textual's CSS system
- **Developer Experience**: The importance of vim-style shortcuts for power users
- **Clean Architecture**: How abstraction layers make replacing mock data with real APIs seamless

## What's next for Tuitter

**Short-term:**

- 🔐 **Real Backend Integration** - Connect to a FastAPI/Flask backend with PostgreSQL
- 🔒 **Authentication** - JWT-based auth with OAuth providers (GitHub, GitLab, Google, Discord)
- 📤 **Post Creation** - Implement the `:n` new post command with a compose dialog
- ❤️ **Interactions** - Like, repost, and comment functionality with real-time updates
- 🔔 **Live Notifications** - WebSocket integration for instant notification delivery
- 🔍 **Advanced Search** - Full-text search with filters (tags, users, date ranges)

**Medium-term:**

- 📊 **Analytics Dashboard** - View your post performance and follower growth
- 🧵 **Thread Support** - Create and view threaded conversations
- 📎 **Media Attachments** - Share images and files in posts/messages
- 🎨 **Theme Customization** - Multiple color schemes and user-customizable themes
- 🌍 **i18n Support** - Internationalization for multiple languages
- 🔌 **Plugin System** - Allow community-built extensions and custom widgets

**Long-term:**

- 🤖 **AI Integration** - Smart replies, content summarization, and trending topic detection
- 📱 **Mobile Companion** - Native mobile app that syncs with the TUI
- 🎥 **Video/Audio Support** - ASCII video playback and audio message visualization
- 🌐 **Federation** - ActivityPub support to connect with Mastodon and other federated networks
- 🏢 **Enterprise Features** - Teams, organizations, and private instances
- 🎓 **Community Features** - Groups, events, and collaborative spaces

**Vision:**
Transform Tuitter into the go-to social platform for developers and terminal enthusiasts. A place where you can engage with your community, share code and ideas, and stay connected - all from the comfort of your terminal. We believe social media doesn't need to be bloated web apps; it can be fast, efficient, and beautiful right in your terminal.

---

## Tech Stack Summary

- **Frontend**: Python + Textual Framework
- **Backend**: AWS Lambda (serverless functions)
- **API**: AWS API Gateway (RESTful endpoints)
- **Storage**: AWS S3 (images, ASCII art, media)
- **Database**: DynamoDB (planned for production)
- **Deployment**: AWS SAM/Serverless Framework + Textual Web
- **Real-time**: API Gateway WebSockets (planned)
- **Auth**: AWS Cognito + JWT + OAuth2
- **CDN**: CloudFront (planned for media delivery)

## Try it yourself!

```bash
git clone --recurse-submodules https://github.com/tuitter/tuitter.git
cd tuitter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

**Or run on web:**

```bash
textual-web --config serve.toml
```

---

Built with ❤️ for the terminal-loving community
