.PHONY: setup data train evaluate safety test api clean
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
api:
	uvicorn app.main:app --reload
clean:
	rm -rf data/generated data/evaluation models/*.joblib revive.db .pytest_cache
