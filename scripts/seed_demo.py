"""Демо-данные через API бэкенда: пользователи, компании, выписки (дальше — сессии и категории как обычно).

Заливает в ту БД, к которой подключён бэкенд:
  * all@seed.ru — все компании датасета (C001…C150);
  * остальные пользователи — копии пары компаний под кодами D… (компания принадлежит одному пользователю,
    поэтому у копии свой код, свой ИНН и свои номера операций; выписка та же).

Запуск (бэкенд уже работает):
    .venv/bin/python scripts/seed_demo.py --base-url http://localhost:8080 \\
        --dataset ml-model/cashflow_data/cashflow_dataset_participants
Повторный запуск безопасен: пользователи входят по паролю, повторные операции пропускаются.
"""
import argparse
import csv
import io
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

TIMEOUT = httpx.Timeout(900.0, connect=10.0)


@dataclass
class DemoUser:
    email: str
    password: str
    companies: list[str] = field(default_factory=list)  # C… — копируются под кодом D…; пусто = все компании


ALL_COMPANIES = DemoUser("all@seed.ru", "seed-all-2026")
COPIES = [
    DemoUser("hotel@seed.ru", "seed-hotel-2026", ["C044", "C140"]),
    DemoUser("cargo@seed.ru", "seed-cargo-2026", ["C001", "C002"]),
]


def copy_id(company_id: str) -> str:
    return "D" + company_id[1:]


def copy_inn(inn: str) -> str:
    """ИНН копии: та же длина, первые две цифры 99 — в датасете ИНН начинаются с 00, пересечений нет."""
    return "99" + inn[2:]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def companies_copy(companies_csv: str, ids: list[str]) -> str:
    rows = list(csv.reader(io.StringIO(companies_csv), delimiter=";"))
    header, body = rows[0], rows[1:]
    out = [header]
    for row in body:
        if row[0] in ids:
            out.append([copy_id(row[0]), f"{row[1]} (демо)", copy_inn(row[2]), *row[3:]])
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";", lineterminator="\n").writerows(out)
    return buffer.getvalue()


def statement_copy(statement_csv: str, company_id: str) -> str:
    """Код компании и префикс номера операции C044- → D044-; остальные поля без изменений."""
    new_id = copy_id(company_id)
    lines = statement_csv.splitlines()
    out = [lines[0]]
    for line in lines[1:]:
        if line.startswith(company_id + ";"):
            line = new_id + line[len(company_id):].replace(f";{company_id}-", f";{new_id}-", 1)
        out.append(line)
    return "\n".join(out) + "\n"


def dataset_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text.encode("utf-8-sig"))
    return buffer.getvalue()


def login_or_register(client: httpx.Client, user: DemoUser) -> None:
    client.cookies.clear()
    body = {"email": user.email, "password": user.password}
    response = client.post("/api/auth/register", json=body)
    if response.status_code == 409:
        response = client.post("/api/auth/login", json=body)
    if response.status_code not in (200, 201):
        sys.exit(f"{user.email}: не удалось войти ({response.status_code}): {response.json()['listErrors']}")


def upload(client: httpx.Client, user: DemoUser, files: dict[str, str]) -> None:
    response = client.post("/api/imports/dataset",
                           files=[("files", ("dataset.zip", dataset_zip(files), "application/zip"))])
    data = response.json()
    if response.status_code != 200:
        sys.exit(f"{user.email}: загрузка не прошла ({response.status_code}): {data['listErrors']}")
    report = data["data"]
    failed = [f"{f['name']}: {f['error']}" for f in report["files"] if f.get("error")]
    print(f"{user.email:18} компаний {report['companies']:>4}  операций {report['operations']:>7}  "
          f"уже были {report['skipped']:>7}  отклонено {report['rejected']:>5}  {report['tookMs'] / 1000:.0f} с"
          + (f"  ошибки: {failed}" if failed else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument("--dataset", type=Path, required=True, help="папка с companies.csv и statements/")
    args = parser.parse_args()

    companies_csv = read_text(args.dataset / "companies.csv")
    statements = sorted((args.dataset / "statements").glob("*.csv"))

    with httpx.Client(base_url=args.base_url, timeout=TIMEOUT) as client:
        login_or_register(client, ALL_COMPANIES)
        files = {"companies.csv": companies_csv}
        files.update({f"statements/{path.name}": read_text(path) for path in statements})
        upload(client, ALL_COMPANIES, files)

        for user in COPIES:
            login_or_register(client, user)
            files = {"companies.csv": companies_copy(companies_csv, user.companies)}
            for company_id in user.companies:
                statement = read_text(args.dataset / "statements" / f"{company_id}.csv")
                files[f"statements/{copy_id(company_id)}.csv"] = statement_copy(statement, company_id)
            upload(client, user, files)

    print("\nВход:")
    for user in [ALL_COMPANIES, *COPIES]:
        what = "все компании датасета" if not user.companies else ", ".join(copy_id(c) for c in user.companies)
        print(f"  {user.email:18} {user.password:18} {what}")


if __name__ == "__main__":
    main()
