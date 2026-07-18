.PHONY: up down logs test reset-data

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

test:
	./scripts/local_checks.sh

reset-data:
	docker compose down --volumes

