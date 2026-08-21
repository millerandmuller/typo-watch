.PHONY: dev test seed replay css install

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt -e .
	npm install --no-fund --no-audit
	$(MAKE) css

css:
	npx tailwindcss -i ./static/src.css -o ./static/app.css --minify

dev:
	.venv/bin/uvicorn squatwatch.app:app --reload --host 0.0.0.0 --port 8000

test:
	.venv/bin/python -m pytest tests/ -v

seed:
	.venv/bin/squatwatch seed name.com
	.venv/bin/squatwatch seed devnetwork.com
	.venv/bin/squatwatch seed apiworld.co
	.venv/bin/squatwatch seed google.com

replay:
	REPLAY_MODE=1 .venv/bin/uvicorn squatwatch.app:app --host 0.0.0.0 --port 8000
