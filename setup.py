from setuptools import setup, find_packages

setup(
    name="fxcore",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "MetaTrader5>=5.0",
        "feedparser",
        "certifi",
        "fastapi",
        "uvicorn[standard]",
        "pytest",
        "jsonschema",
    ],
    author="FX Trading System",
    description="Validated FX market data and quality gates",
)