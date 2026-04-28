# Combine — Frontend

Web-панель управления для combine-модулей (Accounts, Proxies, Warming, Parsers,
Commenting, Reactions, Analytics).

## Prerequisites

- **Node.js 20+** (рекомендуется 22 LTS)
- **npm 10+** (идёт вместе с Node)

## Quick Start

```bash
cd frontend
npm ci
npm run dev
```

Откроется [http://localhost:5173](http://localhost:5173).

## Available Scripts

| Команда              | Описание                               |
| -------------------- | -------------------------------------- |
| `npm run dev`        | Dev-сервер с HMR                       |
| `npm run build`      | Production-сборка в `dist/`            |
| `npm run preview`    | Превью production-сборки               |
| `npm run lint`       | ESLint                                 |
| `npm run typecheck`  | TypeScript type-check (`tsc --noEmit`) |

## Backend Connection

Фронт ходит на backend через Vite proxy: запросы `/api/*` проксируются на
`http://localhost:8000`. Backend (sonya_web) уже имеет CORS-настройки в
`sonya_web/app.py`.

Для переопределения base URL создайте `.env.local`:

```
VITE_API_URL=http://some-other-host:8000/api
```

## Stack

- **Vite** — сборщик
- **React 18** + **TypeScript** — UI
- **Tailwind CSS** + **shadcn/ui** — стилизация
- **React Router** — маршрутизация
- **@tanstack/react-query** — data fetching
- **Zustand** — state management
- **Zod** — runtime-валидация API-ответов

## Project Structure

```
frontend/
├── public/               # Static assets
├── src/
│   ├── api/              # API client, schemas, types
│   ├── components/       # Shared components
│   │   └── ui/           # shadcn/ui primitives
│   ├── hooks/            # React Query hooks
│   ├── layouts/          # Root layout, sidebar
│   ├── lib/              # Utilities (cn, etc.)
│   ├── pages/            # Route pages
│   ├── stores/           # Zustand stores
│   ├── app.tsx           # App root (providers)
│   ├── main.tsx          # Entry point
│   ├── router.tsx        # React Router config
│   └── index.css         # Tailwind + CSS variables
├── index.html
├── package.json
├── vite.config.ts
├── tailwind.config.ts
└── tsconfig.json
```
