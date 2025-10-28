# Contributing to AioFlux

Thank you for your interest in contributing to AioFlux!

## Development Setup

1. Clone the repository:
```bash
git clone https://github.com/Asmin963/aioflux.git
cd aioflux
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
pip install -e .
```

4. Install pre-commit hooks:
```bash
pip install pre-commit
pre-commit install
```

## Running Tests

```bash
python test_basic.py
```

## Code Style

- Follow PEP 8
- Use Black for formatting: `black aioflux/`
- Use type hints where possible
- Write docstrings for public APIs

## Performance Guidelines

- Prioritize zero-lock algorithms
- Use async/await properly
- Profile code for hot paths
- Target <1ms p99 latency

## Submitting Changes

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes
4. Run tests: `python test_basic.py`
5. Commit: `git commit -m 'Add amazing feature'`
6. Push: `git push origin feature/amazing-feature`
7. Open a Pull Request

## Pull Request Guidelines

- Update README.md if needed
- Add tests for new features
- Update CHANGELOG.md
- Ensure CI passes

## Reporting Bugs

Open an issue with:
- Python version
- AioFlux version
- Minimal reproducible example
- Expected vs actual behavior

## Feature Requests

Open an issue describing:
- Use case
- Proposed API
- Performance considerations

## Questions?

Open a GitHub Discussion or issue.

Thank you! 🚀
