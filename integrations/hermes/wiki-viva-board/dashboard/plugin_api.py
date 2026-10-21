"""Authenticated, profile-scoped Hermes edge. Never receives a path or observation."""
import importlib.util
import asyncio
import os
from pathlib import Path
import subprocess

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

spec = importlib.util.spec_from_file_location('wiki_source_access_runtime', Path(__file__).with_name('source_access_runtime.py'))
runtime_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_module)
managed_spec = importlib.util.spec_from_file_location('wiki_managed_source_read', Path(__file__).with_name('managed_source_read.py'))
managed_module = importlib.util.module_from_spec(managed_spec)
managed_spec.loader.exec_module(managed_module)
router = APIRouter()


def runtime():
    from hermes_cli.profiles import profile_matches_home
    from hermes_cli.web_routers.git import git_status_route
    from hermes_constants import get_hermes_home
    def head(path):
        result = subprocess.run(['git', '-C', path, 'rev-parse', '--verify', 'HEAD'], capture_output=True, text=True, timeout=8, check=True)
        return result.stdout.strip()
    async def managed_read(binding):
        def call():
            from tools.connectors.gateway.client import ConnectorClient
            from tools.connectors.gateway.merge import PlannedCall
            from tools.connectors.portal.client import PortalConnectorClient
            from tools.connectors.gateway.errors import GatewayAuthError, ToolGatewayError
            try:
                return managed_module.gmail_profile_read(binding, PortalConnectorClient(), ConnectorClient(), PlannedCall)
            except managed_module.ManagedReadError as exc:
                raise runtime_module.SourceReadError(str(exc)) from None
            except GatewayAuthError:
                raise runtime_module.SourceReadError('authorization_missing') from None
            except ToolGatewayError as exc:
                raise runtime_module.SourceReadError('source_policy_denied' if getattr(exc, 'status', None) == 403 else 'executor_unavailable') from None
        return await asyncio.to_thread(call)
    return runtime_module.SourceAccessRuntime(os.environ.get('WIKI_SOURCE_ORIGIN', 'http://127.0.0.1:8765'),
        profile_matches=profile_matches_home, receipt_root=lambda: get_hermes_home() / 'cache',
        repo_reader=git_status_route, head_reader=head, managed_reader=managed_read)


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


@router.post('/source-read-test')
async def read_test(body: ReadSource):
    try:
        return await runtime().read_test(body.source_id, body.binding_sha256, body.config_sha256, body.request_id)
    except Exception as exc:
        fail(exc)


@router.post('/source-read-receipts')
def receipts(body: BoundSource):
    try:
        return {'receipts': runtime().receipts(body.source_id, body.binding_sha256, body.config_sha256)}
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
