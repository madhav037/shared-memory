"""The console's JSON API.

It is another transport onto the same services the memory tools use, like the hook endpoints. Every endpoint declares
the shape it answers with, once: the same declaration serves the request and describes the API, so the console's types
can be generated from the description and can't drift away from it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

PREFIX = "/api"


class Status(BaseModel):
    """Whether the console has reached the server, and who it is signed in as."""

    signed_in: bool
    github_sign_in: bool


@dataclass(frozen=True)
class Endpoint:
    """One call the console can make: what it answers with, and how that answer is worked out."""

    path: str
    method: str
    operation_id: str
    summary: str
    answers: type[BaseModel]
    answer: Callable[[Request], BaseModel]

    def route(self) -> Route:
        async def handle(request: Request) -> Response:
            return JSONResponse(self.answer(request).model_dump(mode="json"))

        return Route(f"{PREFIX}{self.path}", handle, methods=[self.method], name=self.operation_id)


def _status(request: Request) -> Status:
    # Signing in arrives with the console's GitHub sign-in; until then the console shows that nobody is signed in.
    return Status(signed_in=False, github_sign_in=False)


def endpoints() -> Sequence[Endpoint]:
    return (
        Endpoint(
            path="/status",
            method="GET",
            operation_id="status",
            summary="Whether the console has reached the server, and who it is signed in as.",
            answers=Status,
            answer=_status,
        ),
    )


def description() -> dict[str, Any]:
    """The API's OpenAPI document: what the console generates its types from."""
    paths: dict[str, Any] = {}
    schemas: dict[str, Any] = {}
    for endpoint in endpoints():
        schema = endpoint.answers.model_json_schema(ref_template=f"#/components/schemas/{{model}}")
        schemas.update(schema.pop("$defs", {}))
        schemas[endpoint.answers.__name__] = schema
        paths.setdefault(f"{PREFIX}{endpoint.path}", {})[endpoint.method.lower()] = {
            "operationId": endpoint.operation_id,
            "summary": endpoint.summary,
            "responses": {
                "200": {
                    "description": endpoint.summary,
                    "content": {
                        "application/json": {"schema": {"$ref": f"#/components/schemas/{endpoint.answers.__name__}"}}
                    },
                }
            },
        }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Shared Memory console API", "version": "1"},
        "paths": paths,
        "components": {"schemas": schemas},
    }


def routes() -> list[Route]:
    """The API's routes, including the description the console builds against."""

    async def describe(request: Request) -> Response:
        return JSONResponse(description())

    return [endpoint.route() for endpoint in endpoints()] + [
        Route(f"{PREFIX}/openapi.json", describe, methods=["GET"], name="openapi")
    ]
