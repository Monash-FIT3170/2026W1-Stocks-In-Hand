"""AWS Lambda entry point for the FastAPI application."""

from lambdas.common import load_runtime_configuration

# Configuration must be loaded before main imports the SQLAlchemy engine.
load_runtime_configuration()

from mangum import Mangum  # noqa: E402

from main import app  # noqa: E402


handler = Mangum(app, lifespan="off", api_gateway_base_path="/api")
