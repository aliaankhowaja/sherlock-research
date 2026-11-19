"""Socket-free transport into the installed LangGraph API. One isolated worker per case."""
import json
import os
import sys

import httpx
from starlette.testclient import TestClient

from sherlock import shim_httpx
from sherlock.runtime import Runtime


class CountedReplay(Runtime):
    def __init__(self, tape):
        super().__init__(tape, "replay")
        self.lookups = self.hits = 0

    def lookup(self, kind, name, body):
        self.lookups += 1
        row = super().lookup(kind, name, body)
        self.hits += 1
        return row


class ReplayAPI:
    def __init__(self, work, tape, graphs=None):
        def block_network(event, args):
            if event in ("socket.connect", "socket.getaddrinfo"):
                (work/"net_attempts.txt").open("a").write(event+"\n")
                raise RuntimeError("network disabled during replay")

        sys.addaudithook(block_network)
        os.chdir(work)
        os.environ.update(DATABASE_URI=":memory:", REDIS_URI="fake", MIGRATIONS_PATH="__inmem",
                          LANGGRAPH_RUNTIME_EDITION="inmem", LANGSMITH_LANGGRAPH_API_VARIANT="local_dev",
                          LANGSERVE_GRAPHS=json.dumps(graphs or {"bench_solver":str(work/"bench_solver.py")+":graph"}),
                          N_JOBS_PER_WORKER="1", LANGGRAPH_DISABLE_FILE_PERSISTENCE="true",
                          LANGGRAPH_UI_BUNDLER="false", LANGSMITH_TRACING="false", LANGGRAPH_API_URL="http://testserver",
                          LANGGRAPH_ALLOW_BLOCKING="true", LANGGRAPH_CLI_NO_ANALYTICS="1")
        self.runtime = CountedReplay(tape)
        shim_httpx.patch(httpx,self.runtime)
        tape.mark_replay(os.getpid())
        from langgraph_api.server import app
        self.http = TestClient(app, backend_options={"use_uvloop": True})
        self.http.__enter__()

    def request(self, method, path, body=None):
        response = self.http.request(method,path,json=body)
        response.raise_for_status()
        return response.json() if response.content else None

    def stop(self):
        self.http.__exit__(None,None,None)
