import nox

@nox.session(python=["3.8", "3.9", "3.10", "3.11"])
def tests(session):
    session.install("-r", "requirements.txt")
    session.install("pytest", "pytest-asyncio", "pytest-cov")
    session.run("pytest", "test_basic.py", "-v", "--cov=aioflux")

@nox.session
def lint(session):
    session.install("flake8", "black", "isort")
    session.run("black", "--check", "aioflux")
    session.run("isort", "--check-only", "aioflux")
    session.run("flake8", "aioflux")

@nox.session
def format(session):
    session.install("black", "isort")
    session.run("black", "aioflux")
    session.run("isort", "aioflux")
