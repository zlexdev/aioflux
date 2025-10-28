.PHONY: install test lint format clean docker-build docker-up docker-down

install:
	pip install -r requirements.txt
	pip install -e .

test:
	python test_basic.py

lint:
	flake8 AioFlux
	black --check AioFlux

format:
	black AioFlux
	isort AioFlux

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf build dist *.egg-info
	rm -rf htmlcov .coverage

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

help:
	@echo "Available commands:"
	@echo "  make install      - Install dependencies"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Check code style"
	@echo "  make format       - Format code"
	@echo "  make clean        - Remove build artifacts"
	@echo "  make docker-build - Build Docker images"
	@echo "  make docker-up    - Start Docker containers"
	@echo "  make docker-down  - Stop Docker containers"
