"""Импорт CSV: справочник компаний или выписка операций. Тип файла — по строке заголовков.

Текст в файле — данные, а не инструкции: ничего из назначений платежей не интерпретируется.
"""
import csv
import io
import logging
import time
import zipfile
from dataclasses import dataclass, field
from functools import partial
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import IO, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from psycopg import AsyncConnection
from pydantic_core import PydanticCustomError

from app.classification.jobs import classify_session
from app.common import counterparty_ids, counterparty_key, create_session, link_companies
from app.db import get_conn
from app.responses import ApiError, ok
from app.routers.quality import start_quality_run
from app.schemas import parse_amount
from app.security import CurrentUser, current_user

log = logging.getLogger("backend.imports")
router = APIRouter(prefix="/api/imports", tags=["imports"])

COMPANY_HEADER = ["company_id", "company_name", "company_inn", "legal_form", "industry",
                  "first_operation_date", "last_operation_date", "operations_count"]
OPERATION_HEADER = ["company_id", "operation_id", "operation_date", "amount", "direction",
                    "counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod"]
BATCH_SIZE = 1000
MAX_ERRORS = 100


class RowError(Exception):
    pass


@dataclass
class Report:
    fileType: str
    total: int = 0
    accepted: int = 0
    skipped: int = 0
    rejected: int = 0
    errors: list[dict] = field(default_factory=list)
    company_ids: set[str] = field(default_factory=set)  # компании, чьи строки приняты (для перехода к прогнозу)

    def reject(self, line: int, message: str) -> None:
        self.rejected += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append({"lineNumber": line, "message": message})

    def merge(self, other: "Report") -> None:
        self.accepted += other.accepted
        self.skipped += other.skipped
        self.rejected += other.rejected
        self.company_ids |= other.company_ids
        for err in other.errors:
            if len(self.errors) < MAX_ERRORS:
                self.errors.append(err)

    def to_dict(self) -> dict:
        return {"fileType": self.fileType, "total": self.total, "accepted": self.accepted, "skipped": self.skipped,
                "rejected": self.rejected, "errors": self.errors, "companyIds": sorted(self.company_ids)}


# ---------- разбор полей ----------

def required(value: str, title: str, max_len: int) -> str:
    value = value.strip()
    if not value:
        raise RowError(f"Не заполнено поле «{title}»")
    if len(value) > max_len:
        raise RowError(f"Поле «{title}» длиннее {max_len} символов")
    return value


def parse_date(value: str) -> date:
    value = value.strip()
    try:
        if "." in value:
            return datetime.strptime(value, "%d.%m.%Y").date()
        return date.fromisoformat(value)
    except ValueError:
        raise RowError(f"Дата «{value}» не распознана, нужен формат ГГГГ-ММ-ДД") from None


def normalize_inn(value: str) -> str | None:
    """ИНН — строка. Если Excel съел ведущие нули, возвращаем их (10 цифр у ООО, 12 у ИП)."""
    value = value.strip()
    if not value:
        return None
    if not value.isdigit() or len(value) > 12:
        raise RowError("ИНН должен состоять из 10 или 12 цифр")
    if len(value) < 10:
        return value.zfill(10)
    if len(value) == 11:
        return value.zfill(12)
    return value


def amount_of(value: str) -> Decimal:
    try:
        return parse_amount(value)
    except PydanticCustomError as exc:
        raise RowError(exc.message()) from None


def balance_of(value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    try:
        result = Decimal(value.replace(",", "."))
    except InvalidOperation:
        raise RowError(f"Остаток «{value}» не распознан, нужен формат 12345.67") from None
    return result if result.is_finite() else None


# ---------- компании ----------

@dataclass
class CompanyRow:
    line: int
    company_id: str
    name: str
    inn: str
    legal_form: str
    industry: str


def parse_company(values: list[str], line: int) -> CompanyRow:
    if len(values) != len(COMPANY_HEADER):
        raise RowError(f"Ожидалось {len(COMPANY_HEADER)} колонок, а в строке {len(values)}")
    inn = normalize_inn(required(values[2], "company_inn", 12))
    return CompanyRow(line, required(values[0], "company_id", 10), required(values[1], "company_name", 255),
                      inn, required(values[3], "legal_form", 10), required(values[4], "industry", 100))


async def save_companies(conn: AsyncConnection, user_id: int, rows: list[CompanyRow], report: Report) -> None:
    forms = {r["code"]: r for r in await (await conn.execute("SELECT id, code, inn_length FROM legal_form")).fetchall()}
    # Компания общая; её пользователи — из users_company (пустой список — компания ещё ничья)
    users = {r["company_id"]: set(r["users"]) for r in await (await conn.execute(
        "SELECT c.company_id, array_remove(array_agg(uc.user_id), NULL) AS users FROM company c "
        "LEFT JOIN users_company uc ON uc.company_id = c.company_id WHERE c.company_id = ANY(%s) "
        "GROUP BY c.company_id", [[r.company_id for r in rows]])).fetchall()}
    by_inn = {r["company_inn"]: r["company_id"] for r in await (await conn.execute(
        "SELECT company_id, company_inn FROM company WHERE company_inn = ANY(%s)", [[r.inn for r in rows]])).fetchall()}
    for row in rows:
        form = forms.get(row.legal_form)
        inn_company = by_inn.get(row.inn)
        if form is None:
            report.reject(row.line, "Форма должна быть ООО или ИП")
            continue
        if len(row.inn) != form["inn_length"]:
            report.reject(row.line, f"У {form['code']} ИНН из {form['inn_length']} цифр")
            continue
        if inn_company is not None and inn_company != row.company_id:
            report.reject(row.line, f"Этот ИНН уже указан у компании {inn_company}")
            continue
        linked = users.get(row.company_id)
        if linked is None:
            await conn.execute(
                "INSERT INTO company (company_id, company_name, company_inn, legal_form_id, industry) "
                "VALUES (%s, %s, %s, %s, %s)",
                [row.company_id, row.name, row.inn, form["id"], row.industry])
        elif not linked - {user_id}:
            # Карточку правит только единственный пользователь компании; есть другие — только привязываемся
            await conn.execute(
                "UPDATE company SET company_name = %s, company_inn = %s, legal_form_id = %s, industry = %s "
                "WHERE company_id = %s",
                [row.name, row.inn, form["id"], row.industry, row.company_id])
        await link_companies(conn, user_id, {row.company_id})
        users.setdefault(row.company_id, set()).add(user_id)
        by_inn[row.inn] = row.company_id
        report.accepted += 1
        report.company_ids.add(row.company_id)


# ---------- операции ----------

@dataclass
class OperationRow:
    line: int
    company_id: str
    operation_id: str
    date: date
    amount: Decimal
    direction: str
    inn: str | None
    name: str
    purpose: str | None
    balance_eod: Decimal | None


def parse_operation(values: list[str], line: int, delimiter: str = ";") -> OperationRow:
    if len(values) < len(OPERATION_HEADER):
        raise RowError(f"Ожидалось {len(OPERATION_HEADER)} колонок, а в строке {len(values)}")
    company_id = required(values[0], "company_id", 10)
    operation_id = required(values[1], "operation_id", 20)
    if not operation_id.startswith(company_id + "-"):
        raise RowError(f"Номер операции {operation_id} не относится к компании {company_id}")
    # Разделитель внутри назначения платежа без кавычек: всё между 7-й колонкой и последней (balance_eod) — назначение
    purpose = delimiter.join(values[7:-1]).strip() or None
    return OperationRow(line, company_id, operation_id, parse_date(values[2]), amount_of(values[3]),
                        required(values[4], "direction", 50), normalize_inn(values[5]),
                        required(values[6], "counterparty_name", 255), purpose, balance_of(values[-1]))


@dataclass
class FirstDay:
    """Самая ранняя дата выписки компании в файле: balance_eod этого дня и оборот за день."""
    day: date
    balance_eod: Decimal | None = None
    net: Decimal = Decimal(0)


def track_first_day(first_days: dict[str, FirstDay], row: OperationRow, sign: int) -> None:
    """Учитываем каждую операцию самой ранней даты: их сумма со знаком нужна для остатка на начало дня."""
    current = first_days.get(row.company_id)
    if current is None or row.date < current.day:
        current = first_days[row.company_id] = FirstDay(row.date)
    if row.date == current.day:
        current.net += sign * row.amount
        if row.balance_eod is not None:
            current.balance_eod = row.balance_eod


async def save_operations(conn: AsyncConnection, user_id: int, session_id: int, rows: list[OperationRow],
                          report: Report, first_days: dict[str, FirstDay]) -> None:
    directions = {r["name"]: (r["id"], r["sign"]) for r in
                  await (await conn.execute("SELECT id, name, sign FROM direction")).fetchall()}
    companies = {r["company_id"] for r in await (await conn.execute(
        "SELECT company_id FROM company WHERE company_id = ANY(%s)",
        [list({r.company_id for r in rows})])).fetchall()}
    # Повторы — только среди операций этого пользователя: у другого пользователя данные компании свои
    # ANY по каждой колонке идёт по индексу (user_id, company_id, …); IN по парам из unnest — полный просмотр таблицы.
    # Лишние пары (номер из одной компании, код из другой) безвредны: сверяем ниже по паре целиком
    existing = {(r["company_id"], r["source_operation_id"]) for r in await (await conn.execute(
        "SELECT company_id, source_operation_id FROM operation "
        "WHERE user_id = %s AND company_id = ANY(%s) AND source_operation_id = ANY(%s)",
        [user_id, list({r.company_id for r in rows}), [r.operation_id for r in rows]])).fetchall()}

    new_rows: list[OperationRow] = []
    known_balances: list[OperationRow] = []  # уже загруженные: остаток из выписки дописываем, если его не было
    for row in rows:
        direction = directions.get(row.direction)
        if row.company_id not in companies:
            report.reject(row.line, f"Компании {row.company_id} нет — сначала загрузите справочник компаний")
            continue
        if direction is None:
            report.reject(row.line, "Направление должно быть «Поступление» или «Списание»")
            continue
        # Остаток на начало считаем по всем строкам файла, включая уже загруженные ранее
        track_first_day(first_days, row, direction[1])
        report.company_ids.add(row.company_id)
        key = (row.company_id, row.operation_id)
        if key in existing:
            report.skipped += 1
            if row.balance_eod is not None:
                known_balances.append(row)
            continue
        existing.add(key)
        new_rows.append(row)
    await link_companies(conn, user_id, {row.company_id for row in rows if row.company_id in companies})
    if known_balances:
        async with conn.cursor() as cur:
            await cur.executemany(
                "UPDATE operation SET balance_eod = %s "
                "WHERE user_id = %s AND company_id = %s AND source_operation_id = %s AND balance_eod IS NULL",
                [[r.balance_eod, user_id, r.company_id, r.operation_id] for r in known_balances])
    if not new_rows:
        return

    cp_ids = await counterparty_ids(conn, {counterparty_key(r.inn, r.name) for r in new_rows})
    # Пачка — одним оператором по колонкам-массивам: в разы быстрее executemany по строке
    columns = [[r.operation_id for r in new_rows], [r.company_id for r in new_rows], [r.date for r in new_rows],
               [cp_ids[counterparty_key(r.inn, r.name)] for r in new_rows], [r.amount for r in new_rows],
               [directions[r.direction][0] for r in new_rows], [r.purpose for r in new_rows],
               [r.balance_eod for r in new_rows], [user_id] * len(new_rows), [session_id] * len(new_rows)]
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO operation (source_operation_id, company_id, date, counterparty_id, amount, direction_id, "
            "payment_purpose, balance_eod, user_id, session_id) "
            "SELECT * FROM unnest(%s::text[], %s::text[], %s::date[], %s::bigint[], %s::numeric[], %s::smallint[], "
            "%s::text[], %s::numeric[], %s::bigint[], %s::int[]) "
            "ON CONFLICT DO NOTHING",
            columns)
        inserted = cur.rowcount if cur.rowcount >= 0 else len(new_rows)
    report.accepted += inserted
    report.skipped += len(new_rows) - inserted


async def save_opening_balances(conn: AsyncConnection, first_days: dict[str, FirstDay]) -> None:
    """company.opening_balance = balance_eod самой ранней даты + списания − поступления всех операций этой даты.

    Обновляем, только если у компании в БД нет операций раньше этой даты: иначе файл — не начало выписки.
    """
    for company_id, first in first_days.items():
        if first.balance_eod is None:
            continue
        await conn.execute(
            "UPDATE company SET opening_balance = %s WHERE company_id = %s "
            "AND NOT EXISTS (SELECT 1 FROM operation o WHERE o.company_id = %s AND o.date < %s)",
            [first.balance_eod - first.net, company_id, company_id, first.day])


# ---------- общий проход по файлу ----------

def read_lines(upload: UploadFile) -> io.TextIOWrapper:
    upload.file.seek(0)
    return io.TextIOWrapper(upload.file, encoding="utf-8-sig", newline=None)


def split_row(line: str, delimiter: str) -> list[str]:
    """Строка CSV по разделителю файла; значение в кавычках может содержать разделитель."""
    return next(csv.reader([line], delimiter=delimiter, skipinitialspace=False))


async def import_rows(conn: AsyncConnection, user_id: int, lines: io.TextIOWrapper, report: Report,
                      parse: Callable, save: Callable, delimiter: str = ";") -> None:
    batch: list = []

    async def flush() -> None:
        sub = Report(report.fileType)
        try:
            async with conn.transaction():
                await save(batch, sub)
        except Exception as exc:  # noqa: BLE001 — ошибка БД в пачке: отклоняем пачку, импорт продолжаем
            log.warning("import batch failed user_id=%s first_line=%d error=%s",
                        user_id, batch[0].line, type(exc).__name__)
            for row in batch:
                report.reject(row.line, "Строку не удалось сохранить, проверьте данные")
            return
        report.merge(sub)

    line_number = 1
    for line in lines:
        line_number += 1
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        report.total += 1
        try:
            batch.append(parse(split_row(line, delimiter), line_number))
        except RowError as exc:
            report.reject(line_number, str(exc))
        except csv.Error:
            report.reject(line_number, "Строку не удалось разобрать, проверьте кавычки и разделители")
        if len(batch) >= BATCH_SIZE:
            await flush()
            batch = []
    if batch:
        await flush()


UNKNOWN_FILE = ("Не удалось распознать файл: нужна выписка операций или справочник компаний "
                "со строкой заголовков, как в исходном файле (разделитель «;», «,», табуляция или «|»)")

# Разделитель определяем по заголовку: при «своём» разделителе он совпадает с известным списком колонок
DELIMITERS = (";", ",", "\t", "|")


def detect_file(header_line: str) -> tuple[str | None, str]:
    """Тип файла по заголовку и разделитель колонок. Не распознали — (None, «;»)."""
    line = header_line.rstrip("\r\n").lstrip("\ufeff")
    for delimiter in DELIMITERS:
        header = [c.strip().strip('"').strip() for c in split_row(line, delimiter)] if line else []
        if header == COMPANY_HEADER:
            return "COMPANIES", delimiter
        if header == OPERATION_HEADER:
            return "OPERATIONS", delimiter
    return None, ";"


def file_type(header_line: str) -> str | None:
    return detect_file(header_line)[0]


def parse_as_of(value: str | None) -> date | None:
    """Дата начала для расчёта категорий (с фронта). Пусто — вся история."""
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ApiError(400, "Дата начала — в формате ГГГГ-ММ-ДД", "asOf") from None


def refresh_quality(tasks: BackgroundTasks, request: Request, user: CurrentUser, operations: int) -> None:
    """Данные администратора — основа отчёта о качестве: после его загрузки отчёт пересчитывается в ML."""
    if user.is_admin and operations > 0:
        tasks.add_task(start_quality_run, request)


async def start_classification(conn: AsyncConnection, tasks: BackgroundTasks, session_id: int,
                               as_of: date | None, operations: int) -> bool:
    """Фиксируем загрузку и после ответа считаем категории по сессии (classify_operations_by_session_id)."""
    if operations == 0:
        return False
    await conn.commit()
    tasks.add_task(classify_session, session_id, as_of)
    return True


async def import_stream(conn: AsyncConnection, user_id: int, session_id: int, lines: io.TextIOWrapper) -> Report:
    """Один CSV: тип по заголовку, строки пачками. Ошибка формата — ApiError с текстом для предпринимателя."""
    try:
        header_line = lines.readline()
        if not header_line.strip():
            raise ApiError(400, "Файл пустой")
        kind, delimiter = detect_file(header_line)
        if kind == "COMPANIES":
            report = Report(kind)
            await import_rows(conn, user_id, lines, report, parse_company,
                              lambda rows, sub: save_companies(conn, user_id, rows, sub), delimiter)
        elif kind == "OPERATIONS":
            report = Report(kind)
            first_days: dict[str, FirstDay] = {}
            await import_rows(conn, user_id, lines, report, partial(parse_operation, delimiter=delimiter),
                              lambda rows, sub: save_operations(conn, user_id, session_id, rows, sub, first_days),
                              delimiter)
            async with conn.transaction():
                await save_opening_balances(conn, first_days)
        else:
            raise ApiError(400, UNKNOWN_FILE)
    except UnicodeDecodeError:
        raise ApiError(400, "Файл должен быть в кодировке UTF-8") from None
    return report


def log_report(user_id: int, report: Report, started: float) -> None:
    log.info("csv imported user_id=%s file_type=%s total=%d accepted=%d skipped=%d rejected=%d took_ms=%d",
             user_id, report.fileType, report.total, report.accepted, report.skipped, report.rejected,
             (time.perf_counter() - started) * 1000)


@router.post("")
async def import_file(request: Request, tasks: BackgroundTasks, file: UploadFile = File(...),
                      asOf: str | None = Form(None), user: CurrentUser = Depends(current_user),
                      conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    started = time.perf_counter()
    as_of = parse_as_of(asOf)
    session_id = await create_session(conn, user.id)
    lines = read_lines(file)
    try:
        report = await import_stream(conn, user.id, session_id, lines)
    finally:
        lines.detach()
    log_report(user.id, report, started)
    operations = report.accepted if report.fileType == "OPERATIONS" else 0
    classifying = await start_classification(conn, tasks, session_id, as_of, operations)
    refresh_quality(tasks, request, user, operations)
    return ok(request, {**report.to_dict(), "sessionId": session_id, "classifying": classifying})


# ---------- датасет: несколько CSV и/или ZIP одним запросом ----------

MAX_UNZIPPED_BYTES = 2 * 1024 ** 3  # защита от zip-бомбы: сумма распакованных CSV
TYPE_ORDER = {"COMPANIES": 0, "OPERATIONS": 1}


@dataclass
class Source:
    name: str
    open: Callable[[], IO[bytes]]
    kind: str | None = None


def collect_sources(files: list[UploadFile]) -> tuple[list[Source], list[dict]]:
    """CSV из запроса и из архивов. Файлы не CSV в архиве пропускаются, отдельные — попадают в ошибки."""
    sources: list[Source] = []
    failed: list[dict] = []
    unzipped = 0
    for upload in files:
        name = upload.filename or "file"
        upload.file.seek(0)
        if name.lower().endswith(".zip") or zipfile.is_zipfile(upload.file):
            upload.file.seek(0)
            try:
                archive = zipfile.ZipFile(upload.file)
            except zipfile.BadZipFile:
                failed.append(file_error(name, "Архив повреждён, соберите его заново"))
                continue
            for info in archive.infolist():
                inner = info.filename
                if info.is_dir() or not inner.lower().endswith(".csv") or "__MACOSX" in inner \
                        or inner.rsplit("/", 1)[-1].startswith("."):
                    continue
                unzipped += info.file_size
                if unzipped > MAX_UNZIPPED_BYTES:
                    raise ApiError(413, "Архив слишком большой после распаковки, разделите его на части")
                sources.append(Source(inner, lambda a=archive, i=info: a.open(i)))
        elif name.lower().endswith(".csv"):
            sources.append(Source(name, lambda f=upload.file: (f.seek(0), f)[1]))
        else:
            failed.append(file_error(name, "Нужен файл CSV или архив ZIP"))
    return sources, failed


def file_error(name: str, message: str) -> dict:
    return {"name": name, "fileType": None, "total": 0, "accepted": 0, "skipped": 0, "rejected": 0,
            "errors": [], "companyIds": [], "error": message}


def peek_kind(source: Source) -> str | None:
    raw = source.open()
    lines = io.TextIOWrapper(raw, encoding="utf-8-sig", newline=None)
    try:
        return file_type(lines.readline())
    except UnicodeDecodeError:
        return None
    finally:
        lines.detach()


@router.post("/dataset")
async def import_dataset(request: Request, tasks: BackgroundTasks, files: list[UploadFile] = File(...),
                         asOf: str | None = Form(None), user: CurrentUser = Depends(current_user),
                         conn: AsyncConnection = Depends(get_conn)) -> JSONResponse:
    started = time.perf_counter()
    as_of = parse_as_of(asOf)
    sources, results = collect_sources(files)
    if not sources and not results:
        raise ApiError(400, "В архиве нет файлов CSV")
    for source in sources:
        source.kind = peek_kind(source)
    # Сначала справочник компаний: операции принимаются только по своим компаниям
    sources.sort(key=lambda s: (TYPE_ORDER.get(s.kind or "", 2), s.name))

    session_id = await create_session(conn, user.id)
    totals = Report("DATASET")
    for source in sources:
        file_started = time.perf_counter()
        lines = io.TextIOWrapper(source.open(), encoding="utf-8-sig", newline=None)
        try:
            report = await import_stream(conn, user.id, session_id, lines)
        except ApiError as exc:
            results.append(file_error(source.name, exc.errors[0]["message"]))
            continue
        finally:
            lines.detach()
        log_report(user.id, report, file_started)
        totals.company_ids |= report.company_ids
        results.append({"name": source.name, **report.to_dict()})

    by_type = lambda kind: sum(r["accepted"] for r in results if r["fileType"] == kind)  # noqa: E731
    took_ms = int((time.perf_counter() - started) * 1000)
    log.info("dataset imported user_id=%s files=%d took_ms=%d", user.id, len(results), took_ms)
    classifying = await start_classification(conn, tasks, session_id, as_of, by_type("OPERATIONS"))
    refresh_quality(tasks, request, user, by_type("OPERATIONS"))
    return ok(request, {
        "sessionId": session_id,
        "classifying": classifying,
        "files": results,
        "companies": by_type("COMPANIES"),
        "operations": by_type("OPERATIONS"),
        "skipped": sum(r["skipped"] for r in results),
        "rejected": sum(r["rejected"] for r in results),
        "failedFiles": sum(1 for r in results if r.get("error")),
        "companyIds": sorted(totals.company_ids),
        "tookMs": took_ms,
    })
