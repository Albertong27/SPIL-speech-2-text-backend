# spil-speech-2-text-backend

## Configuration

### docker-compose.yml
```
services:
  postgres:
    container_name: postgres_container
    image: postgres:13
    ports:
      - 5434:5432
    environment:
      POSTGRES_USER: POSTGRES_USER
      POSTGRES_PASSWORD: POSTGRES_PASSWORD
      POSTGRES_DB: spil
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### .env
```
DATABASE_URL="postgresql://POSTGRES_USER:POSTGRES_PASSWORD@localhost:5434/spil?schema=public"
```

```pnpm prisma migrate dev```

```pnpm prisma generate```

### Run The Program
```pnpm run start:dev```
