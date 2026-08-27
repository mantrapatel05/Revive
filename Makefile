.PHONY: setup data train evaluate safety test api clean db-up db-down db-migrate db-reset

setup:
	python -m pip install -r requirements.txt

data:
	python scripts/generate_data.py

train:
	python scripts/train_model.py

evaluate:
	python scripts/evaluate_final.py

safety:
	python scripts/run_adversarial.py
	python scripts/run_property_tests.py

test:
	pytest -q

db-up:
	docker compose up -d db || (echo "ERROR: Failed to start Postgres container. Is Docker running?" && exit 1)

db-down:
	docker compose down

db-migrate:
	docker compose exec -T db psql -U revive_admin -d revive < schema.sql || psql "$${DATABASE_URL:-postgresql://revive_admin:revive_dev_password@localhost:5432/revive}" -f schema.sql

db-reset:
	docker compose exec -T db psql -U revive_admin -d revive -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" || psql "$${DATABASE_URL:-postgresql://revive_admin:revive_dev_password@localhost:5432/revive}" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
	$(MAKE) db-migrate

api: db-up
	uvicorn app.main:app --reload

clean:
	rm -rf data/generated data/evaluation models/*.joblib revive.db .pytest_cache
