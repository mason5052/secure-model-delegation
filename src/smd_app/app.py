from __future__ import annotations

import asyncio
import contextlib
import copy
import hmac
import json
import os
import secrets
from collections import deque
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .engine import DEFAULT_POLICY_TEXT, compile_policy, default_policy, execute, validate_policy
from .hub import HubCatalog
from .providers import ProviderRegistry
from .runtime import ManagedRuntime
from .store import Store, identifier
from .agent_gateway import AgentGateway, create_gateway_router
from .desktop_services import DesktopServices, create_desktop_services_router
from .mlx_runtime import LocalRuntimes
from .workspace import create_workspace_router


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelInput(Input):
    model: str = Field(min_length=1, max_length=512)


class PolicyInput(Input):
    text: str = Field(min_length=1, max_length=16000)


class ProviderInput(Input):
    api_key: str = Field(min_length=1, max_length=1024)
    model: str = Field(min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=1000)


class SettingsInput(Input):
    save_content: StrictBool


class RunInput(Input):
    conversation_id: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=24000)
    destination: str = Field(default="local", pattern="^(local|openai|anthropic|remote)$")


class Job:
    def __init__(self):
        self.id = identifier()
        self.events: deque[dict] = deque(maxlen=500)
        self.changed = asyncio.Event()
        self.done = False
        self.task: asyncio.Task | None = None
        self.sequence = 0
        self.holds_lock = False
        self.is_run = False
        self.dispatched = False

    async def emit(self, event: dict) -> None:
        self.publish(event)

    def publish(self, event: dict) -> None:
        self.sequence += 1
        self.events.append({"type": "progress", **event, "sequence": self.sequence})
        if event.get("type") in {"completed", "failed"}:
            self.done = True
        self.changed.set()

    async def stream(self, request: Request):
        try:
            cursor = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            cursor = 0
        while True:
            self.changed.clear()
            for event in list(self.events):
                if event["sequence"] > cursor:
                    cursor = event["sequence"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if self.done or await request.is_disconnected():
                break
            try:
                await asyncio.wait_for(self.changed.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"


def create_app(data_dir: Path, *, runtime=None, providers=None, engine=execute,
               compiler=compile_policy, hub=None) -> FastAPI:
    store = Store(data_dir)
    local = runtime if runtime is not None else LocalRuntimes(data_dir)
    registry = providers if providers is not None else ProviderRegistry()
    model_hub = hub if hub is not None else HubCatalog()
    if store.policy() is None:
        store.add_policy(DEFAULT_POLICY_TEXT, default_policy(), active=True)
    token = secrets.token_urlsafe(32)
    lock = asyncio.Lock()
    jobs: dict[str, Job] = {}
    conversations: dict[str, list[dict]] = {}
    agent_token = secrets.token_urlsafe(32)
    agent_gateway = AgentGateway(local, registry, store, agent_token, lock)
    desktop_services = DesktopServices(local, store, lock)
    desktop_port = os.environ.get("SMD_DESKTOP_PORT")
    gateway_config = {"base_url": f"http://127.0.0.1:{desktop_port}/api/v1/gateway/v1" if desktop_port else "",
                      "api_key": agent_token, "model": "smd-local", "network_request": desktop_services.network_request}
    workspace_router, workspace = create_workspace_router(data_dir, local, registry, store, gateway_config)

    @asynccontextmanager
    async def lifespan(app):
        try:
            await local.start()
        except Exception:
            # Readiness remains false; the setup screen offers installation and retry.
            pass
        await workspace.start()
        yield
        tasks = [job.task for job in jobs.values() if job.task and not job.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await workspace.stop()
        try:
            await local.stop()
        finally:
            store.close()

    app = FastAPI(title="aethon", lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.store, app.state.runtime, app.state.providers = store, local, registry

    @app.middleware("http")
    async def local_session(request: Request, call_next):
        host = request.url.hostname
        origin = request.headers.get("origin")
        try:
            origin_parts = urlsplit(origin) if origin else None
        except ValueError:
            return JSONResponse({"detail": "Invalid origin."}, status_code=403)
        valid_origin = origin_parts is None or (
            origin_parts.scheme == request.url.scheme and origin_parts.netloc == request.url.netloc)
        if host not in {"127.0.0.1", "localhost", "::1"} or not valid_origin or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Only this application's local browser session is accepted."}, status_code=403)
        gateway_request = request.url.path.startswith("/api/v1/gateway/")
        if gateway_request and not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + agent_token):
            return JSONResponse({"detail": "The private agent token is required."}, status_code=401)
        if request.url.path.startswith("/api/v1/") and request.url.path != "/api/v1/session" and not gateway_request:
            if not hmac.compare_digest(request.cookies.get("smd_session", ""), token):
                return JSONResponse({"detail": "Open the application to establish a local session."}, status_code=401)
            if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(request.headers.get("x-smd-token", ""), token):
                return JSONResponse({"detail": "The local session token is required."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH"}:
            limit = 24 * 1024**2 if request.url.path == "/api/v1/voice/transcribe" else (2 * 1024**2 if gateway_request else 256 * 1024)
            if len(await request.body()) > limit:
                return JSONResponse({"detail": "This request exceeds the application size limit."}, status_code=413)
        response = await call_next(request)
        ancestors = "'self'" if request.url.path.startswith(("/api/v1/workspace/renders/", "/static/canvas/")) else "'none'"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; worker-src 'self' blob:; frame-src 'self' blob:; connect-src 'self'; frame-ancestors " + ancestors + "; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "Invalid request fields or size. Check the highlighted settings."}, status_code=422)

    @app.get("/api/v1/session")
    async def session(request: Request):
        if not gateway_config["base_url"]:
            gateway_config["base_url"] = str(request.base_url).rstrip("/") + "/api/v1/gateway/v1"
        response = JSONResponse({"token": token})
        response.set_cookie("smd_session", token, httponly=True, samesite="strict")
        return response

    @app.get("/api/v1/status")
    async def status():
        return {"runtime": await local.status(), "policy": store.policy(), "draft": store.latest_draft(),
                "providers": registry.status(), "settings": store.settings(), "busy": lock.locked()}

    async def reserve():
        if lock.locked() or any(job.status in {"pending", "running"} for job in workspace.jobs.values()):
            raise HTTPException(409, "Another operation is running. Wait for it or stop it first.")
        await lock.acquire()

    def new_job() -> Job:
        if len(jobs) >= 100:
            for key in [key for key, item in jobs.items() if item.done][:25]:
                del jobs[key]
        job = Job()
        jobs[job.id] = job
        return job

    def release_job(job: Job) -> None:
        if job.holds_lock:
            job.holds_lock = False
            lock.release()

    def launch(job: Job, coroutine) -> None:
        job.holds_lock = True
        job.task = asyncio.create_task(coroutine)

        def finalized(task):
            release_job(job)
            # A task cancelled before its first step never enters work()'s finally.
            if not job.done:
                if job.is_run:
                    with contextlib.suppress(Exception):
                        store.fail_run(job.id, "cancelled", job.dispatched, delivery_unknown=job.dispatched)
                job.publish({"type": "failed", "code": "cancelled", "error": "Operation stopped. You can start another operation."})
        job.task.add_done_callback(finalized)

    @app.get("/api/v1/models/catalog")
    async def catalog(query: str = Query(default="", max_length=120),
                      sort: str = Query(default="lastModified", pattern="^(lastModified|downloads)$"),
                      format: str = Query(default="gguf", pattern="^(gguf|mlx)$")):
        try:
            if format == "mlx" and hasattr(local, "mlx"):
                return await local.mlx.catalog(query, sort)
            return await model_hub.search(query=query, sort=sort)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(503, str(exc)[:500]) from None

    @app.get("/api/v1/models/details")
    async def model_details(repo: str = Query(min_length=3, max_length=160), format: str = Query(default="gguf", pattern="^(gguf|mlx)$")):
        try:
            if format == "mlx" and hasattr(local, "mlx"):
                return await local.mlx.details(repo)
            return await model_hub.details(repo)
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:500]) from None
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)[:500]) from None

    @app.post("/api/v1/models/install")
    async def install(body: ModelInput):
        await reserve()
        job = new_job()
        job.model = body.model

        async def work():
            try:
                result = await local.install(body.model, job.emit)
                await job.emit({"type": "completed", "result": result, "message": "Download and checks complete. Choose Use to activate this model."})
            except asyncio.CancelledError:
                await job.emit({"type": "failed", "error": "Installation stopped. You can retry the download.", "code": "cancelled"})
            except (ValueError, RuntimeError, OSError) as exc:
                # The runtime emits actionable errors, without request or provider content.
                await job.emit({"type": "failed", "error": str(exc)[:500], "code": "installation_failed"})
            except Exception:
                await job.emit({"type": "failed", "error": "Installation failed. Check disk space, network access, and platform support.", "code": "installation_failed"})
            finally:
                release_job(job)

        launch(job, work())
        return {"id": job.id}

    @app.post("/api/v1/models/select")
    async def select(body: ModelInput):
        await reserve()
        try:
            return await local.select(body.model)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)[:500]) from None
        finally:
            lock.release()

    @app.delete("/api/v1/models/{model:path}")
    async def remove_model(model: str):
        await reserve()
        try:
            await local.remove(model)
            return {"removed": True}
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)[:500]) from None
        finally:
            lock.release()

    @app.post("/api/v1/models/unload")
    async def unload_model():
        await reserve()
        try:
            if not hasattr(local, "unload"):
                raise HTTPException(409, "Model unloading is unavailable in this runtime.")
            return await local.unload()
        finally:
            lock.release()

    async def events(job_id: str, request: Request):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "This operation is no longer available.")
        return StreamingResponse(job.stream(request), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    app.add_api_route("/api/v1/jobs/{job_id}/events", events, methods=["GET"])
    app.add_api_route("/api/v1/runs/{job_id}/events", events, methods=["GET"])

    async def cancel(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Operation not found.")
        if job.task and not job.task.done():
            job.task.cancel()
        return {"stopping": not job.done}

    app.add_api_route("/api/v1/jobs/{job_id}/cancel", cancel, methods=["POST"])
    app.add_api_route("/api/v1/runs/{job_id}/cancel", cancel, methods=["POST"])

    @app.post("/api/v1/jobs/{job_id}/pause")
    async def pause_download(job_id: str):
        job = jobs.get(job_id)
        if job is None or not getattr(job, "model", None):
            raise HTTPException(404, "This download is no longer available.")
        await cancel(job_id)
        if job.task:
            await asyncio.gather(job.task, return_exceptions=True)
        return {"paused": True, "model": job.model, "note": "Partial model weights are retained for a resumed installation."}

    @app.post("/api/v1/jobs/{job_id}/resume")
    async def resume_download(job_id: str):
        job = jobs.get(job_id)
        if job is None or not getattr(job, "model", None) or not job.done:
            raise HTTPException(409, "Pause this download before resuming.")
        return await install(ModelInput(model=job.model))

    @app.post("/api/v1/policies/compile")
    async def compile_draft(body: PolicyInput):
        await reserve()
        try:
            draft = store.add_policy(body.text, {"version": 1, "title": "Uninterpreted draft", "source_text": body.text,
                                                "rules": [], "issues": ["This draft has not been interpreted and cannot be activated."]})
            if not (await local.status())["ready"]:
                raise HTTPException(409, "Install and select a local model before interpreting a policy.")
            compiled = await compiler(body.text, local.chat)
            return store.update_draft(draft["id"], compiled)
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:1000]) from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "The local model could not interpret this policy. The active policy was not changed.") from None
        finally:
            lock.release()

    @app.post("/api/v1/policies/{policy_id}/activate")
    async def activate(policy_id: str):
        await reserve()
        try:
            saved = store.policy(policy_id)
            if saved is None:
                raise KeyError(policy_id)
            validate_policy({key: saved[key] for key in ("version", "title", "source_text", "rules", "issues")})
            return store.activate(policy_id)
        except KeyError:
            raise HTTPException(404, "Policy draft not found.") from None
        except ValueError:
            raise HTTPException(422, "Interpret and resolve this draft before activating it.") from None
        finally:
            lock.release()

    @app.put("/api/v1/providers/{provider}")
    async def configure_provider(provider: str, body: ProviderInput):
        await reserve()
        try:
            if provider == "remote":
                registry.configure(provider, body.api_key, body.model, base_url=body.base_url)
            else:
                registry.configure(provider, body.api_key, body.model)
            return {"providers": registry.status()}
        except ValueError as exc:
            raise HTTPException(422, str(exc)[:300]) from None
        finally:
            lock.release()

    @app.delete("/api/v1/providers/{provider}")
    async def remove_provider(provider: str):
        await reserve()
        try:
            registry.remove(provider)
            return {"providers": registry.status()}
        finally:
            lock.release()

    @app.patch("/api/v1/settings")
    async def settings(body: SettingsInput):
        await reserve()
        try:
            return store.set_content_retention(body.save_content)
        finally:
            lock.release()

    @app.post("/api/v1/conversations")
    async def conversation():
        if len(conversations) >= 100:
            raise HTTPException(409, "Clear activity to release the in-memory conversations before starting another.")
        conversation_id = identifier()
        conversations[conversation_id] = []
        return {"id": conversation_id}

    @app.post("/api/v1/runs")
    async def run(body: RunInput):
        if body.conversation_id not in conversations:
            raise HTTPException(404, "Start a new conversation first.")
        if not body.prompt.strip():
            raise HTTPException(422, "Enter a prompt.")
        await reserve()
        try:
            state = await local.status()
            if not state["ready"]:
                raise HTTPException(409, "A working local model is required. Open Models to complete setup.")
            if body.destination != "local" and not registry.configured(body.destination):
                raise HTTPException(409, "This external connection is not configured. Choose Local or add its API key.")
            policy = copy.deepcopy(store.policy())
            messages = copy.deepcopy(conversations[body.conversation_id]) + [{"role": "user", "content": body.prompt}]
            save_content = store.settings()["save_content"]
            job = new_job()
            store.begin_run(job.id, body.conversation_id, body.destination, policy["id"], state, messages)
        except BaseException:
            lock.release()
            raise

        async def work():
            dispatched = False

            async def guarded_provider(destination: str, outgoing: list[dict]):
                nonlocal dispatched
                store.mark_dispatched(job.id, outgoing)
                dispatched = True
                job.dispatched = True
                await job.emit({"stage": "external_dispatch", "message": f"Calling the selected {destination} API with the inspected message bundle."})
                return await registry.complete(destination, outgoing)

            try:
                await job.emit({"stage": "policy_pinned", "message": "Using the active policy revision and complete conversation context.", "policy_id": policy["id"]})
                engine_policy = {key: policy[key] for key in ("version", "title", "source_text", "rules", "issues")}
                result = await engine(messages, engine_policy, body.destination, local.chat,
                                      guarded_provider if body.destination != "local" else None, job.emit)
                result["external_attempted"] = dispatched
                store.finish_run(job.id, result, messages, save_content)
                conversations[body.conversation_id] = messages + [{"role": "assistant", "content": result["answer"]}]
                await job.emit({"type": "completed", "result": result})
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    store.fail_run(job.id, "cancelled", dispatched, delivery_unknown=dispatched)
                await job.emit({"type": "failed", "code": "cancelled", "error":
                    "Stopped. An already dispatched external request may still complete or incur charges." if dispatched else "Stopped before any external request was dispatched."})
            except Exception as exc:
                code = getattr(exc, "code", "processing_failed")
                if code not in {"delivery_unknown", "provider_rejected", "provider_unavailable", "invalid_response", "connection_failed", "authentication_failed"}:
                    code = "processing_failed"
                with contextlib.suppress(Exception):
                    store.fail_run(job.id, code, dispatched, delivery_unknown=bool(getattr(exc, "delivery_unknown", dispatched)))
                await job.emit({"type": "failed", "code": code, "error":
                    "The external request did not produce a usable reply. No other provider or raw-message retry was attempted. Delivery may be uncertain." if dispatched else
                    "Local processing could not complete. Nothing was sent externally. Check model readiness and the conversation size."})
            finally:
                release_job(job)

        job.is_run = True
        launch(job, work())
        return {"id": job.id}

    @app.get("/api/v1/activity")
    async def activity():
        return {"runs": store.activity()}

    @app.get("/api/v1/activity/{run_id}")
    async def run_detail(run_id: str):
        record = store.run(run_id)
        if record is None:
            raise HTTPException(404, "Run not found.")
        return record

    @app.delete("/api/v1/activity")
    async def clear_activity():
        await reserve()
        try:
            store.clear_activity()
            conversations.clear()
            jobs.clear()
            agent_gateway.records.clear()
            return {"deleted": True, "start_new_conversation": True}
        finally:
            lock.release()

    app.include_router(create_gateway_router(agent_gateway))
    app.include_router(create_desktop_services_router(desktop_services))
    app.include_router(workspace_router)
    app.state.workspace, app.state.agent_gateway = workspace, agent_gateway

    @app.get("/api/v1/agent/activity")
    async def agent_activity():
        return {"runs": list(reversed(agent_gateway.records))}

    static_dir = str(files("smd_app").joinpath("static"))
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(Path(static_dir) / "index.html")

    return app
