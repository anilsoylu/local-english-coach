"""Run the server with host/port from config.yaml: python -m coach"""
import uvicorn

from coach import config

uvicorn.run("coach.server:app", host=config.HOST, port=config.PORT)
