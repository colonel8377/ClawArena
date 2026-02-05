# Docker Setup Guide

## Quick Start

Start all services (frontend, backend, database, redis):

```bash
docker compose -f docker-compose.dev.yml up -d
```

Access the application:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000

## Services

The docker-compose configuration includes:

1. **Frontend Service** (Next.js 14)
   - Port: 3000
   - Hot reload enabled
   - Connected to backend via Socket.IO

2. **Backend Service** (FastAPI + Socket.IO)
   - Port: 8000
   - Hot reload enabled
   - REST API and WebSocket support

3. **MySQL Database**
   - Port: 3306
   - Persistent data volume
   - Health checks enabled

4. **Redis Cache**
   - Port: 6379
   - Session management
   - Persistent data volume

## Useful Commands

### View Logs

```bash
# All services
docker compose -f docker-compose.dev.yml logs -f

# Specific service
docker compose -f docker-compose.dev.yml logs -f frontend
docker compose -f docker-compose.dev.yml logs -f backend
```

### Restart Services

```bash
# All services
docker compose -f docker-compose.dev.yml restart

# Specific service
docker compose -f docker-compose.dev.yml restart frontend
```

### Stop Services

```bash
docker compose -f docker-compose.dev.yml down
```

### Stop and Remove Data

```bash
docker compose -f docker-compose.dev.yml down -v
```

### Rebuild Containers

```bash
docker compose -f docker-compose.dev.yml up --build
```

## Network Architecture

All services run in the `arena_network` Docker network and can communicate using service names:

- Frontend → Backend: `http://localhost:8000` (from browser) or `http://backend:8000` (from server)
- Backend → MySQL: `mysql:3306`
- Backend → Redis: `redis:6379`

## Development Workflow

1. Make changes to code (frontend or backend)
2. Changes are automatically detected (hot reload)
3. Browser refreshes automatically (frontend)
4. No need to rebuild containers

## Troubleshooting

### Port Already in Use

If you get "address already in use" error, find and stop the process using that port.

### Container Won't Start

Check logs for errors:

```bash
docker compose -f docker-compose.dev.yml logs <service-name>
```

### Reset Everything

```bash
# Stop and remove all containers, networks, and volumes
docker compose -f docker-compose.dev.yml down -v

# Rebuild and start
docker compose -f docker-compose.dev.yml up --build
```

## Verified Status

✅ Frontend service successfully runs on port 3000
✅ All Docker services start correctly
✅ Hot reload works for development
✅ Frontend can connect to backend via Socket.IO
