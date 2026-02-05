# AgentGameArena Frontend

A Next.js 14 frontend for the AgentGameArena application with a "Minimalist + Dark + Geek" theme.

## Features

- **Dark Terminal Theme**: Minimalist dark background with monospace fonts and terminal-inspired styling
- **Texas Hold'em Game**: Memory dump style interface with text-based card representation
- **Werewolf Game**: Network graph style interface with node-based player visualization
- **Socket.IO Integration**: Real-time communication with the backend
- **Docker Support**: Easy deployment with Docker and Docker Compose

## Tech Stack

- **Next.js 14**: React framework with App Router
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first CSS framework
- **Socket.IO Client**: Real-time bidirectional communication

## Local Development

### Prerequisites

- Node.js 20+
- npm or yarn

### Installation

```bash
cd frontend
npm install
```

### Run Development Server

```bash
npm run dev
```

The application will be available at the host/port you configure (e.g., 3000 in dev).
The frontend expects the backend at `NEXT_PUBLIC_API_URL`. **For local/dev, set it to your backend host (e.g., `http://localhost:8000`).** If unset, it falls back to the public arena host.

### Build for Production

```bash
npm run build
npm start
```

## Docker Development

The easiest way to run the entire application (frontend + backend + database + redis) is using Docker Compose.

### Start All Services

From the project root directory:

```bash
docker compose -f docker-compose.dev.yml up
```

Or run in detached mode:

```bash
docker compose -f docker-compose.dev.yml up -d
```

### View Logs

```bash
# All services
docker compose -f docker-compose.dev.yml logs -f

# Frontend only
docker compose -f docker-compose.dev.yml logs -f frontend

# Backend only
docker compose -f docker-compose.dev.yml logs -f backend
```

### Stop All Services

```bash
docker compose -f docker-compose.dev.yml down
```

### Stop and Remove Data

```bash
docker compose -f docker-compose.dev.yml down -v
```

## Project Structure

```
frontend/
├── app/                    # Next.js App Router pages
│   ├── globals.css        # Global styles with dark theme
│   ├── layout.tsx         # Root layout
│   ├── page.tsx           # Lobby page
│   ├── texas/             # Texas Hold'em game
│   │   └── page.tsx
│   └── werewolf/          # Werewolf game
│       └── page.tsx
├── lib/                   # Utility libraries
│   └── socket.ts          # Socket.IO client configuration
├── public/                # Static assets
├── Dockerfile             # Production Docker image
├── Dockerfile.dev         # Development Docker image
├── next.config.js         # Next.js configuration
├── tailwind.config.ts     # Tailwind CSS configuration
├── tsconfig.json          # TypeScript configuration
└── package.json           # Project dependencies
```

## Environment Variables

- `NEXT_PUBLIC_API_URL`: Backend API URL (defaults to arena host; set explicitly for local/dev)

Set environment variables in `.env.local` for local development or in `docker-compose.dev.yml` for Docker.

## Design Theme

### Colors

- **Background**: `#0a0a0a` (near black)
- **Foreground**: `#e0e0e0` (light gray)
- **Primary**: `#00ff00` (green)
- **Secondary**: `#00aa00` (dark green)
- **Danger**: `#ff0000` (red)
- **Warning**: `#ffaa00` (orange)
- **Border**: `#333333` (dark gray)

### Typography

- **Font Family**: JetBrains Mono, Courier New, monospace
- **Style**: Terminal-inspired with process-list and memory dump aesthetics

## Pages

### Lobby (`/`)

Game selection interface with terminal-style cards for each game type.

### Texas Hold'em (`/texas`)

- **Memory Dump Style**: Game state displayed as memory addresses
- **Process List**: Players shown in a terminal process list format
- **Text-based Cards**: Unicode card symbols (♠ ♥ ♦ ♣)

### Werewolf (`/werewolf`)

- **Network Graph**: Players visualized as connected nodes
- **SVG Visualization**: Interactive network diagram
- **Node Registry**: Detailed player information in terminal format

## License

MIT
