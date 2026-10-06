"""Collect and publish OpenDota data without a paid key, at a configurable cadence."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analytics.normalize import normalize  # noqa: E402
from app.collectors.opendota import OpenDotaClient, RequestPolicy  # noqa: E402
from app.collectors.public_matches import CollectionResult  # noqa: E402
from app.core.clock import to_utc_iso  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.errors import MetadexError, PermanentError, RecoverableError  # noqa: E402
from app.core.paths import get_data_paths  # noqa: E402
from app.core.runs import RunRecord, RunStatus  # noqa: E402
from app.pipeline.runner import run_pipeline  # noqa: E402
from app.storage.locking import pipeline_writer_lock  # noqa: E402
from app.storage.raw import list_run_paths, persist_collection  # noqa: E402

MAX_PUBLIC_MATCHES = 20_000


class QuotaReached(RecoverableError):
    pass


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


class FreeTransport(httpx.AsyncHTTPTransport):
    """Pace every HTTP attempt, including failures, and capture limits on error responses."""

    def __init__(self, state: dict, state_path: Path, *, maximum: int, per_minute: int):
        super().__init__(retries=0)
        self.state = state
        self.state_path = state_path
        self.maximum = maximum
        self.interval = max(60 / per_minute, 1.05)
        self.recent: deque[float] = deque()

    def check_quota(self) -> None:
        if self.state["requests"] >= self.maximum:
            raise QuotaReached("Limite total de chamadas desta coleta atingido")
        today = datetime.now(UTC).date().isoformat()
        if self.state.get("quota_date") != today:
            self.state["remaining_day"] = None
            self.state["remaining_minute"] = None
        if self.state.get("remaining_day") == 0:
            raise QuotaReached("Cota gratuita diária esgotada")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.host != "api.opendota.com"
            or request.url.scheme != "https"
            or "authorization" in request.headers
            or "api_key" in request.url.params
        ):
            raise ValueError("Somente a API oficial sem chave paga é permitida")
        self.check_quota()
        delay = max(0, self.state.get("last_request_at", 0) + self.interval - time.time())
        delay = max(delay, self.state.get("retry_at", 0) - time.time())
        now = time.monotonic()
        while self.recent and self.recent[0] <= now - 60:
            self.recent.popleft()
        if len(self.recent) >= 59:
            delay = max(delay, self.recent[0] + 60.1 - now)
        if self.state.get("remaining_minute") == 0:
            delay = max(delay, self.state.get("last_request_at", 0) + 60.1 - time.time())
        if delay > 0:
            print(f"Aguardando {delay:.1f}s para a próxima chamada...", flush=True)
            await asyncio.sleep(delay)
        self.state["requests"] += 1
        self.state["last_request_at"] = time.time()
        self.recent.append(time.monotonic())
        save_json(self.state_path, self.state)
        response = await super().handle_async_request(request)
        self.state["quota_date"] = datetime.now(UTC).date().isoformat()
        for suffix in ("day", "minute"):
            value = response.headers.get(f"x-rate-limit-remaining-{suffix}")
            try:
                self.state[f"remaining_{suffix}"] = max(0, int(value))
            except (ValueError, TypeError):
                self.state[f"remaining_{suffix}"] = None
        if response.status_code == 429:
            try:
                wait = max(60.1, float(response.headers.get("Retry-After", "60")))
            except ValueError:
                wait = 60.1
            self.state["retry_at"] = time.time() + wait
        else:
            self.state["retry_at"] = 0
        save_json(self.state_path, self.state)
        return response


def archive_pending(paths, pending: Path, dataset: str) -> int:
    files = sorted(pending.glob(f"{dataset}-*.json"))
    if not files:
        return 0
    run = RunRecord(operation=f"collect_free_{dataset}")
    result = CollectionResult(run, [], 0, 0, "Coleta gratuita com intervalo", [], {}, dataset)
    for file in files:
        page = json.loads(file.read_text(encoding="utf-8"))
        index = len(result.source_pages)
        result.source_pages.append(page["source"])
        result.pages += 1
        run.attempts += 1
        run.received_count += len(page["matches"])
        for match in page["matches"]:
            if match["match_id"] in result.match_pages:
                result.discarded_count += 1
                continue
            result.match_pages[match["match_id"]] = index
            result.matches.append(match)
    run.requested_count = run.processed_count = len(result.matches)
    run.finish(RunStatus.SUCCEEDED)
    manifest = persist_collection(paths.raw, result, max_pages=result.pages)
    for file in files:
        file.unlink()
    return manifest["volumes"]["new"]


def detail_candidates(paths, excluded: set[int]) -> list[int]:
    summaries = {}
    for folder in list_run_paths(paths.raw):
        if folder.parent.parent.name == "match_details":
            excluded.update(
                pq.read_table(folder / "matches.parquet", columns=["match_id"])[
                    "match_id"
                ].to_pylist()
            )
        else:
            for text in pq.read_table(folder / "matches.parquet", columns=["payload_json"])[
                "payload_json"
            ].to_pylist():
                payload = json.loads(text)
                if payload["match_id"] not in excluded and normalize([payload]).matches:
                    summaries[payload["match_id"]] = payload["start_time"]
    midnight = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), UTC).timestamp()
    return sorted(
        summaries,
        key=lambda match_id: (summaries[match_id] < midnight, summaries[match_id]),
        reverse=True,
    )


async def collect(args: argparse.Namespace) -> int:
    # Explicitly disable credentials even when backend/.env contains a paid key.
    settings = get_settings().model_copy(
        update={"opendota_api_key": None, "opendota_base_url": "https://api.opendota.com/api"}
    )
    paths = get_data_paths(settings)
    state_path = paths.root / "operations" / "opendota-free-collection.json"
    pending = state_path.parent / "opendota-free-pending"
    with pipeline_writer_lock(paths):
        state = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.is_file()
            else {
                "requests": 0,
                "phase": "public_matches",
                "cursor": None,
                "public_received": 0,
                "details_received": 0,
                "skipped_details": [],
            }
        )
        state["status"] = "running"
        # Pending files survive interruption, including one between saving a page and its cursor.
        for file in pending.glob("public_matches-*.json"):
            saved = json.loads(file.read_text(encoding="utf-8"))
            cursor = min(item["match_id"] for item in saved["matches"])
            state["cursor"] = min(state["cursor"] or cursor, cursor)
        transport = FreeTransport(
            state, state_path, maximum=args.max_requests, per_minute=args.requests_per_minute
        )

        async def publish() -> None:
            print("Processando os dados locais e publicando no banco...", flush=True)
            result = await run_pipeline(settings, collect=False)
            if result.run.status != RunStatus.SUCCEEDED:
                raise RuntimeError(f"Falha ao publicar: {result.message}")
            state["version_id"] = result.version_id
            state["counts"] = result.counts
            state["publication_pending"] = False
            save_json(state_path, state)
            print(f"Banco atualizado: {result.counts}", flush=True)

        async def flush() -> None:
            if any(pending.glob("*.json")):
                state["publication_pending"] = True
                save_json(state_path, state)
            for dataset in ("public_matches", "match_details"):
                archive_pending(paths, pending, dataset)
            if state.get("publication_pending") or (
                "version_id" not in state and list_run_paths(paths.raw)
            ):
                await publish()

        consecutive_errors = 0
        queue = None
        try:
            async with OpenDotaClient(
                settings,
                policy=RequestPolicy(timeout_seconds=30, max_attempts=1),
                transport=transport,
            ) as client:
                while True:
                    try:
                        transport.check_quota()
                    except QuotaReached as exc:
                        state["status"] = "limit_reached"
                        print(str(exc), flush=True)
                        break
                    if state["phase"] == "public_matches" and (
                        state["public_received"] >= MAX_PUBLIC_MATCHES
                    ):
                        state["phase"] = "match_details"
                        await flush()
                    dataset = state["phase"]
                    if dataset == "match_details" and queue is None:
                        excluded = set(state["skipped_details"])
                        for file in pending.glob("match_details-*.json"):
                            excluded.update(
                                item["match_id"] for item in json.loads(file.read_text())["matches"]
                            )
                        queue = deque(detail_candidates(paths, excluded))
                    if dataset == "match_details" and not queue:
                        state["status"] = "source_exhausted"
                        print("Não há outras partidas disponíveis para buscar detalhes.")
                        break
                    try:
                        page = (
                            await client.public_matches(cursor=state["cursor"])
                            if dataset == "public_matches"
                            else await client.match_detail(queue[0])
                        )
                    except QuotaReached as exc:
                        state["status"] = "limit_reached"
                        print(str(exc), flush=True)
                        break
                    except MetadexError as exc:
                        if state.get("remaining_day") == 0:
                            state["status"] = "limit_reached"
                            print("Cota gratuita diária esgotada.", flush=True)
                            break
                        consecutive_errors += 1
                        print(f"Erro na API: {exc}. Tentativa seguinte respeitará o intervalo.")
                        if isinstance(exc, PermanentError):
                            if dataset == "match_details" and "HTTP 404" in str(exc):
                                state["skipped_details"].append(queue.popleft())
                            else:
                                state["status"] = "api_error"
                                break
                        if consecutive_errors >= 5:
                            state["status"] = "api_error"
                            print("Cinco falhas consecutivas; execute novamente para retomar.")
                            break
                        save_json(state_path, state)
                        continue
                    consecutive_errors = 0
                    if not page.matches:
                        state["phase"] = "match_details"
                        await flush()
                        continue
                    if dataset == "public_matches":
                        next_cursor = min(match["match_id"] for match in page.matches)
                        if state["cursor"] is not None and next_cursor >= state["cursor"]:
                            raise ValueError(
                                "A paginação da API não avançou para partidas anteriores"
                            )
                    save_json(
                        pending / f"{dataset}-{state['requests']:06d}.json",
                        {
                            "matches": page.matches,
                            "source": {
                                "endpoint": page.endpoint,
                                "requested_at": to_utc_iso(page.requested_at),
                                "status_code": page.status_code,
                                "parameters": page.parameters,
                                "received_count": len(page.matches),
                            },
                        },
                    )
                    if dataset == "public_matches":
                        state["cursor"] = next_cursor
                        state["public_received"] += len(page.matches)
                    else:
                        queue.popleft()
                        state["details_received"] += 1
                    save_json(state_path, state)
                    print(
                        f"Chamada {state['requests']}/{args.max_requests}: "
                        f"{state['public_received']} resumos, "
                        f"{state['details_received']} detalhes; "
                        f"cota diária restante: {state.get('remaining_day', 'não informada')}",
                        flush=True,
                    )
                    checkpoint = 10 if dataset == "public_matches" else 500
                    if len(list(pending.glob(f"{dataset}-*.json"))) >= checkpoint:
                        await flush()
        except asyncio.CancelledError:
            state["status"] = "interrupted"
            print("Interrompido. Salvando e publicando o lote recebido...", flush=True)
        except (OSError, RuntimeError, ValueError, MetadexError):
            state["status"] = "failed"
            raise
        finally:
            try:
                if state["status"] != "failed":
                    await flush()
            finally:
                save_json(state_path, state)
        print(f"Encerrado: {state['status']}. Progresso salvo em {state_path}", flush=True)
        return 1 if state["status"] == "api_error" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requests-per-minute",
        type=int,
        default=60,
        help="Chamadas por minuto: 1..60 (padrão: 60)",
    )
    parser.add_argument(
        "--max-requests", type=int, default=3000, help="Limite total: 1..3000 (padrão: 3000)"
    )
    args = parser.parse_args()
    if not 1 <= args.requests_per_minute <= 60 or not 1 <= args.max_requests <= 3000:
        parser.error("--requests-per-minute deve ser 1..60 e --max-requests deve ser 1..3000")
    try:
        return asyncio.run(collect(args))
    except KeyboardInterrupt:
        print("Interrompido; execute o mesmo comando para retomar.")
        return 130
    except (OSError, RuntimeError, ValueError, MetadexError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
