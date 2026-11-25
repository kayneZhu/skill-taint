.PHONY: setup test report mock view view-check image docker-test

setup:
	uv sync --frozen --group dev

test:
	uv run pytest

report:
	uv run python scripts/make_report.py

mock:
	./scripts/mock-campaign.sh

view:
	./scripts/view.sh

view-check:
	./scripts/view-check.sh

image:
	docker build -t skill-taint:dev .

docker-test: image
	docker run --rm skill-taint:dev
