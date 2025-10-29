from setuptools import setup, find_packages

setup(
    name="aioflux",
    version="0.1.0",
    description="High-performance async rate limiting and queueing library",
    author="zlexdev",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "redis>=5.3.1",
        "aiohttp>=3.8.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.20.0",
            "black>=22.0.0",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)
