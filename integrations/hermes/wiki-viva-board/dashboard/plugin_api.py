"""Authenticated, profile-scoped Hermes edge. Never receives a path or observation."""
import importlib.util
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

spec = importlib.util.spec_from_file_location('wiki_source_access_runtime', Path(__file__).with_name('source_access_runtime.py'))
runtime_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_module)
router = APIRouter()


def runtime():
    from hermes_cli.profiles import profile_matches_home
    from hermes_constants import get_hermes_home
    return runtime_module.SourceAccessRuntime(os.environ.get('WIKI_SOURCE_ORIGIN', 'http://127.0.0.1:8765'),
        profile_matches=profile_matches_home, receipt_root=lambda: get_hermes_home() / 'cache')


class BoundSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str
    binding_sha256: str
    config_sha256: str


class ReadSource(BoundSource):
    request_id: str


def fail(exc):
    code = str(exc) if isinstance(exc, runtime_module.SourceReadError) else 'source_executor_unavailable'
    raise HTTPException(status_code=409, detail={'error_code': code})


@router.get('/source-binding/{source_id}')
def binding(source_id: str, binding_sha256: str):
    try:
        service = runtime()
        return service.public_binding(service.binding(source_id, binding_sha256))
    except Exception as exc:
        fail(exc)


@router.post('/source-intent-claim')
def claim(body: ReadSource):
    try:
        return runtime().claim(body.source_id, body.binding_sha256, body.config_sha256, body.request_id)
    except Exception as exc:
        fail(exc)


@router.post('/source-read-receipts')
def receipts(body: BoundSource):
    try:
        return {'receipts': runtime().receipts(body.source_id, body.binding_sha256, body.config_sha256)}
    except Exception as exc:
        fail(exc)


class TrackSource(ReadSource):
    tracking: dict


@router.post('/source-intent-track')
def track(body: TrackSource):
    try:
        return runtime().track(body.source_id, body.binding_sha256, body.config_sha256, body.request_id, body.tracking)
    except Exception as exc:
        fail(exc)


class HostChallenge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge: str


@router.post('/bridge-attest')
def attest_host(body: HostChallenge):
    try:
        return runtime().attest_host(body.challenge)
    except Exception as exc:
        fail(exc)
